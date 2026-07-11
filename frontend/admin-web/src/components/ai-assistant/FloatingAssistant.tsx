'use client'

import { useState, useEffect } from 'react'
import { X, Minus, Bot } from 'lucide-react'
import { MibaoLogo } from '@/components/icons/MibaoLogo'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import SessionList from '@/components/chat/SessionList'
import ChatArea from '@/components/chat/ChatArea'
import SessionInsight from '@/components/chat/SessionInsight'

export default function FloatingAssistant() {
  const [isOpen, setIsOpen] = useState(false)
  const [minimized, setMinimized] = useState(false)
  const { fetchSessions } = useChatStore()

  // 首次打开时加载会话列表
  useEffect(() => {
    if (isOpen) fetchSessions()
  }, [isOpen, fetchSessions])

  const togglePanel = () => {
    if (isOpen) {
      setIsOpen(false)
      setMinimized(false)
    } else {
      setIsOpen(true)
    }
  }

  return (
    <>
      {/* 聊天面板 */}
      {isOpen && (
        <div
          className={cn(
            'fixed inset-4 z-50 flex flex-col',
            'bg-white rounded-2xl shadow-2xl border border-gray-200',
            'transition-all duration-300 ease-in-out',
            minimized
              ? 'bottom-4 left-1/2 -translate-x-1/2 w-72 h-12'
              : 'inset-4',
          )}
        >
          {/* 头部 */}
          {minimized ? (
            <button
              onClick={() => setMinimized(false)}
              className="flex items-center gap-2 h-12 px-4 bg-gradient-to-r from-primary-600 to-primary-500 rounded-2xl w-full hover:from-primary-700 hover:to-primary-600 transition-colors"
            >
              <MibaoLogo size={20} className="flex-shrink-0" />
              <span className="text-sm font-semibold text-white">米宝 · 智能助手</span>
            </button>
          ) : (
            <div className="flex items-center justify-between h-12 px-4 border-b border-gray-100 bg-gradient-to-r from-primary-600 to-primary-500 rounded-t-2xl flex-shrink-0">
              <div className="flex items-center gap-2">
                <MibaoLogo size={22} className="flex-shrink-0" />
                <span className="text-sm font-semibold text-white">米宝 · 智能助手</span>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setMinimized(true)}
                  className="p-1 rounded-md hover:bg-white/20 transition-colors"
                  title="最小化"
                >
                  <Minus className="w-4 h-4 text-white" />
                </button>
                <button
                  onClick={() => setIsOpen(false)}
                  className="p-1 rounded-md hover:bg-white/20 transition-colors"
                  title="关闭"
                >
                  <X className="w-4 h-4 text-white" />
                </button>
              </div>
            </div>
          )}

          {/* 聊天内容 — 复用全屏会话模式布局 */}
          {!minimized && (
            <div className="flex-1 flex rounded-b-2xl overflow-hidden">
              <SessionList />
              <ChatArea />
              <SessionInsight />
            </div>
          )}
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
