// p5-refund-precision —— 退款金额**精度准入**三连（主会话复核指向的 P2·涉钱精度线）
// 用法：API_BASE=http://127.0.0.1:8080 node p5-refund-precision.mjs
//
// 判据（三连 + 类级口径）：
//   ① 0.01 —— 最小可表示（列 numeric(x,2)）⇒ 应成功且**逐字落 0.01**（正对照）
//   ② 0.001 —— 小于最小可表示 ⇒ 应 **4xx 显式拒绝**；现状 200 且静默归零 ⇒ 红
//   ③ 0.004 / 0.005 —— 登记**舍入方向**（口径观察，不判缺陷）
//   红线：orders.refund_amount 与 finance_transactions.amount 必须**相等**（不得一个 0 一个非 0）
import { writeFileSync } from 'node:fs'
import {
  api, adminToken, psql, outPath, log, nowCST, Recorder, judge,
  orderRow, financeRefundRows, cents, fmtQty, qtyEq, createProbeOrder, createProbeProduct,
} from './lib.mjs'

const R = new Recorder('B5-refund-precision.json')
const { token, via } = await adminToken()
log(`鉴权成功（via=${via}）`)

// ── 列类型真值（现查；主会话独立复核过同一组值）──
const colTypes = psql(`select table_name||'.'||column_name as col, data_type||'('||coalesce(numeric_precision::text,'')||','||coalesce(numeric_scale::text,'')||')' as typ
                       from information_schema.columns
                       where (table_name='orders' and column_name in ('refund_amount','actual_amount'))
                          or (table_name='finance_transactions' and column_name='amount')
                          or (table_name='after_sales_tickets' and column_name='refund_amount')
                       order by 1`)
writeFileSync(outPath('B5-col-types.json'), JSON.stringify({ at: nowCST(), colTypes }, null, 2))

const refund = (orderId, amount) => api('PUT', `/api/admin/orders/${orderId}/refund`, { token, body: { refund_reason: '线B验收精度探针', refund_amount: amount } })

async function freshOrder(tag) {
  const p = await createProbeProduct(token, { allowRestock: false, stock: 100, price: 150, tag })
  const o = await createProbeOrder(token, { productId: p.productId, productName: p.name, skuId: p.skuId, skuCode: p.skuCode, colorId: p.colorId, qty: 2, unitPrice: 150, tag })
  return { p, o, row: orderRow(o.orderId) }
}

// ① 0.01 —— 最小可表示 ⇒ 成功且逐字落 0.01（两列都必须逐字 0.01）
{
  const A = await freshOrder('P01')
  const r = await refund(A.o.orderId, '0.01')
  const a = orderRow(A.o.orderId)
  const fin = financeRefundRows(A.o.orderId)
  judge(R, {
    id: 'LB-PREC-01', name: '精度①：refund_amount=0.01（最小可表示）⇒ 成功且**逐字**落 0.01',
    expect: '200；orders.refund_amount=0.01；finance_transactions 恰 1 行 amount=0.01；两者**相等**',
    actual: `${r.status}；orders.refund_amount=${a?.refund_amount}；流水 ${fin.length} 行 amount=${fin.map((x) => x.amount).join(',')}`,
    pass: r.status === 200 && qtyEq(a?.refund_amount, '0.01') && fin.length === 1 && qtyEq(fin[0]?.amount, '0.01') &&
          cents(a?.refund_amount) === cents(fin[0]?.amount),
    expectSource: `本包独立算式：请求值 0.01 = 列可表示的最小正数（列类型现查见 B5-col-types.json）⇒ 两处都必须逐字 0.01`,
    evidence: [`响应原文: ${r.text.slice(0, 250)}`, `DB orders: ${JSON.stringify(a)}`, `DB 流水: ${JSON.stringify(fin)}`,
               `列类型: ${JSON.stringify(colTypes)}`],
    extra: { status: r.status, orderRefund: a?.refund_amount, finance: fin.map((x) => x.amount) },
  })
}

