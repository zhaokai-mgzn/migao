'use client'

import { GripHorizontal, GripVertical, MoveDiagonal } from 'lucide-react'
import { useResizableHeight } from '@/hooks/useResizableHeight'
import { useResizableWidth } from '@/hooks/useResizableWidth'
import { cn } from '@/lib/utils'

const HEIGHT_STORAGE_KEY = 'mibao_chat_panel_height'
const WIDTH_STORAGE_KEY = 'mibao_chat_panel_width'
const DEFAULT_HEIGHT = '85vh'
const DEFAULT_WIDTH = '100%'
const MIN_HEIGHT = 300
const MIN_WIDTH = 480
// 缩放上限放开到视口 100%（UI-019：拖到最大不留白）
const MAX_HEIGHT_RATIO = 1
const MAX_WIDTH_RATIO = 1

interface MibaoChatPanelProps {
  children: React.ReactNode
  className?: string
  defaultHeight?: string
  defaultWidth?: string
  /** 是否显示顶部拖拽手柄（拖顶部边缘调整高度） */
  showTopHandle?: boolean
}

export default function MibaoChatPanel({
  children,
  className,
  defaultHeight,
  defaultWidth,
  showTopHandle,
}: MibaoChatPanelProps) {
  const {
    containerStyle: heightStyle,
    handleProps: heightHandleProps,
    topHandleProps,
    setHeight,
    resetHeight,
  } = useResizableHeight({
    storageKey: HEIGHT_STORAGE_KEY,
    defaultHeight: defaultHeight || DEFAULT_HEIGHT,
    minHeight: MIN_HEIGHT,
    maxHeight: typeof window !== 'undefined'
      ? Math.round(window.innerHeight * MAX_HEIGHT_RATIO)
      : undefined,
  })

  const {
    containerStyle: widthStyle,
    handleProps: widthHandleProps,
    setWidth,
    resetWidth,
  } = useResizableWidth({
    storageKey: WIDTH_STORAGE_KEY,
    defaultWidth: defaultWidth || DEFAULT_WIDTH,
    minWidth: MIN_WIDTH,
    maxWidth: typeof window !== 'undefined'
      ? Math.round(window.innerWidth * MAX_WIDTH_RATIO)
      : undefined,
  })

  const containerStyle = { ...heightStyle, ...widthStyle }

  /** UI-029：双击任意缩放手柄 —— 恢复默认尺寸并清除持久化（issue #3021 误冻结自救入口） */
  const resetToDefault = () => {
    resetWidth()
    resetHeight()
  }

  /** 右下角斜向缩放：同时调整宽度与高度（UI-020）
   *  UI-029：仅在实际发生拖动后才持久化 —— 单击误触不再把流式尺寸冻结成 px（issue #3021） */
  const handleCornerMouseDown = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const container = (e.currentTarget as HTMLElement).closest('[data-testid="chat-panel-resize-container"]') as HTMLElement | null
    if (!container) return
    const startX = e.clientX
    const startY = e.clientY
    const { width: startWidth, height: startHeight } = container.getBoundingClientRect()
    let moved = false

    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'nwse-resize'

    const handleMouseMove = (moveEvent: MouseEvent) => {
      moved = true
      setWidth(startWidth + (moveEvent.clientX - startX))
      setHeight(startHeight + (moveEvent.clientY - startY))
    }

    const handleMouseUp = () => {
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      // 与边缘把手一致：松开时持久化；但未发生拖动（纯点击）不持久化，避免冻结当前 px
      if (!moved) return
      try {
        localStorage.setItem(HEIGHT_STORAGE_KEY, String(container.getBoundingClientRect().height))
        localStorage.setItem(WIDTH_STORAGE_KEY, String(container.getBoundingClientRect().width))
      } catch {
        /* silent */
      }
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }

  return (
    <div
      data-testid="chat-panel-resize-container"
      style={containerStyle}
      className={cn(
        'relative flex flex-col overflow-hidden',
        className
      )}
    >
      {/* 内容区域 */}
      <div
        data-testid="chat-panel-content"
        className="flex-1 flex min-h-0 min-w-0 overflow-hidden"
      >
        {children}
      </div>

      {/* 拖拽手柄 — 顶部（垂直缩放，向上拖增大高度），默认透明、hover 时轻提示；双击恢复默认 */}
      {showTopHandle && (
        <div
          data-testid="chat-panel-resize-handle-top"
          className="absolute top-0 left-0 right-0 h-3.5 flex items-center justify-center bg-transparent hover:bg-neutral-100/70 transition-colors select-none group z-10"
          style={{ cursor: 'ns-resize' }}
          title="拖拽调整大小，双击恢复默认大小"
          onDoubleClick={resetToDefault}
          {...topHandleProps}
        >
          <GripHorizontal className="w-5 h-3 text-neutral-400 opacity-0 group-hover:opacity-100 transition-opacity" />
        </div>
      )}

      {/* 拖拽手柄 — 底部（垂直缩放），默认透明、hover 时轻提示；双击恢复默认 */}
      <div
        data-testid="chat-panel-resize-handle"
        className="h-3.5 flex-shrink-0 flex items-center justify-center bg-transparent hover:bg-neutral-100/70 transition-colors select-none group"
        style={{ cursor: 'ns-resize' }}
        title="拖拽调整大小，双击恢复默认大小"
        onDoubleClick={resetToDefault}
        {...heightHandleProps}
      >
        <GripHorizontal className="w-5 h-3 text-neutral-400 opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>

      {/* 拖拽手柄 — 右侧（水平缩放），默认透明、hover 时轻提示；双击恢复默认 */}
      <div
        data-testid="chat-panel-resize-handle-horizontal"
        className="absolute top-0 right-0 bottom-2.5 w-3.5 flex items-center justify-center bg-transparent hover:bg-neutral-100/70 transition-colors select-none group"
        style={{ cursor: 'ew-resize' }}
        title="拖拽调整大小，双击恢复默认大小"
        onDoubleClick={resetToDefault}
        {...widthHandleProps}
      >
        <GripVertical className="w-3 h-5 text-neutral-400 opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>

      {/* 拖拽手柄 — 右下角（斜向缩放，同时调整宽高），默认透明、hover 时轻提示；双击恢复默认 */}
      <div
        data-testid="chat-panel-resize-handle-corner"
        className="absolute bottom-0 right-0 w-4 h-4 flex items-center justify-center bg-transparent hover:bg-neutral-100/70 transition-colors select-none group z-10"
        style={{ cursor: 'nwse-resize' }}
        onMouseDown={handleCornerMouseDown}
        onDoubleClick={resetToDefault}
        title="拖拽调整大小（斜向缩放，双击恢复默认大小）"
        aria-label="拖拽调整大小（斜向缩放）"
      >
        <MoveDiagonal className="w-3.5 h-3.5 text-neutral-400 opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>
    </div>
  )
}