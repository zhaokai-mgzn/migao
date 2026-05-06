'use client'

import { useEffect } from 'react'
import {
  Package,
  ShoppingBag,
  Truck,
  RefreshCw,
  Sparkles,
} from 'lucide-react'
import { useChatStore } from '@/store/chat'

const iconMap: Record<string, React.ReactNode> = {
  'package': <Package className="w-3.5 h-3.5" />,
  'shopping-bag': <ShoppingBag className="w-3.5 h-3.5" />,
  'truck': <Truck className="w-3.5 h-3.5" />,
  'refresh-cw': <RefreshCw className="w-3.5 h-3.5" />,
}

export default function QuickActions() {
  const { quickActions, fetchQuickActions, sendMessage, currentSessionId, isStreaming } = useChatStore()

  useEffect(() => {
    fetchQuickActions()
  }, [fetchQuickActions])

  if (!currentSessionId || quickActions.length === 0) return null

  const handleClick = (prompt: string) => {
    if (isStreaming) return
    sendMessage(prompt)
  }

  return (
    <div className="px-4 py-2 bg-white border-t border-gray-100">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center gap-1.5 mb-1.5">
          <Sparkles className="w-3 h-3 text-amber-500" />
          <span className="text-[10px] text-gray-400 font-medium">快捷操作</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {quickActions.map((action) => (
            <button
              key={action.id}
              onClick={() => handleClick(action.prompt)}
              disabled={isStreaming}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-gray-50 hover:bg-primary-50 border border-gray-200 hover:border-primary-300 rounded-full text-xs text-gray-600 hover:text-primary-700 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {iconMap[action.icon] || <Sparkles className="w-3.5 h-3.5" />}
              {action.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
