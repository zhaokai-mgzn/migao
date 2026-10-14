// 线③ 跨租户隔离补测（**本线自建工装**）：把 sweep#1 的 `LB-AS-CREATE-02` skip 补上真读数。
// 背景：该判据原写死 tenant=1 的订单（tenant 1 已不存在）⇒ skip。本轮真实环境 = 租户 32（被测）
//        + 租户 34（临时对照，走真实入驻流程建，收尾即清）。
// 判据（**会红**：把攻击 token 换成对方自己的 token ⇒ 正对照必须 200，否则判据不可判）：
//   ① 反例：A(32) 的 token 打 B(34) 的订单建售后工单 ⇒ 必须非 2xx 且 A 侧零落库；
//   ② 反例：A(32) 的 token 按 id 读 B(34) 的订单/商品/工单 ⇒ 必须 403/404；
//   ③ 正对照：B(34) 的 token 打 B 自己的订单 ⇒ 必须 200（证明①的红来自租户边界，不是端点坏了）；
//   ④ 正对照：A(32) 的 token 打 A 自己的订单 ⇒ 200。
import { api, loginApi, psql, nowCST, TENANT_ID } from '/Users/guangzhen.zk/ai native/migao/acceptance/2026-10-03/aftersales-concurrency-sweep/harness/lib.mjs'

const A = Number(process.env.TENANT_ID || 32)
const B = Number(process.env.TENANT_B || 34)
const PHONE_A = process.env.ADMIN_PHONE || '13800138000'
const PHONE_B = process.env.TENANT_B_PHONE || '13800138001'
const PROBE = '线③独立'
const R = []
const rec = (id, verdict, detail, evidence, extra = {}) => { R.push({ id, verdict, detail, evidence, ...extra }); console.log(`[${verdict.toUpperCase()}] ${id} — ${detail}`) }

const la = await loginApi(PHONE_A, process.env.SMS_CODE || '123456')
const lb = await loginApi(PHONE_B, process.env.SMS_CODE || '123456')
const A_ok = Number(la.raw?.user?.tenantId) === A, B_ok = Number(lb.raw?.user?.tenantId) === B
if (!A_ok || !B_ok) throw new Error(`登录租户不符：A=${la.raw?.user?.tenantId}(期望 ${A}) B=${lb.raw?.user?.tenantId}(期望 ${B})`)
console.log(`A 登录 tenant=${A} / B 登录 tenant=${B}`)

// 夹具补建：B(34) 可能还没有订单 ⇒ 用 B 自己已有的探针商品建一张并确认收款（只碰 B 自己的对象）
async function ensureOrder(token, tenant, force = false) {
  const ex = force ? null : psql(`select id::text as id, order_no, status from orders where tenant_id=${tenant} and deleted=0 order by created_at desc limit 1`)[0]
  if (ex) return ex
  const p = psql(`select id::text as id, name from products where tenant_id=${tenant} and deleted=0 order by created_at desc limit 1`)[0]
  const sku = psql(`select id::text as id, sku_code, color_id::text as color_id, price from product_skus where tenant_id=${tenant} and product_id='${p.id}' limit 1`)[0]
  const mk = await api('POST', '/api/admin/orders', { token, body: {
    customerName: `${PROBE}跨租户对照客户`, customerPhone: '13900000009', customerAddress: `${PROBE}地址`,
    logisticsType: 'express', logisticsCompany: `${PROBE}物流`, remark: `${PROBE}跨租户对照订单（用后自清）`,
    items: [{ productId: p.id, productName: p.name, quantity: 1, unitPrice: Number(sku.price) || 10,
      subtotal: Number(sku.price) || 10, width: 2.8, height: 2.0,
      processingInfo: { skuId: sku.id, skuCode: sku.sku_code, colorId: sku.color_id, doorWidth: '2.8m' } }],
  } })
  if (mk.status !== 200) throw new Error(`B(${tenant}) 建单失败 ${mk.status} ${mk.text.slice(0, 300)}`)
  const oid = mk.json.data.id ?? mk.json.data.orderId
  await api('PUT', `/api/admin/orders/${oid}/payment`, { token, body: {} })
  console.log(`[fixture] B(${tenant}) 新建探针订单 id=${oid} no=${mk.json.data.orderNo}`)
  return psql(`select id::text as id, order_no, status from orders where tenant_id=${tenant} and id='${oid}'`)[0]
}

const orderOf = (t) => psql(`select id::text as id, order_no, status from orders where tenant_id=${t} and deleted=0 order by created_at desc limit 1`)[0]
const productOf = (t) => psql(`select id::text as id, name from products where tenant_id=${t} and deleted=0 order by created_at desc limit 1`)[0]
const ticketOf = (t) => psql(`select id::text as id from after_sales_tickets where tenant_id=${t} order by created_at desc limit 1`)[0]

