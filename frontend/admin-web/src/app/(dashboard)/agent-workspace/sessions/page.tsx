'use client'

import {
  Monitor,
  UserPlus,
  BarChart3,
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
    icon: Monitor,
    iconColor: 'text-blue-600',
    iconBg: 'bg-blue-50',
    title: '实时会话监控',
    description: '查看当前进行中、排队中的会话状态',
  },
  {
    icon: UserPlus,
    iconColor: 'text-indigo-600',
    iconBg: 'bg-indigo-50',
    title: '手动分配与干预',
    description: '支持手动分配会话、转接、结束等操作',
  },
  {
    icon: BarChart3,
    iconColor: 'text-violet-600',
    iconBg: 'bg-violet-50',
    title: '数据统计看板',
    description: '在线客服数、今日接待量、平均响应时间等关键指标',
  },
]

export default function AgentSessionsPage() {
  return (
    <div className="p-6 max-w-4xl mx-auto">
      {/* 顶部标题区 */}
      <div className="text-center mb-10 pt-8">
        <div className="inline-flex items-center justify-center w-16 h-16 bg-blue-50 rounded-full mb-5">
          <Clock className="w-8 h-8 text-blue-600" />
        </div>
        <h1 className="text-2xl font-bold text-gray-900 mb-2">会话监控</h1>
        <p className="text-base text-gray-500">该功能正在开发中，敬请期待</p>
      </div>

      {/* 功能预告卡片 */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-10">
        {features.map((feature) => (
          <FeatureCard key={feature.title} {...feature} />
        ))}
      </div>

      {/* 底部提示 */}
      <p className="text-center text-sm text-gray-400">
        功能即将上线，届时将在此处为您提供实时的会话监控和管理能力
      </p>
    </div>
  )
}
