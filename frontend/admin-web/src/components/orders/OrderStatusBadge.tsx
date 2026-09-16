'use client'

import StatusBadge from '@/components/ui/StatusBadge'
import { chipToneClasses, orderStatusChipFor } from '@/lib/status-chip'

interface OrderStatusBadgeProps {
  /** 原始状态值（后端枚举或前端枚举均可，chip 内统一归一/区分） */
  status: string
  className?: string
  onClick?: () => void
}

export default function OrderStatusBadge({ status, className, onClick }: OrderStatusBadgeProps) {
  const chip = orderStatusChipFor(status)
  return (
    <StatusBadge
      label={chip.label}
      color={chipToneClasses[chip.tone]}
      dot
      className={className}
      onClick={onClick}
    />
  )
}
