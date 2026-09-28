/**
 * 销售单的**数量口径**判定（issue #5651 收口）—— 纯函数，不碰 React、不发请求、**不算钱**。
 *
 * ## 它补的是哪一段
 *
 * `order_shipment_items`（issue #5648）是「这一单**实际**发了多少」的**唯一真值载体**，
 * 而它此前**只有工人读面**（`GET /api/worker/shipment/orders/{orderId}`，工人 session 准入）
 * ⇒ 跑在 admin-web 的销售单拿不到实发数量，数量列只能退回订单行数量（与报价单/发货单
 * 同一份投影）。本模块把后端新补的 **admin 读面**（`GET /api/admin/orders/{id}/shipments`，
 * 与工人读面共用 `OrderShipmentService.readShipment` —— 一份实现两个面）接到纸面上。
 *
 * ## 🔴 数量口径说清楚（真值有两份，**各归各的 owner**，这里不造第三份）
 *
 * | 真值 | owner | 谁消费 |
 * |---|---|---|
 * | **下单数量** `order_items.quantity` | 订单域 | 报价单 / 发货单 / 加工单（同一份投影） |
 * | **实发数量** `order_shipment_items.shipped_quantity` | `OrderShipmentService.readShipment` | 工人 H5 + **本模块 → 销售单数量列** |
 *
 * ⇒ 销售单的数量列**不新增口径**：有实发就印实发（并标明），没有实发才印**订单数量**
 * （并**显式标明**「这不是实发」）。任何情况下都**不印 0**：`0` 会被读成「实发为零」，
 * 而「没有这个数」「这一行没发」「整单没发」是**三件不同的事**（同族：缺口金额栏标「未采集」
 * 而不是 `0.00`，见 `SalesDoc.tsx` 的 `SALES_DOC_MONEY_GAPS`）。
 *
 * ## 四态（每一态都**可判**，且纸面文案两两不同 —— 守卫判红的是「合并成一种显示」）
 *
 * | 态 | 判定 | 数量列印什么 |
 * |---|---|---|
 * | `shipped` | 有实发，且每一行都发齐（实发 ≥ 下单） | 实发数量 |
 * | `partial` | 有实发，但存在行未发 / 未发齐 | 有实发的行印实发；未发行**显式**标「未发」 |
 * | `not-shipped` | 一条实发明细都没有（含「只打了包」） | 订单数量（单据上标明基准） |
 * | `unavailable` | 读面**没取到**（`null`/`undefined`）—— **不是**「未发货」 | 订单数量 + 标明「发货明细未取到」 |
 *
 * 🔴 `unavailable` 必须与 `not-shipped` 分开：把「取不到数据」显示成「未发货」就是
 * **用缺数据冒充业务状态**（把网络事故读成业务事实），而纸面是要拿去对账的。
 *
 * ## 缺值口径（同一条硬约束的三处落点）
 * 1. 未发行 ⇒ 标 {@link SALES_QTY_NOT_SHIPPED}（`未发`），**不写 0**；
 * 2. 订单行数量缺失 ⇒ 走 `SalesDoc` 的显式占位（`—`），**不写 0**；
 * 3. 实发明细挂不到任何订单行 ⇒ 计入 {@link SalesQtyResolution.unmatchedShippedLines}，
 *    由纸面**显式提示行数**，**不静默丢掉**（丢掉 = 纸面与账目对不上的一种形态）。
 */
/**
 * 订单行的**最小面**：本模块只读 `id`（与实发明细逐行对齐的键）与 `quantity`（下单数量）。
 * 不绑死 `OrderItem` —— 调用方（页面 / 用例）只提供这两个字段就够，也让「缺值」能被显式喂进来。
 */
export interface SalesQtyOrderLine {
  id?: string | null
  quantity?: number | null
}

/** 发货读面上的**一行实发**（后端 `OrderShipmentService.readShipment` 的逐字形状，snake_case） */
export interface OrderShipmentItemRead {
  order_item_id?: string | null
  product_name?: string | null
  /** 实发数量（米 / 套 / 件）—— 与下单数量**同口径但不同真值** */
  shipped_quantity?: number | string | null
  unit?: string | null
  /** 实发套 / 卷；缺值 = `null`（**不填 0**，见 #5648 的口径） */
  set_count?: number | null
  roll_count?: number | null
}

/** 一张发货单（头 + 明细） */
export interface OrderShipmentReadEntry {
  shipment_no?: string | null
  source?: string | null
  packed_at?: string | null
  shipped_at?: string | null
  tracking_no?: string | null
  logistics_company?: string | null
  items?: OrderShipmentItemRead[] | null
}

/** 发货读面响应（`GET /api/admin/orders/{id}/shipments`） */
export interface OrderShipmentRead {
  order_id?: string
  order_no?: string
  status?: string
  shipments?: OrderShipmentReadEntry[] | null
  shipped_totals?: {
    set_count?: number | string
    roll_count?: number | string
    by_unit?: Record<string, number | string>
  } | null
}

/**
 * 数量列的四个态（**唯一字面量清单**；纸面文案见 {@link SALES_QTY_BASIS}）。
 * 守卫 `test_shipment_read_surface_guard.py` 与用例都按这份清单判「三态有没有被合并」。
 */
export const SALES_QTY_STATES = ['shipped', 'partial', 'not-shipped', 'unavailable'] as const

export type SalesQtyState = (typeof SALES_QTY_STATES)[number]

/**
 * 每一态**印在纸上的口径说明**（唯一来源，纸面直接渲染它）。
 * 🔴 四句必须两两不同：合并任意两句 ⇒ 纸面再也判不出「这个数是实发还是下单数量」。
 */
