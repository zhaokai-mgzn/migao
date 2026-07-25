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

  const containerStyle = {
    width: storedWidth !== null ? `${storedWidth}px` : defaultWidth,
  }

  const handleProps = {
    onMouseDown: handleMouseDown,
    role: 'separator' as const,
    tabIndex: 0 as const,
    'aria-label': '拖拽调整宽度',
    'aria-orientation': 'vertical' as const,
  }

  return { containerStyle, handleProps, isDragging, resetWidth }
}
