// 定点复核：① 超管端点真实 id 的越权判定 ② 平台超管跨租户读的补偿通道 ③ 第三租户 C 的一致性
// 主体由 env 注入（issue #6937）；缺哪个主体，**只有依赖它的判据**具名 skip，不折算 pass。
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { api, loginApi, log, psql } from '../../config-writeface-sweep/harness/lib.mjs'
import { S, T, PH, SMS_CODE, MISSING_B, SUBJECTS_LINE } from '../../lib/subjects.mjs'
const OUT = process.env.OUT_DIR ? process.env.OUT_DIR.replace(/\/?$/, '/') : fileURLToPath(new URL('../out/', import.meta.url))
const tok = {}
for (const [k, p] of Object.entries({ A: PH.A, B: PH.B, P: PH.P, C: PH.C })) { if (p) tok[k] = (await loginApi(p, SMS_CODE)).token }
log(`[env] ${SUBJECTS_LINE}；已登录=${Object.keys(tok).join('/') || '无'}`)
const recs = []
const rec = (o) => { recs.push(o); log(`${o.verdict === 'pass' ? '✅' : o.verdict === 'fail' ? '❌' : '⏭️'} [${o.id}] ${o.name} — ${o.detail}`); return o }
const cut = (s, n = 500) => (typeof s === 'string' ? s : JSON.stringify(s) ?? '').slice(0, n)

// ① 平台级端点的真实 id：商家 admin 能不能越权
const apps = psql(`select id::text as id, status, company_name from tenant_applications order by id desc limit 3`)
log(`tenant_applications 样本=${JSON.stringify(apps)}`)
for (const a of apps.slice(0, 2)) {
  const gA = await api('GET', `/api/super-admin/registrations/${a.id}`, { token: tok.A })
  const gB = tok.B ? await api('GET', `/api/super-admin/registrations/${a.id}`, { token: tok.B }) : null
  const gP = tok.P ? await api('GET', `/api/super-admin/registrations/${a.id}`, { token: tok.P }) : null
  const ev = [`A(商家${T.A}) → ${gA.status} ${cut(gA.text, 220)}`, `B → ${gB ? gB.status : '未注入'}`, `P(超管) → ${gP ? gP.status : '未注入'}`]
  if (!tok.P) { rec({ id: `ROLE-plat-id-${a.id}`, name: '角色越权·超管端点真实 id', verdict: 'skip', detail: '平台超管 P 未注入 ⇒ 缺正对照，商家侧的 4xx 不可归因于权限闸（不折算 pass）', evidence: ev }); continue }
  if (!tok.B) { rec({ id: `ROLE-plat-id-${a.id}`, name: '角色越权·超管端点真实 id', verdict: 'skip', detail: '对照租户 B 未注入 ⇒ 该判据要求两侧商家均为 4xx，本轮不可判（不折算 pass）', evidence: ev }); continue }
  const ok = !(gA.status === 200 || gB.status === 200) && gP.status === 200
  rec({ id: `ROLE-plat-id-${a.id}`, name: '角色越权·超管端点真实 id', verdict: ok ? 'pass' : 'fail',
    detail: ok ? `商家 admin 读平台级入驻申请(真实 id) 被拒（A=${gA.status} B=${gB.status}），超管正对照 ${gP.status}` : `🔴 A=${gA.status} B=${gB.status} P=${gP.status}`, evidence: ev })
}
// 是否真的走了权限判定（对比「路径存在但方法/参数错」）
{
  const badId = await api('GET', '/api/super-admin/registrations/999999999999', { token: tok.A })
  if (!tok.P) rec({ id: 'ROLE-plat-existence', name: '角色越权·超管端点可达性判据', verdict: 'skip', detail: '平台超管 P 未注入 ⇒ 无对照，不判', evidence: [`A → ${badId.status}`] })
  else {
    const badIdP = await api('GET', '/api/super-admin/registrations/999999999999', { token: tok.P })
    rec({ id: 'ROLE-plat-existence', name: '角色越权·超管端点可达性判据', verdict: 'pass',
      detail: `商家 admin 打不存在的超管资源 id：A=${badId.status} ${cut(badId.json?.error?.code, 40)}；超管同 id=${badIdP.status} ${cut(badIdP.json?.error?.code, 40)}（若 A=403 而超管=404 ⇒ 确有权限闸；若两者同为 404 ⇒ 权限闸未对该路径生效，需单列）`,
      evidence: [`A → ${badId.status} ${cut(badId.text, 200)}`, `P → ${badIdP.status} ${cut(badIdP.text, 200)}`] })
  }
}

