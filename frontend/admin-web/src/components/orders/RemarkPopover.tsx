'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'

interface RemarkEntry {
  timestamp: string
  content: string
}

/**
 * 解析备注字符串为条目数组。
 * 格式: [YYYY-MM-DD HH:mm] 内容
 * 多条备注以换行符分隔。
 * 后端按添加时间正序存储（最早在前），前端倒序展示（最新在最上）。
 */
function parseRemarks(remark: string | null | undefined): RemarkEntry[] {
  if (!remark || !remark.trim()) return []
  const lines = remark.split('\n')
  const entries: RemarkEntry[] = []
  for (const line of lines) {
    const trimmed = line.trim()
    if (!trimmed) continue
    const match = trimmed.match(/^\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\]\s*([\s\S]*)$/)
    if (match) {
      entries.push({ timestamp: match[1], content: match[2] })
    } else {
      // 无时间戳前缀的行，整体作为内容
      entries.push({ timestamp: '', content: trimmed })
    }
  }
  // 后端 append 新备注（正序，最早在前），前端倒序以显示最新在最上
  return entries.reverse()
}

export interface RemarkPopoverProps {
  remark: string | null | undefined
  children: React.ReactNode
}

/**
 * RemarkPopover — 备注浮窗组件
 *
 * 鼠标悬停触发器时弹出浮窗，显示订单的全部备注（倒序，最新在上）。
 * 空备注显示"暂无备注"占位。
 *
 * 视觉规范：
 * - min-width 320px, max-width 600px
 * - max-height 400px，超出滚动
 * - 背景 #1F1F1F，白色文字 12px
 * - 圆角 8px，阴影 0 6px 16px rgba(0,0,0,0.12)
 * - 三角箭头指向触发元素
 * - Portal 渲染到 body 避免裁剪
 */
export default function RemarkPopover({ remark, children }: RemarkPopoverProps) {
  const [visible, setVisible] = useState(false)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const triggerRef = useRef<HTMLSpanElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const openTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const entries = parseRemarks(remark)

  const updatePosition = useCallback(() => {
    if (!triggerRef.current || !popoverRef.current) return
    const triggerRect = triggerRef.current.getBoundingClientRect()
    const popoverWidth = popoverRef.current.offsetWidth
    const popoverHeight = popoverRef.current.offsetHeight
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight

    // 默认：浮窗左边缘对齐触发元素左边缘（备注列左边缘），显示在下方
    // 向左展开会遮挡"状态"列，因此向右展开
    let left = triggerRect.left
    let top = triggerRect.bottom + 8

    // 水平边界检测：确保不溢出左右视口
    if (left < 8) left = 8
    if (left + popoverWidth > viewportWidth - 8) {
      left = viewportWidth - popoverWidth - 8
    }

    // 垂直边界检测：如果下方空间不够，显示在上方
    if (top + popoverHeight > viewportHeight - 8) {
      top = triggerRect.top - popoverHeight - 8
    }

    // 确保不溢出顶部
    if (top < 8) top = 8

    setPosition({ top, left })
  }, [])

  const handleMouseEnter = () => {
    if (closeTimerRef.current) {
      clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
    openTimerRef.current = setTimeout(() => {
      setVisible(true)
    }, 200)
  }

  const handleMouseLeave = () => {
    if (openTimerRef.current) {
      clearTimeout(openTimerRef.current)
      openTimerRef.current = null
    }
    closeTimerRef.current = setTimeout(() => {
      setVisible(false)
    }, 200)
  }

  // 浮窗可见时更新位置
  useEffect(() => {
    if (visible) {
      // requestAnimationFrame 确保 DOM 已渲染
      requestAnimationFrame(() => {
        updatePosition()
      })
    }
  }, [visible, updatePosition])

  // 滚动和窗口大小变化时关闭浮窗
  useEffect(() => {
    if (!visible) return
    const handleScroll = () => setVisible(false)
    const handleResize = () => setVisible(false)
    window.addEventListener('scroll', handleScroll, true)
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('scroll', handleScroll, true)
      window.removeEventListener('resize', handleResize)
    }
  }, [visible])

  // 清理计时器
  useEffect(() => {
    return () => {
      if (openTimerRef.current) clearTimeout(openTimerRef.current)
      if (closeTimerRef.current) clearTimeout(closeTimerRef.current)
    }
  }, [])

  const popover = visible ? (
    <div
      ref={popoverRef}
      role="tooltip"
      style={{
        position: 'fixed',
        top: position.top,
        left: position.left,
        zIndex: 9999,
      }}
      className="min-w-[320px] max-w-[600px] max-h-[400px] overflow-y-auto
        bg-[#1F1F1F] text-white text-xs leading-5
        rounded-lg shadow-[0_6px_16px_0_rgba(0,0,0,0.12)]
        pointer-events-auto"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {/* 三角箭头 — 指向备注列触发区域 */}
      <div
        className="absolute w-0 h-0"
        style={{
          top: -6,
          left: 16,
          borderLeft: '6px solid transparent',
          borderRight: '6px solid transparent',
          borderBottom: '6px solid #1F1F1F',
        }}
      />

      <div className="p-3">
        {entries.length === 0 ? (
          <span className="text-gray-400">暂无备注</span>
        ) : (
          <ul className="space-y-2.5">
            {entries.map((entry, index) => (
              <li key={index} className="border-b border-gray-700 last:border-b-0 pb-2 last:pb-0">
                {entry.timestamp && (
                  <div className="text-gray-400 text-[11px] mb-1">
                    {entry.timestamp}
                  </div>
                )}
                <div className="whitespace-pre-wrap break-words text-white">
                  {entry.content}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  ) : null

  return (
    <span
      ref={triggerRef}
      className="inline-block max-w-full cursor-default"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}
      {createPortal(popover, document.body)}
    </span>
  )
}
