'use client'

import { Bot, Package, ShoppingBag, BarChart3, Truck, Search } from 'lucide-react'
import { useChatStore } from '@/store/chat'

const EXAMPLES = [
  {
    icon: ShoppingBag,
    text: '查看待处理订单',
    color: 'text-primary-500',
    iconBg: 'bg-primary-50',
  },
  {
    icon: BarChart3,
    text: '今日经营数据',
    color: 'text-primary-500',
    iconBg: 'bg-primary-50',
  },
  {
    icon: Search,
    text: '搜索商品"窗帘"',
    color: 'text-primary-500',
    iconBg: 'bg-primary-50',
  },
  {
    icon: Truck,
    text: '帮我查一个物流单号',
    color: 'text-primary-500',
    iconBg: 'bg-primary-50',
  },
  {
    icon: Package,
    text: '查看加工项列表',
    color: 'text-primary-500',
    iconBg: 'bg-primary-50',
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
        <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700 shadow-card">
          <Bot className="h-9 w-9 text-white" />
        </div>
        <h2 className="mb-1 text-xl font-bold text-neutral-800">欢迎使用米宝</h2>
        <p className="text-sm text-neutral-500">我是你的智能工作助手，可以帮你查订单、管商品、看数据</p>
      </div>

      {/* 示例 prompt 卡片 — 统一主色点缀 */}
      <div className="w-full max-w-sm space-y-2.5">
        {EXAMPLES.map((item) => (
          <button
            key={item.text}
            onClick={() => handleExample(item.text)}
            className="w-full flex items-center gap-3 px-4 py-3 rounded-xl border border-neutral-200 bg-white transition-all text-left hover:border-primary-300 hover:bg-primary-50/50 hover:shadow-card hover:-translate-y-0.5"
          >
            <span className={`w-9 h-9 rounded-lg ${item.iconBg} flex items-center justify-center flex-shrink-0`}>
              <item.icon className={`w-4 h-4 ${item.color}`} />
            </span>
            <span className="text-sm font-medium text-neutral-700">{item.text}</span>
          </button>
        ))}
      </div>

      {/* 底部提示 */}
      <p className="mt-8 max-w-xs text-center text-xs leading-relaxed text-neutral-400">
        发送消息后，点击顶部<span className="font-medium text-neutral-500">洞察</span>按钮可查看查询结果和便签，点击便签标签可快速追问
      </p>
    </div>
  )
}
