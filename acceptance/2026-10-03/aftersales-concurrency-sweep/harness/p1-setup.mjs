// p1-setup —— 建本包的**探针夹具**：一个可退款的已确认订单 + 一条带 skuId 的明细（含回补开关两侧的商品）
// 用法：API_BASE=http://127.0.0.1:8080 node p1-setup.mjs
//
// 为什么走真实 API 而不是 SQL 插行：本线测的就是**写面**（建单/确认收款/退款/售后完结），
// 用 SQL 造单会让「扣库存 / 落台账 / 算实收」这些前置事实失去可信来源。
import { writeFileSync, existsSync } from 'node:fs'
import {
  adminToken, createProbeProduct, createProbeOrder, orderRow, skuStock, ledgerRowsFor,
  outPath, log, nowCST, Recorder, psql, one, cents, fmtQty, qtyEq,
} from './lib.mjs'

const R = new Recorder('B1-setup.json')
const { token, via } = await adminToken()
log(`鉴权成功（via=${via}）`)
writeFileSync(outPath('.token'), String(token))

/** 建「商品 + 已确认订单」一组夹具；restock 控制 allow_return_restock。 */
async function fixture(tag, { allowRestock, stock = 100, qty = 2, unitPrice = 100 }) {
  const p = await createProbeProduct(token, { allowRestock, stock, price: unitPrice, tag })
  if (!p.ok) return { ok: false, step: 'product', resp: p.resp, body: p.body }
  const o = await createProbeOrder(token, {
    productId: p.productId, productName: p.name, skuId: p.skuId, skuCode: p.skuCode,
    colorId: p.colorId, qty, unitPrice, tag,
  })
  if (!o.ok) return { ok: false, step: 'order', resp: o.resp, body: o.body, product: p }
  const row = orderRow(o.orderId)
  const sku = skuStock(p.skuId)
  return { ok: true, tag, allowRestock, product: p, order: o, orderRow: row, skuAfter: sku, qty, unitPrice }
}

const out = { at: nowCST(), via, fixtures: {} }
// ① 回补开关**开**侧：allow_return_restock = true（退货完结应回补库存）
out.fixtures.restockOn = await fixture('RESTOCKON', { allowRestock: true })
// ② 回补开关**关**侧：allow_return_restock = false（默认；退货完结库存零变化）
out.fixtures.restockOff = await fixture('RESTOCKOFF', { allowRestock: false })
// ③ 退款金额专用（不回补，避免库存噪声干扰判据）
out.fixtures.refund = await fixture('REFUND', { allowRestock: false, qty: 2, unitPrice: 150 })

writeFileSync(outPath('B1-fixtures.json'), JSON.stringify(out, null, 2))

// ── 夹具自证：期望由**本包独立算式**给出，不读产品读面 ──
for (const [name, f] of Object.entries(out.fixtures)) {
  if (!f.ok) { R.fail(`LB1-SETUP-${name}`, `夹具 ${name}`, `建夹失败于 ${f.step}: ${f.resp?.status} ${f.resp?.text?.slice(0, 200)}`, []); continue }
  const expectTotal = (cents(f.unitPrice) * BigInt(f.qty))
  const totalOk = qtyEq(f.orderRow.total_amount, fmtQty(expectTotal))
  const expectStock = cents(100) - cents(f.qty)   // 确认收款扣 2 ⇒ 100-2 = 98
  const stockOk = qtyEq(f.skuAfter.stock, fmtQty(expectStock))
  const confirmOk = f.order.confirmResp?.json?.success === true
  const statusOk = f.orderRow.status === 'confirmed'
  const pass = totalOk && stockOk && confirmOk && statusOk
  R.add(`LB1-SETUP-${name}`, `夹具 ${name}（商品+已确认订单）`, pass ? 'pass' : 'fail',
    `orderNo=${f.orderRow.order_no} status=${f.orderRow.status} 实收=${f.orderRow.actual_amount} 总额=${f.orderRow.total_amount} 明细后 SKU 库存=${f.skuAfter.stock}`,
    [`期望来源: 本包独立算式 —— 单价 ${f.unitPrice} × 数量 ${f.qty} = ${fmtQty(expectTotal)}；库存 100 − ${f.qty} = ${fmtQty(expectStock)}`,
     `确认收款响应: ${JSON.stringify(f.order.confirmResp?.json).slice(0, 200)}`,
     `产品侧商品 id=${f.product.productId} skuId=${f.product.skuId} allow_return_restock=${f.allowRestock}`,
     `订单 id=${f.order.orderId} 幂等键域: 无（本夹具不经幂等层）`],
    { fixture: name, orderId: f.order.orderId, orderNo: f.orderRow.order_no, productId: f.product.productId, skuId: f.product.skuId })
}

// ── 扣减台账自证（确认收款应落 reason=order 行，delta=-2）──
const ro = out.fixtures.restockOn
if (ro.ok) {
  const led = psql(`select id, delta, before_qty, after_qty, reason, ref_no from stock_ledger_entries
                    where tenant_id=20 and ref_no='${ro.orderRow.order_no}' and sku_id=${ro.product.skuId}`)
  const d = led[0]?.delta
  R.add('LB1-SETUP-ledger', '确认收款落扣减台账（order 腿）', (led.length === 1 && qtyEq(d, '-2.000')) ? 'pass' : 'fail',
    `台账行数=${led.length} delta=${d} before=${led[0]?.before_qty} after=${led[0]?.after_qty} ref_no=${led[0]?.ref_no}`,
    ['期望来源: 本包独立算式 —— 确认收款扣 2 米 ⇒ 台账恰一行 delta = −2.000（before 100 → after 98）',
     `原始行: ${JSON.stringify(led)}`])
}

log(`p1-setup 完成：${JSON.stringify(R.summary())}；夹具已落 out/B1-fixtures.json`)
