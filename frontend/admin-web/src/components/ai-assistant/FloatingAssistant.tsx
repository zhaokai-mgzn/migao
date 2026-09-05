'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { X, Bot, Maximize2, Minimize2, Minus, Expand, GripHorizontal, MoveDiagonal } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import SessionList from '@/components/chat/SessionList'
import ChatArea from '@/components/chat/ChatArea'
import MibaoChatPanel from '@/components/business/MibaoChatPanel'

// 最小化浮窗尺寸（UI-021）— 参照主流 AI 助手/客服聊天浮窗（Intercom/Zendesk/Crisp 等）竖版比例：
// 宽默认 400；高按视口自适应（默认 ≥600、上限 760），且可通过底部/右下角把手继续调整到贴满视口
const MINIMIZED_DEFAULT_WIDTH = 400
const MINIMIZED_MIN_WIDTH = 320
const MINIMIZED_MIN_HEIGHT = 360
const STORAGE_KEY_MINIMIZED_POS = 'mibao_minimized_pos'
const STORAGE_KEY_MINIMIZED_SIZE = 'mibao_minimized_size'

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

/** 读取 localStorage 中的浮窗尺寸 */
function readStoredSize(): { w: number; h: number } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_MINIMIZED_SIZE)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (typeof parsed.w === 'number' && typeof parsed.h === 'number'
      && parsed.w >= MINIMIZED_MIN_WIDTH && parsed.h >= MINIMIZED_MIN_HEIGHT) {
      return parsed
    }
    return null
  } catch {
    return null
  }
}

/** 默认尺寸：宽 400；高度按视口自适应（不低于 600、上限 760，小屏不超过视口） */
function defaultMinimizedSize(): { w: number; h: number } {
  const h = Math.min(760, Math.max(600, Math.round(window.innerHeight * 0.8)))
  return { w: MINIMIZED_DEFAULT_WIDTH, h }
}

/** 尺寸钳制到视口内（小屏不留白） */
function clampSizeToViewport(size: { w: number; h: number }): { w: number; h: number } {
  return {
    w: Math.min(Math.max(MINIMIZED_MIN_WIDTH, size.w), Math.max(MINIMIZED_MIN_WIDTH, window.innerWidth)),
    h: Math.min(Math.max(MINIMIZED_MIN_HEIGHT, size.h), Math.max(MINIMIZED_MIN_HEIGHT, window.innerHeight)),
  }
}

/** 位置钳制到视口内（0 ≤ x ≤ iw - w，0 ≤ y ≤ ih - h，贴边不留白） */
function clampPos(pos: { x: number; y: number }, size: { w: number; h: number }): { x: number; y: number } {
  const maxX = Math.max(0, window.innerWidth - size.w)
  const maxY = Math.max(0, window.innerHeight - size.h)
  return {
    x: Math.min(Math.max(0, pos.x), maxX),
    y: Math.min(Math.max(0, pos.y), maxY),
  }
}

