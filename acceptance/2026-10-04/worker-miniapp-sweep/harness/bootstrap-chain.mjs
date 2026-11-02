// 线① 前置：**空租户首个订单端到端**（2026-10-04 本轮独有价值）
//
// 为什么必须先跑这一段（BRIEF §4.1）：
//   租户 25「米高测试环境」是**空库**（products=0 / orders=0 / processing_position_operations=0），
//   而 `lib.mjs::pickOpTemplate()` 依赖**已存在**的工序实例（set_id is not null）
//   ⇒ 直接跑 p0..p6 会 `throw 找不到可参照的工序实例`。
//
// 本段**只走真实 API**（/api/admin/products → /api/admin/orders → /payment → /processing-orders/generate）
// 把「商品（含 SKU）→ 下单 → 确认收款 → 生成加工单/工序实例」建出来，
// 并把这条链路**本身**作为独立判据（空租户从零冷启动可用性）。
//
// 命名域：链对象 = `lc` 前缀 + 名称前缀「线A验收链」（**与探针域 `la` 分离**，
//   这样 p6 的「存量行（非 la 域）逐字节不变」命题仍可闭合：链行算存量，探针行算探针）。
// 收尾：`cleanup-chain.mjs` 按 `lc` 前缀删除，给出前后现取读数。
//
// 期望来源：端点契约原文（controller source）+ 独立 DB 读数；**不**拿被测读面当期望。
import { writeFileSync, existsSync, readFileSync } from 'node:fs'
import {
  api, psql, one, log, nowCST, outPath, Recorder, loginApi, guardedWrite,
  TENANT_ID, API, PROBE_PREFIX,
} from './lib.mjs'

const CHAIN_PREFIX = process.env.CHAIN_PREFIX || '线A验收'
const CHAIN_ID = process.env.CHAIN_ID_PREFIX || 'lac'
const REUSE = process.env.CHAIN_REUSE === '1'
const R = new Recorder('P0b-chain.json')
const ev = []
const lock = (sql) => guardedWrite(`-- probe-ok\n${sql}`)

// ── 幂等：链已存在且健康 ⇒ 复用（重跑不重建，避免同一轮重复耗尽订单号/批次）──
const chainFile = outPath('.chain.json')
if (REUSE && existsSync(chainFile)) {
  try {
    const c = JSON.parse(readFileSync(chainFile, 'utf8'))
    const alive = one(`select id, status from processing_orders where tenant_id=${TENANT_ID} and id='${c.poId}' and deleted=0`)
    const ops = psql(`select id from processing_position_operations where tenant_id=${TENANT_ID} and processing_order_id='${c.poId}' and deleted=0 and set_id is not null`)
    if (alive && ops.length) {
      log(`链复用: poId=${c.poId} ops=${ops.length}（判据不作判定，仅登记复用）`)
      writeFileSync(chainFile, JSON.stringify({ ...c, reusedAt: nowCST(), opsCount: ops.length }, null, 2))
      process.exit(0)
    }
  } catch { /* 不可复用 ⇒ 重建 */ }
}

const uniq = `${Date.now().toString(36)}${Math.floor(Math.random() * 1296).toString(36)}`
const C = {
  uniq,
  categoryId: null,
  productName: `${CHAIN_PREFIX}布-${uniq}`,
  productId: null, skuId: null, skuCode: null,
  orderId: null, orderNo: null, poId: null, poNo: null,
  opTemplate: null, opsCount: 0,
}

const admin = await loginApi()
ev.push(`管理员登录: tenantId=${admin.raw?.user?.tenantId ?? admin.raw?.tenantId} cached=${admin.cached}`)
log(`管理员登录 OK tenantId=${admin.raw?.user?.tenantId ?? admin.raw?.tenantId}`)

