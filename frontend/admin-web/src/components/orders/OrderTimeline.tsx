'use client'

import { cn } from '@/lib/utils'
import { Check } from 'lucide-react'
import type { OrderStatus, StatusHistory } from '@/types'
import { OrderStatusLabels, OrderStatusFlow } from '@/types'
import dayjs from 'dayjs'

interface OrderTimelineProps {
  currentStatus: OrderStatus
  statusHistory?: StatusHistory[]
  className?: string
}

const statusColors: Record<OrderStatus, { bg: string; border: string; text: string }> = {
  pending_payment: { bg: 'bg-amber-500', border: 'border-amber-500', text: 'text-amber-700' },
  pending_shipment: { bg: 'bg-blue-500', border: 'border-blue-500', text: 'text-blue-700' },
  shipped: { bg: 'bg-indigo-500', border: 'border-indigo-500', text: 'text-indigo-700' },
  completed: { bg: 'bg-green-500', border: 'border-green-500', text: 'text-green-700' },
  closed: { bg: 'bg-gray-500', border: 'border-gray-500', text: 'text-gray-700' },
  refund: { bg: 'bg-red-500', border: 'border-red-500', text: 'text-red-700' },
}

export default function OrderTimeline({ currentStatus, statusHistory, className }: OrderTimelineProps) {
  const isClosed = currentStatus === 'closed'
  const currentIndex = OrderStatusFlow.indexOf(currentStatus)

  const getHistoryItem = (status: OrderStatus) => {
    return statusHistory?.find((h) => h.status === status)
  }

  return (
    <div className={cn('', className)}>
      {/* 步骤条 */}
      <div className="flex items-center justify-between mb-6">
        {OrderStatusFlow.map((status, index) => {
          const isCompleted = !isClosed && currentIndex >= index
          const isCurrent = !isClosed && currentIndex === index
          const historyItem = getHistoryItem(status)
          const colors = statusColors[status]

          return (
            <div key={status} className="flex items-center flex-1 last:flex-none">
              {/* 节点 */}
              <div className="flex flex-col items-center">
                <div
                  className={cn(
                    'w-8 h-8 rounded-full flex items-center justify-center border-2 transition-all',
                    isCompleted
                      ? `${colors.bg} border-transparent text-white`
                      : isCurrent
                      ? `bg-white ${colors.border} ${colors.text}`
                      : 'bg-gray-100 border-gray-200 text-gray-400'
                  )}
                >
                  {isCompleted && !isCurrent ? (
                    <Check className="w-4 h-4" />
                  ) : (
                    <span className="text-xs font-bold">{index + 1}</span>
                  )}
                </div>
                <span
                  className={cn(
                    'mt-2 text-xs font-medium whitespace-nowrap',
                    isCompleted || isCurrent ? colors.text : 'text-gray-400'
                  )}
                >
                  {OrderStatusLabels[status]}
                </span>
                {historyItem && (
                  <span className="mt-0.5 text-[10px] text-gray-400">
                    {dayjs(historyItem.time).format('MM-DD HH:mm')}
                  </span>
                )}
              </div>

              {/* 连接线 */}
              {index < OrderStatusFlow.length - 1 && (
                <div
                  className={cn(
                    'flex-1 h-0.5 mx-2 mt-[-20px]',
                    !isClosed && currentIndex > index ? 'bg-green-400' : 'bg-gray-200'
                  )}
                />
              )}
            </div>
          )
        })}
      </div>

      {/* 已关闭状态 */}
      {isClosed && (
        <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-lg">
          <div className="w-6 h-6 rounded-full bg-red-500 flex items-center justify-center">
            <span className="text-white text-xs font-bold">✕</span>
          </div>
          <div>
            <span className="text-sm font-medium text-red-700">订单已关闭</span>
            {getHistoryItem('closed') && (
              <span className="ml-2 text-xs text-red-500">
                {dayjs(getHistoryItem('closed')!.time).format('YYYY-MM-DD HH:mm')}
              </span>
            )}
          </div>
        </div>
      )}

      {/* 状态历史时间线 */}
      {statusHistory && statusHistory.length > 0 && (
        <div className="mt-4 border-t border-gray-100 pt-4">
          <h4 className="text-sm font-medium text-gray-700 mb-3">状态变更记录</h4>
          <div className="space-y-3">
            {[...statusHistory].reverse().map((item, index) => {
              const colors = statusColors[item.status]
              return (
                <div key={index} className="flex items-start gap-3">
                  <div className="flex flex-col items-center">
                    <div className={cn('w-2.5 h-2.5 rounded-full mt-1', colors.bg)} />
                    {index < statusHistory.length - 1 && (
                      <div className="w-px h-6 bg-gray-200 mt-1" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={cn('text-sm font-medium', colors.text)}>
                        {OrderStatusLabels[item.status]}
                      </span>
                      <span className="text-xs text-gray-400">
                        {dayjs(item.time).format('YYYY-MM-DD HH:mm:ss')}
                      </span>
                    </div>
                    {item.operator && (
                      <p className="text-xs text-gray-500 mt-0.5">操作人: {item.operator}</p>
                    )}
                    {item.remark && (
                      <p className="text-xs text-gray-500 mt-0.5">{item.remark}</p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
