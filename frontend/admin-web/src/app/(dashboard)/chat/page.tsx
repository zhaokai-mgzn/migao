'use client'

import { Suspense, useEffect, useRef } from 'react'
import { useSearchParams } from 'next/navigation'
import { useChatStore } from '@/store/chat'
import SessionList from '@/components/chat/SessionList'
import ChatArea from '@/components/chat/ChatArea'
import SessionInsight from '@/components/chat/SessionInsight'
import MibaoChatPanel from '@/components/business/MibaoChatPanel'

/** 监听 URL 中的 session_id 并选中对应会话 */
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

  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  return (
    <MibaoChatPanel>
      <Suspense fallback={null}>
        <SessionFromQuery />
      </Suspense>
      <SessionList />
      <ChatArea />
      <SessionInsight />
    </MibaoChatPanel>
  )
}
