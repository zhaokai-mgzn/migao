'use client'

import { useState, useMemo } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import type { OrderTrendPoint } from '@/types'
import { cn } from '@/lib/utils'

interface OrderTrendChartProps {
  data: OrderTrendPoint[]
  loading?: boolean
  onRangeChange?: (days: number) => void
}

/** Check whether all data values (orders) are zero or empty */
function isAllZeroData(data: OrderTrendPoint[]): boolean {
  if (data.length === 0) return true
  return data.every((d) => (d.orders ?? 0) === 0)
}

export default function OrderTrendChart({ data, loading, onRangeChange }: OrderTrendChartProps) {
  const [range, setRange] = useState<7 | 30>(7)

  const handleRangeChange = (days: 7 | 30) => {
    setRange(days)
    onRangeChange?.(days)
  }

  const empty = useMemo(() => isAllZeroData(data), [data])

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <div className="flex items-center justify-between mb-5">
        <h3 className="text-sm font-semibold text-gray-900">订单趋势</h3>
        <div className="flex gap-1 bg-gray-100 rounded-lg p-0.5">
          {([7, 30] as const).map((d) => (
            <button
              key={d}
              onClick={() => handleRangeChange(d)}
              className={cn(
                'px-3 py-1 rounded-md text-xs font-medium transition-colors',
                range === d
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700'
              )}
            >
              {d === 7 ? '近7天' : '近30天'}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="h-[260px] flex items-center justify-center">
          <div className="animate-spin w-6 h-6 border-2 border-primary-500 border-t-transparent rounded-full" />
        </div>
      ) : empty ? (
        <div className="h-[260px] flex items-center justify-center text-gray-400 text-sm">
          暂无数据
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={data} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 12, fill: '#8c8c8c' }}
              tickLine={false}
              axisLine={{ stroke: '#e8e8e8' }}
            />
            <YAxis
              domain={[0, 'auto']}
              tick={{ fontSize: 12, fill: '#8c8c8c' }}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{
                borderRadius: 8,
                border: '1px solid #e8e8e8',
                boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
                fontSize: 13,
              }}
            />
            <Legend
              verticalAlign="top"
              height={36}
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ fontSize: 12 }}
            />
            <Line
              type="monotone"
              dataKey="orders"
              name="订单数"
              stroke="#2563eb"
              strokeWidth={2}
              dot={{ r: 3, fill: '#2563eb' }}
              activeDot={{ r: 5 }}
            />
            <Line
              type="monotone"
              dataKey="sessions"
              name="会话数"
              stroke="#16a34a"
              strokeWidth={2}
              dot={{ r: 3, fill: '#16a34a' }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
