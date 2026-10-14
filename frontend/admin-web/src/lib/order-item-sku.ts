/**
 * 订单行的**商品 SKU 身份**（品名 / 货号 / 颜色 / 门幅）—— **唯一**取值口（纸面单据 + 屏幕面共用）。
 *
 * 消费方：四张纸面单据（`components/orders/*Doc.tsx`）+ 发货页 `ShipOrder` 的商品表
 * （issue #6882：屏幕面原先各读一份会漂的字段，实测三列恒空）。
 *
 * ## 为什么单独一个模块（issue #6869 的根因）
 *
 * 用户 2026-10-14 报「打印出来的表格缺了商品 sku 的信息」。实测根因**不是**漏了列，
 * 是**读了一个不在响应里的字段**：
 * - 后端 `GET /api/admin/orders/{id}` 返回 `OrderDetailResponse.OrderItemResponse`，货号字段名是
 *   **`skuCode`**（`backend/admin-api/.../dto/OrderDetailResponse.java`，
 *   由 `OrderService.convertToItemResponse` 从 `products.sku_code` 回填）；
 * - 而三张单据原先读的是 `item.productCode` / `item.color` —— `order_items` 表**没有这两列**、
 *   DTO 也不含这两个键（`OrderItem` 实体 + `OrderItemResponse` 逐字段核对），
 *   它们只在**测试夹具**里存在 ⇒ 纸面上「货号」列恒缺值：报价单/加工单只印出颜色，
 *   销售单回落成商品名（`productCode || productName`）。
 * - 颜色同理：真值在 `processingInfo.colorName`（下单时写入），不是 `item.color`。
 *
 * ⇒ 取值口收敛到**这一处**：三张单据 + 发货单共用它，不再各写一份会漂的别名链
 * （「同一件事实两处各写一次 ⇒ 将来改一处、另一处静默不一致」）。
 *
 * ## 门幅为什么从 `craftSpecRows` 里取（而不是 `processingInfo.doorWidth` 直读）
 *
 * 门幅是 SKU 属性，落库两种存量形态（`'2.8米'` / `'2.8'`，见 `lib/craft-display.ts` 的 `meters`）
 * ⇒ 展示口径必须走**同一份**解析（`'2.8米'`）。本模块不另写一份米数解析。
 *
 * ## 缺值口径
 *
 * 一律返回**空串**（不编默认值、不印 `undefined`）—— 占位形态（`—` / 空）由各单据自己决定：
 * 报价单留空、加工单印 `—`（两份单据既有口径不同，属**有意**差异，本模块不替它们选）。
 */
import { craftSpecRows, type CraftSpecRow } from './craft-display'

/**
 * 取值口接受的**最小形态** —— 详情行 `OrderItem` 与列表行 `OrderBriefItem` **都**满足它
 * （issue #6882：两个形态的货号键名不同 —— 详情侧是 `skuCode`，列表侧是 `productCode`，
 * 而后端两处填的都是 `products.sku_code`）。
 *
 * 用结构类型而不是绑死某一个 interface：两个调用方共用**同一份**取值口径，
 * 不再各写一条会漂的别名链（这正是 issue #6869 的病灶形态）。
 */
export interface OrderItemSkuSource {
  productName?: string
  /** 详情侧：`OrderDetailResponse.OrderItemResponse.skuCode`（= `products.sku_code`） */
  skuCode?: string
  /** 列表侧：`OrderListResponse.OrderItemBrief.productCode`（后端填的也是 `products.sku_code`） */
  productCode?: string
  processingInfo?: Record<string, unknown> | null
}

/** 订单行的商品身份（缺值 = 空串） */
export interface OrderItemSku {
  /** 商品名称 */
  name: string
  /** 货号：`skuCode`（响应真字段）优先，`productCode` 为历史别名 */
  code: string
  /** 颜色：`processingInfo.colorName`（`item.color` 不在响应里） */
  color: string
  /** 门幅：已按 `craftSpecRows` 的「门幅」行格式化（如 `2.8米`） */
  doorWidth: string
  /**
   * 工艺说明行：`craftSpecRows()` 去掉「门幅」。
   *
   * 🔴 必须排除「门幅」—— 它已有自己的列，同一真值印两处只是噪音（与原先排除「部位」同理；
   * 「部位」**不再**排除：`curtainType` 现在只在工艺说明里露面，见 issue #6869 的裁定）。
   */
  specRows: CraftSpecRow[]
}

