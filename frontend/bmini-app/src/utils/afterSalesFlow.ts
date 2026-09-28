/**
 * 售后工单状态机与状态文案（手机端镜像）—— issue #5654
 *
 * 🔴 **唯一真值在后端**：`backend/admin-api/src/main/java/com/migao/admin/service/AfterSalesTicketService.java`
 * 的 `STATUS_TRANSITIONS`（允许流转）与 `TICKET_STATUS_LABELS`（中文文案）。
 * 本文件是它们的**镜像**，存在的理由只有一个：手机端不能在「点了才知道不能这么改」上浪费
 * 管理员一次动作（车间、单手、戴手套）。
 *
 * ⇒ 不靠纪律防漂移：`tests/admin-surfaces-permission-codes.test.ts` 直接解析那两个 Java
 * 字面量**逐值比对**（多一个状态 / 少一条边 / 改一个中文名 ⇒ 红）。
 * ⚠️ 若后端改了状态机而本文件没跟 ⇒ 判据红，**出口是改这里，不是改判据**。
 *
 * 为什么不「把所有状态都摆出来让服务端拒」：那会造出四个必然失败的按钮（且失败文案是
 * 「工单状态不允许从 [待处理] 变更为 [已完成]」——用户得先读报错才知道自己点错了）。
 */

/** 工单状态（枚举值域，与后端 `@Pattern(regexp = "^(pending|processing|resolved|rejected|closed)$")` 同源） */
export const AFTER_SALES_STATUSES = ['pending', 'processing', 'resolved', 'rejected', 'closed'] as const

export type AfterSalesStatus = (typeof AFTER_SALES_STATUSES)[number]

/** 状态 → 中文（逐字取后端 `TICKET_STATUS_LABELS`） */
export const AFTER_SALES_STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  processing: '处理中',
  resolved: '已解决',
  rejected: '已拒绝',
  closed: '已关闭',
}

/**
 * 允许流转的目标状态（逐值取后端 `STATUS_TRANSITIONS`；空数组 = 终态）。
 * 键缺失（服务端回了没登记的状态）⇒ `allowedAfterSalesTargets` 返回空数组（**不给按钮**，
 * 不猜 —— 猜一个必然被拒的动作是更坏的失败方向）。
 */
export const AFTER_SALES_STATUS_TRANSITIONS: Record<string, string[]> = {
  pending: ['processing', 'rejected', 'closed'],
  processing: ['resolved', 'closed'],
  resolved: [],
  rejected: [],
  closed: [],
}

/** 状态中文（未登记 ⇒ 原样回显枚举，不编名字） */
export function afterSalesStatusLabel(status: string | null | undefined): string {
  if (!status) return ''
  return AFTER_SALES_STATUS_LABELS[status] ?? status
}

/** 当前状态可流转到的目标（未登记状态 / 终态 ⇒ 空数组） */
export function allowedAfterSalesTargets(status: string | null | undefined): string[] {
  if (!status) return []
  return AFTER_SALES_STATUS_TRANSITIONS[status] ?? []
}

/**
 * 写动作（改状态）的确认文案 —— 不可逆动作必须说清「改成什么」。
 * 拒绝/关闭是**终态**（后端 `STATUS_TRANSITIONS` 里无出边）⇒ 文案显式提示不可再流转。
 */
export function afterSalesActionConfirmText(
  ticketNo: string,
  status: string,
): string {
  const label = afterSalesStatusLabel(status)
  const terminal = allowedAfterSalesTargets(status).length === 0
  return `工单 ${ticketNo} 将变更为「${label}」${terminal ? '（终态，之后不能再流转）' : ''}`
}
