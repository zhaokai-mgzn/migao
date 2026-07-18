'use client'

import { useState, useEffect } from 'react'
import { X, Bot } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import SessionList from '@/components/chat/SessionList'
import ChatArea from '@/components/chat/ChatArea'
import SessionInsight from '@/components/chat/SessionInsight'
import MibaoChatPanel from '@/components/business/MibaoChatPanel'

export default function FloatingAssistant() {
  const [isOpen, setIsOpen] = useState(false)
  const { fetchSessions } = useChatStore()

  // 首次打开时加载会话列表
  useEffect(() => {
    if (isOpen) fetchSessions()
  }, [isOpen, fetchSessions])

  const togglePanel = () => setIsOpen(!isOpen)

  return (
    <>
      {/* 可拖拽调整高度的米宝聊天面板 — 右侧浮动 */}
      {isOpen && (
        <div className="fixed right-4 top-4 bottom-20 z-50 w-[440px] max-w-[calc(100vw-2rem)]">
          <MibaoChatPanel className="h-full bg-white shadow-2xl">
            <div className="flex flex-col h-full min-h-0">
              {/* 头部 */}
              <div className="flex items-center justify-between h-12 px-4 border-b border-gray-100 bg-gradient-to-r from-primary-600 to-primary-500 flex-shrink-0">
                <div className="flex items-center gap-2">
                  <span className="text-lg flex-shrink-0">🤖</span>
                  <span className="text-sm font-semibold text-white">米宝 · 智能助手</span>
                </div>
                <button
                  onClick={() => setIsOpen(false)}
                  className="p-1 rounded-md hover:bg-white/20 transition-colors"
                  title="关闭"
                >
                  <X className="w-4 h-4 text-white" />
                </button>
              </div>

              {/* 聊天内容 — 复用全屏会话模式布局 */}
              <div className="flex-1 flex min-h-0 overflow-hidden">
                <SessionList />
                <ChatArea />
                <SessionInsight />
              </div>
            </div>
          </MibaoChatPanel>
        </div>
      )}

      {/* FAB 悬浮按钮 */}
      <button
        onClick={togglePanel}
        className={cn(
          'fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full',
          'flex items-center justify-center',
          'bg-primary-600 text-white shadow-lg',
          'hover:bg-primary-700 hover:shadow-xl hover:scale-110',
          'active:scale-95',
          'transition-all duration-200 ease-in-out',
        )}
        title={isOpen ? '关闭米宝' : '打开米宝'}
      >
        {isOpen ? (
          <X className="w-6 h-6" />
        ) : (
          <Bot className="w-6 h-6" />
        )}
      </button>
    </>
  )
}
