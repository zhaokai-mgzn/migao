'use client'

import { useEffect } from 'react'
import { useChatStore } from '@/store/chat'
import SessionList from '@/components/chat/SessionList'
import ChatArea from '@/components/chat/ChatArea'
import CustomerPanel from '@/components/chat/CustomerPanel'

export default function ChatPage() {
  const { fetchSessions } = useChatStore()

  // 初始加载会话列表
  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  return (
    <div className="h-[calc(100vh-120px)] flex rounded-lg overflow-hidden">
      {/* 左侧：会话列表 (240px) */}
      <SessionList />

      {/* 中间：聊天区域 (弹性宽度) */}
      <ChatArea />

      {/* 右侧：客户信息面板 (280px, 可收起) */}
      <CustomerPanel />
    </div>
  )
}
