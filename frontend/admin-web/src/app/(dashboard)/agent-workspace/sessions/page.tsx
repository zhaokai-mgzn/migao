'use client'

/**
 * 会话管理工作台（客服中心 / 会话管理）
 *
 * 会话管理重构落地页（docs/design/session-management-redesign.md 前端侧）：
 *   - 复用已重构的 SessionService API（chatApi，ai-agent-service /api/chat/*，
 *     底层为 SessionService 生命周期状态机 + SessionStateStore 跨轮状态）
 *   - 顶部监控统计条：活跃 / 已关闭 / 总会话数（从 store.sessions 派生，DSH 监控风格）
 *   - 主体复用 /chat 组件链：SessionList（会话列表）+ ChatArea（聊天区，
 *     内含 SessionInsight 会话洞察抽屉 = 工具卡片 / 状态面板）
 */
import { useEffect } from 'react'
import { MessageSquare, Archive, ListChecks } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import SessionList from '@/components/chat/SessionList'
import ChatArea from '@/components/chat/ChatArea'

/** 监控统计条单格 */
function StatCell({
  icon,
  label,
  value,
  valueClass,
}: {
  icon: React.ReactNode
  label: string
  value: number
  valueClass?: string
}) {
  return (
    <div className="flex items-center gap-2.5 px-4 py-2 rounded-lg bg-neutral-50/80 border border-neutral-100">
      {icon}
      <div className="flex items-baseline gap-1.5">
        <span className={cn('text-lg font-semibold tabular-nums', valueClass ?? 'text-neutral-900')}>
          {value}
        </span>
        <span className="text-xs text-neutral-500">{label}</span>
      </div>
    </div>
  )
}

export default function AgentSessionsPage() {
  const { sessions, fetchSessions } = useChatStore()

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  const activeCount = sessions.filter(s => s.status === 'active').length
  const closedCount = sessions.filter(s => s.status === 'closed').length

  return (
    <div className="h-[calc(100vh-180px)] flex flex-col">
      {/* 顶部：标题 + 监控统计条 */}
      <div className="flex items-center justify-between flex-shrink-0 px-5 h-14 border-b border-neutral-200/80">
        <h1 className="text-base font-semibold text-neutral-900">会话管理</h1>
        <div className="flex items-center gap-2" data-testid="session-stats-bar">
          <StatCell
            icon={<MessageSquare className="w-4 h-4 text-primary-500" />}
            label="活跃"
            value={activeCount}
            valueClass="text-emerald-600"
          />
          <StatCell
            icon={<Archive className="w-4 h-4 text-neutral-400" />}
            label="已关闭"
            value={closedCount}
          />
          <StatCell
            icon={<ListChecks className="w-4 h-4 text-indigo-400" />}
            label="共"
            value={sessions.length}
          />
        </div>
      </div>

      {/* 主体：会话列表 + 聊天区（复用 /chat 组件链，SessionInsight 为 ChatArea 内抽屉） */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        <SessionList />
        <ChatArea />
      </div>
    </div>
  )
}
