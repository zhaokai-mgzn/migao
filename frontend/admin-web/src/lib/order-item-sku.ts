/**
 * 订单行的**商品 SKU 身份**（品名 / 货号 / 颜色 / 门幅）—— 纸面单据的**唯一**取值口。
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
import type { OrderItem } from '@/types'

/** 订单行的商品身份（缺值 = 空串） */
export interface PaperItemSku {
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

export function paperItemSku(item: OrderItem): PaperItemSku {
  const rows = craftSpecRows(item.processingInfo)
  const info = (item.processingInfo ?? {}) as Record<string, unknown>
  return {
    name: text(item.productName),
    code: text(item.skuCode) || text(item.productCode),
    color: text(info.colorName),
    doorWidth: rows.find((row) => row.label === '门幅')?.value ?? '',
    specRows: rows.filter((row) => row.label !== '门幅'),
  }
}