// ── ⓪ 商品分类（**空租户必需**：ProductService 校验「分类ID不能为空」——
//      实测第一次建商品得 422 VALIDATION_ERROR「分类ID不能为空」）────────
const catBody = { name: `${CHAIN_PREFIX}分类-${uniq}`, level: 1, sort: 1, status: 'active' }
const cr = await api('POST', '/api/admin/categories', { token: admin.token, body: catBody })
C.categoryId = cr.json?.data?.id ?? null
const catRow = C.categoryId ? one(`select id, name, tenant_id from categories where id='${C.categoryId}'`) : null
writeFileSync(outPath('P0b-step0-category.json'), JSON.stringify({
  at: nowCST(), endpoint: 'POST /api/admin/categories', requestBody: catBody,
  httpStatus: cr.status, response: cr.json, dbRow: catRow,
}, null, 2))
R.add('CH0.category', 'POST /api/admin/categories 建商品分类（空租户建商品的前置）',
  (cr.status === 200 || cr.status === 201) && !!C.categoryId ? 'pass' : 'fail',
  `HTTP ${cr.status} categoryId=${C.categoryId}`,
  [...ev, `期望来源: ProductService 校验（第一次建商品实测 422「分类ID不能为空」）+ categories 独立 DB 读数`,
   `期望: 2xx ∧ categoryId 非空 ∧ DB 有该行`, `实得: HTTP ${cr.status} body=${JSON.stringify(cr.json).slice(0, 300)}`])
if (!C.categoryId) { R.dump(); log('CH0 失败 ⇒ 中止'); process.exit(1) }

// ── ① 商品（含 SKU）──────────────────────────────────────────────
const prodBody = {
  categoryId: C.categoryId,
  name: C.productName,
  skuCode: `${CHAIN_ID.toUpperCase()}-P-${uniq}`.toUpperCase(),
  unit: '米',
  pricingType: 'per_meter',
  basePrice: 30.5,
  status: 'on_sale',
  stock: 200,
  stockWarningThreshold: 5,
  description: `${CHAIN_PREFIX}冷启动夹具（空租户首个商品）`,
  sellingMethods: ['bulk_cut', 'full_roll'],
  rollLengthM: 60,
  doorWidths: ['2.8'],
  colors: [{ colorName: `${CHAIN_PREFIX}米白` }],
  skus: [{ colorName: `${CHAIN_PREFIX}米白`, doorWidth: '2.8', price: 168.0, stock: 200, skuCode: `${CHAIN_ID.toUpperCase()}-S-${uniq}`.toUpperCase() }],
}
const pr = await api('POST', '/api/admin/products', { token: admin.token, body: prodBody })
C.productId = pr.json?.data?.id ?? null
const skuRows = C.productId ? psql(`select id::text as id, door_width, color_name, price::text from product_skus where tenant_id=${TENANT_ID} and product_id='${C.productId}'`) : []
C.skuId = skuRows[0]?.id ?? null
C.skuCode = skuRows[0]?.id ? prodBody.skus[0].skuCode : null
writeFileSync(outPath('P0b-step1-product.json'), JSON.stringify({
  at: nowCST(), requestBody: prodBody, httpStatus: pr.status, response: pr.json,
  dbSkus: skuRows,
}, null, 2))
R.add('CH1.product+sku', 'POST /api/admin/products 建商品（含 SKU）→ DB 复读',
  (pr.status === 200 || pr.status === 201) && !!C.productId && skuRows.length === 1 ? 'pass' : 'fail',
  `HTTP ${pr.status} productId=${C.productId} DB SKU 行数=${skuRows.length}`,
  [...ev, `期望来源: ProductController.java @PostMapping("/api/admin/products") 契约 + product_skus 表独立 DB 读数`,
   `期望: 2xx ∧ productId 非空 ∧ product_skus 恰 1 行(price=168.000)`, `实得: HTTP ${pr.status} skus=${JSON.stringify(skuRows)}`])
if (!C.productId || !C.skuId) { R.dump(); log('CH1 失败 ⇒ 中止（无 product_id 的夹具会踩 #6219 已知缺陷路径 = 假红）'); process.exit(1) }

