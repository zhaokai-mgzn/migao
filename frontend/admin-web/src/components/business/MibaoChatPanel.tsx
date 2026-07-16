'use client'

import { GripHorizontal } from 'lucide-react'
import { useResizableHeight } from '@/hooks/useResizableHeight'
import { cn } from '@/lib/utils'

const STORAGE_KEY = 'mibao_chat_panel_height'
const DEFAULT_HEIGHT = '85vh'
const MIN_HEIGHT = 300
const MAX_HEIGHT_RATIO = 0.9

interface MibaoChatPanelProps {
  children: React.ReactNode
  className?: string
}

export default function MibaoChatPanel({ children, className }: MibaoChatPanelProps) {
  const { containerStyle, handleProps } = useResizableHeight({
    storageKey: STORAGE_KEY,
    defaultHeight: DEFAULT_HEIGHT,
    minHeight: MIN_HEIGHT,
    maxHeight: typeof window !== 'undefined'
      ? Math.round(window.innerHeight * MAX_HEIGHT_RATIO)
      : undefined,
  })

  return (
    <div
      data-testid="chat-panel-resize-container"
      style={containerStyle}
      className={cn(
        'relative flex flex-col rounded-lg overflow-hidden border border-gray-200',
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

      {/* 拖拽手柄 — 底部 */}
      <div
        data-testid="chat-panel-resize-handle"
        className="h-2 flex-shrink-0 flex items-center justify-center bg-gray-100 hover:bg-blue-100 border-t border-gray-200 transition-colors select-none"
        style={{ cursor: 'ns-resize' }}
        {...handleProps}
      >
        <GripHorizontal className="w-5 h-3 text-gray-400" />
      </div>
    </div>
  )
}
