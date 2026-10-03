// 判据批次 5~9：写面有效载荷复核 / 头与参数伪造 / 认证 / 角色越权 / 超管反向对照
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { api, loginApi, log, psql, one } from '../../config-writeface-sweep/harness/lib.mjs'
import { RESOURCES, dbIds, rowSnapshot, realCols } from './registry.mjs'

const OUT = fileURLToPath(new URL('../out/', import.meta.url))
const FLIP = process.argv.includes('--flip')
const recs = []
const rec = (o) => { recs.push(o); const i = o.verdict === 'pass' ? '✅' : o.verdict === 'fail' ? '❌' : '⏭️'
  log(`${i} [${o.id}] ${o.name} — ${o.detail}`); return o }
const pass = (o) => rec({ ...o, verdict: 'pass' }), fail = (o) => rec({ ...o, verdict: 'fail' }), skip = (o) => rec({ ...o, verdict: 'skip' })
const pathFor = (R, id) => (R.read ? R.read(id) : ({ categories: `/api/admin/categories/${id}`, customer_tags: `/api/admin/customer-tags/${id}`, operations: `/api/admin/production/operations/${id}`, routings: `/api/admin/production/routings/${id}`, route_rules: `/api/admin/production/route-rules/${id}`, fee_combos: `/api/admin/production/processing-fee-combinations/${id}`, op_positions: `/api/admin/production/operation-positions/${id}`, notif_templates: `/api/admin/notification-templates/${id}`, notif_rules: `/api/admin/notification-rules/${id}`, knowledge_cards: `/api/admin/knowledge/cards/${id}` }[R.key] ?? `/api/admin/${R.key}/${id}`))
const cut = (s, n = 400) => (typeof s === 'string' ? s : JSON.stringify(s) ?? '').slice(0, n)

const tok = {}; const info = {}
for (const [k, phone] of Object.entries({ A: '13870217889', B: '13797101248', P: '13456800919' })) {
  const r = await loginApi(phone); tok[k] = r.token; info[k] = r.raw.user
}
const EXPECT_DENY = [401, 403, 404]
const denied = (st) => (FLIP ? st === 200 : EXPECT_DENY.includes(st))
const leakIn = (text, ids) => (ids ?? []).filter((id) => text.includes(String(id)))

// ─────────── 5. 写面：**有效载荷**跨租户复核（把 422 的「校验先于租户」问到底）
const VALID = {
  products: (bid) => {
    const r = psql(`select name, category_id, unit, base_price, status from products where id::text='${bid}'`)[0]
    return { name: r.name, unit: r.unit ?? '米', basePrice: Number(r.base_price ?? 0), status: r.status ?? 'on_sale' }
  },
  categories: (bid) => ({ name: psql(`select name from categories where id::text='${bid}'`)[0].name }),
  processing_items: (bid) => {
    const r = psql(`select name, category_id from processing_items where id::text='${bid}'`)[0]
    return { name: r.name, categoryId: r.category_id, unit: '米' }
  },
  orders: (bid) => ({ customerName: '张三', customerPhone: '13800138000', items: [{ productName: 'x', quantity: 1, unitPrice: 1 }] }),
}
for (const [key, mk] of Object.entries(VALID)) {
  const R = RESOURCES.find((x) => x.key === key)
  const bIds = dbIds(R.table, 21), aIds = dbIds(R.table, 20)
  if (!bIds.length) { skip({ id: `WV-${key}`, name: `跨租户写(有效载荷)·${R.label}`, detail: 'B 侧无存活行' }); continue }
  R.snap = realCols(R.table, R.snap ?? [])
  const bid = bIds[0]
  const before = rowSnapshot(R.table, bid, R.snap)
  const body = mk(bid)
  const path = key === 'orders' ? `/api/admin/orders/${bid}/content` : pathFor(R, bid)
  const r = await api('PUT', path, { token: tok.A, body })
  const after = rowSnapshot(R.table, bid, R.snap)
  const unchanged = JSON.stringify(before) === JSON.stringify(after)
  const leaked = leakIn(r.text, bIds)
  // 同租户正对照（同样有效载荷，A 打 A）
  let pc = null
  if (aIds.length) { const aid = aIds[0]
    pc = await api('PUT', key === 'orders' ? `/api/admin/orders/${aid}/content` : pathFor(R, aid), { token: tok.A, body: mk(aid) }) }
  const ev = [
    `A(20)→B(21) 有效载荷 PUT ${path} body=${cut(body, 200)} → ${r.status} ${cut(r.text, 240)}`,
    `DB 快照 before=${cut(before, 260)} after=${cut(after, 260)} unchanged=${unchanged}`,
    `正对照 A→A 同载荷 → ${pc ? pc.status + ' ' + cut(pc.text, 180) : '无 A 侧对象'}`,
  ]
  if (denied(r.status) && unchanged && leaked.length === 0)
    pass({ id: `WV-${key}`, name: `跨租户写(有效载荷)·${R.label}`, detail: `有效载荷也被拒：${r.status}；库逐字段未变；无 B 数据泄漏`, evidence: ev })
  else
    fail({ id: `WV-${key}`, name: `跨租户写(有效载荷)·${R.label}`, detail: `🔴 有效载荷跨租户写得到 ${r.status}；库变动=${!unchanged}；泄漏=${JSON.stringify(leaked)}`, evidence: ev })
}

