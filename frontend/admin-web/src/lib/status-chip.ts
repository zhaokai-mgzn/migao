// 织物质感改版：订单/售后状态语义色 chips 映射（纯函数，无 JSX）。
//
// 状态 → { label, tone } 的语义色映射是页面级「状态 chips」的单一事实源，
// 供看板「近期订单」等列表与售后列表复用，避免各处手写颜色。
import { OrderStatusLabels, AfterSalesStatusLabels } from '@/types'
import type { OrderStatus, AfterSalesStatus } from '@/types'

/** 语义色阶（与 tailwind 织物质感 token 对齐，不使用默认蓝 blue 系）。 */
export type ChipTone = 'warning' | 'info' | 'success' | 'error' | 'neutral' | 'accent'

export interface StatusChip {
  label: string
  tone: ChipTone
}

/** 语义色 → Tailwind class（软分层 chips：浅底 + 深字 + 极细描边）。 */
export const chipToneClasses: Record<ChipTone, string> = {
  warning: 'bg-amber-50 text-amber-800 border-amber-200',
  info: 'bg-primary-50 text-primary-700 border-primary-200',
  success: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  error: 'bg-red-50 text-red-700 border-red-200',
  neutral: 'bg-neutral-100 text-neutral-600 border-neutral-200',
  accent: 'bg-accent-50 text-accent-700 border-accent-200',
}

const ORDER_TONES: Record<OrderStatus, ChipTone> = {
  pending_payment: 'warning',
  pending_shipment: 'info',
  shipped: 'info',
  completed: 'success',
  closed: 'neutral',
  refund: 'error',
}

const AFTERSALES_TONES: Record<AfterSalesStatus, ChipTone> = {
  pending: 'warning',
  processing: 'info',
  resolved: 'success',
  rejected: 'error',
  closed: 'neutral',
}

/** 未知/空状态回退的语义色（中性，非 '-' 占位）。 */
const UNKNOWN_CHIP: StatusChip = { label: '暂无数据', tone: 'neutral' }

/**
 * 订单状态 → 语义色 chip。
 * 未知/空值回退 neutral 且 label 恒为「暂无数据」，绝不返回 '-' 占位。
 */
export function orderStatusChip(status?: string | null): StatusChip {
  if (!status) return UNKNOWN_CHIP
  const tone = ORDER_TONES[status as OrderStatus]
  if (!tone) return UNKNOWN_CHIP
  return { label: OrderStatusLabels[status as OrderStatus], tone }
}

/**
 * 售后状态 → 语义色 chip。
 * 未知/空值回退 neutral 且 label 恒为「暂无数据」，绝不返回 '-' 占位。
 */
export function afterSalesStatusChip(status?: string | null): StatusChip {
  if (!status) return UNKNOWN_CHIP
  const tone = AFTERSALES_TONES[status as AfterSalesStatus]
  if (!tone) return UNKNOWN_CHIP
  return { label: AfterSalesStatusLabels[status as AfterSalesStatus], tone }
}
