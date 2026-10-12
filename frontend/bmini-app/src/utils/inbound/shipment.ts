/**
 * 工人**拍照发货**纯逻辑（issue #6761）—— 识别候选 ⇒ 工人可核对的初值 / 发货请求体 / 实发汇总。
 *
 * ## 为什么这里有一份「纯逻辑」，而不是直接调后端拿结果上屏
 *
 * 三条纪律（沿用 #5648 已落码的口径，见 `frontend/worker-h5/src/shipment.mjs` 的注释）都
 * **发生在提交之前**，必须能在端侧被单测钉住：
 *
 * 1. 🔴 **白名单式构造请求体**：`worker_id` / `worker_name` 一个字节都不进 body
 *    （身份只由 `X-Worker-Session-Id` 解）—— 发货留痕（谁发的货）是**责任凭证**，
 *    「多带一个字段」在服务端**不会被拒**（它压根不读），但会把「客户端自称身份」这条路留下；
 * 2. 🔴 **识别只是候选**：`fields[].value` 为 null / 空串的格子 ⇒ **留空**，
 *    **绝不**预填 0 / 空串 / 猜测值，并逐格说清「这一格要手输」；
 * 3. 🔴 **实发由人给**：识别只认得出一个总数，**不是**订单行的实发明细
 *    ⇒ 端侧从识别结果**不构造** `items`；数量/单位由工人填，缺了就在提交前拦住。
 *
 * ⚠️ **不 import 跨包文件**：`frontend/worker-h5/src/shipment.mjs` 是**只读参考**，
 * 照它的语义在 bmini 侧独立实现（跨包静态 import 会让部署构建上下文红，见 issue #6744 / #6745）。
 */

/** 识别字段面：与后端 `app/vision/targets.py` 的 `shipment` target **逐字同名**。 */
export const SHIPMENT_FIELD_KEYS = ['order_no', 'product_name', 'quantity', 'width', 'height']

/**
 * 识别回执里的一格（后端**原样搬运** ai-agent 的字段表：`{key,label,value,source,reason,…}`）。
 *
 * `value` 允许是 null（没认出来）—— 这正是「不预填」判据的输入形态；数字 `0` 是**真值**
 * （图上确实写着 0），与 null 是两件事。
 */
export interface ShipmentField {
  key: string
  label?: string | null
  value?: string | number | null
  source?: string | null
  reason?: string | null
}

/** 后端 `ImageRecognitionClient.ImageRecognitionResult` 的形状。 */
export interface ShipmentRecognition {
  targetType?: string | null
  fields?: ShipmentField[] | null
  degraded?: boolean | null
}

/** 需要在页面上**手输**的一格（键 + 中文名 + 为什么）。 */
export interface UncertainCell {
  key: string
  label: string
  reason: string
}

/** 识别候选 ⇒ 工人可核对的初值（不确定的格子**留空**）。 */
export interface ShipmentDraft {
  orderNo: string
  productName: string
  quantity: string
  /** 单位**不从识别结果推**（识别面只认数量）⇒ 恒空串，由工人在「米/套/件」里选 */
  unit: string
  width: string
  height: string
  /** 需要工人手输的格子（页面据此逐格提示，而不是替工人猜） */
  uncertain: UncertainCell[]
}

export interface ShipmentItemInput {
  orderItemId?: string | null
  productName?: string | null
  shippedQuantity: string | number
  unit: string
}

/** 实发明细的一行 —— 字段面与后端 `OrderShipmentService.parseDetails` **逐字同名**。 */
export interface ShipmentItemBody {
  order_item_id: string | null
  product_name: string | null
  shipped_quantity: string | number
  unit: string
}

export interface ShipBodyInput {
  trackingNo?: string
  logisticsCompany?: string | null
  photoRefs?: string[] | null
  recognition?: ShipmentRecognition | null
  /**
   * 实发明细。既接受「工人填的形态」（`shippedQuantity` / 驼峰），也接受**已经构造成后端字段面**的行
   * （`buildShipmentItem` 的产物）—— 两边的数量字段名不同（`shippedQuantity` vs `shipped_quantity`），
   * 下面 `normaliseItem` 一处归一，调用方不必关心自己给的是哪一种。
   */
  items?: (ShipmentItemInput | ShipmentItemBody)[]
}

/** 发货请求体（**白名单**后的形状：恰好这五个键里用得上的那几个）。 */
export interface ShipBody {
  trackingNo: string
  items: ShipmentItemBody[]
  logisticsCompany?: string
  photoRefs?: string[]
  recognition?: ShipmentRecognition
}

/** 实发汇总（后端 `OrderShipmentService.totals`：`{by_unit, set_count, roll_count}`）。 */
export interface ShippedTotals {
  by_unit?: Record<string, number | string> | null
  set_count?: number | string | null
  roll_count?: number | string | null
}

/** 发货单读面的一行（`GET …/orders/{orderId}` 的 `shipments[]`）。 */
export interface ShipmentRow {
  shipment_no?: string | null
  source?: string | null
  tracking_no?: string | null
  logistics_company?: string | null
  packed_by?: string | null
  shipped_by?: string | null
  photo_refs?: string[] | null
  items?: {
    product_name?: string | null
    shipped_quantity?: number | string | null
    unit?: string | null
    set_count?: number | null
    roll_count?: number | null
  }[] | null
  unpacked_at?: string | null
  unpacked_by?: string | null
  unpack_reason?: string | null
}

