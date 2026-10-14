// 线② 最小复现（M8-01 幂等重放 422 / M9-01 超报未拒）—— 只为本轮判据取原始证据，不改产品代码。
//
// 判据来源（被测 harness 断言原文）：
//   M8-01 期望 `before===after && data.replayed===true`，实测 HTTP 422、replayed=undefined
//   M9-01 期望 HTTP 422 且 message 含「超上限」，实测 HTTP 200
// 本脚本 = 最小复现 + 原始响应体留存（含 X-Client-Request-Id 三态对照），收尾自清。
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
// 复用被测 harness 的共享库（不复制、不改动它）——绝对路径 import，故本脚本可放任意目录
import { api, loginApi, psql, one, log, OUT, guardedWrite } from '/Users/guangzhen.zk/ai native/migao/acceptance/2026-10-03/piecework-wage-sweep/harness/lib.mjs'

const T = 32
const PHONE = process.env.ADMIN_PHONE || '13800138000'
const RUN = `REPRO${String(Date.now()).slice(-6)}`
const PFX = `线②复现${RUN}`
const WORKER = `${PFX}工人`
const RATED = 0.4
const out = { run: RUN, at: new Date().toISOString(), probes: [], reports: [], note: '' }

const { token } = await loginApi(PHONE)

// ── 建探针对象（与 p1-p2-matrix.buildProbe 同形，只改前缀）──
const cat = await api('POST', '/api/admin/categories', { token, body: { name: PFX, sortOrder: 1 } })
const catId = cat.json?.data?.id
const prod = await api('POST', '/api/admin/products', {
  token, body: {
    name: PFX, unit: '米', pricingType: 'fixed', basePrice: 68,
    status: catId ? 'on_sale' : 'draft', categoryId: catId,
    colors: [{ colorName: '本白', mainColorHex: '#FAFAFA', sortOrder: 1 }],
    skus: [{ colorName: '本白', doorWidth: '2.8m', price: 68, stock: 100000, skuCode: `${RUN}-SKU` }],
  },
})
const productId = prod.json?.data?.id
const skuId = one(`select id::text as id from product_skus where product_id='${productId}'`)?.id
out.created = { catId, productId, skuId, prodStatus: prod.status, catStatus: cat.status }

const items = [{
  productId, skuId, productName: `${PFX}行`, quantity: 1, unitPrice: 68, subtotal: 68, width: 2.8, height: 2.6,
  processingInfo: {
    sku: null, colorName: '本白', unit: '米', sellingMethod: 'bulk_cut',
    fabric_meters: 12.3, pleat_count: 40, panels: 2, holes: 24, fullness: 2, fullness_actual: 2,
    curtainType: '布帘', craft: '罗马帘',
    processingItems: [{ id: 'pi_repro', name: '锁边', quantity: 1, unit: '米' }],
  },
}]
const order = await api('POST', '/api/admin/orders', {
  token, body: {
    customerName: PFX, customerPhone: '13300000004', customerAddress: '杭州市余杭区复现路 1 号',
    logisticsType: 'express', logisticsCompany: '顺丰速运', items,
  },
})
const orderId = order.json?.data?.id
await api('PUT', `/api/admin/orders/${orderId}/payment`, { token })
const gen = await api('POST', '/api/admin/processing-orders/generate', { token, body: { orderIds: [orderId] } })
const po = one(`select id, processing_order_no from processing_orders where order_id='${orderId}' and tenant_id=${T} order by created_at desc limit 1`)
out.created = { ...out.created, orderId, poId: po?.id, poNo: po?.processing_order_no, orderStatus: order.status, genStatus: gen.status }
if (!po) throw new Error(`派工失败 ${gen.status}: ${gen.text.slice(0, 200)}`)

const instRows = () => psql(`select id, operation_name, seq, qty::text as qty, done_qty::text as done_qty,
  unit_price::text as unit_price from processing_position_operations
  where processing_order_id='${po.id}' and coalesce(deleted,0)=0 order by seq`)
const logRows = () => psql(`select id, operation_name, worker_name, qty::text as qty, qualified_qty::text as qualified_qty,
  unit_price::text as unit_price, work_type from production_work_logs
  where tenant_id=${T} and processing_order_id='${po.id}' order by created_at`)

let rows = instRows()
out.instanceOps = rows.map((r) => `${r.operation_name}(qty=${r.qty},seq=${r.seq})`)
// 取前两道工序做探针：甲的应做量在报告里会被改小以构造「超应做」
const opA = rows[0], opB = rows[1]
const setPrice = (id, price, qty) => guardedWrite(`-- probe-ok
update processing_position_operations set unit_price=${price === null ? 'NULL' : price}${qty === undefined ? '' : `, qty=${qty}`}, updated_at=NOW()
where id='${id}' and processing_order_id='${po.id}'`)
setPrice(opA.id, RATED, 20)
setPrice(opB.id, RATED, 20)
out.pricedOps = instRows().map((r) => `${r.operation_name}@${r.unit_price} qty=${r.qty}`)

const report = async (label, id, body, key, extraHeaders = {}) => {
  const r = await api('POST', `/api/admin/production/orders/${orderId}/operations/${id}/report`,
    { token, body, headers: { ...(key ? { 'X-Client-Request-Id': key } : {}), ...extraHeaders } })
  const rec = {
    label, key: key ?? null, body,
    http: r.status, resp: r.json ?? r.text.slice(0, 400),
  }
  out.reports.push(rec)
  log(`[${label}] key=${key ?? '-'} HTTP ${r.status} ${JSON.stringify(r.json?.error ?? r.json?.data ?? r.text.slice(0, 120))}`)
  return { r, rec }
}

