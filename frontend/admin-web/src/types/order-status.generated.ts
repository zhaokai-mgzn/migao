/**
 * ⚠️ 生成物 —— **不要手改**（改这里会在判据上判红）。
 * 源：backend/admin-api/src/main/java/com/migao/admin/service/OrderStatusTransitions.java
 * 重新生成：python3 scripts/order_status_codegen.py --write
 * 新鲜度判据：python3 scripts/order_status_codegen.py --check（0 = 同步 / 1 = 陈旧 / 3 = 无法判定）
 */

/** 后端订单状态的唯一取值全集（顺序 = Java 常量声明顺序，排序键显式写死）。 */
export const ORDER_STATUSES = [
  "pending",
  "confirmed",
  "producing",
  "packed",
  "shipped",
  "completed",
  "cancelled",
] as const

export type CanonicalOrderStatus = (typeof ORDER_STATUSES)[number]

/** Java 侧常量名 → 值（消费方按名引用，避免裸字面量）。 */
export const ORDER_STATUS_VALUES = {
  PENDING: "pending",
  CONFIRMED: "confirmed",
  PRODUCING: "producing",
  PACKED: "packed",
  SHIPPED: "shipped",
  COMPLETED: "completed",
  CANCELLED: "cancelled",
} as const

/** 状态 → 中文业务术语（源 = Java `ORDER_STATUS_LABELS`）。 */
export const ORDER_STATUS_LABELS: Record<CanonicalOrderStatus, string> = {
  "pending": "待付款",
  "confirmed": "已确认",
  "producing": "生产中",
  "packed": "已打包",
  "shipped": "已发货",
  "completed": "已完成",
  "cancelled": "已取消",
}

/** 合法流转（源 = Java `STATUS_TRANSITIONS`；目标按全集顺序排序）。 */
export const ORDER_STATUS_TRANSITIONS: Record<CanonicalOrderStatus, readonly CanonicalOrderStatus[]> = {
  "pending": ["confirmed", "cancelled"],
  "confirmed": ["producing", "packed", "shipped", "cancelled"],
  "producing": ["packed", "shipped", "cancelled"],
  "packed": ["shipped"],
  "shipped": ["completed"],
  "completed": [],
  "cancelled": [],
}

/** 内容可编辑的状态（源 = Java `CONTENT_EDITABLE_STATUSES`；按全集顺序排序）。 */
export const CONTENT_EDITABLE_STATUSES: readonly CanonicalOrderStatus[] = ["pending"]
