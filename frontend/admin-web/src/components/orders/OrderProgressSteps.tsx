'use client'

import { Check } from 'lucide-react'
import dayjs from 'dayjs'
import type { OrderStatus } from '@/types'
import { cn } from '@/lib/utils'

interface OrderProgressStepsProps {
  status: OrderStatus
  paidAt?: string
  shippedAt?: string
  receivedAt?: string
}

interface StepDef {
  index: number
  label: string
  time?: string
}

/**
 * 计算每个步骤的状态
 * - completed: 已完成（蓝色 + 勾号）
 * - current: 当前步骤（蓝色 + 数字 + 外圈光晕）
 * - upcoming: 未来步骤（灰色 + 数字）
 */
function getStepStates(status: OrderStatus): Array<'completed' | 'current' | 'upcoming'> {
  // 4 steps: 已付款(0) -> 待发货(1) -> 待收货(2) -> 已完成(3)
  switch (status) {
    case 'pending_payment':
      return ['current', 'upcoming', 'upcoming', 'upcoming']
    case 'pending_shipment':
      return ['completed', 'current', 'upcoming', 'upcoming']
    case 'shipped':
      return ['completed', 'completed', 'current', 'upcoming']
    case 'completed':
      return ['completed', 'completed', 'completed', 'completed']
    case 'closed':
    case 'refund':
      return ['upcoming', 'upcoming', 'upcoming', 'upcoming']
    default:
      return ['upcoming', 'upcoming', 'upcoming', 'upcoming']
  }
}

function fmt(time?: string): string | undefined {
  if (!time) return undefined
  return dayjs(time).format('YYYY-MM-DD HH:mm')
}

export default function OrderProgressSteps({
  status,
  paidAt,
  shippedAt,
  receivedAt,
}: OrderProgressStepsProps) {
  const states = getStepStates(status)

  const steps: StepDef[] = [
    { index: 1, label: '已付款', time: fmt(paidAt) },
    { index: 2, label: '待发货', time: fmt(paidAt) },
    { index: 3, label: '待收货', time: fmt(shippedAt) },
    { index: 4, label: '已完成', time: fmt(receivedAt) },
  ]

  return (
    <div className="w-full">
      <div className="flex items-start">
        {steps.map((step, i) => {
          const state = states[i]
          const isFirst = i === 0
          const isLast = i === steps.length - 1
          // 左侧连接线：根据"前一个节点"是否已完成决定颜色
          const leftActive = !isFirst && states[i - 1] === 'completed'
          // 右侧连接线：根据"当前节点"是否已完成决定颜色
          const rightActive = !isLast && state === 'completed'

          return (
            <div
              key={step.label}
              className="flex-1 flex flex-col items-center relative"
            >
              {/* 节点 + 连接线层 */}
              <div className="relative w-full flex items-center justify-center h-9">
                {/* 左侧连接线（首个节点不需要） */}
                {!isFirst && (
                  <div
                    className={cn(
                      'absolute top-1/2 right-1/2 h-0.5 w-1/2 -translate-y-1/2 transition-colors',
                      leftActive ? 'bg-primary-500' : 'bg-gray-200'
                    )}
                  />
                )}

                {/* 右侧连接线（末尾节点不需要） */}
                {!isLast && (
                  <div
                    className={cn(
                      'absolute top-1/2 left-1/2 h-0.5 w-1/2 -translate-y-1/2 transition-colors',
                      rightActive ? 'bg-primary-500' : 'bg-gray-200'
                    )}
                  />
                )}

                {/* 圆形节点 */}
                <div
                  className={cn(
                    'relative z-10 flex items-center justify-center w-9 h-9 rounded-full border-2 text-sm font-medium shrink-0 transition-colors',
                    state === 'completed' && 'bg-primary-500 border-primary-500 text-white',
                    state === 'current' && 'bg-primary-500 border-primary-500 text-white ring-4 ring-primary-100',
                    state === 'upcoming' && 'bg-white border-gray-300 text-gray-400'
                  )}
                >
                  {state === 'completed' ? (
                    <Check className="w-4 h-4" strokeWidth={3} />
                  ) : (
                    <span>{step.index}</span>
                  )}
                </div>
              </div>

              {/* 标签 */}
              <div className="mt-3 text-center">
                <div
                  className={cn(
                    'text-sm font-medium',
                    state === 'completed' || state === 'current' ? 'text-gray-900' : 'text-gray-400'
                  )}
                >
                  {step.label}
                </div>
                {step.time && (state === 'completed' || state === 'current') && (
                  <div className="text-xs text-gray-500 mt-1 whitespace-nowrap">{step.time}</div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
