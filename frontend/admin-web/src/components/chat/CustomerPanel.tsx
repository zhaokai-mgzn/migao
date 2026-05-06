'use client'

import { useState, useEffect } from 'react'
import {
  PanelRightClose,
  PanelRightOpen,
  User,
  Phone,
  Star,
  ShoppingBag,
  MessageCircle,
  Clock,
  Package,
  Globe,
} from 'lucide-react'
import { cn, formatFullDateTime, formatChatTime } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import { chatApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import type { ChatCustomerInfo } from '@/types'

export default function CustomerPanel() {
  const [collapsed, setCollapsed] = useState(false)
  const { currentSessionId, sessions } = useChatStore()
  const [customerInfo, setCustomerInfo] = useState<ChatCustomerInfo | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const currentSession = sessions.find(
    (s) => s.session_id === currentSessionId
  )

  // Load customer info when session changes
  useEffect(() => {
    if (!currentSessionId) {
      setCustomerInfo(null)
      return
    }

    // Build info from current session data
    const info: ChatCustomerInfo = {
      name: currentSession?.customer_name || '未知客户',
      source: '在线客服',
    }
    setCustomerInfo(info)
  }, [currentSessionId, currentSession])

  if (!currentSessionId) return null

  // 收起状态 - 只显示切换按钮
  if (collapsed) {
    return (
      <div className="flex-shrink-0 border-l border-gray-200 bg-white">
        <button
          onClick={() => setCollapsed(false)}
          className="p-3 hover:bg-gray-50 transition-colors"
          title="展开客户信息"
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
        <h3 className="text-sm font-semibold text-gray-800">客户信息</h3>
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
        {/* 客户基本信息 */}
        <div className="px-4 py-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-primary-100 flex items-center justify-center flex-shrink-0">
              <User className="w-5 h-5 text-primary-600" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-gray-800 truncate">
                {customerInfo?.name || '未知客户'}
              </p>
              <p className="text-xs text-gray-500">
                会话 {currentSessionId?.slice(0, 8)}...
              </p>
            </div>
          </div>

          {/* 标签 */}
          <div className="flex flex-wrap gap-1.5 mt-3">
            {customerInfo?.vipLevel ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-amber-50 text-amber-700 border border-amber-200 rounded text-[11px] font-medium">
                <Star className="w-3 h-3" />
                {customerInfo.vipLevel}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-50 text-gray-400 border border-gray-200 rounded text-[11px] font-medium">
                <Star className="w-3 h-3" />
                未设置等级
              </span>
            )}
            <span className={cn(
              'inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium',
              currentSession?.status === 'active'
                ? 'bg-green-50 text-green-700 border border-green-200'
                : 'bg-gray-50 text-gray-500 border border-gray-200'
            )}>
              {currentSession?.status === 'active' ? '在线中' : '已结束'}
            </span>
          </div>
        </div>

        {/* 联系信息 */}
        <div className="px-4 py-3 border-b border-gray-100">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
            联系信息
          </h4>
          <div className="space-y-2">
            <InfoRow
              icon={<Phone className="w-3.5 h-3.5" />}
              label="电话"
              value={customerInfo?.phone || '暂无'}
            />
            <InfoRow
              icon={<Globe className="w-3.5 h-3.5" />}
              label="来源"
              value={customerInfo?.source || '在线客服'}
            />
            <InfoRow
              icon={<Clock className="w-3.5 h-3.5" />}
              label="注册"
              value={customerInfo?.registeredDays !== undefined ? `${customerInfo.registeredDays} 天` : '暂无'}
            />
            <InfoRow
              icon={<Clock className="w-3.5 h-3.5" />}
              label="开始"
              value={formatFullDateTime(currentSession?.created_at)}
            />
          </div>
        </div>

        {/* 历史订单摘要 */}
        <div className="px-4 py-3 border-b border-gray-100">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
            最近订单
          </h4>
          {customerInfo?.recentOrders && customerInfo.recentOrders.length > 0 ? (
            <>
              <div className="grid grid-cols-2 gap-2">
                <StatCard
                  icon={<ShoppingBag className="w-4 h-4" />}
                  label="总订单"
                  value={String(customerInfo.totalOrders || 0)}
                />
                <StatCard
                  icon={<Package className="w-4 h-4" />}
                  label="总会话"
                  value={String(customerInfo.totalSessions || 0)}
                />
              </div>
              <div className="mt-3 space-y-2">
                {customerInfo.recentOrders.slice(0, 3).map((order) => (
                  <RecentOrder
                    key={order.id}
                    orderNo={order.orderNo}
                    status={order.status}
                    amount={`¥${order.totalAmount.toFixed(2)}`}
                    time={formatChatTime(order.createdAt)}
                  />
                ))}
              </div>
            </>
          ) : (
            <div className="text-xs text-gray-400 text-center py-3 bg-gray-50 rounded-lg">
              暂无订单数据
            </div>
          )}
        </div>

        {/* 会话信息 */}
        <div className="px-4 py-3">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
            会话信息
          </h4>
          <div className="space-y-2 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-gray-500">会话 ID</span>
              <span className="text-gray-700 font-mono text-[10px]">{currentSessionId?.slice(0, 12)}...</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-500">状态</span>
              <span className={cn(
                'px-1.5 py-0.5 rounded text-[10px] font-medium',
                currentSession?.status === 'active'
                  ? 'bg-green-50 text-green-700'
                  : 'bg-gray-50 text-gray-600'
              )}>
                {currentSession?.status === 'active' ? '进行中' : '已结束'}
              </span>
            </div>
            <div className="mt-2">
              <span className="text-gray-500 block mb-1">最后消息</span>
              <p className="text-gray-600 text-[11px] line-clamp-2 bg-gray-50 rounded p-2">
                {currentSession?.last_message || '暂无消息'}
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function InfoRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string
}) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-gray-400">{icon}</span>
      <span className="text-gray-500 w-8">{label}</span>
      <span className="text-gray-700">{value}</span>
    </div>
  )
}

function StatCard({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode
  label: string
  value: string
}) {
  return (
    <div className="bg-gray-50 rounded-lg p-2.5 flex items-center gap-2">
      <span className="text-primary-500">{icon}</span>
      <div>
        <p className="text-base font-semibold text-gray-800">{value}</p>
        <p className="text-[10px] text-gray-500">{label}</p>
      </div>
    </div>
  )
}

function RecentOrder({
  orderNo,
  status,
  amount,
  time,
}: {
  orderNo: string
  status: string
  amount: string
  time: string
}) {
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
    <div className="bg-gray-50 rounded-lg p-2.5">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[11px] text-gray-500">{orderNo}</span>
        <span
          className={cn(
            'text-[10px] px-1.5 py-0.5 rounded border font-medium',
            info.className
          )}
        >
          {info.label}
        </span>
      </div>
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-red-500">{amount}</p>
        <span className="text-[10px] text-gray-400">{time}</span>
      </div>
    </div>
  )
}
