'use client'

import { TrendingUp, TrendingDown } from 'lucide-react'
import { cn } from '@/lib/utils'

interface StatCardProps {
  title: string
  value: string | number
  change?: {
    value: string
    isPositive: boolean
  }
  description?: string
  icon: React.ReactNode
  iconBgColor: string
  iconColor?: string
}

export default function StatCard({ title, value, change, description, icon, iconBgColor }: StatCardProps) {
  return (
    <div className="bg-white rounded-xl p-5 border border-gray-100 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-sm text-gray-500 mb-1">{title}</p>
          <h3 className="text-2xl font-bold text-gray-900 tabular-nums tracking-tight">{value}</h3>

          {change && (
            <div className="flex items-center gap-1 mt-2">
              {change.isPositive ? (
                <TrendingUp className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
              ) : (
                <TrendingDown className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />
              )}
              <span
                className={cn(
                  'text-xs font-medium',
                  change.isPositive ? 'text-green-600' : 'text-red-600'
                )}
              >
                {change.value}
              </span>
            </div>
          )}

          {description && (
            <p className="text-xs text-gray-400 mt-1">{description}</p>
          )}
        </div>

        <div className={cn('w-11 h-11 rounded-lg flex items-center justify-center flex-shrink-0 ml-3', iconBgColor)}>
          {icon}
        </div>
      </div>
    </div>
  )
}
