'use client'

import type { OrderStatus } from '@/types'
import { OrderStatusLabels } from '@/types'
import StatusBadge from '@/components/ui/StatusBadge'

interface OrderStatusBadgeProps {
  status: OrderStatus
  className?: string
  onClick?: () => void
}

const statusStyles: Record<OrderStatus, string> = {
  pending_payment: 'bg-amber-50 text-amber-700 border-amber-200',
  pending_shipment: 'bg-blue-50 text-blue-700 border-blue-200',
  shipped: 'bg-indigo-50 text-indigo-700 border-indigo-200',
  completed: 'bg-green-50 text-green-700 border-green-200',
  closed: 'bg-gray-50 text-gray-700 border-gray-200',
  refund: 'bg-red-50 text-red-700 border-red-200',
}

export default function OrderStatusBadge({ status, className, onClick }: OrderStatusBadgeProps) {
  return (
    <StatusBadge
      label={OrderStatusLabels[status]}
      color={statusStyles[status]}
      dot
      className={className}
      onClick={onClick}
    />
  )
}
