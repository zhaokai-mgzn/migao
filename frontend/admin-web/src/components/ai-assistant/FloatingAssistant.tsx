'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { X, Bot, Maximize2, Minimize2, Minus, Expand } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import SessionList from '@/components/chat/SessionList'
import ChatArea from '@/components/chat/ChatArea'
import MibaoChatPanel from '@/components/business/MibaoChatPanel'

// 最小化浮窗尺寸
const MINIMIZED_WIDTH = 360
const MINIMIZED_HEIGHT = 480
const STORAGE_KEY_MINIMIZED_POS = 'mibao_minimized_pos'

/** 读取 localStorage 中的浮窗位置 */
function readStoredPos(): { x: number; y: number } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_MINIMIZED_POS)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (typeof parsed.x === 'number' && typeof parsed.y === 'number') {
      return parsed
    }
    return null
  } catch {
    return null
  }
}

export default function FloatingAssistant() {
  const [isOpen, setIsOpen] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [isMinimized, setIsMinimized] = useState(false)
  const { fetchSessions } = useChatStore()

  // 最小化浮窗位置
  const [floatPos, setFloatPos] = useState<{ x: number; y: number }>(() => {
    if (typeof window === 'undefined') return { x: 16, y: 16 }
    return readStoredPos() || {
      x: window.innerWidth - MINIMIZED_WIDTH - 16,
      y: window.innerHeight - MINIMIZED_HEIGHT - 80,
    }
  })
  const [isDraggingFloat, setIsDraggingFloat] = useState(false)
  const dragOffset = useRef<{ x: number; y: number }>({ x: 0, y: 0 })

  // 首次打开时加载会话列表
  useEffect(() => {
    if (isOpen) fetchSessions()
  }, [isOpen, fetchSessions])

  // 最小化浮窗拖拽
  const handleFloatMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsDraggingFloat(true)
    dragOffset.current = {
      x: e.clientX - floatPos.x,
      y: e.clientY - floatPos.y,
    }
  }, [floatPos])

  useEffect(() => {
    if (!isDraggingFloat) return

    const handleMouseMove = (e: MouseEvent) => {
      const newX = Math.max(0, Math.min(window.innerWidth - MINIMIZED_WIDTH, e.clientX - dragOffset.current.x))
      const newY = Math.max(0, Math.min(window.innerHeight - MINIMIZED_HEIGHT, e.clientY - dragOffset.current.y))
      setFloatPos({ x: newX, y: newY })
    }

    const handleMouseUp = () => {
      setIsDraggingFloat(false)
      // 持久化位置
      try {
        setFloatPos(pos => {
          localStorage.setItem(STORAGE_KEY_MINIMIZED_POS, JSON.stringify(pos))
          return pos
        })
      } catch { /* ignore */ }
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isDraggingFloat])

  const togglePanel = () => {
    if (isMinimized) {
      // 从最小化恢复
      setIsMinimized(false)
    } else {
      setIsOpen(!isOpen)
      setIsFullscreen(false)
      setIsMinimized(false)
    }
  }

  const handleClose = () => {
    setIsOpen(false)
    setIsFullscreen(false)
    setIsMinimized(false)
  }

  const handleFullscreenToggle = () => {
    setIsFullscreen(!isFullscreen)
    // 全屏时自动取消最小化
    if (isMinimized) setIsMinimized(false)
  }

  const handleMinimize = () => {
    setIsMinimized(true)
    setIsFullscreen(false)
  }

  const handleRestoreFromMinimized = () => {
    setIsMinimized(false)
  }

  return (
    <>
      {/* ===== 正常/全屏 面板 ===== */}
      {isOpen && !isMinimized && (
        <>
          {/* 遮罩 — 居中模态时显示，点击关闭（z-50 覆盖侧边栏，模态完整） */}
          {!isFullscreen && (
            <div
              className="fixed inset-0 z-50 bg-black/40"
              onClick={handleClose}
              data-testid="float-assistant-overlay"
            />
          )}

          {/* 居中大窗 / 全屏容器 */}
          <div className={cn(
            'fixed z-[60]',
            isFullscreen ? 'inset-0' : 'inset-0 flex items-center justify-center pointer-events-none'
          )}>
            <div className={cn(isFullscreen ? 'h-full w-full' : 'pointer-events-auto')}>
              <MibaoChatPanel
                defaultHeight={isFullscreen ? '100vh' : 'min(720px, calc(100vh - 3rem))'}
                defaultWidth={isFullscreen ? '100%' : 'min(920px, calc(100vw - 3rem))'}
                showTopHandle={!isFullscreen}
                className={cn(
                  'bg-white shadow-2xl rounded-2xl border border-gray-200',
                  isFullscreen && 'rounded-none border-0'
                )}
              >
                <div className="flex flex-col flex-1 min-h-0">
              {/* 头部 */}
              <div
                className={cn(
                  'flex items-center justify-between h-12 px-4 bg-gradient-to-r from-primary-600 to-primary-500 flex-shrink-0',
                  isFullscreen ? '' : 'rounded-t-2xl'
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="text-lg flex-shrink-0">🤖</span>
                  <span className="text-sm font-semibold text-white">米宝 · 智能助手</span>
                </div>
                <div className="flex items-center gap-1">
                  {/* 全屏/退出全屏 */}
                  <button
                    onClick={handleFullscreenToggle}
                    className="p-1.5 rounded-md hover:bg-white/20 transition-colors"
                    title={isFullscreen ? '退出全屏' : '全屏'}
                  >
                    {isFullscreen ? (
                      <Minimize2 className="w-4 h-4 text-white" />
                    ) : (
                      <Maximize2 className="w-4 h-4 text-white" />
                    )}
                  </button>
                  {/* 收起（最小化） */}
                  <button
                    onClick={handleMinimize}
                    className="p-1.5 rounded-md hover:bg-white/20 transition-colors"
                    title="收起"
                  >
                    <Minus className="w-4 h-4 text-white" />
                  </button>
                  {/* 关闭 */}
                  <button
                    onClick={handleClose}
                    className="p-1.5 rounded-md hover:bg-white/20 transition-colors"
                    title="关闭"
                  >
                    <X className="w-4 h-4 text-white" />
                  </button>
                </div>
              </div>

              {/* 聊天内容 — 居中大窗两栏（会话列表 + 聊天区） */}
              <div className="flex-1 flex min-h-0 overflow-hidden rounded-b-2xl">
                <SessionList />
                <ChatArea />
              </div>
            </div>
          </MibaoChatPanel>
            </div>
          </div>
        </>
      )}

      {/* ===== 最小化浮窗 ===== */}
      {isOpen && isMinimized && (
        <div
          className="fixed z-50 bg-white shadow-2xl rounded-xl border border-gray-200 overflow-hidden flex flex-col"
          style={{
            left: floatPos.x,
            top: floatPos.y,
            width: MINIMIZED_WIDTH,
            height: MINIMIZED_HEIGHT,
          }}
        >
          {/* 浮窗头部（可拖拽） */}
          <div
            className="flex items-center justify-between h-10 px-3 bg-gradient-to-r from-primary-600 to-primary-500 flex-shrink-0 cursor-move select-none"
            onMouseDown={handleFloatMouseDown}
          >
            <div className="flex items-center gap-1.5">
              <span className="text-sm">🤖</span>
              <span className="text-xs font-semibold text-white">米宝</span>
            </div>
            <div className="flex items-center gap-1">
              {/* 恢复 */}
              <button
                onClick={handleRestoreFromMinimized}
                className="p-1 rounded hover:bg-white/20 transition-colors"
                title="展开"
              >
                <Expand className="w-3.5 h-3.5 text-white" />
              </button>
              {/* 关闭 */}
              <button
                onClick={handleClose}
                className="p-1 rounded hover:bg-white/20 transition-colors"
                title="关闭"
              >
                <X className="w-3.5 h-3.5 text-white" />
              </button>
            </div>
          </div>

          {/* 浮窗聊天内容 */}
          <div className="flex-1 flex min-h-0 overflow-hidden">
            <ChatArea />
          </div>
        </div>
      )}

      {/* ===== FAB 悬浮按钮 — 面板关闭时显示 ===== */}
      {!isOpen && (
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
          title="打开米宝"
        >
          <Bot className="w-6 h-6" />
        </button>
      )}
    </>
  )
}