// ─────────── 6. 参数 / 头部伪造（X-Tenant-Id 是真实攻击面）
const FORGE = [
  { name: 'query ?tenantId=21', q: '?tenantId=21', h: {} },
  { name: 'query ?tenant_id=21', q: '?tenant_id=21', h: {} },
  { name: 'header X-Tenant-Id: 21', q: '', h: { 'X-Tenant-Id': '21' } },
  { name: 'header X-Tenant-Id: 21 + query tenantId=21', q: '?tenantId=21', h: { 'X-Tenant-Id': '21' } },
]
const FKEYS = ['products', 'orders', 'customers', 'users', 'roles']
for (const key of FKEYS) {
  const R = RESOURCES.find((x) => x.key === key)
  const bIds = dbIds(R.table, 21)
  if (!bIds.length || !R.read) { skip({ id: `F-${key}`, name: `伪造越权·${R.label}`, detail: 'B 无对象或无读端点' }); continue }
  const bid = bIds[0]
  const rows = []
  for (const f of FORGE) {
    const r = await api('GET', R.read(bid) + f.q, { token: tok.A, headers: f.h })
    rows.push({ f: f.name, status: r.status, leak: leakIn(r.text, bIds), body: cut(r.text, 160) })
  }
  // 正对照：A 打自己 + 同样伪造头 ⇒ 200（证明伪造头没把请求打死，探针有效）
  const aid = dbIds(R.table, 20)[0]
  const pcr = aid ? await api('GET', R.read(aid) + '?tenantId=21', { token: tok.A, headers: { 'X-Tenant-Id': '21' } }) : null
  const bad = rows.filter((x) => !denied(x.status) || x.leak.length > 0)
  const ev = [...rows.map((x) => `${x.f} → ${x.status} leak=${JSON.stringify(x.leak)} body=${x.body}`),
    `正对照 A→A(带同伪造头) id=${aid} → ${pcr?.status}`]
  if (bad.length === 0 && pcr?.status === 200)
    pass({ id: `F-${key}`, name: `伪造越权·${R.label}`, detail: `4 种伪造（query/body 风格 tenantId + X-Tenant-Id 头）全部拒绝：${rows.map((x) => x.status).join('/')}；无 B 数据`, evidence: ev })
  else if (bad.length === 0)
    skip({ id: `F-${key}`, name: `伪造越权·${R.label}`, detail: `伪造全被拒，但**正对照未 200**（实测 ${pcr?.status}）⇒ 结论弱化：无法排除「路径本就无效」`, evidence: ev })
  else fail({ id: `F-${key}`, name: `伪造越权·${R.label}`, detail: `🔴 ${bad.map((x) => x.f + ':' + x.status).join(' ')}`, evidence: ev })
}
// body 内伪造 tenantId（写面）
{
  const bIds = dbIds('products', 21); const bid = bIds[0]
  const before = rowSnapshot('products', bid, realCols('products', ['name', 'base_price', 'status', 'updated_at', 'deleted']))
  const r = await api('PUT', `/api/admin/products/${bid}`, { token: tok.A, body: { name: '伪造越权探针', tenantId: 21, tenant_id: 21 } })
  const after = rowSnapshot('products', bid, realCols('products', ['name', 'base_price', 'status', 'updated_at', 'deleted']))
  const ok = denied(r.status) && JSON.stringify(before) === JSON.stringify(after)
  const o = { id: 'F-body', name: '伪造越权·body.tenantId', detail: `A 的 token + body{tenantId:21,name:'伪造越权探针'} PUT B 的商品 → ${r.status}；库未变=${JSON.stringify(before) === JSON.stringify(after)}`,
    evidence: [`PUT /api/admin/products/${bid} body={"name":"伪造越权探针","tenantId":21} → ${r.status} ${cut(r.text, 240)}`, `before=${cut(before, 200)} after=${cut(after, 200)}`], res: 'products' }
  ok ? pass(o) : fail(o)
}

