// p7-refund-negative（线② overlay 版）—— 退款金额负例补强：null / 非法字符串 / 空白串
//
// ⚠️ 与底座 `acceptance/2026-10-03/aftersales-concurrency-sweep/harness/p7-refund-negative.mjs` 的差异（**底座未改**）：
//    底座那份在「③ 空白字符串」的 evidence 模板串里**嵌套了未转义的反引号** ⇒ 文件级 `SyntaxError`
//    ⇒ 底座跑这段时整段 `exit 1`、`B7-refund-negative.json` **不生成**（上一轮 2026-10-03 的 REPORT 也没有 B7 产物
//    —— 即「那段判据其实从未跑过」）。本线把该串改成不带反引号，**判据内容逐字不变**，只修语法。
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
const refundRaw = (orderId, body) => api('PUT', `/api/admin/orders/${orderId}/refund`, { token, body: { refund_reason: `${'线B验收'}负例`, ...body } })

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
     `响应原文: ${r.text.slice(0, 250)}`, `DB orders: ${JSON.stringify(a)}`],
    { extra: { status: r.status, refundAmount: a?.refund_amount, actual: a?.actual_amount } })
}

// ② 非法字符串（非数字）
{
  const B = await freshOrder('N2')
  const r = await refundRaw(B.o.orderId, { refund_amount: '一百元' })
  const b = orderRow(B.o.orderId)
  R.add('LB-REF-C02', '退款：非法字符串（"一百元"）⇒ 422 且零写入（不得 500）',
    r.status === 422 && /格式不正确/.test(r.text) && cents(b?.refund_amount ?? '0') === 0n ? 'pass' : 'fail',
    `${r.status} ${r.bookErr?.code} ${r.bookErr?.message}；refund_amount=${b?.refund_amount}`,
    [`期望来源: 源码 OrderController.refundOrder 的 NumberFormatException ⇒ BusinessException.validationError("退款金额格式不正确")`,
     `响应原文: ${r.text.slice(0, 250)}`],
    { extra: { status: r.status, refundAmount: b?.refund_amount } })
}

// ③ 空白字符串
{
  const C = await freshOrder('N3')
  const r = await refundRaw(C.o.orderId, { refund_amount: '   ' })
  const c = orderRow(C.o.orderId)
  R.add('LB-REF-C03', '退款：空白字符串 "   " ⇒ 视为未传（全额）的口径登记',
    r.status === 200 && qtyEq(c?.refund_amount, c?.actual_amount) ? 'pass' : (r.status === 422 ? 'pass' : 'fail'),
    `${r.status}；refund_amount=${c?.refund_amount} 实收=${c?.actual_amount}`,
    [`期望来源: 源码 OrderController —— amount.toString().isBlank() ⇒ 不改 refundAmount ⇒ 全额`,
     `⚠️ 底座同名文件此处为语法错误（模板串内嵌未转义反引号 ⇒ 整段 SyntaxError、B7 产物不生成）；overlay 只修语法、判据逐字不变`,
     `响应原文: ${r.text.slice(0, 250)}`],
    { extra: { status: r.status, refundAmount: c?.refund_amount, actual: c?.actual_amount } })
}

log(`p7 完成：${JSON.stringify(R.summary())}`)