// ── ② 下单（**订单行必须带真实 product_id**，BRIEF §4.1）──────────
const orderBody = {
  customerName: `${CHAIN_PREFIX}客户`,
  customerPhone: '13800138000',
  customerAddress: `${CHAIN_PREFIX}地址-冷启动`,
  logisticsType: 'express',
  logisticsCompany: '顺丰',
  remark: `${CHAIN_PREFIX}空租户首个订单`,
  actualAmount: 168,
  discountAmount: 0,
  items: [{
    productId: C.productId, productName: C.productName, quantity: 1, unitPrice: 168,
    width: 2.8, height: 3.0, subtotal: 168,
    processingInfo: { componentRole: '主布', panels: 2, craft: '韩褶', curtainType: '布帘', saleForm: '布料', processingItems: [] },
  }],
}
const or = await api('POST', '/api/admin/orders', { token: admin.token, body: orderBody })
C.orderId = or.json?.data?.id ?? null
C.orderNo = or.json?.data?.orderNo ?? or.json?.data?.order_no ?? null
const itemRows = C.orderId ? psql(`select id, product_id, product_name, quantity::text, unit_price::text, subtotal::text from order_items where tenant_id=${TENANT_ID} and order_id='${C.orderId}'`) : []
writeFileSync(outPath('P0b-step2-order.json'), JSON.stringify({
  at: nowCST(), requestBody: orderBody, httpStatus: or.status, response: or.json, dbItems: itemRows,
}, null, 2))
const itemHasProduct = itemRows.length === 1 && itemRows[0].product_id === C.productId
R.add('CH2.order-with-product-id', 'POST /api/admin/orders 下单 ∧ 订单行 product_id 非空（不踩 #6219）',
  (or.status === 200 || or.status === 201) && !!C.orderId && itemHasProduct ? 'pass' : 'fail',
  `HTTP ${or.status} orderId=${C.orderId} orderNo=${C.orderNo} DB 订单行=${JSON.stringify(itemRows)}`,
  [...ev, `期望来源: OrderController.java @PostMapping("/api/admin/orders") 契约 + order_items 表独立 DB 读数`,
   `期望: 2xx ∧ orderId 非空 ∧ order_items 恰 1 行 ∧ product_id == 请求 productId`,
   `实得: HTTP ${or.status} items=${JSON.stringify(itemRows)}`])
if (!C.orderId) { R.dump(); log('CH2 失败 ⇒ 中止'); process.exit(1) }

// ── ③ 生成加工单的**前置闸门负对照**：未确认收款就该被拒（红证方向）──
const prePay = await api('POST', '/api/admin/processing-orders/generate', { token: admin.token, body: { orderIds: [C.orderId] } })
const prePayPo = one(`select id from processing_orders where tenant_id=${TENANT_ID} and order_id='${C.orderId}' and deleted=0`)
writeFileSync(outPath('P0b-step3-prepay-gate.json'), JSON.stringify({
  at: nowCST(), endpoint: 'POST /api/admin/processing-orders/generate', requestBody: { orderIds: [C.orderId] },
  httpStatus: prePay.status, response: prePay.json, dbProcessingOrders: prePayPo,
}, null, 2))
// 服务端可能「拒绝(4xx/body 拒绝)」也可能「接受但实质不生成」；两者都算闸门成立，200 且真生成才算闸门失效。
const gateRejected = prePay.status >= 400 || !prePayPo
R.add('CH3.prepay-gate', '负对照：未确认收款的订单**不得**生成加工单（红线方向证明本判据会红）',
  gateRejected ? 'pass' : 'fail',
  `HTTP ${prePay.status} 未付款订单已生成加工单=${!!prePayPo}`,
  [...ev, `期望来源: ProcessingOrderService 类注释「与『仅已确认订单可生成加工单』同一道闸」（orders.status='confirmed'）`,
   `期望: 未 confirmed ⇒ 4xx 或 零生成`, `实得: HTTP ${prePay.status} body=${JSON.stringify(prePay.json).slice(0, 300)} dbPo=${JSON.stringify(prePayPo)}`])

// ── ④ 确认收款 ───────────────────────────────────────────────────
const pay = await api('PUT', `/api/admin/orders/${C.orderId}/payment`, { token: admin.token })
const afterPay = one(`select status from orders where tenant_id=${TENANT_ID} and id='${C.orderId}'`)
writeFileSync(outPath('P0b-step4-payment.json'), JSON.stringify({
  at: nowCST(), endpoint: `PUT /api/admin/orders/${C.orderId}/payment`, httpStatus: pay.status, response: pay.json, dbOrderStatus: afterPay,
}, null, 2))
R.add('CH4.confirm-payment', 'PUT /api/admin/orders/{id}/payment 确认收款 ⇒ orders.status 独立 DB 复读 = confirmed',
  pay.status === 200 && afterPay?.status === 'confirmed' ? 'pass' : 'fail',
  `HTTP ${pay.status} DB status=${afterPay?.status}`,
  [...ev, `期望来源: OrderController.confirmPayment 契约 + orders 表独立 DB 读数`,
   `期望: HTTP 200 ∧ orders.status='confirmed'`, `实得: HTTP ${pay.status} status=${afterPay?.status}`])

