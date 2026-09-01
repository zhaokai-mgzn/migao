import type { AfterSalesStatus, OrderStatus } from '@/types'

/**
 * 语义色 chips 的 Tailwind tone 类（织物质感 token，issue #2539 子任务 D）。
 * 替代默认蓝/灰/绿：info→primary、success→emerald、neutral→neutral、warning/error 沿用 amber/red。
 */
export type ChipTone = 'warning' | 'info' | 'success' | 'error' | 'neutral'

export interface StatusChip {
  tone: ChipTone
  label: string
}

export const chipToneClasses: Record<ChipTone, string> = {
  warning: 'bg-amber-50 text-amber-700 border-amber-200',
  info: 'bg-primary-50 text-primary-700 border-primary-200',
  success: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  error: 'bg-red-50 text-red-700 border-red-200',
  neutral: 'bg-neutral-100 text-neutral-700 border-neutral-200',
}

export const orderStatusChip: Record<OrderStatus, StatusChip> = {
  pending_payment: { tone: 'warning', label: '待付款' },
  pending_shipment: { tone: 'info', label: '待发货' },
  shipped: { tone: 'info', label: '已发货' },
  completed: { tone: 'success', label: '已完成' },
  closed: { tone: 'neutral', label: '已关闭' },
  refund: { tone: 'error', label: '退款/售后' },
}

export const afterSalesStatusChip: Record<AfterSalesStatus, StatusChip> = {
  pending: { tone: 'warning', label: '待处理' },
  processing: { tone: 'info', label: '处理中' },
  resolved: { tone: 'success', label: '已完成' },
  rejected: { tone: 'error', label: '已拒绝' },
  closed: { tone: 'neutral', label: '已关闭' },
}

const UNKNOWN_CHIP: StatusChip = { tone: 'neutral', label: '暂无数据' }

/** 订单状态 → chip；未知/空状态回退 neutral 且 label 恒为「暂无数据」。 */
export function orderStatusChipFor(status: string | null | undefined): StatusChip {
  if (status && status in orderStatusChip) {
    return orderStatusChip[status as OrderStatus]
  }
  return UNKNOWN_CHIP
}

/** 售后状态 → chip；未知/空状态回退 neutral 且 label 恒为「暂无数据」。 */
export function afterSalesStatusChipFor(status: string | null | undefined): StatusChip {
  if (status && status in afterSalesStatusChip) {
    return afterSalesStatusChip[status as AfterSalesStatus]
  }
  return UNKNOWN_CHIP
}
