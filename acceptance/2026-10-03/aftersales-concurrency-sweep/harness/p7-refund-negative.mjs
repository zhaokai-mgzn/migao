// p7-refund-negative —— 退款金额负例补强：`refund_amount: null` 与非法字符串
// 用法：API_BASE=http://127.0.0.1:8080 node p7-refund-negative.mjs
import { api, adminToken, psql, outPath, log, nowCST, Recorder, orderRow, financeRefundRows,
         cents, qtyEq, createProbeOrder, createProbeProduct } from './lib.mjs'

const R = new Recorder('B7-refund-negative.json')
const { token, via } = await adminToken()
log(`鉴权成功（via=${via}）`)

async function freshOrder(tag) {
  const p = await createProbeProduct(token, { allowRestock: false, stock: 100, price: 150, tag })
  const o = await createProbeOrder(token, { productId: p.productId, productName: p.name, skuId: p.skuId, skuCode: p.skuCode, colorId: p.colorId, qty: 2, unitPrice: 150, tag })
  return { p, o, row: orderRow(o.orderId) }
}
const refundRaw = (orderId, body) => api('PUT', `/api/admin/orders/${orderId}/refund`, { token, body: { refund_reason: '线B验收负例', ...body } })

// ① refund_amount: null ⇒ 应等价「未传」= 全额退款
{
  const A = await freshOrder('N1')
  const r = await refundRaw(A.o.orderId, { refund_amount: null })
  const a = orderRow(A.o.orderId)
  const fin = financeRefundRows(A.o.orderId)
  R.add('LB-REF-C01', '退款：refund_amount=null（显式 null，非缺键）⇒ 等价未传 = 全额退款',
    r.status === 200 && qtyEq(a?.refund_amount, a?.actual_amount) && fin.length === 1 && qtyEq(fin[0]?.amount, a?.actual_amount) ? 'pass'
      : (r.status === 422 ? 'pass' : 'fail'),
    `${r.status}；refund_amount=${a?.refund_amount} 实收=${a?.actual_amount}；流水 ${fin.length} 行 ${fin.map((x) => x.amount).join(',')}`,
    [`期望来源: 源码 backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java —— body.containsKey("refund_amount") 且值为 null ⇒ 不改 refundAmount（保持 null）⇒ service 侧「null = 全额」`,
     `响应原文: ${r.text.slice(0, 250)}`, `DB orders: ${JSON.stringify(a)}`])

// ② 非法字符串
{
  const B = await freshOrder('N2')
  const r = await refundRaw(B.o.orderId, { refund_amount: '一百元' })
  const b = orderRow(B.o.orderId)
  R.add('LB-REF-C02', '退款：非法字符串（"一百元"）⇒ 422 且零写入（不得 500）',
    r.status === 422 && /格式不正确/.test(r.text) && cents(b?.refund_amount ?? '0') === 0n ? 'pass' : 'fail',
    `${r.status} ${r.bookErr?.code} ${r.bookErr?.message}；refund_amount=${b?.refund_amount}`,
    [`期望来源: 源码 OrderController.refundOrder 的 NumberFormatException ⇒ BusinessException.validationError("退款金额格式不正确")`,
     `响应原文: ${r.text.slice(0, 250)}`])

// ③ 空白字符串 "   "
{
  const C = await freshOrder('N3')
  const r = await refundRaw(C.o.orderId, { refund_amount: '   ' })
  const c = orderRow(C.o.orderId)
  R.add('LB-REF-C03', '退款：空白字符串 "   " ⇒ 视为未传（全额）的口径登记',
    r.status === 200 && qtyEq(c?.refund_amount, c?.actual_amount) ? 'pass' : (r.status === 422 ? 'pass' : 'fail'),
    `${r.status}；refund_amount=${c?.refund_amount} 实收=${c?.actual_amount}`,
    [`期望来源: 源码 OrderController —— `amount.toString().isBlank()` ⇒ 不改 refundAmount ⇒ 全额`,
     `响应原文: ${r.text.slice(0, 250)}`])

log(`p7 完成：${JSON.stringify(R.summary())}`)
