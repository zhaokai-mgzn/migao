// 集成侧**独立**复现：同一工单并发状态流转（PUT /api/admin/after-sales/{id}/status）
// 目的：判定「部署面行为」与「被测 SHA ff655a06c 的源码（含 #6220 原子条件更新）」是否一致。
// 不采信任何子代理 harness 的结论；本脚本自带夹具、自带顺序对照、自带清理。
//
// 用法（仓库根）：
//   API_BASE=https://api.migaozn.com TENANT_ID=25 ADMIN_PHONE=13800138000 SMS_CODE=123456 \
//   OUT_DIR=acceptance/2026-10-04/env/out node acceptance/2026-10-04/env/repro-cas-independent.mjs
import { writeFileSync } from 'node:fs'
import {
  api, adminToken, psql, one, outPath, nowCST, raceStart, overlapEvidence,
  orderRow, ticketRow, skuStock, guardedWrite, createProbeProduct, createProbeOrder, TENANT_ID,
} from '../../../acceptance/2026-10-03/aftersales-concurrency-sweep/harness/lib.mjs'

const TAG = 'ZCAS集成复核'
const out = { at: nowCST(), tenant: TENANT_ID, steps: {} }
const rec = []
const note = (k, v) => { out.steps[k] = v; rec.push(`${k}: ${JSON.stringify(v).slice(0, 300)}`) }

const { token, via } = await adminToken()
note('auth', { via, tokenLen: String(token).length })

// ── 夹具（自建，走真实 API）──
const p = await createProbeProduct(token, { allowRestock: true, stock: 100, price: 150, tag: TAG })
const o = await createProbeOrder(token, {
  productId: p.productId, productName: p.name, skuId: p.skuId, skuCode: p.skuCode,
  colorId: p.colorId, qty: 2, unitPrice: 150, tag: TAG,
})
note('fixture', { productId: p.productId, skuId: p.skuId, orderId: o.orderId, orderNo: o.orderNo ?? orderRow(o.orderId)?.order_no })

const c = await api('POST', '/api/admin/after-sales', {
  token, body: { orderId: o.orderId, ticketType: 'return', description: `${TAG}-双路并发复现`, refundAmount: '300.00' },
})
const ticketId = c.json?.data?.id
const ticketNo = c.json?.data?.ticketNo
note('ticket.create', { status: c.status, ticketId, ticketNo, body: String(c.text || '').slice(0, 200) })

// 先合法推进到 processing（pending → resolved 非法）
const toProc = await api('PUT', `/api/admin/after-sales/${ticketId}/status`, { token, body: { status: 'processing', remark: TAG } })
note('ticket.toProcessing', { status: toProc.status, dbStatus: ticketRow(ticketId)?.status })

// 预热：把连接/JIT 开销挪到 barrier 之前
await Promise.all([1, 2].map(() => api('GET', `/api/admin/orders/${o.orderId}`)))

const skuBefore = skuStock(p.skuId)?.stock
const put = (status, remark) => api('PUT', `/api/admin/after-sales/${ticketId}/status`, { token, body: { status, ...(remark ? { remark } : {}) } })

// ── ① 真并发：N=4 同时打 processing → resolved ──
const race = await raceStart(4, () => put('resolved', `${TAG}-并发`))
const codes = race.results.map((r) => r.out?.status)
const bodies = race.results.map((r) => String(r.out?.text || '').slice(0, 140))
note('race.N4', {
  httpCodes: codes, okCount: codes.filter((x) => x === 200).length,
  overlap: overlapEvidence(race), bodies,
})

const tk = ticketRow(ticketId)
const skuAfter = skuStock(p.skuId)?.stock
const timeline = psql(`select id, action, content from ticket_timeline where tenant_id=${TENANT_ID} and ticket_id='${ticketId}' and action='status_change' order by created_at`)
const ledger = psql(`select id, delta, reason, ref_no from stock_ledger_entries where tenant_id=${TENANT_ID} and ref_no='${ticketNo}' order by id`)
const orderAfter = orderRow(o.orderId)
note('after.race', {
  dbStatus: tk?.status, timelineRows: timeline.length, ledgerRows: ledger.length,
  skuBefore, skuAfter, refundAmount: orderAfter?.refund_amount, actualAmount: orderAfter?.actual_amount,
})

// ── ② 顺序对照（单路串行：第二发必须被状态机拒绝）──
const seq1 = await put('resolved', `${TAG}-串行1`)
const seq2 = await put('resolved', `${TAG}-串行2`)
note('sequential.control', { first: { status: seq1.status, body: String(seq1.text || '').slice(0, 120) }, second: { status: seq2.status, body: String(seq2.text || '').slice(0, 160) } })

// ── ③ 清理（只碰本脚本自建的行；按 FK 拓扑序）──
const ids = { ticketId, orderId: o.orderId, skuId: p.skuId, productId: p.productId }
const clean = () => {
  guardedWrite(`-- ${TAG} 清理\ndelete from ticket_timeline where tenant_id=${TENANT_ID} and ticket_id='${ticketId}';`)
  guardedWrite(`delete from after_sales_tickets where tenant_id=${TENANT_ID} and id='${ticketId}';`)
  guardedWrite(`delete from stock_ledger_entries where tenant_id=${TENANT_ID} and ref_no='${ticketNo}';`)
  guardedWrite(`delete from finance_transactions where tenant_id=${TENANT_ID} and order_id='${o.orderId}';`)
  guardedWrite(`delete from order_items where tenant_id=${TENANT_ID} and order_id='${o.orderId}';`)
  guardedWrite(`delete from orders where tenant_id=${TENANT_ID} and id='${o.orderId}';`)
  guardedWrite(`delete from product_skus where tenant_id=${TENANT_ID} and id=${p.skuId};`)
  guardedWrite(`delete from products where tenant_id=${TENANT_ID} and id='${p.productId}';`)
}
try { clean(); note('cleanup', 'ok') } catch (e) { note('cleanup', `FAILED: ${e.message}`) }

const residue = {
  tickets: psql(`select count(*) c from after_sales_tickets where tenant_id=${TENANT_ID} and id='${ticketId}'`)[0]?.c,
  orders: psql(`select count(*) c from orders where tenant_id=${TENANT_ID} and id='${o.orderId}'`)[0]?.c,
  products: psql(`select count(*) c from products where tenant_id=${TENANT_ID} and id='${p.productId}'`)[0]?.c,
}
note('residue', residue)

writeFileSync(outPath('repro-cas-independent.json'), JSON.stringify(out, null, 2))
console.log(rec.join('\n'))
console.log('\n→ 读数文件: acceptance/2026-10-04/env/out/repro-cas-independent.json')
