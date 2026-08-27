'use client'

import type { ChatCard } from '@/types'
import ProductCard from './ProductCard'
import LogisticsCard from './LogisticsCard'
import KnowledgeCard from './KnowledgeCard'

interface ToolResultCardProps {
  card: ChatCard
}

export default function ToolResultCard({ card }: ToolResultCardProps) {
  switch (card.type) {
    case 'product_list':
      return <ProductListCard data={card.data} />
    case 'product_detail':
      return <ProductCard data={card.data} />
    case 'logistics':
      return <LogisticsCard data={card.data} />
    case 'knowledge':
      return <KnowledgeCard data={card.data} />
    case 'order':
      return <OrderCard data={card.data} />
    default:
      return (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs text-gray-500">
          <span className="font-medium">未知卡片类型:</span> {card.type}
        </div>
      )
  }
}

function ProductListCard({ data }: { data: Record<string, unknown> }) {
  const products = (data.products as Array<Record<string, unknown>>) || []
  if (products.length === 0) return null

  return (
    <div className="space-y-2">
      {products.map((product, index) => (
        <ProductCard key={index} data={product} />
      ))}
    </div>
  )
}

function OrderCard({ data }: { data: Record<string, unknown> }) {
  const order = (data.order as Record<string, unknown>) || data
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-3 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-700">
          订单 {String(order.orderNo || order.order_no || '')}
        </span>
        <OrderStatusBadge status={(order.status as string) || ''} />
      </div>
      {typeof order.customerName === 'string' && order.customerName && (
        <p className="text-xs text-gray-500 mb-1">客户: {order.customerName}</p>
      )}
      {order.totalAmount !== undefined && (
        <p className="text-sm font-semibold text-red-500">
          ¥{Number(order.totalAmount || order.total_amount || 0).toFixed(2)}
        </p>
      )}
      {typeof order.createdAt === 'string' && order.createdAt && (
        <p className="text-[10px] text-gray-400 mt-1">
          {new Date(order.createdAt).toLocaleDateString('zh-CN')}
        </p>
      )}
    </div>
  )
}

function OrderStatusBadge({ status }: { status: string }) {
  const statusMap: Record<string, { label: string; className: string }> = {
    pending: { label: '待确认', className: 'bg-amber-50 text-amber-700 border-amber-200' },
    confirmed: { label: '已确认', className: 'bg-blue-50 text-blue-700 border-blue-200' },
    producing: { label: '生产中', className: 'bg-purple-50 text-purple-700 border-purple-200' },
    shipped: { label: '已发货', className: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
    completed: { label: '已完成', className: 'bg-green-50 text-green-700 border-green-200' },
    cancelled: { label: '已取消', className: 'bg-gray-50 text-gray-600 border-gray-200' },
  }

  const info = statusMap[status] || { label: status, className: 'bg-gray-50 text-gray-600 border-gray-200' }

  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${info.className}`}>
      {info.label}
    </span>
  )
}
