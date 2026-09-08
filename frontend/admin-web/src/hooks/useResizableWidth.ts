'use client'

import { useState, useCallback, useEffect, useRef } from 'react'

interface UseResizableWidthOptions {
  storageKey: string
  defaultWidth: string
  minWidth: number
  maxWidth?: number
}

interface UseResizableWidthReturn {
  containerStyle: { width: string }
  handleProps: {
    onMouseDown: (e: React.MouseEvent) => void
    role: 'separator'
    tabIndex: 0
    'aria-label': string
    'aria-orientation': 'vertical'
  }
  isDragging: boolean
  resetWidth: () => void
  /** 程序化设置宽度（夹在 [minWidth, maxWidth] 内）——右下角斜向缩放共用 */
  setWidth: (width: number) => void
}

function readStoredWidth(key: string): number | null {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return null
    const parsed = parseInt(raw, 10)
    if (isNaN(parsed) || parsed <= 0) return null
    return parsed
  } catch {
    return null
  }
}

function persistWidth(key: string, width: number): void {
  try {
    localStorage.setItem(key, String(width))
  } catch {
    /* silent */
  }
}

export function useResizableWidth({
  storageKey,
  defaultWidth,
  minWidth,
  maxWidth: maxWidthProp,
}: UseResizableWidthOptions): UseResizableWidthReturn {
  const [storedWidth, setStoredWidth] = useState<number | null>(
    () => readStoredWidth(storageKey)
  )
  const [isDragging, setIsDragging] = useState(false)

  // 视口宽度（加载 + resize 时刷新）：持久化的 px 宽度若大于当前视口（换窗口/浏览器
  // 缩放/FAB 与 /chat 工作台共用 storageKey 互相污染），面板会超出视口、右侧「会话简报」
  // 被推出屏幕 → 样式错乱。加载/缩放时实时钳制到视口内（不覆盖持久化原文，仅渲染层钳制）。
  const [viewportWidth, setViewportWidth] = useState<number | null>(() =>
    typeof window !== 'undefined' ? window.innerWidth : null
  )

  useEffect(() => {
    const onResize = () => setViewportWidth(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const dragRef = useRef<{
    startX: number
    startWidth: number
    maxWidth: number
  } | null>(null)

  useEffect(() => {
    if (isDragging) {
      document.body.style.userSelect = 'none'
      document.body.style.cursor = 'ew-resize'
    } else {
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }
    return () => {
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }
  }, [isDragging])

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      const container = (e.currentTarget as HTMLElement).closest('[data-testid="chat-panel-resize-container"]')
      if (!container) return
      const startX = e.clientX
      const startWidth = container.getBoundingClientRect().width
      const maxWidth = maxWidthProp ?? window.innerWidth * 0.9
      dragRef.current = { startX, startWidth, maxWidth }
      setIsDragging(true)

      const handleMouseMove = (moveEvent: MouseEvent) => {
        if (!dragRef.current) return
        const { startX: sX, startWidth: sW, maxWidth: mW } = dragRef.current
        const deltaX = sX - moveEvent.clientX  // 向左拖 = 缩小
        const newWidth = Math.min(mW, Math.max(minWidth, sW - deltaX))
        setStoredWidth(Math.round(newWidth))
      }

      const handleMouseUp = () => {
        setIsDragging(false)
        dragRef.current = null
        document.removeEventListener('mousemove', handleMouseMove)
        document.removeEventListener('mouseup', handleMouseUp)
      }

      document.addEventListener('mousemove', handleMouseMove)
      document.addEventListener('mouseup', handleMouseUp)
    },
    [minWidth, maxWidthProp]
  )

  const prevDragging = useRef(false)
  useEffect(() => {
    if (prevDragging.current && !isDragging && storedWidth !== null) {
      persistWidth(storageKey, storedWidth)
    }
    prevDragging.current = isDragging
  }, [isDragging, storedWidth, storageKey])

  const resetWidth = useCallback(() => {
    try { localStorage.removeItem(storageKey) } catch { /* ignore */ }
    setStoredWidth(null)
  }, [storageKey])

  /** 程序化设置宽度（夹在 [minWidth, maxWidth] 内）——右下角斜向缩放共用 */
  const setWidth = useCallback((width: number) => {
    const maxWidth = maxWidthProp ?? window.innerWidth
    setStoredWidth(Math.round(Math.min(maxWidth, Math.max(minWidth, width))))
  }, [minWidth, maxWidthProp])

  const containerStyle = {
    width: storedWidth !== null
      ? // 钳制：不超过视口；显式 maxWidth（如 UI 上限）比视口更小时取更小值
        `${Math.min(storedWidth, maxWidthProp ?? Infinity, viewportWidth ?? Infinity)}px`
      : defaultWidth,
  }

  const handleProps = {
    onMouseDown: handleMouseDown,
    role: 'separator' as const,
    tabIndex: 0 as const,
    'aria-label': '拖拽调整宽度',
    'aria-orientation': 'vertical' as const,
  }

  return { containerStyle, handleProps, isDragging, resetWidth, setWidth }
}
