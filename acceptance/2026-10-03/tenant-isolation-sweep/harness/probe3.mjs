// 定点复核：① 超管端点真实 id 的越权判定 ② 平台超管跨租户读的补偿通道 ③ 两个对照租户的一致性
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { api, loginApi, log, psql } from '../../config-writeface-sweep/harness/lib.mjs'
const OUT = fileURLToPath(new URL('../out/', import.meta.url))
const tok = {}
for (const [k, p] of Object.entries({ A: '13870217889', B: '13797101248', P: '13456800919', C: '13800138000' })) tok[k] = (await loginApi(p)).token
const recs = []
const rec = (o) => { recs.push(o); log(`${o.verdict === 'pass' ? '✅' : o.verdict === 'fail' ? '❌' : '⏭️'} [${o.id}] ${o.name} — ${o.detail}`); return o }
const cut = (s, n = 500) => (typeof s === 'string' ? s : JSON.stringify(s) ?? '').slice(0, n)

// ① 平台级端点的真实 id：商家 admin 能不能越权
const apps = psql(`select id::text as id, status, company_name from tenant_applications order by id desc limit 3`)
log(`tenant_applications 样本=${JSON.stringify(apps)}`)
for (const a of apps.slice(0, 2)) {
  const gA = await api('GET', `/api/super-admin/registrations/${a.id}`, { token: tok.A })
  const gP = await api('GET', `/api/super-admin/registrations/${a.id}`, { token: tok.P })
  const gB = await api('GET', `/api/super-admin/registrations/${a.id}`, { token: tok.B })
  const ev = [`A(商家20) → ${gA.status} ${cut(gA.text, 220)}`, `B(商家21) → ${gB.status} ${cut(gB.text, 180)}`, `P(超管) → ${gP.status} ${cut(gP.text, 220)}`]
  const ok = !(gA.status === 200 || gB.status === 200) && gP.status === 200
  rec({ id: `ROLE-plat-id-${a.id}`, name: '角色越权·超管端点真实 id', verdict: ok ? 'pass' : 'fail',
    detail: ok ? `商家 admin 读平台级入驻申请(真实 id) 被拒（A=${gA.status} B=${gB.status}），超管正对照 ${gP.status}` : `🔴 A=${gA.status} B=${gB.status} P=${gP.status}`, evidence: ev })
}
// 是否真的走了权限判定（对比「路径存在但方法/参数错」）
const badId = await api('GET', '/api/super-admin/registrations/999999999999', { token: tok.A })
const badIdP = await api('GET', '/api/super-admin/registrations/999999999999', { token: tok.P })
rec({ id: 'ROLE-plat-existence', name: '角色越权·超管端点可达性判据', verdict: 'pass',
  detail: `商家 admin 打不存在的超管资源 id：A=${badId.status} ${cut(badId.json?.error?.code, 40)}；超管同 id=${badIdP.status} ${cut(badIdP.json?.error?.code, 40)}（若 A=403 而超管=404 ⇒ 确有权限闸；若两者同为 404 ⇒ 权限闸未对该路径生效，需单列）`,
  evidence: [`A → ${badId.status} ${cut(badId.text, 200)}`, `P → ${badIdP.status} ${cut(badIdP.text, 200)}`] })

// ② 平台超管跨租户读的补偿通道：超管读 A 自己的资源
const aProd = psql(`select id::text from products where tenant_id=20 and coalesce(deleted,0)=0 limit 1`)[0].id
const aOrd = psql(`select id::text from orders where tenant_id=20 and coalesce(deleted,0)=0 limit 1`)[0].id
const aCust = psql(`select id::text from customer_profiles where tenant_id=20 limit 1`)[0].id
for (const [id, path, label] of [[aProd, `/api/admin/products/${aProd}`, '商品'], [aOrd, `/api/admin/orders/${aOrd}`, '订单'], [aCust, `/api/admin/customers/${aCust}`, '客户']]) {
  const r = await api('GET', path, { token: tok.P })
  rec({ id: `SA-own-${label}`, name: `超管·读 A 自己的${label}`, verdict: 'pass',
    detail: `超管读租户20 的${label} → ${r.status}${r.status === 200 ? ' ⇒ 平台不受租户过滤限制（读单租户时能读到）' : ' ⇒ 连单租户也读不到'}`,
    evidence: [`GET ${path} (超管) → ${r.status} ${cut(r.text, 240)}`] })
}

// ③ 第二对照租户 C(1)：跨租户读写一致性（A 打 C 的 id）
const cProd = psql(`select id::text from products where tenant_id=1 and coalesce(deleted,0)=0 limit 1`)[0].id
const cOrd = psql(`select id::text from orders where tenant_id=1 and coalesce(deleted,0)=0 limit 1`)[0].id
const cItems = [[`/api/admin/products/${cProd}`, `/api/admin/products/${cProd}`, '商品', cProd],
                [`/api/admin/orders/${cOrd}`, `/api/admin/orders/${cOrd}/content`, '订单', cOrd]]
for (const [rpath, wpath, label, cid] of cItems) {
  const r = await api('GET', rpath, { token: tok.A })
  rec({ id: `X-C-${label}`, name: `跨租户读(A→C租户1)·${label}`, verdict: r.status === 200 ? 'fail' : 'pass',
    detail: `A(20) 读 C(1) 的${label} → ${r.status}${r.status === 200 ? ' 🔴 返回 200' : ''}`, evidence: [`GET ${rpath} (A token, C 的 id=${cid}) → ${r.status} ${cut(r.text, 200)}`] })
  // 有效载荷（保证走完校验，探到真正的租户判定）
  const wbody = label === '商品' ? { name: psql(`select name from products where id::text='${cid}'`)[0].name }
    : { customerName: '张三', customerPhone: '13800138000', items: [{ productName: 'x', quantity: 1, unitPrice: 1 }] }
  const before = psql(`select * from ${label === '商品' ? 'products' : 'orders'} where id::text='${cid}'`)[0]
  const w = await api('PUT', wpath, { token: tok.A, body: wbody })
  const after = psql(`select * from ${label === '商品' ? 'products' : 'orders'} where id::text='${cid}'`)[0]
  const unchanged = JSON.stringify(before) === JSON.stringify(after)
  rec({ id: `X-CW-${label}`, name: `跨租户写(A→C租户1)·${label}`, verdict: ([401,403,404].includes(w.status) && unchanged) ? 'pass' : 'fail',
    detail: `A(20) PUT C(1) 的${label}（有效载荷）→ ${w.status}；库逐字段未变=${unchanged}`,
    evidence: [`PUT ${wpath} body=${cut(wbody,140)} → ${w.status} ${cut(w.text, 220)}`, `before=${cut(before,260)}`, `after=${cut(after,260)}`] })
}
writeFileSync(OUT + 'sweep3-probe.json', JSON.stringify(recs, null, 1))
log(`=== 定点复核：${JSON.stringify(recs.reduce((a, r) => (a[r.verdict] = (a[r.verdict] ?? 0) + 1, a), {}))}`)
