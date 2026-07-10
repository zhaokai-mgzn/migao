'use client'

import { useState, useMemo } from 'react'
import { useCallback } from 'react'
import {
  PanelRightClose,
  PanelRightOpen,
  Package,
  ShoppingBag,
  Truck,
  BookOpen,
  MessageSquare,
  Clock,
  Inbox,
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

/** 从单条消息的 tool_calls 和 cards 中提取实体 */
function extractEntities(msg: ChatMessage): SessionEntity[] {
  const entities: SessionEntity[] = []

  // 从 tool_call input 提取
  for (const tc of msg.tool_calls || []) {
    const input = tc.input || {}
    // 订单查询工具 → 订单实体
    const orderId = input.order_id || input.order_no || input.orderId
    if (orderId && typeof orderId === 'string') {
      entities.push({
        type: 'order',
        value: orderId,
        label: orderId,
        followUp: `查看订单 ${orderId}`,
      })
    }
    // 物流查询工具 → 物流实体
    const trackingNo = input.tracking_no || input.trackingNo
    if (trackingNo && typeof trackingNo === 'string') {
      entities.push({
        type: 'logistics',
        value: trackingNo,
        label: trackingNo,
        followUp: `查询物流 ${trackingNo}`,
      })
    }
    // 商品详情工具 → 商品实体
    const productName = input.product_name || input.productName || input.name
    if (productName && typeof productName === 'string' && !orderId) {
      entities.push({
        type: 'product',
        value: productName,
        label: productName,
        followUp: `查看 ${productName} 详情`,
      })
    }
  }

  // 从 card data 提取
  for (const card of msg.cards || []) {
    const data = card.data || {}
    switch (card.type) {
      case 'order': {
        const order = data.order as Record<string, unknown> | undefined
        if (order?.orderNo) {
          entities.push({
            type: 'order',
            value: String(order.orderNo),
            label: String(order.orderNo),
            followUp: `查看订单 ${order.orderNo}`,
          })
        }
        break
      }
      case 'product_list': {
        const products = data.products as Array<{ name?: string }> | undefined
        if (products) {
          for (const p of products) {
            if (p.name) {
              entities.push({
                type: 'product',
                value: p.name,
                label: p.name,
                followUp: `查看 ${p.name} 详情`,
              })
            }
          }
        }
        break
      }
      case 'product_detail': {
        const product = data.product as { name?: string } | undefined
        if (product?.name) {
          entities.push({
            type: 'product',
            value: product.name,
            label: product.name,
            followUp: `查看 ${product.name} 详情`,
          })
        }
        break
      }
      case 'logistics': {
        const tn = data.tracking_no as string | undefined
        if (tn) {
          entities.push({
            type: 'logistics',
            value: tn,
            label: tn,
            followUp: `查询物流 ${tn}`,
          })
        }
        break
      }
    }
  }

  return entities
}

/** 实体去重：同 type + value 只保留一个 */
function dedupEntities(all: SessionEntity[]): SessionEntity[] {
  const seen = new Set<string>()
  return all.filter(e => {
    const k = `${e.type}:${e.value}`
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

/** 卡片去重 key */
function cardKey(card: ChatCard): string {
  const data = card.data || {}
  switch (card.type) {
    case 'order': {
      const order = data.order as Record<string, unknown> | undefined
      return `order-${order?.orderNo || JSON.stringify(data)}`
    }
    case 'product_list': {
      const products = data.products as Array<{ name?: string }> | undefined
      return `product_list-${products?.map(p => p.name).join(',') || JSON.stringify(data)}`
    }
    case 'logistics': {
      const tn = data.tracking_no as string | undefined
      return `logistics-${tn || JSON.stringify(data)}`
    }
    case 'product_detail': {
      const product = data.product as { name?: string } | undefined
      return `product_detail-${product?.name || JSON.stringify(data)}`
    }
    case 'knowledge': {
      return `knowledge-${data.title || JSON.stringify(data)}`
    }
    default:
      return `${card.type}-${JSON.stringify(data)}`
  }
}

/** 从卡片中提取一行摘要文本 */
function cardSummary(card: ChatCard): string {
  const data = card.data || {}
  switch (card.type) {
    case 'order': {
      const order = data.order as Record<string, unknown> | undefined
      return `订单 ${order?.orderNo || '—'}`
    }
    case 'product_list': {
      const products = data.products as Array<{ name?: string }> | undefined
      return products?.map(p => p.name).join('、') || '商品列表'
    }
    case 'logistics': {
      return `${data.company || '物流'} ${data.tracking_no || ''}`.trim()
    }
    case 'product_detail': {
      const product = data.product as { name?: string } | undefined
      return product?.name || '商品详情'
    }
    case 'knowledge': {
      return (data.title as string) || '知识库'
    }
    default:
      return card.type
  }
}

/** 卡片图标 */
function CardIcon({ type }: { type: string }) {
  const cls = 'w-4 h-4 flex-shrink-0'
  switch (type) {
    case 'order': return <ShoppingBag className={cn(cls, 'text-blue-500')} />
    case 'product_list':
    case 'product_detail': return <Package className={cn(cls, 'text-amber-500')} />
    case 'logistics': return <Truck className={cn(cls, 'text-green-500')} />
    case 'knowledge': return <BookOpen className={cn(cls, 'text-purple-500')} />
    default: return <Inbox className={cn(cls, 'text-gray-400')} />
  }
}

export default function SessionInsight() {
  const [collapsed, setCollapsed] = useState(false)
  const { currentSessionId, sessions, messages, sendMessage } = useChatStore()

  const currentSession = useMemo(
    () => sessions.find(s => s.session_id === currentSessionId),
    [sessions, currentSessionId],
  )

  // 从所有消息中提取卡片，按时间倒序去重
  const cards = useMemo(() => {
    const all: ChatCard[] = []
    // 从最新消息往前遍历
    for (let i = messages.length - 1; i >= 0; i--) {
      const msgCards = messages[i]?.cards
      if (msgCards) all.push(...msgCards)
    }
    // 去重：同 key 只保留第一个（最新）
    const seen = new Set<string>()
    return all.filter(c => {
      const k = cardKey(c)
      if (seen.has(k)) return false
      seen.add(k)
      return true
    })
  }, [messages])

  // 从所有消息中提取实体，去重
  const entities = useMemo(() => {
    const all: SessionEntity[] = []
    for (let i = messages.length - 1; i >= 0; i--) {
      all.push(...extractEntities(messages[i]))
    }
    return dedupEntities(all)
  }, [messages])

  const handleEntityClick = useCallback(
    (followUp: string) => {
      sendMessage(followUp)
    },
    [sendMessage],
  )

  const messageCount = currentSession?.message_count ?? messages.length
  const sessionStatus = currentSession?.status || 'active'

  // 计算会话时长（必须在 early return 之前，hooks 规则）
  const duration = useMemo(() => {
    if (!currentSession?.created_at) return null
    const start = new Date(currentSession.created_at).getTime()
    const end = currentSession.updated_at
      ? new Date(currentSession.updated_at).getTime()
      : Date.now()
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
    <div className="w-[280px] flex-shrink-0 border-l border-gray-200 bg-white flex flex-col h-full overflow-hidden">
      {/* 头部 */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-800">会话洞察</h3>
        <button
          onClick={() => setCollapsed(true)}
          className="p-1 rounded hover:bg-gray-100 transition-colors"
          title="收起"
        >
          <PanelRightClose className="w-4 h-4 text-gray-400" />
        </button>
      </div>

      {/* 内容区 */}
      <div className="flex-1 overflow-y-auto">
        {/* 会话统计 */}
        <div className="px-4 py-3 border-b border-gray-100">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
            会话统计
          </h4>
          <div className="grid grid-cols-2 gap-2">
            <StatBadge
              icon={<MessageSquare className="w-3.5 h-3.5" />}
              label="消息"
              value={String(messageCount)}
            />
            {duration && (
              <StatBadge
                icon={<Clock className="w-3.5 h-3.5" />}
                label="历时"
                value={duration}
              />
            )}
          </div>
          <div className="mt-2">
            <span
              className={cn(
                'inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium',
                sessionStatus === 'active'
                  ? 'bg-green-50 text-green-700 border border-green-200'
                  : 'bg-gray-50 text-gray-500 border border-gray-200',
              )}
            >
              {sessionStatus === 'active' ? '进行中' : '已结束'}
            </span>
          </div>
        </div>

        {/* 查询结果 */}
        <div className="px-4 py-3">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
            查询结果
          </h4>

          {cards.length === 0 ? (
            <div className="text-xs text-gray-400 text-center py-6 bg-gray-50 rounded-lg">
              暂无查询结果
              <br />
              <span className="text-[11px]">发送消息后这里会展示</span>
              <br />
              <span className="text-[11px]">AI 查到的商品和订单</span>
            </div>
          ) : (
            <div className="space-y-1.5">
              {cards.map((card, idx) => (
                <div
                  key={`${card.type}-${idx}`}
                  className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors cursor-default"
                >
                  <CardIcon type={card.type} />
                  <span className="text-xs text-gray-700 truncate flex-1">
                    {cardSummary(card)}
                  </span>
                  <span className="text-[10px] text-gray-400 flex-shrink-0">
                    {cardTypeLabel(card.type)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 便签板 */}
        <div className="px-4 py-3 border-t border-gray-100">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2 flex items-center gap-1">
            <Pin className="w-3 h-3" />
            便签板
          </h4>

          {entities.length === 0 ? (
            <div className="text-xs text-gray-400 text-center py-4 bg-gray-50 rounded-lg">
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

function cardTypeLabel(type: string): string {
  switch (type) {
    case 'order': return '订单'
    case 'product_list': return '商品'
    case 'logistics': return '物流'
    case 'product_detail': return '详情'
    case 'knowledge': return '知识'
    default: return type
  }
}
