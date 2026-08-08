'use client'

import { GripHorizontal, GripVertical } from 'lucide-react'
import { useResizableHeight } from '@/hooks/useResizableHeight'
import { useResizableWidth } from '@/hooks/useResizableWidth'
import { cn } from '@/lib/utils'

const HEIGHT_STORAGE_KEY = 'mibao_chat_panel_height'
const WIDTH_STORAGE_KEY = 'mibao_chat_panel_width'
const DEFAULT_HEIGHT = '85vh'
const DEFAULT_WIDTH = '100%'
const MIN_HEIGHT = 300
const MIN_WIDTH = 480
const MAX_HEIGHT_RATIO = 0.9
const MAX_WIDTH_RATIO = 0.9

interface MibaoChatPanelProps {
  children: React.ReactNode
  className?: string
  defaultHeight?: string
  defaultWidth?: string
}

export default function MibaoChatPanel({
  children,
  className,
  defaultHeight,
  defaultWidth,
}: MibaoChatPanelProps) {
  const { containerStyle: heightStyle, handleProps: heightHandleProps } = useResizableHeight({
    storageKey: HEIGHT_STORAGE_KEY,
    defaultHeight: defaultHeight || DEFAULT_HEIGHT,
    minHeight: MIN_HEIGHT,
    maxHeight: typeof window !== 'undefined'
      ? Math.round(window.innerHeight * MAX_HEIGHT_RATIO)
      : undefined,
  })

  const { containerStyle: widthStyle, handleProps: widthHandleProps } = useResizableWidth({
    storageKey: WIDTH_STORAGE_KEY,
    defaultWidth: defaultWidth || DEFAULT_WIDTH,
    minWidth: MIN_WIDTH,
    maxWidth: typeof window !== 'undefined'
      ? Math.round(window.innerWidth * MAX_WIDTH_RATIO)
      : undefined,
  })

  const containerStyle = { ...heightStyle, ...widthStyle }

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

      {/* 拖拽手柄 — 底部（垂直缩放），默认透明、hover 时轻提示 */}
      <div
        data-testid="chat-panel-resize-handle"
        className="h-2 flex-shrink-0 flex items-center justify-center bg-transparent hover:bg-gray-100/70 transition-colors select-none group"
        style={{ cursor: 'ns-resize' }}
        {...heightHandleProps}
      >
        <GripHorizontal className="w-5 h-3 text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>

      {/* 拖拽手柄 — 右侧（水平缩放），默认透明、hover 时轻提示 */}
      <div
        data-testid="chat-panel-resize-handle-horizontal"
        className="absolute top-0 right-0 bottom-2 w-2 flex items-center justify-center bg-transparent hover:bg-gray-100/70 transition-colors select-none group"
        style={{ cursor: 'ew-resize' }}
        {...widthHandleProps}
      >
        <GripVertical className="w-3 h-5 text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>
    </div>
  )
}
