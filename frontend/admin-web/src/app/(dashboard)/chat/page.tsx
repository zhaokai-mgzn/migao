'use client'

import { Suspense, useEffect, useRef } from 'react'
import { useSearchParams } from 'next/navigation'
import { useChatStore } from '@/store/chat'
import { useAuthStore } from '@/store/auth'
import SessionList from '@/components/chat/SessionList'
import ChatArea from '@/components/chat/ChatArea'
import MibaoChatPanel from '@/components/business/MibaoChatPanel'
import MibaoAccessGate from '@/components/business/MibaoAccessGate'

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
  // 米宝唤出能力位（issue #5642 功能⑤）：**只**取服务端 `/api/auth/me` 下发的
  // `capabilities.mibaoChat` —— 前端不判任何权限码（单一真值在服务端 `AdminGate`，
  // 改一处即小程序端与 admin-web 两端同步）。
  const mibaoAllowed = useAuthStore((s) => s.user?.capabilities?.mibaoChat)

  useEffect(() => {
    // 未授权时不拉会话列表：避免「页面看起来正常、一发消息什么都没有」的静默形态
    if (mibaoAllowed === true) {
      fetchSessions()
    }
  }, [fetchSessions, mibaoAllowed])

  return (
    <MibaoAccessGate allowed={mibaoAllowed}>
      <MibaoChatPanel>
        <Suspense fallback={null}>
          <SessionFromQuery />
        </Suspense>
        {/* 左中两栏布局 — 会话简报默认在右侧展开（docked 常驻列，可向右缩回） */}
        <SessionList />
        <ChatArea insightDefaultOpen insightVariant="docked" />
      </MibaoChatPanel>
    </MibaoAccessGate>
  )
}
