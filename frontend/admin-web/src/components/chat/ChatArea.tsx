'use client'

import { useState } from 'react'
import { PanelRightOpen } from 'lucide-react'
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
    <div className="flex-shrink-0 h-14 flex items-center justify-between px-5 bg-white border-b border-gray-100">
      <div className="flex items-center gap-2.5 min-w-0">
        <h2 className="text-sm font-semibold text-gray-800 truncate">
          {session?.title || '新对话'}
        </h2>
        {session?.status === 'closed' ? (
          <span className="inline-flex items-center px-1.5 py-px rounded text-[10px] font-medium bg-gray-100 text-gray-500 flex-shrink-0">
            已结束
          </span>
        ) : (
          <span className="inline-flex items-center px-1.5 py-px rounded text-[10px] font-medium bg-green-50 text-green-600 flex-shrink-0">
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
              : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
          )}
          data-testid="insight-toggle-btn"
          title={insightOpen ? '收起洞察' : '打开会话洞察'}
        >
          <PanelRightOpen className="w-3.5 h-3.5" />
          洞察
        </button>
      </div>
    </div>
  )
}

export default function ChatArea() {
  const [isInsightOpen, setIsInsightOpen] = useState(false)

  return (
    <div className="relative flex-1 flex flex-col min-w-0 bg-gray-50">
      <ChatHeader
        insightOpen={isInsightOpen}
        onInsightToggle={() => setIsInsightOpen(prev => !prev)}
      />
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
