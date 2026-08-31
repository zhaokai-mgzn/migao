'use client'

import { useState, useCallback, useMemo } from 'react'
import {
  Plus,
  Search,
  X,
  MoreHorizontal,
  Trash2,
  RotateCcw,
} from 'lucide-react'
import { cn, formatChatTime } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import type { ChatSession } from '@/types'

export default function SessionList() {
  const {
    sessions,
    currentSessionId,
    isLoadingSessions,
    searchKeyword,
    setSearchKeyword,
    createSession,
    selectSession,
    closeSession,
    reopenSession,
  } = useChatStore()

  const [contextMenuId, setContextMenuId] = useState<string | null>(null)

  // 单列表：活跃在前，同组按 updated_at 倒序（状态是元数据，不是导航）
  const sortedSessions = useMemo(
    () =>
      [...sessions].sort((a, b) => {
        const aClosed = a.status === 'closed' ? 1 : 0
        const bClosed = b.status === 'closed' ? 1 : 0
        if (aClosed !== bClosed) return aClosed - bClosed
        const at = new Date(a.updated_at || a.created_at || 0).getTime()
        const bt = new Date(b.updated_at || b.created_at || 0).getTime()
        return bt - at
      }),
    [sessions]
  )

  const filteredSessions = useMemo(() => {
    if (!searchKeyword.trim()) return sortedSessions
    const kw = searchKeyword.toLowerCase()
    return sortedSessions.filter(s =>
      (s.title || '').toLowerCase().includes(kw) ||
      (s.customer_name || '').toLowerCase().includes(kw) ||
      (s.last_message || '').toLowerCase().includes(kw)
    )
  }, [sortedSessions, searchKeyword])

  const handleCloseSession = useCallback(
    (e: React.MouseEvent, id: string) => {
      e.stopPropagation()
      setContextMenuId(null)
      closeSession(id)
    },
    [closeSession]
  )


  return (
    <div className="w-64 bg-white border-r border-neutral-200/80 flex flex-col h-full flex-shrink-0">
      {/* 新建会话 */}
      <div className="p-3 border-b border-neutral-100">
        <button
          onClick={() => createSession()}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-gradient-to-r from-primary-600 to-primary-500 text-white rounded-lg hover:from-primary-700 hover:to-primary-600 transition-all text-sm font-medium shadow-sm"
        >
          <Plus className="w-4 h-4" />
          新建对话
        </button>
      </div>

      {/* 搜索 */}
      <div className="px-3 py-2 border-b border-neutral-100">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-neutral-400" />
          <input
            type="text"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            placeholder="搜索会话..."
            className="w-full h-8 pl-8 pr-8 text-xs bg-neutral-50 border border-neutral-200 rounded-lg focus:outline-none focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20"
          />
          {searchKeyword && (
            <button
              onClick={() => setSearchKeyword('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-neutral-600"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* 会话列表（单列表：无 tab、无筛选控件，状态只靠排序与灰化表达） */}
      <div className="flex-1 overflow-y-auto">
        {isLoadingSessions ? (
          <div className="flex items-center justify-center py-8">
            <div className="w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : filteredSessions.length === 0 ? (
          <div className="text-center py-8 text-neutral-400 text-xs">
            {searchKeyword ? '没有匹配的会话' : '暂无会话'}
          </div>
        ) : (
          <div className="py-1">
            {filteredSessions.map((session) => (
              <SessionItem
                key={session.session_id}
                session={session}
                isActive={currentSessionId === session.session_id}
                showContextMenu={contextMenuId === session.session_id}
                onSelect={() => selectSession(session.session_id)}
                onToggleMenu={(e) => {
                  e.stopPropagation()
                  // 已关闭会话不提供“结束会话”菜单项，点击按钮不起作用
                  if (session.status === 'closed') {
                    setContextMenuId(null)
                    return
                  }
                  setContextMenuId(
                    contextMenuId === session.session_id ? null : session.session_id
                  )
                }}
                onCloseSession={(e) => handleCloseSession(e, session.session_id)}
                onReopenSession={() => reopenSession(session.session_id)}
                formatTime={formatChatTime}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function SessionItem({
  session,
  isActive,
  showContextMenu,
  onSelect,
  onToggleMenu,
  onCloseSession,
  onReopenSession,
  formatTime,
}: {
  session: ChatSession
  isActive: boolean
  showContextMenu: boolean
  onSelect: () => void
  onToggleMenu: (e: React.MouseEvent) => void
  onCloseSession: (e: React.MouseEvent) => void
  onReopenSession: () => void
  formatTime: (d: string) => string
}) {
  return (
    <div
      onClick={onSelect}
      data-testid="session-item"
      className={cn(
        'group relative mx-1 mb-0.5 px-3 py-2 rounded-lg cursor-pointer transition-colors',
        isActive
          ? 'bg-primary-50/80 border border-primary-200/60'
          : 'hover:bg-neutral-50/80'
      )}
    >
      {/* 选中态左侧色条（钉钉风格） */}
      {isActive && (
        <div className="absolute left-0 top-1.5 bottom-1.5 w-0.5 rounded-full bg-primary-500" />
      )}
      <div className="flex items-start gap-2.5">
        {/* 状态指示器 */}
        <div className="mt-1.5 flex-shrink-0">
          <div
            className={cn(
              'w-2 h-2 rounded-full',
              session.status === 'active' ? 'bg-emerald-500' : 'bg-neutral-300'
            )}
          />
        </div>

        <div className="flex-1 min-w-0">
          {/* 标题 + 时间 */}
          <div className="flex items-center justify-between gap-1">
            <span
              className={cn(
                'text-sm font-medium truncate',
                session.status === 'closed'
                  ? 'text-neutral-400'
                  : isActive
                    ? 'text-primary-700'
                    : 'text-neutral-800'
              )}
            >
              {session.title || '新对话'}
            </span>
            <span className="text-[10px] text-neutral-400 flex-shrink-0">
              {formatTime(session.updated_at || session.created_at)}
            </span>
          </div>

          {/* 状态标签 + 最后消息预览 */}
          <div className="flex items-center gap-1.5 mt-0.5">
            {session.status === 'closed' && (
              <span className="inline-flex items-center px-1.5 py-px rounded text-[10px] font-medium bg-neutral-100 text-neutral-500 flex-shrink-0">
                已结束
              </span>
            )}
            <p
              className={cn(
                'text-xs truncate',
                session.status === 'closed' ? 'text-neutral-400' : 'text-neutral-500'
              )}
            >
              {session.last_message || '暂无消息'}
            </p>
          </div>
        </div>

        {/* 操作菜单：已关闭会话显示重新打开，活跃会话显示结束 */}
        {session.status === 'closed' ? (
          <button
            onClick={(e) => {
              e.stopPropagation()
              onReopenSession()
            }}
            className="flex-shrink-0 p-0.5 rounded opacity-0 group-hover:opacity-100 transition-opacity hover:bg-green-100"
            title="重新打开"
          >
            <RotateCcw className="w-3.5 h-3.5 text-green-500" />
          </button>
        ) : (
          <button
            onClick={onToggleMenu}
            className={cn(
              'flex-shrink-0 p-0.5 rounded transition-opacity',
              showContextMenu
                ? 'opacity-100'
                : 'opacity-0 group-hover:opacity-100',
              'hover:bg-neutral-200'
            )}
          >
            <MoreHorizontal className="w-3.5 h-3.5 text-neutral-400" />
          </button>
        )}
      </div>

      {/* 右键菜单 */}
      {showContextMenu && (
        <div className="absolute right-2 top-full mt-1 z-20 bg-white border border-neutral-200 rounded-lg shadow-lg py-1 min-w-[120px]">
          <button
            onClick={onCloseSession}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-red-600 hover:bg-red-50 transition-colors"
          >
            <Trash2 className="w-3.5 h-3.5" />
            结束会话
          </button>
        </div>
      )}
    </div>
  )
}