// ─────────── 7. 未认证 / 乱 token / 篡改 token
const tamper = (t) => { const p = t.split('.'); return p[0] + '.' + p[1].slice(0, -2) + 'xy.' + p[2] }
const AUTH_CASES = [
  { name: '无 token', token: undefined, h: {} },
  { name: '乱 token', token: 'garbage.token.value', h: {} },
  { name: '篡改 token（签名改字符）', token: tamper(tok.A), h: {} },
]
for (const key of ['products', 'orders', 'users', 'customers']) {
  const R = RESOURCES.find((x) => x.key === key)
  const aIds = dbIds(R.table, 20); if (!aIds.length || !R.read) { skip({ id: `N-${key}`, name: `未认证·${R.label}`, detail: '无对象/无读端点' }); continue }
  const aid = aIds[0]; const rows = []
  for (const c of AUTH_CASES) { const r = await api('GET', R.read(aid), { token: c.token, headers: c.h }); rows.push({ n: c.name, status: r.status, body: cut(r.text, 140) }) }
  const pc = await api('GET', R.read(aid), { token: tok.A })
  const bad = rows.filter((x) => !denied(x.status))
  const ev = [...rows.map((x) => `${x.n} → ${x.status} ${x.body}`), `正对照 A→A 有效 token → ${pc.status}`]
  if (bad.length === 0 && pc.status === 200) pass({ id: `N-${key}`, name: `未认证·${R.label}`, detail: `无/乱/篡改 token 全拒：${rows.map((x) => x.status).join('/')}；正对照 200`, evidence: ev })
  else if (bad.length === 0) skip({ id: `N-${key}`, name: `未认证·${R.label}`, detail: `全拒但正对照非 200（${pc.status}）⇒ 不可判`, evidence: ev })
  else fail({ id: `N-${key}`, name: `未认证·${R.label}`, detail: `🔴 ${bad.map((x) => x.n + ':' + x.status).join(' ')}`, evidence: ev })
}

