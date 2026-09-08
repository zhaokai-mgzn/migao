'use client'

import { useState, useCallback, useEffect, useRef } from 'react'

interface UseResizableHeightOptions {
  storageKey: string
  defaultHeight: string
  minHeight: number
  maxHeight?: number
}

interface UseResizableHeightReturn {
  containerStyle: { height: string }
  handleProps: {
    onMouseDown: (e: React.MouseEvent) => void
    role: 'separator'
    tabIndex: 0
    'aria-label': string
    'aria-orientation': 'horizontal'
  }
  /** 顶部手柄（向上拖 = 增大高度，与底部手柄方向相反） */
  topHandleProps: {
    onMouseDown: (e: React.MouseEvent) => void
    role: 'separator'
    tabIndex: 0
    'aria-label': string
    'aria-orientation': 'horizontal'
  }
  isDragging: boolean
  resetHeight: () => void
  /** 程序化设置高度（夹在 [minHeight, maxHeight] 内）——右下角斜向缩放共用 */
  setHeight: (height: number) => void
}

function readStoredHeight(key: string): number | null {
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

function persistHeight(key: string, height: number): void {
  try {
    localStorage.setItem(key, String(height))
  } catch {
    /* silent */
  }
}

export function useResizableHeight({
  storageKey,
  defaultHeight,
  minHeight,
  maxHeight: maxHeightProp,
}: UseResizableHeightOptions): UseResizableHeightReturn {
  const [storedHeight, setStoredHeight] = useState<number | null>(
    () => readStoredHeight(storageKey)
  )
  const [isDragging, setIsDragging] = useState(false)

  const dragRef = useRef<{
    startY: number
    startHeight: number
    maxHeight: number
  } | null>(null)

  useEffect(() => {
    if (isDragging) {
      document.body.style.userSelect = 'none'
      document.body.style.cursor = 'ns-resize'
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
    (e: React.MouseEvent, direction: 'bottom' | 'top' = 'bottom') => {
      e.preventDefault()
      const container = e.currentTarget.parentElement
      if (!container) return
      const startY = e.clientY
      const startHeight = container.getBoundingClientRect().height
      const maxHeight = maxHeightProp ?? window.innerHeight
      dragRef.current = { startY, startHeight, maxHeight }
      setIsDragging(true)

      const handleMouseMove = (moveEvent: MouseEvent) => {
        if (!dragRef.current) return
        const { startY: sY, startHeight: sH, maxHeight: mH } = dragRef.current
        const deltaY = moveEvent.clientY - sY
        // 底部手柄：向下拖增大；顶部手柄：向上拖增大（方向相反）
        const newHeight = direction === 'top'
          ? Math.min(mH, Math.max(minHeight, sH - deltaY))
          : Math.min(mH, Math.max(minHeight, sH + deltaY))
        setStoredHeight(Math.round(newHeight))
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
    [minHeight, maxHeightProp]
  )

  const prevDragging = useRef(false)
  useEffect(() => {
    if (prevDragging.current && !isDragging && storedHeight !== null) {
      persistHeight(storageKey, storedHeight)
    }
    prevDragging.current = isDragging
  }, [isDragging, storedHeight, storageKey])

  /** UI-029：把残留高度钳制进 [minHeight, min(maxHeight, 当前视口高)] ——
   *  换更大/更小窗口后，旧 px 残留不得溢出视口（不留死白）；
   *  视口变大时不放大刻意缩小的高度；无残留（null）原样返回。 */
  const clampToViewport = useCallback(
    (h: number | null): number | null => {
      if (h === null) return null
      const liveMax = typeof window !== 'undefined' ? window.innerHeight : h
      const bound = maxHeightProp !== undefined ? Math.min(maxHeightProp, liveMax) : liveMax
      return Math.round(Math.min(Math.max(h, minHeight), bound))
    },
    [minHeight, maxHeightProp]
  )

  // UI-029：挂载时钳制历史残留 + 监听窗口 resize 持续钳制（issue #3021）
  useEffect(() => {
    setStoredHeight(clampToViewport)
    const handleResize = () => setStoredHeight(clampToViewport)
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [clampToViewport])

  const resetHeight = useCallback(() => {
    try { localStorage.removeItem(storageKey) } catch { /* ignore */ }
    setStoredHeight(null)
  }, [storageKey])

  /** 程序化设置高度（夹在 [minHeight, maxHeight] 内）——右下角斜向缩放共用 */
  const setHeight = useCallback((height: number) => {
    const maxHeight = maxHeightProp ?? window.innerHeight
    setStoredHeight(Math.round(Math.min(maxHeight, Math.max(minHeight, height))))
  }, [minHeight, maxHeightProp])

  const containerStyle = {
    // UI-029 状态层已钳制（clampToViewport）：残留高度 ≤ min(maxHeight, 当前视口高)，
    // 渲染层直接输出即可，不重复钳制
    height: storedHeight !== null ? `${storedHeight}px` : defaultHeight,
  }

  const handleProps = {
    onMouseDown: (e: React.MouseEvent) => handleMouseDown(e, 'bottom'),
    role: 'separator' as const,
    tabIndex: 0 as const,
    'aria-label': '拖拽调整高度',
    'aria-orientation': 'horizontal' as const,
  }

  const topHandleProps = {
    onMouseDown: (e: React.MouseEvent) => handleMouseDown(e, 'top'),
    role: 'separator' as const,
    tabIndex: 0 as const,
    'aria-label': '拖拽调整高度（顶部）',
    'aria-orientation': 'horizontal' as const,
  }

  return { containerStyle, handleProps, topHandleProps, isDragging, resetHeight, setHeight }
}
