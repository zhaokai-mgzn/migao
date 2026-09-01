'use client'

import Link from 'next/link'
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
        <div className="bg-neutral-50 border border-neutral-200 rounded-lg p-3 text-xs text-neutral-500">
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
  // 兼容后端归一化后的两种载荷：
  //   单订单 {"order": {...}} / 列表 {"orders": [...]}
  const single = (data.order as Record<string, unknown> | undefined) ?? undefined
  const orders = Array.isArray(data.orders) ? (data.orders as Array<Record<string, unknown>>) : undefined

  // 无任何可识别订单数据 → 不渲染（修复：此前 order_query 列表容器被原样下发，
  // 渲染出只剩「订单」二字的空盒子，用户无法理解也无法点击）
  if (!single && (!orders || orders.length === 0)) return null

  if (single) {
    return <OrderRow order={single} />
  }

  return (
    <div data-testid="order-card" className="bg-white border border-neutral-200 rounded-xl p-3 shadow-sm space-y-2">
      {orders!.map((order, index) => (
        <OrderRow key={(order.id as string) || index} order={order} />
      ))}
    </div>
  )
}

function OrderRow({ order }: { order: Record<string, unknown> }) {
  // 兼容后端字段两种命名（camelCase 与 snake_case）
  const orderNo = String(order.orderNo ?? order.order_no ?? '')
  const status = (order.status as string) || ''
  const customerName = (order.customerName ?? order.customer_name ?? '') as string
  const totalAmount = (order.totalAmount ?? order.total_amount) as number | undefined
  const createdAt = (order.createdAt ?? order.created_at) as string | undefined
  const orderId = (order.id as string | undefined)

  const content = (
    <div
      data-testid="order-card"
      className="bg-white border border-neutral-200 rounded-xl p-3 shadow-sm"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-neutral-700">
          {orderNo ? `订单 ${orderNo}` : '订单'}
        </span>
        <OrderStatusBadge status={status} />
      </div>
      {customerName && (
        <p className="text-xs text-neutral-500 mb-1">客户: {customerName}</p>
      )}
      {totalAmount !== undefined && (
        <p className="text-sm font-semibold text-red-500">
          ¥{Number(totalAmount).toFixed(2)}
        </p>
      )}
      {typeof createdAt === 'string' && createdAt && (
        <p className="text-[10px] text-neutral-400 mt-1">
          {new Date(createdAt).toLocaleDateString('zh-CN')}
        </p>
      )}
    </div>
  )

  // 有订单 ID 时整卡可点击跳转订单详情（用户反馈：此前的「订单」字样无法点击）
  if (orderId) {
    return (
      <Link
        href={`/orders/${orderId}`}
        className="block hover:opacity-90 transition-opacity"
        title={orderNo ? `查看订单 ${orderNo}` : '查看订单详情'}
      >
        {content}
      </Link>
    )
  }
  return content
}

function OrderStatusBadge({ status }: { status: string }) {
  const statusMap: Record<string, { label: string; className: string }> = {
    pending: { label: '待确认', className: 'bg-amber-50 text-amber-700 border-amber-200' },
    confirmed: { label: '已确认', className: 'bg-blue-50 text-blue-700 border-blue-200' },
    producing: { label: '生产中', className: 'bg-purple-50 text-purple-700 border-purple-200' },
    shipped: { label: '已发货', className: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
    completed: { label: '已完成', className: 'bg-green-50 text-green-700 border-green-200' },
    cancelled: { label: '已取消', className: 'bg-neutral-50 text-neutral-600 border-neutral-200' },
  }

  const info = statusMap[status] || { label: status, className: 'bg-neutral-50 text-neutral-600 border-neutral-200' }

  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${info.className}`}>
      {info.label}
    </span>
  )
}
