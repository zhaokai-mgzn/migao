'use client'

import { useState } from 'react'
import { PanelRightOpen, RotateCcw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import MessageList from './MessageList'
import MessageInput from './MessageInput'
import QuickActions from './QuickActions'
import SessionInsight from './SessionInsight'

/** 会话头部栏（钉钉风格）— 会话标题 + 状态 + 洞察按钮 */
function ChatHeader({
  insightOpen,
  onInsightToggle,
}: {
  insightOpen: boolean
  onInsightToggle: () => void
}) {
  const { currentSessionId, sessions } = useChatStore()
  const session = sessions.find(s => s.session_id === currentSessionId)

  if (!currentSessionId) return null

  return (
    <div className="flex-shrink-0 h-14 bg-white/90 border-b border-neutral-200/80 backdrop-blur-sm">
      <div className="h-full w-full max-w-3xl mx-auto px-5 flex items-center justify-between">
        <div className="flex items-center gap-2.5 min-w-0">
          {/* 会话状态呼吸点 */}
          <span className={cn(
            'h-2 w-2 rounded-full flex-shrink-0',
            session?.status === 'closed' ? 'bg-neutral-300' : 'bg-emerald-500 animate-breathe'
          )} />
          <h2 className="text-sm font-semibold text-neutral-800 truncate">
            {session?.title || '新对话'}
          </h2>
          {session?.status === 'closed' ? (
            <span className="inline-flex items-center px-1.5 py-px rounded text-[10px] font-medium bg-neutral-100 text-neutral-500 flex-shrink-0">
              已结束
            </span>
          ) : (
            <span className="inline-flex items-center px-1.5 py-px rounded text-[10px] font-medium bg-emerald-50 text-emerald-600 flex-shrink-0">
              进行中
            </span>
          )}
        </div>

        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={onInsightToggle}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
              insightOpen
                ? 'bg-primary-50 text-primary-600'
                : 'text-neutral-500 hover:text-neutral-700 hover:bg-neutral-100'
            )}
            data-testid="insight-toggle-btn"
            title={insightOpen ? '收起洞察' : '打开会话洞察'}
          >
            <PanelRightOpen className="w-3.5 h-3.5" />
            洞察
          </button>
        </div>
      </div>
    </div>
  )
}

/** 已结束会话续聊 banner — 查看已结束会话时提示，可一键重新打开并聚焦输入框 */
function ClosedSessionBanner() {
  const { currentSessionId, sessions, reopenSession } = useChatStore()
  const session = sessions.find(s => s.session_id === currentSessionId)

  if (!currentSessionId || session?.status !== 'closed') return null

  const handleReopen = async () => {
    if (!currentSessionId) return
    await reopenSession(currentSessionId)
    // reopen 成功后聚焦输入框（MessageInput 的 textarea 带固定 id）
    setTimeout(() => {
      document.getElementById('chat-message-input')?.focus()
    }, 0)
  }

  return (
    <div
      className="flex items-center justify-between gap-3 px-5 py-2 bg-amber-50/90 border-b border-amber-200/70"
      data-testid="closed-session-banner"
    >
      <span className="text-xs text-amber-700">会话已结束，历史消息已保留</span>
      <button
        onClick={handleReopen}
        className="flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-medium text-amber-700 bg-amber-100 hover:bg-amber-200 transition-colors"
      >
        <RotateCcw className="w-3 h-3" />
        继续此会话
      </button>
    </div>
  )
}

export default function ChatArea() {
  const [isInsightOpen, setIsInsightOpen] = useState(false)

  return (
    <div className="relative flex-1 flex flex-col min-w-0 bg-neutral-50/70">
      <ChatHeader
        insightOpen={isInsightOpen}
        onInsightToggle={() => setIsInsightOpen(prev => !prev)}
      />
      <ClosedSessionBanner />
      <MessageList />
      <QuickActions />
      <MessageInput />
      {/* 洞察抽屉 — 从右侧滑入覆盖在聊天区上方 */}
      <SessionInsight
        isOpen={isInsightOpen}
        onClose={() => setIsInsightOpen(false)}
      />
    </div>
  )
}