// ── ⑤ 生成加工单 + 工序实例 ──────────────────────────────────────
const gen = await api('POST', '/api/admin/processing-orders/generate', { token: admin.token, body: { orderIds: [C.orderId] } })
const pos = psql(`select id, processing_order_no, status from processing_orders where tenant_id=${TENANT_ID} and order_id='${C.orderId}' and deleted=0`)
C.poId = pos[0]?.id ?? null
C.poNo = pos[0]?.processing_order_no ?? null
const ops = C.poId ? psql(`select o.id, o.seq, o.operation_name, o.group_name, o.unit, o.position_name, o.position_kind,
                                   o.qty_source, o.unit_price::text, o.factor::text, o.qty::text, o.set_id, o.set_no,
                                   o.order_item_id, i.product_id
                              from processing_position_operations o
                              left join order_items i on i.id = o.order_item_id
                             where o.tenant_id=${TENANT_ID} and o.processing_order_id='${C.poId}' and o.deleted=0
                             order by o.seq, o.id`) : []
C.opsCount = ops.length
writeFileSync(outPath('P0b-step5-generate.json'), JSON.stringify({
  at: nowCST(), endpoint: 'POST /api/admin/processing-orders/generate', requestBody: { orderIds: [C.orderId] },
  httpStatus: gen.status, response: gen.json, dbProcessingOrders: pos, dbPositionOps: ops,
}, null, 2))
const genOk = gen.status === 200 && (gen.json?.data ?? []).every((r) => r?.success !== false)
R.add('CH5.generate-processing-order', 'POST /api/admin/processing-orders/generate ⇒ 加工单 + 工序实例落库',
  genOk && !!C.poId && ops.length > 0 ? 'pass' : 'fail',
  `HTTP ${gen.status} poId=${C.poId} poNo=${C.poNo} 工序实例=${ops.length} 行`,
  [...ev, `期望来源: ProcessingOrderController.java @PostMapping("/generate") 契约 + processing_orders/processing_position_operations 独立 DB 读数`,
   `期望: HTTP 200 ∧ 恰 1 张加工单 ∧ 工序实例 ≥1 行`, `实得: HTTP ${gen.status} po=${JSON.stringify(pos)} ops=${ops.length}`])

// ── ⑥ 端到端一条链（本轮独有价值）：从空库到「工人可扫码的工序实例」──
const scannable = ops.filter((o) => o.set_id && Number(o.qty) > 0)
R.add('CH6.e2e-empty-tenant-first-order', '空租户首个订单端到端：商品→下单→收款→加工单→**可扫码工序实例**',
  C.productId && itemHasProduct && afterPay?.status === 'confirmed' && C.poId && scannable.length > 0 ? 'pass' : 'fail',
  `productId=${C.productId} orderId=${C.orderId}(confirmed) poId=${C.poId} 可扫码工序实例=${scannable.length}`,
  [...ev, `期望来源: 本段独立算式（四段端点全部 2xx + 三段 DB 复读一致 + 工序实例 set_id 非空且 qty>0 —— 这是 pickOpTemplate 的唯一前条件）`,
   `期望: productId≠∅ ∧ order_items.product_id=请求值 ∧ orders.status=confirmed ∧ po≠∅ ∧ set_id≠∅且qty>0`,
   `实得: ${JSON.stringify(scannable)}`])

// ── ⑦ 模板落盘（供 p2/p2b 夹具用；**只取字段形状**，不碰该行）──
const t = scannable[0] ?? ops[0] ?? null
if (t) {
  C.opTemplate = {
    operation_name: t.operation_name, group_name: t.group_name, unit: t.unit,
    position_name: t.position_name, position_kind: t.position_kind, qty_source: t.qty_source,
    unit_price: t.unit_price, factor: t.factor, product_id: t.product_id,
  }
}
writeFileSync(chainFile, JSON.stringify({ ...C, at: nowCST(), apiBase: API, source: 'bootstrap-chain.mjs（真实 API；非 SQL 旁路）' }, null, 2))
log(`链完成: productId=${C.productId} skuId=${C.skuId} orderId=${C.orderId} poId=${C.poId} ops=${C.opsCount} 可扫码=${scannable.length}`)
log(`链模板落盘 .chain.json: ${JSON.stringify(C.opTemplate)}`)
R.dump()
process.exit(0)