/** 非空字符串（trim 后）；空串 / null / 非串 ⇒ 空串 */
function text(value: unknown): string {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : ''
}

/**
 * 订单行的**数量口径**（值 + 单位）—— 屏幕 / 纸面共用的唯一取值口（issue #6901）。
 *
 * 病根（实测）：同一个 `quantity` 在四处各拼一遍（纸面列名写死「数量(米)」、加工单块
 * `数量 ${quantity}${unit}`、进度表 `${n} ${unit}`、复制文本 `数量:${q}${unit}`）
 * ⇒ 单位换一处、别处仍印「米」（**没有任何东西会因此变红**）。
 *
 * 单位真值源（按可用性顺序）：
 * ① 加工单**快照行** `unit`（`ProcessingOrderItem.unit`，后端快照键）；
 * ② 订单行自己的 `unit`（本系统的 `OrderItem` 详情 DTO **不下发**该键 ——
 *    `docs/design/print-media-matrix.md` 的缺口表登记为「数量恒为米」；键一旦下发即自动生效）。
 * 两者都缺 ⇒ 只给值（**不编「米」**：编了就是替客户断言一个没采集到的口径）。
 *
 * ⚠️ 非有限数（`undefined` / `null` / `NaN` / 空串）⇒ `quantity` 为 `null`，
 * 由调用方按自己的缺值口径渲染（纸面印 `—`）—— 本 helper **不**决定占位形态。
 */
export function orderItemQuantity(source: {
  quantity?: unknown
  unit?: unknown
}): { quantity: string | null; unit: string } {
  const unit = text(source.unit)
  const raw = source.quantity
  if (typeof raw === 'number' && Number.isFinite(raw)) return { quantity: String(raw), unit }
  if (typeof raw === 'string' && raw.trim() !== '') return { quantity: raw.trim(), unit }
  return { quantity: null, unit }
}

/** 数量 + 单位（单位缺省 ⇒ 只给数量，不留悬空空格） */
export function quantityWithUnit(source: { quantity?: unknown; unit?: unknown }): string {
  const { quantity, unit } = orderItemQuantity(source)
  if (quantity === null) return ''
  return unit ? `${quantity} ${unit}` : quantity
}

/**
 * `craftSpecRows()` **去掉「门幅」** —— 屏幕 / 纸面凡**另有**一处印门幅的面都用它（issue #6893）。
 *
 * 为什么必须收敛成**一个** helper：`craftSpecRows()` 会带出「门幅」行，而屏幕上很多地方另印一处
 * （列表/详情的「门幅:」、加工单属性行、纸面单据的门幅列）⇒ 直调它 = 同一真值印两处。
 * 实测（issue #6893）曾散成 4 处重复：详情「规格尺寸」格、详情采购明细块、加工单快照块、
 * 加工单「复制全部」文本。收口后**任何**"要工艺行但不要门幅"的面都调这里。
 *
 * ⚠️ 入参是**行对象**（`processingInfo` 在内部）还是**扁平的 `processingInfo` 本身**都行 ——
 * `craftSpecRows` 直读键，两种形态都能取到值（加工单快照的行是**扁平**的：`it.doorWidth`）。
 */
export function craftRowsWithoutDoorWidth(source: unknown): CraftSpecRow[] {
  return craftSpecRows(source).filter((row) => row.label !== '门幅')
}

export function orderItemSku(item: OrderItemSkuSource): OrderItemSku {
  const rows = craftSpecRows(item.processingInfo)
  const info = (item.processingInfo ?? {}) as Record<string, unknown>
  return {
    name: text(item.productName),
    code: text(item.skuCode) || text(item.productCode),
    color: text(info.colorName),
    doorWidth: rows.find((row) => row.label === '门幅')?.value ?? '',
    specRows: craftRowsWithoutDoorWidth(item.processingInfo),
  }
}
