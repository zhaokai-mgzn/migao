'use client'

/**
 * 会话管理工作台（客服中心 / 会话管理）
 *
 * 会话管理重构落地页（docs/design/session-management-redesign.md 前端侧）：
 *   - 复用已重构的 SessionService API（chatApi，ai-agent-service /api/chat/*，
 *     底层为 SessionService 生命周期状态机 + SessionStateStore 跨轮状态）
 *   - 顶部监控统计条：活跃 / 已结束 / 总会话数（从 store.sessions 派生，DSH 监控风格）
 *   - 主体复用 /chat 组件链：SessionList（会话列表）+ ChatArea（聊天区，
 *     内含 SessionInsight 会话洞察抽屉 = 工具卡片 / 状态面板）
 *
 * 🔴 issue #6721（「读面失败不得印派生零值」第三处承载体）：
 *   统计条是**从 `store.sessions` 派生**的读数，而 `sessions` 的初值是 `[]` ——
 *   读失败时**没有任何东西**告诉它这个空数组不可信 ⇒ 三格照旧印 `0`，屏上逐字「0活跃0已结束0共」。
 *   ⇒ 与 #6691（读面故障不得画成空态）/ #6703（读失败不得印派生零值）同族：**读不到被画成"就是 0"**。
 *   改后：失败 ⇒ 派生值一律印 `—`（**不印 0**，也不整格不渲染：保留格子才看得出"少了一个读数"），
 *   统计条整体 `role="alert"`（不印 ≠ 不告知），并在顶上给**常驻**失败面 + 真重发的重试出口。
 *   真为 0（读成功、确实没有会话）⇒ 照旧印 `0`（真值 0 不是不可信读数）。
 */
import { useEffect, useState } from 'react'
import { AlertTriangle, MessageSquare, Archive, ListChecks } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import SessionList from '@/components/chat/SessionList'
import ChatArea from '@/components/chat/ChatArea'

/**
 * 读面失败的**常驻**出口（issue #6721）。
 *
 * 🔴 **为什么内联而不是复用 `components/common/ListLoadError.tsx`**：本判据的类级扫描器
 * （`frontend/admin-web/scripts/count-row-derived-scan.mjs`）读的是**字面量** `data-testid`
 * —— 共享件把 `testId` 当 prop 传（`data-testid={testId}` / `${testId}-retry`），
 * 机械判据**看不见**它 ⇒ 用共享件会让这页在「正向核」里判红（实测读数）。
 * 这与 #6718 的取舍**同源**（那一批最终也全部内联失败面，理由逐字相同）。
 */
function SessionsLoadError({ retryFailed, onRetry }: { retryFailed: boolean; onRetry: () => void }) {
  return (
    <div
      data-testid="agent-sessions-load-failed"
      role="alert"
      className="flex items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700"
    >
      <AlertTriangle className="w-4 h-4 flex-shrink-0" />
      <span className="flex-1">
        {retryFailed
          ? '会话列表重试仍未成功 —— 顶部统计与左侧列表当前都不可信'
          : '会话列表读取失败 —— 顶部统计与左侧列表当前都不可信'}
      </span>
      <button
        type="button"
        data-testid="agent-sessions-load-failed-retry"
        onClick={onRetry}
        className="flex-shrink-0 rounded border border-red-300 px-2 py-1 text-xs font-medium text-red-700 hover:bg-red-100"
      >
        重新加载
      </button>
    </div>
  )
}

/** 监控统计条单格 —— `value` 为 `null` ⇒ 印「不可信」占位（读面失败，不是 0） */
function StatCell({
  icon,
  label,
  value,
  valueClass,
}: {
  icon: React.ReactNode
  label: string
  value: number | null
  valueClass?: string
}) {
  return (
    <div className="flex items-center gap-2.5 px-4 py-2 rounded-lg bg-neutral-50/80 border border-neutral-100">
      {icon}
      <div className="flex items-baseline gap-1.5">
        <span className={cn('text-lg font-semibold tabular-nums', valueClass ?? 'text-neutral-900')}>
          {value === null ? '—' : value}
        </span>
        <span className="text-xs text-neutral-500">{label}</span>
      </div>
    </div>
  )
}

export default function AgentSessionsPage() {
  const { sessions, sessionsLoadFailed, fetchSessions } = useChatStore()
  const [failed, setFailed] = useState(false)
  /** 重试是否走完（用来给「重试仍失败」一个可读的说法；成功路径由 `sessionsLoadFailed` 落回 false 接管） */
  const [retryFailed, setRetryFailed] = useState(false)

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  useEffect(() => {
    // 重试失败（点了重试、store 仍标失败）⇒ 把说法从「未能读取」换成「重试仍未成功」，
    // 否则用户点了按钮看不到任何变化（§31 P4：只陈述事实 + 该做什么）。
    setRetryFailed(failed && sessionsLoadFailed)
    setFailed(sessionsLoadFailed)
  }, [sessionsLoadFailed, failed])

  const retry = async () => {
    setRetryFailed(false)
    await fetchSessions()
  }

  // 统计条的三格**全部**派生自同一次读 ⇒ 失败时**整体**不可信（三格一起印「—」）
  const untrusted = failed || sessionsLoadFailed
  const activeCount = untrusted ? null : sessions.filter(s => s.status === 'active').length
  const closedCount = untrusted ? null : sessions.filter(s => s.status === 'closed').length
  const totalCount = untrusted ? null : sessions.length

  return (
    <div className="h-[calc(100vh-180px)] flex flex-col">
      {/* 读面失败：**常驻**失败面 + 真重发的重试出口（不占主体高度，§31 P1 常驻面克制） */}
      {untrusted && (
        <div className="flex-shrink-0 px-5 pt-3">
          <SessionsLoadError retryFailed={retryFailed} onRetry={retry} />
        </div>
      )}

      {/* 顶部：标题 + 监控统计条 */}
      <div className="flex items-center justify-between flex-shrink-0 px-5 h-14 border-b border-neutral-200/80">
        <h1 className="text-base font-semibold text-neutral-900">会话监控</h1>
        {/* 失败时整条带 `role="alert"`：不印数字 ≠ 不告知（读屏器要读到一个异常读数） */}
        <div
          className="flex items-center gap-2"
          data-testid="session-stats-bar"
          role={untrusted ? 'alert' : undefined}
        >
          <StatCell
            icon={<MessageSquare className="w-4 h-4 text-primary-500" />}
            label="活跃"
            value={activeCount}
            valueClass="text-emerald-600"
          />
          <StatCell
            icon={<Archive className="w-4 h-4 text-neutral-400" />}
            label="已结束"
            value={closedCount}
          />
          <StatCell
            icon={<ListChecks className="w-4 h-4 text-indigo-400" />}
            label="共"
            value={totalCount}
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
