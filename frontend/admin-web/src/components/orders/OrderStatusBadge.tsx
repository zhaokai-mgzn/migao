'use client'

import type { OrderStatus } from '@/types'
import StatusBadge from '@/components/ui/StatusBadge'
import { chipToneClasses, orderStatusChipFor } from '@/lib/status-chip'

interface OrderStatusBadgeProps {
  status: OrderStatus
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