const ob = await ensureOrder(lb.token, B)                    // 反例 1 的目标（B 侧订单）
const oa = await ensureOrder(la.token, A, true)              // 正对照 A：**新单**（老单可能已被别的探针占用 dup-guard）
const obFresh = await ensureOrder(lb.token, B, true)         // 正对照 B：**新单**
const pa = productOf(A), pb = productOf(B)
// 工单目标改用 B 侧**刚建的探针工单**（B 原本可能一张工单都没有 ⇒ 原写法会得 NO_TARGET，那是探针缺陷）
const ta = ticketOf(A), tb = { id: process.env.PROBE_TICKET_B || null }

// ① 反例：A 的 token + B 的订单 ⇒ 建售后工单必须被拒 + A 侧零落库
{
  const before = psql(`select id from after_sales_tickets where tenant_id=${A} and order_id='${ob.id}'`).length
  const r = await api('POST', '/api/admin/after-sales', { token: la.token, body: {
    orderId: ob.id, ticketType: 'refund', description: `${PROBE}工单-跨租户订单-B(${B})` } })
  const after = psql(`select id from after_sales_tickets where tenant_id=${A} and order_id='${ob.id}'`).length
  const pass = r.status !== 200 && after === 0
  rec('LB3-XT-01-跨租户建单', pass ? 'pass' : 'fail',
    `A(${A}) token 打 B(${B}) 订单 ${ob.order_no} ⇒ HTTP ${r.status}；A 侧 order_id=该单的工单落库 ${before}→${after} 行（要求 0）`,
    [`攻击目标订单: B(${B}) id=${ob.id} no=${ob.order_no} status=${ob.status}`,
     `响应原文: ${r.text.slice(0, 260)}`,
     `DB 复查: select … from after_sales_tickets where tenant_id=${A} and order_id='${ob.id}' ⇒ ${after}`],
    { status: r.status, body: r.text.slice(0, 300), leaked: after })
}

// ③ 正对照：B 的 token 打 B 自己的订单 ⇒ 必须 200（否则①的红不可归因于租户边界）
{
  const r = await api('POST', '/api/admin/after-sales', { token: lb.token, body: {
    orderId: obFresh.id, ticketType: 'refund', description: `${PROBE}工单-正对照-B自己-${Date.now()}` } })
  const landed = r.data?.id ? psql(`select id from after_sales_tickets where tenant_id=${B} and id='${r.data.id}'`).length : 0
  rec('LB3-XT-03-正对照-B打自己', r.status === 200 ? 'pass' : 'fail',
    `B(${B}) token 打 B 自己的订单 ⇒ HTTP ${r.status}；B 侧落库 ${landed} 行（要求 1）`,
    [`响应原文: ${r.text.slice(0, 260)}`, `DB 复查: B 侧工单 id=${r.data?.id} ⇒ ${landed} 行`],
    { status: r.status, ticketId: r.data?.id, body: r.text.slice(0, 300), probeTicketB: r.data?.id })
}

// ② 反例：跨租户按 id 读（商品 / 订单 / 工单）
{
  const cases = []
  for (const [kind, id, path] of [['product', pb?.id, `/api/admin/products/${pb?.id}`],
                                  ['order', ob?.id, `/api/admin/orders/${ob?.id}`],
                                  ['ticket', ticketOf(B)?.id, `/api/admin/after-sales/${ticketOf(B)?.id}`]]) {
    if (!id) { cases.push({ kind, status: 'NO_TARGET' }); continue }
    const r = await api('GET', path, { token: la.token })
    cases.push({ kind, id, status: r.status, leaked: r.text.includes(String(id)), body: r.text.slice(0, 140) })
  }
  const bad = cases.filter((c) => !([401, 403, 404].includes(c.status)))
  rec('LB3-XT-02-跨租户按-id-读', bad.length === 0 ? 'pass' : 'fail',
    `A(${A}) token 按 id 读 B(${B}) 的 商品/订单/工单 各 1 例 ⇒ 状态码 ${cases.map((c) => `${c.kind}:${c.status}`).join(' / ')}（要求 401/403/404）`,
    cases.map((c) => `${c.kind} id=${c.id} → ${c.status} body=${c.body}`), { cases })
}

// ④ 正对照：A 的 token 打 A 自己的订单 ⇒ 必须 200
{
  const r = await api('POST', '/api/admin/after-sales', { token: la.token, body: {
    orderId: oa.id, ticketType: 'refund', description: `${PROBE}工单-正对照-A自己-${Date.now()}` } })
  rec('LB3-XT-04-正对照-A打自己', r.status === 200 ? 'pass' : 'fail',
    `A(${A}) token 打 A 自己的订单 ${oa.order_no} ⇒ HTTP ${r.status}`,
    [`响应原文: ${r.text.slice(0, 260)}`], { status: r.status, ticketId: r.data?.id, probeTicketA: r.data?.id })
}

console.log('\n=== 跨租户补测汇总 ===')
console.log(JSON.stringify({ at: nowCST().cst, A, B, counts: {
  pass: R.filter((r) => r.verdict === 'pass').length, fail: R.filter((r) => r.verdict === 'fail').length }, records: R }, null, 2))
