'use client'

import {
  MessageSquare,
  UserPlus,
  Bot,
  Zap,
  Clock,
  type LucideIcon,
} from 'lucide-react'

interface FeatureCardProps {
  icon: LucideIcon
  iconColor: string
  iconBg: string
  title: string
  description: string
}

function FeatureCard({ icon: Icon, iconColor, iconBg, title, description }: FeatureCardProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 p-6 shadow-sm hover:shadow-md transition-shadow">
      <div className={`w-12 h-12 ${iconBg} rounded-lg flex items-center justify-center mb-4`}>
        <Icon className={`w-6 h-6 ${iconColor}`} />
      </div>
      <h3 className="text-base font-semibold text-gray-900 mb-2">{title}</h3>
      <p className="text-sm text-gray-500 leading-relaxed">{description}</p>
    </div>
  )
}

const features: FeatureCardProps[] = [
  {
    icon: MessageSquare,
    iconColor: 'text-blue-600',
    iconBg: 'bg-blue-50',
    title: '实时对话工作台',
    description: '客服人员在线接待C端消费者的实时对话',
  },
  {
    icon: UserPlus,
    iconColor: 'text-indigo-600',
    iconBg: 'bg-indigo-50',
    title: '智能会话分配',
    description: '自动轮询分配，支持排队管理和优先级调度',
  },
  {
    icon: Bot,
    iconColor: 'text-violet-600',
    iconBg: 'bg-violet-50',
    title: 'AI辅助回复',
    description: '结合AI智能客服历史对话，提供上下文辅助',
  },
  {
    icon: Zap,
    iconColor: 'text-amber-600',
    iconBg: 'bg-amber-50',
    title: '快捷回复模板',
    description: '预设常用回复模板，提升客服响应效率',
  },
]

export default function AgentWorkspacePage() {
  return (
    <div className="p-6 max-w-4xl mx-auto">
      {/* 顶部标题区 */}
      <div className="text-center mb-10 pt-8">
        <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-50 rounded-full mb-5">
          <Clock className="w-8 h-8 text-blue-600" />
        </div>
        <h1 className="text-2xl font-bold text-gray-900 mb-2">客服工作台</h1>
        <p className="text-base text-gray-500">该功能正在开发中，敬请期待</p>
      </div>

      {/* 功能预告卡片 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-10">
        {features.map((feature) => (
          <FeatureCard key={feature.title} {...feature} />
        ))}
      </div>

      {/* 底部提示 */}
      <p className="text-center text-sm text-gray-400">
        功能即将上线，届时将在此处为您提供完整的客服工作台体验
      </p>
    </div>
  )
}
