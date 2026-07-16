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
  isDragging: boolean
  resetHeight: () => void
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
    (e: React.MouseEvent) => {
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
        const newHeight = Math.min(mH, Math.max(minHeight, sH + deltaY))
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

  const resetHeight = useCallback(() => {
    try { localStorage.removeItem(storageKey) } catch { /* ignore */ }
    setStoredHeight(null)
  }, [storageKey])

  const containerStyle = {
    height: storedHeight !== null ? `${storedHeight}px` : defaultHeight,
  }

  const handleProps = {
    onMouseDown: handleMouseDown,
    role: 'separator' as const,
    tabIndex: 0 as const,
    'aria-label': '拖拽调整高度',
    'aria-orientation': 'horizontal' as const,
  }

  return { containerStyle, handleProps, isDragging, resetHeight }
}