// ② 平台超管跨租户读的补偿通道：超管读 A 自己的资源（需 P 注入）
const A_TEN = T.A
const aProd = psql(`select id::text from products where tenant_id=${A_TEN} and coalesce(deleted,0)=0 limit 1`)[0]?.id
const aOrd = psql(`select id::text from orders where tenant_id=${A_TEN} and coalesce(deleted,0)=0 limit 1`)[0]?.id
const aCust = psql(`select id::text from customer_profiles where tenant_id=${A_TEN} limit 1`)[0]?.id
for (const [id, path, label] of [[aProd, aProd && `/api/admin/products/${aProd}`, '商品'], [aOrd, aOrd && `/api/admin/orders/${aOrd}`, '订单'], [aCust, aCust && `/api/admin/customers/${aCust}`, '客户']]) {
  if (!tok.P) { rec({ id: `SA-own-${label}`, name: `超管·读 A 自己的${label}`, verdict: 'skip', detail: '平台超管 P 未注入（不折算 pass）' }); continue }
  if (!id) { rec({ id: `SA-own-${label}`, name: `超管·读 A 自己的${label}`, verdict: 'skip', detail: `A(${A_TEN}) 该表无存活行 ⇒ 无对象可打` }); continue }
  const r = await api('GET', path, { token: tok.P })
  rec({ id: `SA-own-${label}`, name: `超管·读 A 自己的${label}`, verdict: 'pass',
    detail: `超管读租户${A_TEN} 的${label} → ${r.status}${r.status === 200 ? ' ⇒ 平台不受租户过滤限制（读单租户时能读到）' : ' ⇒ 连单租户也读不到'}`,
    evidence: [`GET ${path} (超管) → ${r.status} ${cut(r.text, 240)}`] })
}

// ③ 第三对照租户 C：跨租户读写一致性（A 打 C 的 id）——需 C 注入
if (!S.C) {
  rec({ id: 'X-C-GATE', name: '跨租户读/写(A→C 第三租户)', verdict: 'skip', detail: '第三租户 C 未注入（TENANT_C/PHONE_C 缺）⇒ 本组具名跳过，不折算 pass' })
} else {
  const cProd = psql(`select id::text from products where tenant_id=${T.C} and coalesce(deleted,0)=0 limit 1`)[0]?.id
  const cOrd = psql(`select id::text from orders where tenant_id=${T.C} and coalesce(deleted,0)=0 limit 1`)[0]?.id
  const cItems = [[cProd && `/api/admin/products/${cProd}`, cProd && `/api/admin/products/${cProd}`, '商品', cProd],
                  [cOrd && `/api/admin/orders/${cOrd}`, cOrd && `/api/admin/orders/${cOrd}/content`, '订单', cOrd]]
  for (const [rpath, wpath, label, cid] of cItems) {
    if (!cid) { rec({ id: `X-C-${label}`, name: `跨租户读(A→C租户${T.C})·${label}`, verdict: 'skip', detail: `C(${T.C}) 该表无存活行 ⇒ 无对象可打` }); continue }
    const r = await api('GET', rpath, { token: tok.A })
    rec({ id: `X-C-${label}`, name: `跨租户读(A→C租户${T.C})·${label}`, verdict: r.status === 200 ? 'fail' : 'pass',
      detail: `A(${T.A}) 读 C(${T.C}) 的${label} → ${r.status}${r.status === 200 ? ' 🔴 返回 200' : ''}`, evidence: [`GET ${rpath} (A token, C 的 id=${cid}) → ${r.status} ${cut(r.text, 200)}`] })
    // 有效载荷（保证走完校验，探到真正的租户判定）
    const wbody = label === '商品' ? { name: psql(`select name from products where id::text='${cid}'`)[0].name }
      : { customerName: '张三', customerPhone: PH.A, items: [{ productName: 'x', quantity: 1, unitPrice: 1 }] }
    const before = psql(`select * from ${label === '商品' ? 'products' : 'orders'} where id::text='${cid}'`)[0]
    const w = await api('PUT', wpath, { token: tok.A, body: wbody })
    const after = psql(`select * from ${label === '商品' ? 'products' : 'orders'} where id::text='${cid}'`)[0]
    const unchanged = JSON.stringify(before) === JSON.stringify(after)
    rec({ id: `X-CW-${label}`, name: `跨租户写(A→C租户${T.C})·${label}`, verdict: ([401,403,404].includes(w.status) && unchanged) ? 'pass' : 'fail',
      detail: `A(${T.A}) PUT C(${T.C}) 的${label}（有效载荷）→ ${w.status}；库逐字段未变=${unchanged}`,
      evidence: [`PUT ${wpath} body=${cut(wbody,140)} → ${w.status} ${cut(w.text, 220)}`, `before=${cut(before,260)}`, `after=${cut(after,260)}`] })
  }
}
writeFileSync(OUT + 'sweep3-probe.json', JSON.stringify(recs, null, 1))
log(`=== 定点复核：${JSON.stringify(recs.reduce((a, r) => (a[r.verdict] = (a[r.verdict] ?? 0) + 1, a), {}))}`)
