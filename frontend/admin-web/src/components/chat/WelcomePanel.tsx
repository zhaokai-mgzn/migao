'use client'

import { Bot, Package, ShoppingBag, BarChart3, Truck, Search } from 'lucide-react'
import { useChatStore } from '@/store/chat'

const EXAMPLES = [
  {
    icon: ShoppingBag,
    text: '查看待处理订单',
    color: 'text-blue-500',
    bg: 'bg-blue-50 border-blue-200 hover:bg-blue-100',
  },
  {
    icon: BarChart3,
    text: '今日经营数据',
    color: 'text-green-500',
    bg: 'bg-green-50 border-green-200 hover:bg-green-100',
  },
  {
    icon: Search,
    text: '搜索商品"窗帘"',
    color: 'text-amber-500',
    bg: 'bg-amber-50 border-amber-200 hover:bg-amber-100',
  },
  {
    icon: Truck,
    text: '帮我查一个物流单号',
    color: 'text-purple-500',
    bg: 'bg-purple-50 border-purple-200 hover:bg-purple-100',
  },
  {
    icon: Package,
    text: '查看加工项列表',
    color: 'text-rose-500',
    bg: 'bg-rose-50 border-rose-200 hover:bg-rose-100',
  },
]

export default function WelcomePanel() {
  const { sendMessage, createSession, currentSessionId } = useChatStore()

  const handleExample = (text: string) => {
    if (!currentSessionId) {
      createSession().then(() => {
        const { sendMessage: send } = useChatStore.getState()
        send(text)
      })
      return
    }
    sendMessage(text)
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center px-6 py-8">
      {/* 头部 */}
      <div className="flex flex-col items-center mb-8">
        <div className="w-16 h-16 rounded-2xl bg-primary-100 flex items-center justify-center mb-4 shadow-sm">
          <Bot className="w-9 h-9 text-primary-600" />
        </div>
        <h2 className="text-xl font-bold text-gray-800 mb-1">欢迎使用米宝</h2>
        <p className="text-sm text-gray-500">我是你的智能工作助手，可以帮你查订单、管商品、看数据</p>
      </div>

      {/* 示例 prompt 卡片 */}
      <div className="w-full max-w-sm space-y-2.5">
        {EXAMPLES.map((item) => (
          <button
            key={item.text}
            onClick={() => handleExample(item.text)}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl border transition-colors text-left ${item.bg}`}
          >
            <item.icon className={`w-5 h-5 ${item.color} flex-shrink-0`} />
            <span className="text-sm font-medium text-gray-700">{item.text}</span>
          </button>
        ))}
      </div>

      {/* 底部提示 */}
      <p className="mt-8 text-xs text-gray-400 text-center max-w-xs leading-relaxed">
        发送消息后，右侧<span className="text-gray-500 font-medium">会话洞察</span>面板会实时展示查询结果和便签，点击便签标签可快速追问
      </p>
    </div>
  )
}
