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
  /**
   * 这一块的读面**失败了**（issue #6715）。
   *
   * 🔴 为什么必须显式传：`total = data.reduce(…)` 而 `data` 是调用方的 `useState([])` 初值
   * ⇒ 读失败时会把「**读不到**」印成**事实性断言**「共 0 单」（健康基线是「共 308 单」）。
   * 读失败 ⇒ **不渲染计数位**（与失败横幅同一口径：不印 0，也不印「暂无」式结论）。
   * 默认 `false`：读成功且真为 0 单时照旧显示「共 0 单」（那是事实）。
   */
  readFailed?: boolean
}

export default function OrderStatusChart({ data, loading, readFailed = false }: OrderStatusChartProps) {
  const total = data.reduce((sum, item) => sum + item.count, 0)

  return (
    <div className="bg-white rounded-xl border border-neutral-100 shadow-sm p-5">
      <div className="flex items-center justify-between mb-5">
        <h3 className="text-sm font-semibold text-neutral-900">订单状态分布</h3>
        {!readFailed && <span data-testid="order-status-count" className="text-xs text-neutral-400">共 {total} 单</span>}
      </div>

      {loading ? (
        <div className="h-[260px] flex items-center justify-center">
          <div className="animate-spin w-6 h-6 border-2 border-primary-500 border-t-transparent rounded-full" />
        </div>
      ) : readFailed ? (
        <div data-testid="order-status-read-failed" className="h-[260px] flex items-center justify-center text-sm text-neutral-400">
          订单状态分布没读到
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