// ─────────── 8. 角色越权：商家 token 打平台级端点
const PLATFORM = ['/api/super-admin/registrations?page=1&size=5', '/api/super-admin/registrations/x', '/api/super-admin/registrations/x/approve']
const rows8 = []
for (const p of PLATFORM) {
  const r = await api(p.includes('approve') ? 'PUT' : 'GET', p, { token: tok.A, body: p.includes('approve') ? {} : undefined })
  rows8.push({ p, status: r.status, body: cut(r.text, 160) })
}
const pr8 = await api('GET', '/api/super-admin/registrations?page=1&size=5', { token: tok.P })
const bad8 = rows8.filter((x) => !denied(x.status))
const ev8 = [...rows8.map((x) => `A(商家 admin, tenant 20) → ${x.p} → ${x.status} ${x.body}`), `正对照 超管 P → ${pr8.status} ${cut(pr8.text, 160)}`]
if (bad8.length === 0) pass({ id: 'ROLE-plat', name: '角色越权·平台级端点', detail: `商家 admin 打 ${rows8.length} 个 /api/super-admin/** 全拒（${rows8.map((x) => x.status).join('/')}）；超管正对照 ${pr8.status}`, evidence: ev8 })
else fail({ id: 'ROLE-plat', name: '角色越权·平台级端点', detail: `🔴 ${bad8.map((x) => x.p + ':' + x.status).join(' ')}`, evidence: ev8 })
// 店家管理员是否有租户管理类端点（租户 CRUD）
const reg = await api('GET', '/api/admin/tenants', { token: tok.A })
rec({ id: 'ROLE-tenants', name: '角色越权·租户管理端点存在性', verdict: reg.status === 404 ? 'pass' : 'skip',
  detail: reg.status === 404 ? '不存在商家侧「租户管理」端点（GET /api/admin/tenants → 404）⇒ 如实登记「不存在」' : `GET /api/admin/tenants → ${reg.status}（存在，需另行判权）`,
  evidence: [`GET /api/admin/tenants → ${reg.status} ${cut(reg.text, 200)}`] })

// ─────────── 9. 平台超管反向对照（若跨租户读被允许 ⇒ 设计允许，不得报成缺陷）
const CROSS = [['products', '商品'], ['orders', '订单'], ['customers', '客户'], ['users', '员工用户']]
for (const [key, label] of CROSS) {
  const R = RESOURCES.find((x) => x.key === key)
  const bIds = dbIds(R.table, 21)
  if (!bIds.length || !R.read) { skip({ id: `SA-${key}`, name: `超管反向对照·${label}`, detail: 'B 无对象/无读端点' }); continue }
  const r = await api('GET', R.read(bIds[0]), { token: tok.P })
  const bodyHasB = r.status === 200 && leakIn(r.text, bIds).length > 0
  rec({ id: `SA-${key}`, name: `超管反向对照·${label}`, verdict: 'pass',
    detail: `超管(P tenantId=-1) 读 B(21) 的 ${label} → ${r.status}${bodyHasB ? '（返回体含 B 的 id ⇒ **平台跨租户读 = 设计允许**）' : '（未返回 B 数据）'}`,
    evidence: [`GET ${R.read(bIds[0])} (超管 token) → ${r.status} ${cut(r.text, 300)}`] })
}
for (const key of ['products']) {
  const R = RESOURCES.find((x) => x.key === key); const bid = dbIds(R.table, 21)[0]
  const rows = []
  for (const f of FORGE) { const r = await api('GET', R.read(bid) + f.q, { token: tok.A, headers: f.h }); rows.push(`${f.name}→${r.status}`) }
  pass({ id: 'SA-note', name: '超管反向对照·判据边界', detail: `同一伪造手法在商家 token 下：${rows.join(' ')}（若上面超管能读 ⇒ 差异来自**主体身份**而非伪造头，属设计允许）`, evidence: rows })
}
writeFileSync(OUT + `sweep2-${FLIP ? 'flip' : 'main'}.json`, JSON.stringify(recs, null, 1))
const c = (v) => recs.filter((r) => r.verdict === v).length
log(`=== 批次2 读数（${FLIP ? 'FLIP' : '主跑'}）：pass=${c('pass')} fail=${c('fail')} skip=${c('skip')} total=${recs.length}`)