// ② 0.001 —— 小于最小可表示 ⇒ 期望 4xx 显式拒绝；现状 200 + 静默归零 = 红
{
  const B = await freshOrder('P001')
  const r = await refund(B.o.orderId, '0.001')
  const b = orderRow(B.o.orderId)
  const fin = financeRefundRows(B.o.orderId)
  const silentZero = r.status === 200 && cents(b?.refund_amount ?? '0') === 0n
  const twoSidesEqual = fin.length > 0 && cents(b?.refund_amount ?? '0') === cents(fin[0].amount)
  R.add('LB-PREC-02', '精度②：refund_amount=0.001（小于最小可表示）⇒ 应 4xx 显式拒绝；现状 200 静默归零',
    r.status >= 400 && r.status < 500 ? 'pass' : (silentZero ? 'fail' : 'fail'),
    `${r.status}；orders.refund_amount=${b?.refund_amount}；流水 ${fin.length} 行 amount=${fin.map((x) => x.amount).join(',')}；refund_at=${b?.refund_at ? 'set' : 'null'}`,
    [`期望来源: 本仓**类级范式**（同系统内的既有口径）—— 精度不足必须**显式拒绝、不静默取整**：`,
     `   · backend/admin-api/src/main/java/com/migao/admin/service/StockQuantity.java 的 requireOneDecimal（库存数量超 1 位小数 ⇒ 直接拒）`,
     `   · backend/admin-api/src/main/java/com/migao/admin/service/InboundOrderService.java 的 requireItemNumbers（逐字「超 1 位小数显式拒绝、不静默取整」）`,
     `   金额侧**没有**对应准入（源码 backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java 只 new BigDecimal(…) ⇒ 任意精度进入；`,
     `   而 orders.refund_amount / finance_transactions.amount 皆为 numeric(…,2) ⇒ 库内四舍五入）`,
     `⇒ 请求被「成功」接受（HTTP 200 + refund_at 落笔）而退款金额**一分未落**（订单与资金流水两处都 0.00）`,
     `红线断言: orders.refund_amount 与 finance_transactions.amount 必须相等 —— 实测 两者相等=${twoSidesEqual}（相等则无「一侧 0 一侧非 0」的更重证据）`,
     `响应原文: ${r.text.slice(0, 300)}`, `DB orders: ${JSON.stringify(b)}`, `DB 流水: ${JSON.stringify(fin)}`,
     `列类型: ${JSON.stringify(colTypes)}`],
    { extra: { status: r.status, orderRefund: b?.refund_amount, refundAt: b?.refund_at, finance: fin.map((x) => x.amount), silentZero, twoSidesEqual } })
}

// ③ 0.004 / 0.005 —— 舍入方向登记（口径观察，不判缺陷）
{
  const rows = []
  for (const v of ['0.004', '0.005', '0.009']) {
    const C = await freshOrder(`P${v.replace('.', '')}`)
    const r = await refund(C.o.orderId, v)
    const c = orderRow(C.o.orderId)
    const fin = financeRefundRows(C.o.orderId)
    rows.push({ requested: v, status: r.status, orderRefund: c?.refund_amount,
                finance: fin.map((x) => x.amount), equal: fin.length > 0 ? String(cents(c?.refund_amount ?? '0')) === String(cents(fin[0].amount)) : null })
  }
  writeFileSync(outPath('B5-rounding.json'), JSON.stringify({ at: nowCST(), rows }, null, 2))
  R.add('LB-PREC-03', '精度③：0.004 / 0.005 / 0.009 的舍入方向（口径登记，不判缺陷）', 'pass',
    `逐字读数：${JSON.stringify(rows.map((x) => `${x.requested} ⇒ ${x.status} / 订单 ${x.orderRefund} / 流水 ${x.finance.join(',')}`))}`,
    [`期望来源: **只登记口径**（任务书纪律：不设主观阈值、不判性能/口径偏好）`,
     `关注点: 0.005 的舍入方向（PG numeric 为「四舍五入、.005 进位」）与「订单侧 = 流水侧」的一致性`,
     `原始读数: ${JSON.stringify(rows)}`],
    { extra: { rows } })
}

log(`p5 完成：${JSON.stringify(R.summary())}`)
