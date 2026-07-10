'use client'

import { useState, useMemo, useCallback } from 'react'
import {
  PanelRightClose,
  PanelRightOpen,
  Package,
  ShoppingBag,
  Truck,
  BookOpen,
  MessageSquare,
  Clock,
  Pin,
  Hash,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import type { ChatCard, ChatMessage } from '@/types'

// ─── 实体类型 ───────────────────────────────────────

interface SessionEntity {
  type: 'order' | 'product' | 'logistics'
  value: string
  label: string
  followUp: string
}

// ─── 卡片展示元信息 ──────────────────────────────────

interface CardMeta {
  icon: React.ReactNode
  typeLabel: string
  colorClass: string
  title: string           // 主标识（订单号/商品名/物流单号）
  subtitle: string | null  // 副信息（状态/金额/客户等）
  detail: string | null    // 额外细节
  entities: SessionEntity[] // 从该卡片提取的实体
}

/** 从卡片数据提取展示元信息 */
function getCardMeta(card: ChatCard): CardMeta | null {
  const data = card.data || {}

  switch (card.type) {
    // ─── 订单（单笔 or 列表）───
    case 'order': {
      // 列表格式: { items: [...] }
      const items = data.items as Array<Record<string, unknown>> | undefined
      if (items && items.length > 0) {
        const total = data.total as number | undefined
        const entities: SessionEntity[] = []
        const orderNos: string[] = []
        for (const item of items.slice(0, 5)) {
          const no = String(item.orderNo || item.order_no || '')
          if (no) {
            orderNos.push(no)
            entities.push({ type: 'order', value: no, label: no, followUp: `查看订单 ${no}` })
          }
        }
        return {
          icon: <ShoppingBag className="w-4 h-4 text-blue-500 flex-shrink-0" />,
          typeLabel: '订单',
          colorClass: 'border-l-blue-400',
          title: `订单列表 (${total || items.length} 条)`,
          subtitle: orderNos.slice(0, 5).join(' · ') + (orderNos.length > 5 ? ' ...' : '') || null,
          detail: null,
          entities,
        }
      }

      // 单笔格式: { order: {...} } 或扁平 { orderNo, ... }
      const order = (data.order || data) as Record<string, unknown>
      const orderNo = String(order.orderNo || order.order_no || '')
      if (!orderNo) return null
      const status = order.status || order.orderStatus
      const amount = order.totalAmount || order.amount
      const customer = order.customerName || order.customer_name

      const parts: string[] = []
      if (status) parts.push(statusLabel(String(status)))
      if (amount != null) parts.push(`¥${Number(amount).toFixed(2)}`)
      if (customer) parts.push(String(customer))
      const subtitle = parts.join(' · ') || null

      return {
        icon: <ShoppingBag className="w-4 h-4 text-blue-500 flex-shrink-0" />,
        typeLabel: '订单',
        colorClass: 'border-l-blue-400',
        title: orderNo,
        subtitle,
        detail: null,
        entities: [{ type: 'order', value: orderNo, label: orderNo, followUp: `查看订单 ${orderNo}` }],
      }
    }

    // ─── 商品列表 ───
    case 'product_list': {
      const products = data.products as Array<Record<string, unknown>> | undefined
      if (!products || products.length === 0) return null
      const entities: SessionEntity[] = []
      const names: string[] = []
      for (const p of products) {
        const name = String(p.name || '')
        if (name) {
          names.push(name)
          entities.push({ type: 'product', value: name, label: name, followUp: `查看 ${name} 详情` })
        }
      }
      return {
        icon: <Package className="w-4 h-4 text-amber-500 flex-shrink-0" />,
        typeLabel: '商品',
        colorClass: 'border-l-amber-400',
        title: `${products.length} 件商品`,
        subtitle: names.join(' · ') || null,
        detail: null,
        entities,
      }
    }

    // ─── 商品详情 ───
    case 'product_detail': {
      const product = (data.product || data) as Record<string, unknown>
      const name = String(product.name || '')
      if (!name) return null
      const price = product.price
      const unit = product.unit
      const parts: string[] = []
      if (price != null) parts.push(`¥${price}${unit ? `/${unit}` : ''}`)
      const spec = product.specifications as Record<string, string> | undefined
      if (spec) {
        parts.push(Object.values(spec).join(' · '))
      }
      return {
        icon: <Package className="w-4 h-4 text-amber-500 flex-shrink-0" />,
        typeLabel: '商品',
        colorClass: 'border-l-amber-400',
        title: name,
        subtitle: parts.join(' · ') || null,
        detail: product.description as string || null,
        entities: [{ type: 'product', value: name, label: name, followUp: `查看 ${name} 详情` }],
      }
    }

    // ─── 物流 ───
    case 'logistics': {
      const tn = String(data.tracking_no || data.trackingNo || '')
      if (!tn) return null
      const company = String(data.company || '')
      const status = data.status || data.logisticsStatus
      return {
        icon: <Truck className="w-4 h-4 text-green-500 flex-shrink-0" />,
        typeLabel: '物流',
        colorClass: 'border-l-green-400',
        title: tn,
        subtitle: [company, status ? statusLabel(String(status)) : null].filter(Boolean).join(' · ') || null,
        detail: null,
        entities: [{ type: 'logistics', value: tn, label: tn, followUp: `查询物流 ${tn}` }],
      }
    }

    // ─── 知识库 ───
    case 'knowledge': {
      const title = String(data.title || '')
      if (!title) return null
      return {
        icon: <BookOpen className="w-4 h-4 text-purple-500 flex-shrink-0" />,
        typeLabel: '知识',
        colorClass: 'border-l-purple-400',
        title,
        subtitle: null,
        detail: data.content ? String(data.content).slice(0, 80) : null,
        entities: [],
      }
    }

    default:
      return null
  }
}

function statusLabel(s: string): string {
  const map: Record<string, string> = {
    pending: '待确认', confirmed: '已确认', producing: '生产中',
    shipped: '已发货', completed: '已完成', cancelled: '已取消',
    paid: '已付款', refunding: '退款中', refunded: '已退款',
    transporting: '运输中', delivered: '已签收',
    waiting: '待处理', active: '进行中', closed: '已结束',
  }
  return map[s] || s
}

/** 卡片去重 key */
function cardKey(card: ChatCard): string {
  const data = card.data || {}
  switch (card.type) {
    case 'order': {
      // 列表格式用 items 去重
      if (data.items) return `order-list-${data.total || JSON.stringify(data.items)}`
      const order = (data.order || data) as Record<string, unknown>
      return `order-${order.orderNo || order.order_no || JSON.stringify(data)}`
    }
    case 'product_list': {
      const products = data.products as Array<{ name?: string }> | undefined
      return `product_list-${products?.map(p => p.name).join(',') || JSON.stringify(data)}`
    }
    case 'logistics': {
      return `logistics-${data.tracking_no || data.trackingNo || JSON.stringify(data)}`
    }
    case 'product_detail': {
      const product = (data.product || data) as { name?: string }
      return `product_detail-${product?.name || JSON.stringify(data)}`
    }
    case 'knowledge':
      return `knowledge-${data.title || JSON.stringify(data)}`
    default:
      return `${card.type}-${JSON.stringify(data)}`
  }
}

/** 从单条消息中提取实体（tool_calls + cards） */
function extractEntities(msg: ChatMessage): SessionEntity[] {
  const entities: SessionEntity[] = []

  for (const tc of msg.tool_calls || []) {
    const input = tc.input || {}
    const orderId = input.order_id || input.order_no || input.orderId
    if (orderId && typeof orderId === 'string') {
      entities.push({ type: 'order', value: orderId, label: orderId, followUp: `查看订单 ${orderId}` })
    }
    const trackingNo = input.tracking_no || input.trackingNo
    if (trackingNo && typeof trackingNo === 'string') {
      entities.push({ type: 'logistics', value: trackingNo, label: trackingNo, followUp: `查询物流 ${trackingNo}` })
    }
    const productName = input.product_name || input.productName || input.name
    if (productName && typeof productName === 'string' && !orderId) {
      entities.push({ type: 'product', value: productName, label: productName, followUp: `查看 ${productName} 详情` })
    }
  }

  for (const card of msg.cards || []) {
    const meta = getCardMeta(card)
    if (meta) entities.push(...meta.entities)
  }

  return entities
}

/** 实体去重 */
function dedupEntities(all: SessionEntity[]): SessionEntity[] {
  const seen = new Set<string>()
  return all.filter(e => {
    const k = `${e.type}:${e.value}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

// ═══════════════════════════════════════════════════

export default function SessionInsight() {
  const [collapsed, setCollapsed] = useState(false)
  const { currentSessionId, sessions, messages, sendMessage } = useChatStore()

  const currentSession = useMemo(
    () => sessions.find(s => s.session_id === currentSessionId),
    [sessions, currentSessionId],
  )

  // 卡片去重 + 元信息提取
  const cardMetas = useMemo(() => {
    const all: CardMeta[] = []
    const seenKeys = new Set<string>()
    for (let i = messages.length - 1; i >= 0; i--) {
      for (const card of messages[i]?.cards || []) {
        const k = cardKey(card)
        if (seenKeys.has(k)) continue
        seenKeys.add(k)
        const meta = getCardMeta(card)
        if (meta) all.push(meta)
      }
    }
    return all
  }, [messages])

  // 实体提取 + 去重
  const entities = useMemo(() => {
    const all: SessionEntity[] = []
    for (let i = messages.length - 1; i >= 0; i--) {
      all.push(...extractEntities(messages[i]))
    }
    return dedupEntities(all)
  }, [messages])

  const handleEntityClick = useCallback(
    (followUp: string) => { sendMessage(followUp) },
    [sendMessage],
  )

  const messageCount = currentSession?.message_count ?? messages.length
  const sessionStatus = currentSession?.status || 'active'

  const duration = useMemo(() => {
    if (!currentSession?.created_at) return null
    const start = new Date(currentSession.created_at).getTime()
    const end = currentSession.updated_at ? new Date(currentSession.updated_at).getTime() : Date.now()
    const mins = Math.round((end - start) / 60000)
    if (mins < 1) return '刚刚'
    if (mins < 60) return `${mins} 分钟`
    const hours = Math.floor(mins / 60)
    const remainMins = mins % 60
    return remainMins > 0 ? `${hours} 小时 ${remainMins} 分钟` : `${hours} 小时`
  }, [currentSession?.created_at, currentSession?.updated_at])

  if (!currentSessionId) return null

  if (collapsed) {
    return (
      <div className="flex-shrink-0 border-l border-gray-200 bg-white">
        <button
          onClick={() => setCollapsed(false)}
          className="p-3 hover:bg-gray-50 transition-colors"
          title="展开会话洞察"
        >
          <PanelRightOpen className="w-4 h-4 text-gray-500" />
        </button>
      </div>
    )
  }

  return (
    <div className="w-[300px] flex-shrink-0 border-l border-gray-200 bg-white flex flex-col h-full overflow-hidden">
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-800">会话洞察</h3>
        <button onClick={() => setCollapsed(true)} className="p-1 rounded hover:bg-gray-100 transition-colors" title="收起">
          <PanelRightClose className="w-4 h-4 text-gray-400" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* 会话统计 */}
        <div className="px-4 py-3 border-b border-gray-100">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">会话统计</h4>
          <div className="grid grid-cols-2 gap-2">
            <StatBadge icon={<MessageSquare className="w-3.5 h-3.5" />} label="消息" value={String(messageCount)} />
            {duration && <StatBadge icon={<Clock className="w-3.5 h-3.5" />} label="历时" value={duration} />}
          </div>
          <div className="mt-2">
            <span className={cn(
              'inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium',
              sessionStatus === 'active'
                ? 'bg-green-50 text-green-700 border border-green-200'
                : 'bg-gray-50 text-gray-500 border border-gray-200',
            )}>
              {sessionStatus === 'active' ? '进行中' : '已结束'}
            </span>
          </div>
        </div>

        {/* 查询结果 — 丰富卡片 */}
        <div className="px-3 py-3">
          <h4 className="px-1 text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">查询结果</h4>

          {cardMetas.length === 0 ? (
            <div className="text-xs text-gray-400 text-center py-8 bg-gray-50 rounded-lg leading-relaxed">
              暂无查询结果
              <br />
              <span className="text-[11px]">发送消息查询订单、商品或物流</span>
              <br />
              <span className="text-[11px]">结果会实时展示在这里</span>
            </div>
          ) : (
            <div className="space-y-2">
              {cardMetas.map((meta, idx) => (
                <div
                  key={`${meta.typeLabel}-${idx}`}
                  className={cn(
                    'bg-white border border-gray-200 rounded-lg p-2.5 border-l-[3px]',
                    meta.colorClass,
                  )}
                >
                  {/* 标题行 */}
                  <div className="flex items-center gap-2">
                    {meta.icon}
                    <span className="text-xs font-semibold text-gray-800 truncate flex-1">
                      {meta.title}
                    </span>
                    <span className="text-[10px] text-gray-400 flex-shrink-0">
                      {meta.typeLabel}
                    </span>
                  </div>

                  {/* 副信息行 */}
                  {meta.subtitle && (
                    <div className="mt-1.5 ml-6 text-[11px] text-gray-500 leading-relaxed break-all">
                      {meta.subtitle}
                    </div>
                  )}

                  {/* 详情行 */}
                  {meta.detail && (
                    <div className="mt-1 ml-6 text-[11px] text-gray-400 leading-relaxed line-clamp-2">
                      {meta.detail}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 便签板 */}
        <div className="px-3 py-3 border-t border-gray-100">
          <h4 className="px-1 text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-1">
            <Pin className="w-3 h-3" />
            便签板
          </h4>

          {entities.length === 0 ? (
            <div className="text-xs text-gray-400 text-center py-4 bg-gray-50 rounded-lg leading-relaxed">
              暂无便签
              <br />
              <span className="text-[11px]">查询订单或商品后</span>
              <br />
              <span className="text-[11px]">可点击标签快速追问</span>
            </div>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {entities.map((entity, idx) => (
                <button
                  key={`${entity.type}-${entity.value}-${idx}`}
                  onClick={() => handleEntityClick(entity.followUp)}
                  className={cn(
                    'inline-flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-medium transition-colors cursor-pointer border',
                    entity.type === 'order' && 'bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100',
                    entity.type === 'product' && 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100',
                    entity.type === 'logistics' && 'bg-green-50 text-green-700 border-green-200 hover:bg-green-100',
                  )}
                  title={`点击追问：${entity.followUp}`}
                >
                  <Hash className="w-3 h-3" />
                  {entity.label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function StatBadge({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="bg-gray-50 rounded-lg p-2.5 flex items-center gap-2">
      <span className="text-primary-500">{icon}</span>
      <div>
        <p className="text-base font-semibold text-gray-800 leading-tight">{value}</p>
        <p className="text-[10px] text-gray-500">{label}</p>
      </div>
    </div>
  )
}
