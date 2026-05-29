'use client'

import { Suspense, useEffect, useRef } from 'react'
import { useSearchParams } from 'next/navigation'
import { useChatStore } from '@/store/chat'
import SessionList from '@/components/chat/SessionList'
import ChatArea from '@/components/chat/ChatArea'
import CustomerPanel from '@/components/chat/CustomerPanel'

/** 监听 URL 中的 session_id 并选中对应会话；独立子组件以满足 Suspense 边界 */
function SessionFromQuery() {
  const { selectSession } = useChatStore()
  const searchParams = useSearchParams()
  const targetSessionId = searchParams?.get('session_id') || null
  const handledSessionRef = useRef<string | null>(null)

  useEffect(() => {
    if (!targetSessionId) return
    if (handledSessionRef.current === targetSessionId) return
    handledSessionRef.current = targetSessionId
    selectSession(targetSessionId)
  }, [targetSessionId, selectSession])

  return null
}

export default function ChatPage() {
  const { fetchSessions } = useChatStore()

  // 初始加载会话列表
  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  return (
    <div className="h-[calc(100vh-120px)] flex rounded-lg overflow-hidden">
      <Suspense fallback={null}>
        <SessionFromQuery />
      </Suspense>

      {/* 左侧：会话列表 (240px) */}
      <SessionList />

      {/* 中间：聊天区域 (弹性宽度) */}
      <ChatArea />

      {/* 右侧：客户信息面板 (280px, 可收起) */}
      <CustomerPanel />
    </div>
  )
}