// ① 正常报工（opA qty=4，打基线）
await report('M8-a1 幂等键首次', opA.id, { worker_name: WORKER, qty: 4, qualified_qty: 4, work_type: 'normal' }, `${RUN}-IDEM`)
// ② 同键同体重放（被测 harness 的 M8-01 断言形态）
await report('M8-a2 幂等键重放', opA.id, { worker_name: WORKER, qty: 4, qualified_qty: 4, work_type: 'normal' }, `${RUN}-IDEM`)
// ③ 同键不同体（幂等键冲突应如何？）
await report('M8-a3 同键不同体', opA.id, { worker_name: WORKER, qty: 1, qualified_qty: 1, work_type: 'normal' }, `${RUN}-IDEM`)
// ④ 换新键、同操作同量（区分「幂等」与「重复提交窗口」：若这也被拒 ⇒ 与幂等键无关）
await report('M8-a4 新键同操作同量', opA.id, { worker_name: WORKER, qty: 4, qualified_qty: 4, work_type: 'normal' }, `${RUN}-OTHER`)
// ⑤ 超应做（opB 应做 20，报 30 ⇒ 期望 422「超上限」）
await report('M9-b1 超应做', opB.id, { worker_name: WORKER, qty: 30, qualified_qty: 30, work_type: 'normal' }, `${RUN}-OVER`)
// ⑥ 精确等于应做（20 ⇒ 合法，正对照）
await report('M9-b2 等于应做', opB.id, { worker_name: WORKER, qty: 20, qualified_qty: 20, work_type: 'normal' }, `${RUN}-EXACT`)
// ⑦ 再超报 1（已报满 20 ⇒ 期望拒）
await report('M9-b3 报满后再报', opB.id, { worker_name: WORKER, qty: 1, qualified_qty: 1, work_type: 'normal' }, `${RUN}-OVER2`)
// ⑧ 【M8-01 精确复现】对**已报满**的 opB 用同一幂等键连报两次 qty=1：
//    被测 harness 的 M8-01 正是这个形态（opRated2 先被 step r2 报满 20，再用新键报 qty=1 两次）
await report('M8-c1 已报满+键首用', opB.id, { worker_name: WORKER, qty: 1, qualified_qty: 1, work_type: 'normal' }, `${RUN}-FULL`)
await report('M8-c2 已报满+同键重放', opB.id, { worker_name: WORKER, qty: 1, qualified_qty: 1, work_type: 'normal' }, `${RUN}-FULL`)

out.logsAfter = logRows()
out.instancesAfter = instRows().map((r) => `${r.operation_name} done=${r.done_qty}/${r.qty} @${r.unit_price}`)

// ── 自清（只删本前缀对象）──
const sql = [
  `delete from worker_report_audits where tenant_id=${T} and processing_order_id='${po.id}'`,
  `delete from production_work_logs where tenant_id=${T} and processing_order_id='${po.id}'`,
  `delete from processing_set_part_tokens where tenant_id=${T} and processing_order_id='${po.id}'`,
  `delete from processing_position_operations where tenant_id=${T} and processing_order_id='${po.id}'`,
  `delete from processing_order_sets where tenant_id=${T} and processing_order_id='${po.id}'`,
  `delete from processing_orders where tenant_id=${T} and id='${po.id}'`,
  `delete from order_logistics where tenant_id=${T} and order_id='${orderId}'`,
  `delete from order_items where tenant_id=${T} and order_id='${orderId}'`,
  `delete from orders where tenant_id=${T} and id='${orderId}'`,
  `delete from stock_batch_consumptions where tenant_id=${T} and product_id='${productId}'`,
  `delete from stock_batches where tenant_id=${T} and product_id='${productId}'`,
  `delete from fabric_remnants where tenant_id=${T} and product_id='${productId}'`,
  `delete from stock_ledger_entries where tenant_id=${T} and product_id='${productId}'`,
  `delete from product_colors where tenant_id=${T} and product_id='${productId}'`,
  `delete from product_skus where tenant_id=${T} and product_id='${productId}'`,
  `delete from product_attributes where tenant_id=${T} and product_id='${productId}'`,
  `delete from products where tenant_id=${T} and id='${productId}'`,
  `delete from categories where tenant_id=${T} and id='${catId}'`,
]
out.cleanup = []
for (const s of sql) {
  try { guardedWrite(`-- probe-ok\n${s}`); out.cleanup.push({ sql: s.slice(0, 70), ok: true }) } catch (e) {
    out.cleanup.push({ sql: s.slice(0, 70), ok: false, err: String(e).split('\n').find((l) => l.includes('ERROR')) ?? String(e).slice(0, 150) })
  }
}
out.residueAfter = one(`select
  (select count(*)::int from orders where tenant_id=${T} and id='${orderId}') orders,
  (select count(*)::int from processing_orders where tenant_id=${T} and id='${po.id}') pos,
  (select count(*)::int from production_work_logs where tenant_id=${T} and processing_order_id='${po.id}') logs,
  (select count(*)::int from products where tenant_id=${T} and id='${productId}') products,
  (select count(*)::int from categories where tenant_id=${T} and id='${catId}') cats`)
writeFileSync(join(OUT, 'line2-repro-m8m9.json'), JSON.stringify(out, null, 2))
log(`repro done; 残留=${JSON.stringify(out.residueAfter)}`)
