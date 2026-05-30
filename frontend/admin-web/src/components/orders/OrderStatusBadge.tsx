'use client'

import { cn } from '@/lib/utils'
import type { OrderStatus } from '@/types'
import { OrderStatusLabels } from '@/types'

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

const statusDotColors: Record<OrderStatus, string> = {
  pending_payment: 'bg-amber-500',
  pending_shipment: 'bg-blue-500',
  shipped: 'bg-indigo-500',
  completed: 'bg-green-500',
  closed: 'bg-gray-500',
  refund: 'bg-red-500',
}

export default function OrderStatusBadge({ status, className, onClick }: OrderStatusBadgeProps) {
  return (
    <span
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border',
        onClick && 'cursor-pointer hover:opacity-80 transition-opacity',
        statusStyles[status],
        className
      )}
    >
      <span className={cn('w-1.5 h-1.5 rounded-full', statusDotColors[status])} />
      {OrderStatusLabels[status]}
    </span>
  )
}
