'use client'

import Link from 'next/link'
import { ArrowRight } from 'lucide-react'
import Badge from '@/components/ui/Badge'
import type { Order, OrderStatus } from '@/types'
import { OrderStatusLabels } from '@/types'

interface RecentOrdersProps {
  orders: Order[]
  loading?: boolean
}

const statusVariantMap: Record<OrderStatus, 'warning' | 'info' | 'default' | 'success' | 'error'> = {
  pending_payment: 'warning',
  pending_shipment: 'info',
  shipped: 'info',
  completed: 'success',
  closed: 'default',
  refund: 'error',
}

function formatAmount(amount: number): string {
  return '¥' + amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatTime(dateStr?: string): string {
  if (!dateStr) return '--'
  const d = new Date(dateStr)
  return `${(d.getMonth() + 1).toString().padStart(2, '0')}-${d.getDate().toString().padStart(2, '0')} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

export default function RecentOrders({ orders, loading }: RecentOrdersProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-gray-900">近期订单</h3>
        <Link
          href="/orders"
          className="flex items-center gap-1 text-xs text-primary-600 hover:text-primary-700 font-medium"
        >
          查看全部
          <ArrowRight className="w-3.5 h-3.5" />
        </Link>
      </div>

      {loading ? (
        <div className="h-40 flex items-center justify-center">
          <div className="animate-spin w-6 h-6 border-2 border-primary-500 border-t-transparent rounded-full" />
        </div>
      ) : orders.length === 0 ? (
        <div className="h-40 flex items-center justify-center text-sm text-gray-400">
          暂无订单数据
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left py-2.5 px-2 text-xs font-medium text-gray-500">订单号</th>
                <th className="text-left py-2.5 px-2 text-xs font-medium text-gray-500">客户</th>
                <th className="text-right py-2.5 px-2 text-xs font-medium text-gray-500">金额</th>
                <th className="text-center py-2.5 px-2 text-xs font-medium text-gray-500">状态</th>
                <th className="text-right py-2.5 px-2 text-xs font-medium text-gray-500">时间</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => (
                <tr key={order.id} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50">
                  <td className="py-2.5 px-2">
                    <Link href={`/orders/${order.id}`} className="text-primary-600 hover:underline font-mono text-xs">
                      {order.orderNo}
                    </Link>
                  </td>
                  <td className="py-2.5 px-2 text-gray-700">{order.customerName}</td>
                  <td className="py-2.5 px-2 text-right font-medium text-gray-900 tabular-nums">
                    {formatAmount(order.totalAmount)}
                  </td>
                  <td className="py-2.5 px-2 text-center">
                    <Badge variant={statusVariantMap[order.status]}>
                      {OrderStatusLabels[order.status]}
                    </Badge>
                  </td>
                  <td className="py-2.5 px-2 text-right text-gray-400 text-xs tabular-nums">
                    {formatTime(order.createdAt)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