export default function FloatingAssistant() {
  const [isOpen, setIsOpen] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [isMinimized, setIsMinimized] = useState(false)
  const { fetchSessions } = useChatStore()

  // 最小化浮窗尺寸（含存储恢复 + 视口钳制）
  const [floatSize, setFloatSize] = useState<{ w: number; h: number }>(() => {
    if (typeof window === 'undefined') return { w: MINIMIZED_DEFAULT_WIDTH, h: MINIMIZED_MIN_HEIGHT }
    return clampSizeToViewport(readStoredSize() || defaultMinimizedSize())
  })

  // 最小化浮窗位置（含存储恢复 + 越界回钳）
  const [floatPos, setFloatPos] = useState<{ x: number; y: number }>(() => {
    if (typeof window === 'undefined') return { x: 16, y: 16 }
    const size = clampSizeToViewport(readStoredSize() || defaultMinimizedSize())
    const stored = readStoredPos()
    if (stored) return clampPos(stored, size)
    return {
      x: Math.max(0, window.innerWidth - size.w - 16),
      y: Math.max(0, window.innerHeight - size.h - 80),
    }
  })
  const [isDraggingFloat, setIsDraggingFloat] = useState(false)
  const dragOffset = useRef<{ x: number; y: number }>({ x: 0, y: 0 })

  // 浮窗缩放（底部调高 / 右下角斜向缩放）
  const [isResizingFloat, setIsResizingFloat] = useState(false)
  const resizeStartRef = useRef<{
    startX: number
    startY: number
    startW: number
    startH: number
    mode: 'bottom' | 'corner'
  } | null>(null)

  // 首次打开时加载会话列表
  useEffect(() => {
    if (isOpen) fetchSessions()
  }, [isOpen, fetchSessions])

  // 最小化浮窗拖拽（移动）
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
      const newX = Math.max(0, Math.min(window.innerWidth - floatSize.w, e.clientX - dragOffset.current.x))
      const newY = Math.max(0, Math.min(window.innerHeight - floatSize.h, e.clientY - dragOffset.current.y))
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
  }, [isDraggingFloat, floatSize.w, floatSize.h])

  // 最小化浮窗缩放（底部调高 / 右下角斜向缩放）
  const handleFloatResizeMouseDown = useCallback((e: React.MouseEvent, mode: 'bottom' | 'corner') => {
    e.preventDefault()
    e.stopPropagation()
    resizeStartRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      startW: floatSize.w,
      startH: floatSize.h,
      mode,
    }
    document.body.style.userSelect = 'none'
    document.body.style.cursor = mode === 'corner' ? 'nwse-resize' : 'ns-resize'
    setIsResizingFloat(true)
  }, [floatSize.w, floatSize.h])

  useEffect(() => {
    if (!isResizingFloat) return

    const handleMouseMove = (e: MouseEvent) => {
      const start = resizeStartRef.current
      if (!start) return
      const dx = e.clientX - start.startX
      const dy = e.clientY - start.startY
      const w = start.mode === 'corner'
        ? Math.min(Math.max(MINIMIZED_MIN_WIDTH, start.startW + dx), window.innerWidth)
        : start.startW
      const h = Math.min(Math.max(MINIMIZED_MIN_HEIGHT, start.startH + dy), window.innerHeight)
      setFloatSize({ w, h })
      // 尺寸变化后重新钳制位置，避免浮窗越出视口（贴边不留白）
      setFloatPos(prev => clampPos(prev, { w, h }))
    }

    const handleMouseUp = () => {
      setIsResizingFloat(false)
      resizeStartRef.current = null
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      // 持久化尺寸
      try {
        setFloatSize(size => {
          localStorage.setItem(STORAGE_KEY_MINIMIZED_SIZE, JSON.stringify(size))
          return size
        })
      } catch { /* ignore */ }
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [isResizingFloat])

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
                  'bg-white shadow-float rounded-2xl border border-neutral-200/80',
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
          data-testid="float-minimized-window"
          className="fixed z-50 bg-white shadow-float rounded-xl border border-neutral-200/80 overflow-hidden flex flex-col"
          style={{
            left: floatPos.x,
            top: floatPos.y,
            width: floatSize.w,
            height: floatSize.h,
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

          {/* 底部高度调节把手（拖上下调整高度），默认透明、hover 时轻提示 */}
          <div
            data-testid="float-minimized-resize-bottom"
            className="absolute bottom-0 left-0 right-0 h-3 flex items-center justify-center bg-transparent hover:bg-neutral-100/70 transition-colors select-none group"
            style={{ cursor: 'ns-resize' }}
            onMouseDown={(e) => handleFloatResizeMouseDown(e, 'bottom')}
            title="拖拽调整高度"
          >
            <GripHorizontal className="w-5 h-3 text-neutral-400 opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>

          {/* 右下角斜向缩放把手（同时调整宽高） */}
          <div
            data-testid="float-minimized-resize-corner"
            className="absolute bottom-0 right-0 w-4 h-4 flex items-center justify-center bg-transparent hover:bg-neutral-100/70 transition-colors select-none group z-10"
            style={{ cursor: 'nwse-resize' }}
            onMouseDown={(e) => handleFloatResizeMouseDown(e, 'corner')}
            title="拖拽调整大小（斜向缩放）"
            aria-label="拖拽调整大小（斜向缩放）"
          >
            <MoveDiagonal className="w-3.5 h-3.5 text-neutral-400 opacity-0 group-hover:opacity-100 transition-opacity" />
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
            'bg-gradient-to-br from-primary-600 to-primary-500 text-white shadow-float',
            'hover:from-primary-700 hover:to-primary-600 hover:shadow-float hover:scale-110',
            'active:scale-95',
            'transition-all duration-200 ease-in-out',
          )}
          title="打开米宝"
        >
          {/* 呼吸光环 */}
          <span className="absolute inset-0 rounded-full bg-primary-500/40 animate-ping" style={{ animationDuration: '2.4s' }} />
          <Bot className="relative w-6 h-6" />
        </button>
      )}
    </>
  )
}