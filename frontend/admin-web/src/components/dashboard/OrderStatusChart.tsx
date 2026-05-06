'use client'

import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
  Legend,
} from 'recharts'
import type { OrderStatusDistribution } from '@/types'

interface OrderStatusChartProps {
  data: OrderStatusDistribution[]
  loading?: boolean
}

export default function OrderStatusChart({ data, loading }: OrderStatusChartProps) {
  const total = data.reduce((sum, item) => sum + item.count, 0)

  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <div className="flex items-center justify-between mb-5">
        <h3 className="text-sm font-semibold text-gray-900">订单状态分布</h3>
        <span className="text-xs text-gray-400">共 {total} 单</span>
      </div>

      {loading ? (
        <div className="h-[260px] flex items-center justify-center">
          <div className="animate-spin w-6 h-6 border-2 border-primary-500 border-t-transparent rounded-full" />
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie
              data={data}
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={90}
              dataKey="count"
              nameKey="label"
              strokeWidth={2}
              stroke="#fff"
            >
              {data.map((entry, index) => (
                <Cell key={index} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip
              formatter={(value: number, name: string) => [`${value} 单`, name]}
              contentStyle={{
                borderRadius: 8,
                border: '1px solid #e8e8e8',
                boxShadow: '0 2px 8px rgba(0,0,0,0.08)',
                fontSize: 13,
              }}
            />
            <Legend
              verticalAlign="bottom"
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ fontSize: 12 }}
              formatter={(value: string, entry: any) => {
                const item = data.find(d => d.label === value)
                return `${value} ${item ? item.count : ''}`
              }}
            />
          </PieChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
