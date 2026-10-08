/**
 * 库存明细页的**展示口径纯函数**（issue #6404）。
 *
 * ## 为什么单独成一个模块
 *
 * 与 `frontend/admin-web/src/lib/stock-quantity.ts` / `saving-board.ts` 同一姿势：
 * 口径抽成**纯函数**才能被单测直接断言（`frontend/admin-web/tests/unit/pages/stock-ledger.test.tsx`），
 * 而不是靠「渲染整个页面再读文本」。
 *
 * ## 🔴 三条口径（都不是格式化偏好，是**不许假绿**）
 *
 * ① **成本 `null` = 「未知」**：`StockLedger` 的 javadoc 逐字写着「NULL = 该次变更发生时成本未知
 *   （存量行全部为 NULL，**不伪造**）」⇒ 渲染成 `¥0.00` 就是把「读不出」说成「不要钱」；
 * ② **数量 `null` = 「-」**：与「成本未知」区分开 —— 一个是**读不出**，一个是这行**没有数**；
 * ③ **不重算**：`delta` / `beforeQty` / `afterQty` / 金额一律**原样渲染服务端下发的值**。
 *   在浏览器里再算一遍 = 第二份会漂的口径（同族教训见 `lib/saving-board.ts` 的页头注释）。
 *   判别器 = 测试里的**见证行**（服务端值与现算值故意不等的那一行）。
 */

import { formatStockQuantity } from '@/lib/stock-quantity'

/**
 * 变更来源 → 用户看得懂的词。取值真值源 = `backend/admin-api/src/main/java/com/migao/admin/entity/StockLedger.java`
 * 的 `REASON_*` 常量（order / aftersales / manual / inbound）。
 */
export const REASON_LABELS: Record<string, string> = {
  order: '订单扣减',
  aftersales: '售后回补',
  manual: '手工调整',
  inbound: '入库过账',
}

/**
 * 🔴 未知取值**原样显示**（不吞成空白、不回落成「其他」）——
 * 服务端加了新的 reason 而前端还没跟上时，商家至少能看见原始标记并来报障；
 * 静默显示空白会让这行看起来「没有原因」。
 */
export function reasonLabel(reason?: string | null): string {
  if (!reason) return '—'
  return REASON_LABELS[reason] ?? reason
}

/** 数量：复用库存数量的既有展示口径（最多 1 位小数、去尾零；缺值 ⇒ `-`） */
export function formatQty(value?: number | string | null): string {
  return formatStockQuantity(value)
}

/** 变动量：在数量口径上加**正号**（`+50` / `-3`），让「补进来还是扣出去」一眼可辨 */
export function formatDelta(value?: number | string | null): string {
  const text = formatStockQuantity(value)
  if (text === '-') return '-'
  return Number(text) > 0 ? `+${text}` : text
}

/** 成本金额：`null` ⇒ **「未知」**（不伪造 0）；有值 ⇒ `¥1240.00` */
export function formatCost(value?: number | string | null): string {
  if (value === null || value === undefined || value === '') return '未知'
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return '未知'
  return `¥${n.toFixed(2)}`
}

/** 时间：本机时区可读形态；缺值 / 不可解析 ⇒ `—` */
export function formatTime(value?: string | null): string {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN')
}
