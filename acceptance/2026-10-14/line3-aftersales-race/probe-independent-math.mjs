// 线③ 独立算式探针（**本线自建工装**，不改既有 harness）：售后退货回补的**端到端**两侧判据。
// 目标（任务书：退款金额/库存期望值必须由本线独立算式给出）：
//   ① 自己建品（自定 stock=137.0）、自建订单（qty=3）、自己确认收款 ⇒ 记下扣减后读数 S1；
//   ② 退货工单 pending→processing→resolved ⇒ 记下 S2 / 台账行；
//   ③ 期望**由本线算式给出**：ON 侧 S2 == S1 + qty(=3) 且台账 delta==+3；
//      OFF 侧 S2 == S1 且该工单号下台账 0 行；两侧 orders.refund_amount == 传入金额。
// 纪律：只碰本前缀对象（PROBE_PREFIX=线③独立 名域 + LB3IS 机器前缀）；用后由本线清理器删。
import { createProbeProduct, createProbeOrder, skuStock, orderRow, psql, api, loginApi,
         TENANT_ID, PROBE_PREFIX, ID_PREFIX, nowCST } from '/Users/guangzhen.zk/ai native/migao/acceptance/2026-10-03/aftersales-concurrency-sweep/harness/lib.mjs'

const R = []
const rec = (id, verdict, detail, evidence, extra = {}) => { R.push({ id, verdict, detail, evidence, ...extra }); console.log(`[${verdict.toUpperCase()}] ${id} — ${detail}`) }
const num = (v) => Number(v)

const l = await loginApi()
const TOK = l.token
if (Number(l.raw?.user?.tenantId) !== TENANT_ID) throw new Error(`登录租户不符：${l.raw?.user?.tenantId} != ${TENANT_ID}`)
console.log(`登录 tenant=${l.raw.user.tenantId}；本线命名域前缀=${PROBE_PREFIX}；独立算式基准 stock=137.0 / qty=3 / 单价 50 ⇒ 实收 ¥150.00`)

const ON = { allowRestock: true, tag: 'IS-ON' }
const OFF = { allowRestock: false, tag: 'IS-OFF' }
const STOCK0 = 137.0, QTY = 3, UNIT = 50
const REFUND = '150.00'

for (const C of [ON, OFF]) {
  // ── 夹具（全部本线自建；期望一律本线算式）──
  const p = await createProbeProduct(TOK, { allowRestock: C.allowRestock, stock: STOCK0, price: UNIT, tag: C.tag })
  if (!p.ok) { rec(`LB3-${C.tag}-FIXTURE`, 'skip', `建品失败 ${p.resp?.status} ${p.resp?.text?.slice(0, 200)}`, []); continue }
  const skuAtCreate = num(p.stock)
  const o = await createProbeOrder(TOK, { productId: p.productId, productName: p.name, skuId: p.skuId, skuCode: p.skuCode, colorId: p.colorId, qty: QTY, unitPrice: UNIT, tag: C.tag })
  if (!o.ok) { rec(`LB3-${C.tag}-FIXTURE`, 'skip', `建单失败 ${o.resp?.status} ${o.resp?.text?.slice(0, 200)}`, []); continue }

  const S1 = num(skuStock(p.skuId)?.stock)
  const actual = num(orderRow(o.orderId)?.actual_amount)
  rec(`LB3-${C.tag}-DEDUCT`, (S1 === STOCK0 - QTY && actual === QTY * UNIT) ? 'pass' : 'fail',
    `确认收款后 SKU ${skuAtCreate}→${S1}（本线算式 ${STOCK0}-${QTY}=${STOCK0 - QTY}）；实收 ${actual}（算式 ${QTY}×${UNIT}=${QTY * UNIT}）`,
    [`建品响应 stock=${p.stock}`, `订单 actual_amount=${actual}`, `扣减后 skuStock=${S1}`],
    { skuId: p.skuId, orderId: o.orderId })

  // ── 退货工单：pending → processing → resolved ──
  const c = await api('POST', '/api/admin/after-sales', { token: TOK, body: {
    orderId: o.orderId, ticketType: 'return', description: `${PROBE_PREFIX}工单-独立算式-${C.tag}`, refundAmount: REFUND } })
  const tid = c.data?.id, tno = c.data?.ticketNo
  const mk = await api('PUT', `/api/admin/after-sales/${tid}/status`, { token: TOK, body: { status: 'processing', remark: `${PROBE_PREFIX}：受理` } })
  const rs = await api('PUT', `/api/admin/after-sales/${tid}/status`, { token: TOK, body: { status: 'resolved', remark: `${PROBE_PREFIX}：退货完结` } })

  const S2 = num(skuStock(p.skuId)?.stock)
  const led = psql(`select id, delta, before_qty, after_qty, reason, ref_no from stock_ledger_entries where tenant_id=${TENANT_ID} and ref_no='${tno}'`)
  const row = orderRow(o.orderId)
  const refundSide = num(row?.refund_amount)
  const expectStock = C.allowRestock ? STOCK0 - QTY + QTY : STOCK0 - QTY   // 本线算式（ON 回补 / OFF 不回补）
  const expectLedger = C.allowRestock ? 1 : 0
  const expectLedgerDelta = C.allowRestock ? QTY : 0

  const ok = S2 === expectStock && led.length === expectLedger && refundSide === QTY * UNIT
    && (!C.allowRestock || num(led[0]?.delta) === expectLedgerDelta)
  rec(`LB3-${C.tag}-RESTOCK`, ok ? 'pass' : 'fail',
    `开关${C.allowRestock ? '开' : '关'}：工单 ${tno} 完结 ⇒ SKU ${S1}→${S2}（本线算式 ${expectStock}）；台账 ${led.length} 行（算式 ${expectLedger}）；退款 ${refundSide}（算式 ${QTY * UNIT}）`,
    [`期望来源: 本线独立算式（stock0=${STOCK0}, qty=${QTY}）+ 产品开关 allow_return_restock=${C.allowRestock}`,
     `创建工单 status=${c.status} / processing=${mk.status} / resolved=${rs.status}`,
     `台账原始读数: ${JSON.stringify(led)}`,
     `订单退款侧: refund_amount=${row?.refund_amount} refund_at=${row?.refund_at}`,
     `工单号=${tno} 工单id=${tid} 探针 SKU=${p.skuId} 探针订单=${o.orderId}`],
    { skuId: p.skuId, orderId: o.orderId, ticketId: tid, ticketNo: tno, stockBefore: S1, stockAfter: S2, ledgerRows: led.length })
}

console.log('\n=== 独立算式探针汇总 ===')
console.log(JSON.stringify({ at: nowCST().cst, tenant: TENANT_ID, prefix: PROBE_PREFIX, idPrefix: ID_PREFIX, counts: {
  pass: R.filter((r) => r.verdict === 'pass').length, fail: R.filter((r) => r.verdict === 'fail').length, skip: R.filter((r) => r.verdict === 'skip').length }, records: R }, null, 2))
