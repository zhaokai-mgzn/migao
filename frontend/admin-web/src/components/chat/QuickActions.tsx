'use client'

import { useEffect } from 'react'
import {
  Package,
  ClipboardList,
  BarChart3,
  Users,
  Image as ImageIcon,
  Sparkles,
} from 'lucide-react'
import { useChatStore } from '@/store/chat'

const iconMap: Record<string, React.ReactNode> = {
  'clipboard-list': <ClipboardList className="w-3.5 h-3.5" />,
  'package': <Package className="w-3.5 h-3.5" />,
  'bar-chart-3': <BarChart3 className="w-3.5 h-3.5" />,
  'users': <Users className="w-3.5 h-3.5" />,
  'image': <ImageIcon className="w-3.5 h-3.5" />,
}

export default function QuickActions() {
  const { quickActions, quickTools, fetchQuickActions, sendMessage, currentSessionId, isStreaming } =
    useChatStore()

  useEffect(() => {
    fetchQuickActions()
  }, [fetchQuickActions])

  if (!currentSessionId || (quickActions.length === 0 && quickTools.length === 0)) return null

  const handleClick = (prompt: string) => {
    if (isStreaming) return
    sendMessage(prompt)
  }

  return (
    <div className="px-4 py-2 bg-white border-t border-neutral-100">
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center gap-1.5 mb-1.5">
          <Sparkles className="w-3 h-3 text-accent-500" />
          <span className="text-[10px] text-neutral-400 font-medium">快捷操作</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {quickActions.map((action) => (
            <button
              key={action.id}
              onClick={() => handleClick(action.prompt)}
              disabled={isStreaming}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white hover:bg-primary-50 border border-neutral-200 hover:border-primary-200 rounded-full text-xs text-neutral-600 hover:text-primary-600 transition-all shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {iconMap[action.icon] || <Sparkles className="w-3.5 h-3.5" />}
              {action.name}
            </button>
          ))}
          {/* 工具类入口（issue #7351）：营销海报等「动作」入口 —— 与上面问句型 pills 同区，
              用主色描边区分（点一下进入「引导补文案」的对话，不是直接发问句）。 */}
          {quickTools.map((tool) => (
            <button
              key={tool.id}
              onClick={() => handleClick(tool.prompt)}
              disabled={isStreaming}
              data-testid="quick-tool-action"
              className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-primary-50 hover:bg-primary-100 border border-primary-200 rounded-full text-xs text-primary-700 transition-all shadow-sm disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {iconMap[tool.icon] || <Sparkles className="w-3.5 h-3.5" />}
              {tool.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
