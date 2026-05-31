'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Phone, MapPin, Star, Plus, X, MessageSquare, ShoppingCart, StickyNote, Save } from 'lucide-react'
import { toast } from 'sonner'
import { Button, Badge } from '@/components/ui'
import { useRouteId } from '@/lib/use-route-id'
import type { CustomerDetail, CustomerTag, CustomerOrder, CustomerSession, CustomerChannel } from '@/types'
import { CustomerChannelLabels } from '@/types'
import dayjs from 'dayjs'

const TAG_COLORS = [
  '#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6',
  '#EC4899', '#06B6D4', '#F97316', '#14B8A6', '#6366F1',
]

export default function CustomerDetailPage() {
  const router = useRouter()
  const id = useRouteId('id')

  const [customer, setCustomer] = useState<CustomerDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'orders' | 'sessions' | 'notes'>('orders')
  const [remark, setRemark] = useState('')
  const [savingRemark, setSavingRemark] = useState(false)

  // 标签管理
  const [allTags, setAllTags] = useState<CustomerTag[]>([])
  const [showTagPicker, setShowTagPicker] = useState(false)

  const loadCustomer = useCallback(async () => {
    if (!id) return
    setLoading(true)
    try {
      await new Promise((resolve) => setTimeout(resolve, 500))
      const mockTags: CustomerTag[] = [
        { id: 't1', name: 'VIP客户', color: '#EF4444' },
        { id: 't2', name: '窗帘定制', color: '#3B82F6' },
        { id: 't3', name: '需要跟进', color: '#F59E0B' },
        { id: 't4', name: '售后中', color: '#8B5CF6' },
        { id: 't5', name: '新客户', color: '#10B981' },
      ]
      setAllTags(mockTags)

      const mockCustomer: CustomerDetail = {
        id,
        name: '张美丽',
        nickname: '美丽窗帘店',
        phone: '13812341234',
        avatar: '',
        channel: 'wechat_mini',
        vipLevel: 3,
        tags: [mockTags[0], mockTags[1]],
        remark: '老客户，偏好遮光窗帘，预算中高端',
        lastActiveAt: '2026-04-20T14:30:00',
        createdAt: '2026-01-15T10:00:00',
        orders: [
          { id: 'o1', orderNo: 'ORD20260415001', totalAmount: 2680, status: 'completed', createdAt: '2026-04-15T10:00:00' },
          { id: 'o2', orderNo: 'ORD20260410002', totalAmount: 1560, status: 'producing', createdAt: '2026-04-10T14:30:00' },
          { id: 'o3', orderNo: 'ORD20260320003', totalAmount: 890, status: 'completed', createdAt: '2026-03-20T09:00:00' },
        ],
        sessions: [
          { id: 's1', lastMessage: '我想看看新款遮光窗帘', channel: 'wechat_mini', isAI: true, createdAt: '2026-04-20T14:30:00' },
          { id: 's2', lastMessage: '我的订单什么时候能好？', channel: 'wechat_mini', isAI: false, createdAt: '2026-04-18T09:15:00' },
          { id: 's3', lastMessage: '尺寸怎么量？', channel: 'wechat_mini', isAI: true, createdAt: '2026-04-10T16:00:00' },
        ],
      }
      setCustomer(mockCustomer)
      setRemark(mockCustomer.remark || '')
    } catch (error) {
      toast.error('加载客户信息失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    loadCustomer()
  }, [loadCustomer])

  const handleSaveRemark = async () => {
    setSavingRemark(true)
    try {
      await new Promise((resolve) => setTimeout(resolve, 500))
      toast.success('备注已保存')
    } catch (error) {
      toast.error('保存失败')
    } finally {
      setSavingRemark(false)
    }
  }

  const handleAddTag = async (tag: CustomerTag) => {
    if (!customer) return
    const tags = customer.tags || []
    if (tags.find((t) => t.id === tag.id)) {
      toast.info('该标签已存在')
      return
    }
    setCustomer({ ...customer, tags: [...tags, tag] })
    setShowTagPicker(false)
    toast.success(`已添加标签「${tag.name}」`)
  }

  const handleRemoveTag = async (tagId: string) => {
    if (!customer) return
    const tags = customer.tags || []
    setCustomer({ ...customer, tags: tags.filter((t) => t.id !== tagId) })
    toast.success('已移除标签')
  }

  const getChannelLabel = (channel: CustomerChannel | string | undefined) => {
    if (!channel) return ''
    return CustomerChannelLabels[channel as CustomerChannel] || String(channel)
  }

  const getOrderStatusLabel = (status: string) => {
    const map: Record<string, { label: string; variant: 'success' | 'warning' | 'info' | 'default' | 'error' }> = {
      pending: { label: '待确认', variant: 'warning' },
      confirmed: { label: '已确认', variant: 'info' },
      producing: { label: '生产中', variant: 'info' },
      completed: { label: '已完成', variant: 'success' },
      cancelled: { label: '已取消', variant: 'default' },
    }
    return map[status] || { label: status, variant: 'default' as const }
  }

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <div className="flex items-center gap-2 text-gray-500">
          <div className="w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
          加载中...
        </div>
      </div>
    )
  }

  if (!customer) {
    return (
      <div className="p-6 text-center text-gray-500">
        <p>客户不存在</p>
        <Button variant="secondary" className="mt-4" onClick={() => router.back()}>返回</Button>
      </div>
    )
  }

  const initials = (customer.name || '?').slice(0, 1)
  const availableTags = allTags.filter((t) => !((customer.tags || []).find((ct) => ct.id === t.id)))
  const vipLevelNum = typeof customer.vipLevel === 'number'
    ? customer.vipLevel
    : (() => {
        const m = String(customer.vipLevel ?? '').toLowerCase().match(/(\d+)/)
        return m ? Number(m[1]) : 0
      })()

  return (
    <div className="p-6">
      {/* 返回按钮 */}
      <button onClick={() => router.back()} className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-900 mb-4 transition-colors">
        <ArrowLeft className="w-4 h-4" />
        返回客户列表
      </button>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧：客户信息卡片 */}
        <div className="lg:col-span-1 space-y-4">
          {/* 基本信息 */}
          <div className="bg-white border border-gray-200 rounded-lg p-6">
            <div className="flex items-center gap-4 mb-4">
              <div className="w-16 h-16 rounded-full bg-blue-500 flex items-center justify-center text-white text-2xl font-bold">
                {initials}
              </div>
              <div>
                <h2 className="text-lg font-semibold text-gray-900">{customer.name || '未知客户'}</h2>
                {customer.nickname && <p className="text-sm text-gray-500">{customer.nickname}</p>}
                <div className="flex items-center gap-1 mt-1">
                  {vipLevelNum > 0 ? (
                    Array.from({ length: vipLevelNum }).map((_, i) => (
                      <Star key={i} className="w-4 h-4 fill-amber-400 text-amber-400" />
                    ))
                  ) : (
                    <span className="text-xs text-gray-400">普通客户</span>
                  )}
                </div>
              </div>
            </div>

            <div className="space-y-3 text-sm">
              <div className="flex items-center gap-2 text-gray-600">
                <Phone className="w-4 h-4 text-gray-400" />
                <span>{customer.phone || '未填写'}</span>
              </div>
              <div className="flex items-center gap-2 text-gray-600">
                <MapPin className="w-4 h-4 text-gray-400" />
                <Badge variant="info">{getChannelLabel(customer.channel)}</Badge>
              </div>
              <div className="text-xs text-gray-400 pt-2 border-t border-gray-100">
                <div>注册时间：{dayjs(customer.createdAt).format('YYYY-MM-DD')}</div>
                <div>最后互动：{dayjs(customer.lastActiveAt).format('YYYY-MM-DD HH:mm')}</div>
              </div>
            </div>
          </div>

          {/* 标签管理 */}
          <div className="bg-white border border-gray-200 rounded-lg p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-900">标签</h3>
              <div className="relative">
                <button
                  className="p-1 text-gray-400 hover:text-primary-600 transition-colors"
                  onClick={() => setShowTagPicker(!showTagPicker)}
                >
                  <Plus className="w-4 h-4" />
                </button>
                {showTagPicker && availableTags.length > 0 && (
                  <div className="absolute right-0 top-8 bg-white border border-gray-200 rounded-lg shadow-lg py-2 min-w-[150px] z-10">
                    {availableTags.map((tag) => (
                      <button
                        key={tag.id}
                        className="w-full text-left px-3 py-1.5 text-sm hover:bg-gray-50 flex items-center gap-2"
                        onClick={() => handleAddTag(tag)}
                      >
                        <span className="w-3 h-3 rounded-full" style={{ backgroundColor: tag.color }} />
                        {tag.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {(!customer.tags || customer.tags.length === 0) && <span className="text-xs text-gray-400">暂无标签</span>}
              {(customer.tags || []).map((tag) => (
                <span
                  key={tag.id}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium group"
                  style={{
                    backgroundColor: tag.color + '15',
                    color: tag.color,
                    border: `1px solid ${tag.color}30`,
                  }}
                >
                  {tag.name}
                  <button
                    className="opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={() => handleRemoveTag(tag.id)}
                  >
                    <X className="w-3 h-3" />
                  </button>
                </span>
              ))}
            </div>
          </div>

          {/* 客户备注 */}
          <div className="bg-white border border-gray-200 rounded-lg p-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-900">备注</h3>
              <Button size="sm" variant="ghost" onClick={handleSaveRemark} loading={savingRemark}>
                <Save className="w-3.5 h-3.5 mr-1" />
                保存
              </Button>
            </div>
            <textarea
              rows={4}
              className="w-full px-3 py-2 rounded border border-gray-300 text-sm placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
              placeholder="添加客户备注..."
              value={remark}
              onChange={(e) => setRemark(e.target.value)}
            />
          </div>
        </div>

        {/* 右侧：订单和会话历史 */}
        <div className="lg:col-span-2">
          <div className="bg-white border border-gray-200 rounded-lg">
            {/* Tab 栏 */}
            <div className="flex border-b border-gray-200">
              {[
                { key: 'orders' as const, label: '订单历史', icon: ShoppingCart, count: customer.orders?.length },
                { key: 'sessions' as const, label: '会话历史', icon: MessageSquare, count: customer.sessions?.length },
                { key: 'notes' as const, label: '跟进记录', icon: StickyNote },
              ].map((tab) => (
                <button
                  key={tab.key}
                  className={`flex items-center gap-2 px-6 py-3 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === tab.key
                      ? 'border-primary-600 text-primary-600'
                      : 'border-transparent text-gray-500 hover:text-gray-900'
                  }`}
                  onClick={() => setActiveTab(tab.key)}
                >
                  <tab.icon className="w-4 h-4" />
                  {tab.label}
                  {tab.count !== undefined && (
                    <span className="text-xs bg-gray-100 rounded-full px-2 py-0.5">{tab.count}</span>
                  )}
                </button>
              ))}
            </div>

            {/* Tab 内容 */}
            <div className="p-6">
              {/* 订单历史 */}
              {activeTab === 'orders' && (
                <div className="space-y-3">
                  {(!customer.orders || customer.orders.length === 0) ? (
                    <p className="text-center text-gray-500 py-8 text-sm">暂无订单记录</p>
                  ) : (
                    customer.orders.map((order) => {
                      const statusInfo = getOrderStatusLabel(order.status)
                      return (
                        <div key={order.id} className="flex items-center justify-between p-4 border border-gray-100 rounded-lg hover:bg-gray-50 transition-colors">
                          <div>
                            <div className="font-medium text-gray-900">{order.orderNo || '-'}</div>
                            <div className="text-xs text-gray-500 mt-1">
                              {order.createdAt ? dayjs(order.createdAt).format('YYYY-MM-DD HH:mm') : '-'}
                            </div>
                          </div>
                          <div className="flex items-center gap-4">
                            <span className="text-base font-semibold text-gray-900">
                              ¥{(order.totalAmount ?? 0).toFixed(2)}
                            </span>
                            <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
                          </div>
                        </div>
                      )
                    })
                  )}
                </div>
              )}

              {/* 会话历史 */}
              {activeTab === 'sessions' && (
                <div className="space-y-3">
                  {(!customer.sessions || customer.sessions.length === 0) ? (
                    <p className="text-center text-gray-500 py-8 text-sm">暂无会话记录</p>
                  ) : (
                    customer.sessions.map((session) => (
                      <div key={session.id} className="flex items-start gap-3 p-4 border border-gray-100 rounded-lg hover:bg-gray-50 transition-colors">
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${session.isAI ? 'bg-purple-100' : 'bg-blue-100'}`}>
                          <MessageSquare className={`w-4 h-4 ${session.isAI ? 'text-purple-600' : 'text-blue-600'}`} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <Badge variant={session.isAI ? 'default' : 'info'}>
                              {session.isAI ? 'AI 对话' : '人工客服'}
                            </Badge>
                            <span className="text-xs text-gray-400">
                              {dayjs(session.createdAt).format('MM-DD HH:mm')}
                            </span>
                          </div>
                          <p className="text-sm text-gray-600 truncate">{session.lastMessage}</p>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              )}

              {/* 跟进记录 */}
              {activeTab === 'notes' && (
                <div className="text-center text-gray-500 py-8 text-sm">
                  暂无跟进记录，功能开发中...
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