export const SALES_QTY_BASIS: Record<SalesQtyState, string> = {
  shipped: '数量列 = 实发数量（已发货）',
  partial: '数量列 = 实发数量（部分发货；未发行的数量列标「未发」）',
  'not-shipped': '未发货：数量列 = 订单数量（尚无可核的实发）',
  // ⚠️ 纸面文案**不带 markdown 强调**（`**`）—— 它直接印在纸上，不经渲染器
  // （守卫 `tests/unit/lib/copy-no-markdown-emphasis.test.ts`：带标记的文案必须登记接渲染器）
  unavailable: '发货明细未取到：数量列 = 订单数量（不是实发口径）',
}

/** 未发行在数量列上的**显式**标记（不是 0、不是空白） */
export const SALES_QTY_NOT_SHIPPED = '未发'

/** 数量列取值口径：`shipped` = 实发（本单要接的那一份）；`ordered` = 订单数量（并已在纸面标明） */
export type SalesQtyBasis = 'shipped' | 'ordered'

export interface SalesQtyCell {
  basis: SalesQtyBasis
  /** 要印的值；`null` = 该行没有这个数（纸面显式占位 / 标「未发」）—— **绝不填 0** */
  value: number | null
}

export interface SalesQtyResolution {
  state: SalesQtyState
  /** 纸面口径说明（= {@link SALES_QTY_BASIS}[state]，直接渲染） */
  basisLabel: string
  /** 与订单行**同序**的逐行取值 */
  cells: SalesQtyCell[]
  /** 实发明细里挂不到任何订单行的行数（>0 ⇒ 纸面显式提示，不静默丢） */
  unmatchedShippedLines: number
}

/** 有限数才收（`null` / `undefined` / `NaN` / 字符串数字都过一遍） */
function finiteOrNull(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

/**
 * 实发明细 ⇒ 「订单行 id → 实发合计」+ 「挂不到订单行的行数」。
 *
 * 口径：**累加全部发货单的明细**（一次发货一张单，补发会是第二张 ⇒ 合计才是这一单发出去的总量）。
 * ⚠️ 不按 `shipped_at` 过滤：明细只在**发货**时写入（#5648 的写序），过滤只会把异常数据
 * **静默**丢掉 —— 宁可算进来，也不让纸面少算。
 */
function shippedByOrderItem(read: OrderShipmentRead | null | undefined, orderItemIds: Set<string>): {
  byItem: Map<string, number>
  matched: number
  unmatched: number
} {
  const byItem = new Map<string, number>()
  let matched = 0
  let unmatched = 0
  for (const shipment of read?.shipments ?? []) {
    for (const item of shipment?.items ?? []) {
      const key = typeof item?.order_item_id === 'string' ? item.order_item_id : ''
      const quantity = finiteOrNull(item?.shipped_quantity)
      // 挂不到本订单行（没给 id / id 不属于本订单）或没有可加的数量 ⇒ 计入「未挂到订单行」，
      // 由纸面**显式提示行数** —— 静默丢掉就是纸面与账目对不上的一种形态。
      if (key === '' || !orderItemIds.has(key) || quantity === null) {
        unmatched += 1
        continue
      }
      byItem.set(key, (byItem.get(key) ?? 0) + quantity)
      matched += 1
    }
  }
  return { byItem, matched, unmatched }
}

/**
 * 订单行 + 发货读面 ⇒ 销售单数量列的**四态 + 逐行取值**（纸面只渲染结果，不再自己判）。
 *
 * @param items 订单商品行（`order.items`）—— **下单数量**的真值
 * @param read  admin 发货读面（`null`/`undefined` = 没取到 ⇒ `unavailable`，**不是**「未发货」）
 */
export function resolveSalesQuantity(
  items: ReadonlyArray<SalesQtyOrderLine> | null | undefined,
  read: OrderShipmentRead | null | undefined,
): SalesQtyResolution {
  const rows = items ?? []
  const orderItemIds = new Set(rows.map((it) => it.id).filter((id): id is string => typeof id === 'string' && id !== ''))
  const { byItem, matched, unmatched } = shippedByOrderItem(read, orderItemIds)

  // ── 先按「后端有没有给出实发」定基调（不给读面 ⇒ 取不到，与「未发货」分开）──
  const hasShippedData = matched > 0 || unmatched > 0

  let state: SalesQtyState
  if (read === null || read === undefined) {
    state = 'unavailable'
  } else if (!hasShippedData) {
    state = 'not-shipped'
  } else {
    // 有实发 ⇒ 判「发齐了没有」：每一行都要有实发，且实发 ≥ 下单（下单数量缺失 ⇒ 不可比 ⇒ 保守算未齐）
    const allFull = rows.every((it) => {
      const shipped = typeof it.id === 'string' && it.id !== '' ? byItem.get(it.id) : undefined
      const ordered = finiteOrNull(it.quantity)
      return shipped !== undefined && ordered !== null && shipped >= ordered
    })
    state = allFull && rows.length > 0 ? 'shipped' : 'partial'
  }

  const basis: SalesQtyBasis = state === 'shipped' || state === 'partial' ? 'shipped' : 'ordered'
  const cells: SalesQtyCell[] = rows.map((it) => {
    if (basis === 'shipped') {
      const shipped = typeof it.id === 'string' && it.id !== '' ? byItem.get(it.id) : undefined
      return { basis, value: shipped === undefined ? null : shipped }
    }
    return { basis, value: finiteOrNull(it.quantity) }
  })

  return { state, basisLabel: SALES_QTY_BASIS[state], cells, unmatchedShippedLines: unmatched }
}
