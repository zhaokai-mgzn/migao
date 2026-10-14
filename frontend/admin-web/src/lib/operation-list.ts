/**
 * **工序清单**的读面口径（issue #6901）—— 加工单纸面（A4）与商家端加工单块、以及后者的
 * 「复制全部」文本**共用同一份**：按订单行索引 + 状态文案。给**多处**渲染面用的取值/格式化
 * 只许有一份实现（`frontend/admin-web/src/lib/order-item-sku.ts` 的 `orderItemSku()` 是同族先例：
 * 各面各拼一份必然漂移，而漂移的那一份**不会变红**）。
 *
 * 显示名**不在本模块**：它走仓内唯一口径
 * `frontend/admin-web/src/lib/operation-display.ts::operationDisplayName()`
 * （issue #4621：**不得**渲染工人端快照名 `operation`）。
 */
import type { ProductionPosition } from '@/types'

/**
 * 工序清单**按订单行（= 部位 / 套）索引**。
 *
 * 键 = `position.order_item_id`（后端 `ProductionService.buildPositions` 按它分组，
 * 与洗水码 / 批号**同一把钥匙**）。没有 `order_item_id` 的分组（老数据 / 读面未升级）
 * **不索引** —— 挂不到具体一套上就不上纸面（不猜）；分组内 `operations` 为空 / 缺键
 * 同样不入表 ⇒ 消费方按「整块不出现」渲染（不印空表、不印占位表头）。
 *
 * 同一 `order_item_id` 有多组时取**第一组**（读面按部位分组，一部位一组；多组只会出现在
 * 读面口径变化时，此时宁可少印也不许把两组缝成一份假清单）。
 */
export function operationsByItem(
  positions?: ProductionPosition[] | null,
): Map<string, ProductionPosition> {
  const index = new Map<string, ProductionPosition>()
  for (const position of positions ?? []) {
    const itemId = position.order_item_id
    if (!itemId || !position.operations?.length) continue
    if (!index.has(itemId)) index.set(itemId, position)
  }
  return index
}

/**
 * 一道工序的**状态文案**（读面 `status` 只有 `done` / 其余；缺值按「待做」印 ——
 * **不显示空**）。与生产进度表 `components/production/ProductionProgressTable.tsx::statusChip`
 * 同一份词表（「已完成」/「待做」）。
 */
export function operationStatusText(status?: string | null): string {
  return status === 'done' ? '已完成' : '待做'
}