/** 实发读面（`GET /api/worker/shipment/orders/{orderId}`）。 */
export interface ShipmentView {
  order_id?: string | null
  order_no?: string | null
  status?: string | null
  shipments?: ShipmentRow[] | null
  shipped_totals?: ShippedTotals | null
}

/**
 * 识别候选 ⇒ 表单初值（**不确定的格子留空**）。
 *
 * 🔴 判据：`value` 为 `null` / `undefined` / 纯空白 ⇒ **空串**（不是 `'0'`、不是任何默认值）。
 * 数字 `0` 是识别出来的**真值**，照抄。
 *
 * 红证：把 `null` 折成 `'0'` ⇒ `frontend/bmini-app/tests/worker-shipment-service.test.ts`
 * 的「null / 空串 ⇒ 空串」与页面判据 P3 各自判红。
 */
export function prefillFromRecognition(fields?: ShipmentField[] | null): ShipmentDraft {
  const table = fields ?? []
  const valueOf = (key: string): string => {
    const cell = table.find((item) => item?.key === key)
    const value = cell?.value
    if (value === null || value === undefined) return ''
    const text = String(value).trim()
    return text
  }
  const uncertain: UncertainCell[] = table
    .filter((cell) => cell && valueOf(cell.key) === '')
    .map((cell) => ({
      key: cell.key,
      label: cell.label || cell.key,
      reason: cell.reason || '识别不确定，请手工填写',
    }))
  return {
    orderNo: valueOf('order_no'),
    productName: valueOf('product_name'),
    quantity: valueOf('quantity'),
    unit: '',
    width: valueOf('width'),
    height: valueOf('height'),
    uncertain,
  }
}

/** 实发明细的一行（`order_item_id` 拿不到就 null —— 服务端会按订单行兜底，**不冒充**已知 id）。 */
export function buildShipmentItem(input: ShipmentItemInput): ShipmentItemBody {
  return {
    order_item_id: input.orderItemId || null,
    product_name: input.productName || null,
    shipped_quantity: input.shippedQuantity,
    unit: input.unit,
  }
}

/** 两种入参形态 ⇒ 后端字段面（数量键不同：`shippedQuantity` vs `shipped_quantity`）。 */
function normaliseItem(input: ShipmentItemInput | ShipmentItemBody): ShipmentItemBody {
  const body = input as ShipmentItemBody
  const camel = input as ShipmentItemInput
  return {
    order_item_id: body.order_item_id ?? camel.orderItemId ?? null,
    product_name: body.product_name ?? camel.productName ?? null,
    shipped_quantity: body.shipped_quantity ?? camel.shippedQuantity,
    unit: body.unit ?? camel.unit,
  }
}

/**
 * 构造发货请求体（**白名单**：只从入参里挑出服务端认得的键，其余一律丢弃）。
 *
 * 🔴 刻意**不含** `worker_id` / `worker_name` / `order_id` / `status` —— 身份与状态都由服务端定。
 * 空值维度（`logisticsCompany` 空串 / `photoRefs` 空数组 / `recognition` 空）**不进 body**
 * （不是填 0、不是填空串）。
 */
export function buildShipBody(input: ShipBodyInput = {}): ShipBody {
  const body: ShipBody = {
    trackingNo: input.trackingNo ?? '',
    items: (input.items ?? []).map((item) => normaliseItem(item)),
  }
  if (input.logisticsCompany) body.logisticsCompany = input.logisticsCompany
  if (Array.isArray(input.photoRefs) && input.photoRefs.length > 0) body.photoRefs = [...input.photoRefs]
  if (input.recognition) body.recognition = input.recognition
  return body
}

/** 「这一维不适用」（服务端给 `null`）与「真的是 0」是两件事 ⇒ 只看数字、`null` 不出现在屏上。 */
function positive(value: number | string | null | undefined): number {
  const n = Number(value)
  return Number.isFinite(n) && n > 0 ? n : 0
}

/**
 * 实发汇总 ⇒ 一句话（单位 / 套 / 卷三样）。
 *
 * 🔴 `set_count` / `roll_count` 为 `null`（这一维不适用）⇒ **不印 0**；三样都空 ⇒ `—`
 * （空集不是「发了 0 件」）。
 *
 * 红证：把 `null` 折成 0 并照印 ⇒ `worker-shipment-service.test.ts` 的「全空 ⇒ —」判红
 * （会收到 `0套 / 0卷`）。
 */
export function formatShippedTotals(totals?: ShippedTotals | null): string {
  if (!totals) return '—'
  const parts: string[] = []
  for (const [unit, qty] of Object.entries(totals.by_unit ?? {})) {
    if (qty === null || qty === undefined) continue
    parts.push(`${qty}${unit}`)
  }
  const sets = positive(totals.set_count)
  const rolls = positive(totals.roll_count)
  if (sets > 0) parts.push(`${sets}套`)
  if (rolls > 0) parts.push(`${rolls}卷`)
  return parts.length > 0 ? parts.join(' / ') : '—'
}
