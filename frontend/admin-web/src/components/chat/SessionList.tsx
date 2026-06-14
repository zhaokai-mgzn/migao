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

type SessionTab = 'active' | 'closed'

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
  const [activeTab, setActiveTab] = useState<SessionTab>('active')

  // 按 tab 过滤
  const tabFiltered = useMemo(
    () => sessions.filter(s => s.status === activeTab || (activeTab === 'active' && !s.status)),
    [sessions, activeTab]
  )

  const filteredSessions = useMemo(() => {
    if (!searchKeyword.trim()) return tabFiltered
    const kw = searchKeyword.toLowerCase()
    return tabFiltered.filter(s =>
      (s.title || '').toLowerCase().includes(kw) ||
      (s.customer_name || '').toLowerCase().includes(kw) ||
      (s.last_message || '').toLowerCase().includes(kw)
    )
  }, [tabFiltered, searchKeyword])

  const activeCount = useMemo(
    () => sessions.filter(s => s.status === 'active' || !s.status).length,
    [sessions]
  )
  const closedCount = useMemo(
    () => sessions.filter(s => s.status === 'closed').length,
    [sessions]
  )

  const handleCloseSession = useCallback(
    (e: React.MouseEvent, id: string) => {
      e.stopPropagation()
      setContextMenuId(null)
      closeSession(id)
    },
    [closeSession]
  )


  return (
    <div className="w-60 bg-white border-r border-gray-200 flex flex-col h-full flex-shrink-0">
      {/* 新建会话 */}
      <div className="p-3 border-b border-gray-100">
        <button
          onClick={() => createSession()}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-primary-600 text-white rounded-lg hover:bg-primary-700 transition-colors text-sm font-medium"
        >
          <Plus className="w-4 h-4" />
          新建对话
        </button>
      </div>

      {/* 搜索 */}
      <div className="px-3 py-2 border-b border-gray-100">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
          <input
            type="text"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            placeholder="搜索会话..."
            className="w-full h-8 pl-8 pr-8 text-xs bg-gray-50 border border-gray-200 rounded-md focus:outline-none focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20"
          />
          {searchKeyword && (
            <button
              onClick={() => setSearchKeyword('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Tab 切换：活跃 / 已关闭 */}
      <div className="flex border-b border-gray-100">
        <button
          onClick={() => setActiveTab('active')}
          className={cn(
            'flex-1 py-2 text-xs font-medium transition-colors border-b-2',
            activeTab === 'active'
              ? 'text-primary-600 border-primary-600'
              : 'text-gray-400 border-transparent hover:text-gray-600'
          )}
        >
          活跃 ({activeCount})
        </button>
        <button
          onClick={() => setActiveTab('closed')}
          className={cn(
            'flex-1 py-2 text-xs font-medium transition-colors border-b-2',
            activeTab === 'closed'
              ? 'text-primary-600 border-primary-600'
              : 'text-gray-400 border-transparent hover:text-gray-600'
          )}
        >
          已关闭 ({closedCount})
        </button>
      </div>

      {/* 会话列表 */}
      <div className="flex-1 overflow-y-auto">
        {isLoadingSessions ? (
          <div className="flex items-center justify-center py-8">
            <div className="w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : filteredSessions.length === 0 ? (
          <div className="text-center py-8 text-gray-400 text-xs">
            {searchKeyword ? '没有匹配的会话' : activeTab === 'active' ? '暂无活跃会话' : '暂无已关闭会话'}
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
      className={cn(
        'group relative mx-1.5 mb-0.5 px-3 py-2.5 rounded-lg cursor-pointer transition-colors',
        isActive
          ? 'bg-primary-50 border border-primary-200'
          : 'hover:bg-gray-50'
      )}
    >
      <div className="flex items-start gap-2.5">
        {/* 状态指示器 */}
        <div className="mt-1.5 flex-shrink-0">
          <div
            className={cn(
              'w-2 h-2 rounded-full',
              session.status === 'active' ? 'bg-green-500' : 'bg-gray-300'
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
                  ? 'text-gray-400'
                  : isActive
                    ? 'text-primary-700'
                    : 'text-gray-800'
              )}
            >
              {session.title || '新对话'}
            </span>
            <span className="text-[10px] text-gray-400 flex-shrink-0">
              {formatTime(session.updated_at || session.created_at)}
            </span>
          </div>

          {/* 状态标签 + 最后消息预览 */}
          <div className="flex items-center gap-1.5 mt-0.5">
            {session.status === 'closed' && (
              <span className="inline-flex items-center px-1.5 py-px rounded text-[10px] font-medium bg-gray-100 text-gray-500 flex-shrink-0">
                已结束
              </span>
            )}
            <p
              className={cn(
                'text-xs truncate',
                session.status === 'closed' ? 'text-gray-400' : 'text-gray-500'
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
              'hover:bg-gray-200'
            )}
          >
            <MoreHorizontal className="w-3.5 h-3.5 text-gray-400" />
          </button>
        )}
      </div>

      {/* 右键菜单 */}
      {showContextMenu && (
        <div className="absolute right-2 top-full mt-1 z-20 bg-white border border-gray-200 rounded-lg shadow-lg py-1 min-w-[120px]">
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
