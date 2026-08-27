import type { Metadata } from 'next'
import { Lightbulb, Heart, Sprout, Lock, Target, Eye } from 'lucide-react'

export const metadata: Metadata = {
  title: '关于米高 — AI双助手重新定义企业电商管理',
  description:
    '米高致力于为企业提供从内部运营到客户服务的一站式智能解决方案，以米宝+小布双助手模式构建行业标杆。',
}

const values = [
  {
    icon: Lightbulb,
    title: '技术驱动',
    description: '持续探索AI前沿技术，将大模型能力转化为商家触手可及的智能工具',
  },
  {
    icon: Heart,
    title: '客户至上',
    description: '以商家需求为导向，让每一位用户都能感受到AI带来的效率提升',
  },
  {
    icon: Sprout,
    title: '行业深耕',
    description: '深入理解行业场景与业务逻辑，打造真正贴合实际的智能方案',
  },
  {
    icon: Lock,
    title: '数据安全',
    description: '租户级数据隔离，严格的隐私保护，让商家安心托付核心数据',
  },
]

const timeline = [
  {
    period: '2024 Q1',
    title: '项目启动',
    description: '完成技术架构设计，确定米高产品方向与AI技术路线',
  },
  {
    period: '2024 Q2',
    title: '核心引擎开发',
    description: 'AI Agent框架搭建，米宝与小布双智能助手引擎开发',
  },
  {
    period: '2024 Q3',
    title: '平台上线',
    description: '商家管理后台正式发布，米宝助手入驻管理后台，首批商家测试',
  },
  {
    period: '2024 Q4',
    title: '多渠道接入',
    description: '微信小程序上线，小布客服实现多渠道统一服务',
  },
  {
    period: '2025',
    title: '能力进化',
    description: '米宝与小布持续进化，功能扩展，服务更多行业商家',
  },
]

export default function AboutPage() {
  return (
    <>
      {/* Page Header with dot pattern */}
      <section className="relative bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800 text-white py-16 sm:py-20 overflow-hidden">
        {/* Subtle dot pattern background */}
        <div
          className="absolute inset-0 opacity-10"
          style={{
            backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.8) 1px, transparent 1px)',
            backgroundSize: '24px 24px',
          }}
        />
        {/* Gradient blobs */}
        <div className="absolute -top-24 -right-24 w-80 h-80 bg-blue-400/15 rounded-full blur-3xl" />
        <div className="absolute -bottom-24 -left-24 w-64 h-64 bg-indigo-400/15 rounded-full blur-3xl" />

        <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 text-center">
          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight">
            关于米高
          </h1>
          <p className="mt-4 text-lg sm:text-xl text-blue-100/90 max-w-2xl mx-auto leading-relaxed">
            以AI双助手重新定义企业电商管理，让智能运营触手可及
          </p>
        </div>
      </section>

      {/* Company Intro */}
      <section className="py-20 sm:py-28 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="max-w-3xl mx-auto space-y-6 text-gray-600 leading-relaxed text-base sm:text-lg">
            <p>
              米高是词元通达旗下的AI智能电商管理平台，致力于为企业提供从内部运营到客户服务的一站式智能解决方案。
            </p>
            <p>
              我们深知，不同行业的企业在商品管理、订单处理、客户服务等环节面临着各自独特的挑战。传统管理模式人力成本高、响应效率低、多平台协同困难——米高正是为解决这些痛点而生。
            </p>
            <p>
              基于大语言模型技术，米高为每一位商家打造了两位AI助手：面向企业员工的「米宝」智能工作助手，和面向消费者的「小布」智能客服。米宝帮助运营团队高效处理商品管理、订单跟踪、库存盘点、售后协调等日常事务；小布则7×24小时在线，精准理解客户意图，提供专业贴心的购物咨询服务。
            </p>
            <p>
              作为SaaS平台，我们为每位商家提供独立的数据空间和个性化的AI能力，确保数据安全的同时，让AI深度学习每位商家的业务知识，提供越来越精准的智能服务。
            </p>
          </div>
        </div>
      </section>

      {/* Mission & Vision */}
      <section className="py-20 sm:py-28 bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-4xl mx-auto">
            {/* Mission */}
            <div className="group relative bg-gradient-to-br from-white to-blue-50/30 p-8 rounded-2xl shadow-sm border border-gray-100 hover:border-blue-200 hover:shadow-lg transition-all duration-300 hover:-translate-y-1">
              <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-blue-600 rounded-xl flex items-center justify-center mb-5 shadow-sm shadow-blue-200">
                <Target className="w-6 h-6 text-white" />
              </div>
              <h2 className="text-xl font-bold text-gray-900 mb-3">我们的使命</h2>
              <p className="text-gray-600 leading-relaxed">
                让每一家企业都能拥有自己的AI助手团队，用智能技术消除管理能力差距，帮助中小商家也能提供大品牌级别的运营效率和客户体验。
              </p>
            </div>

            {/* Vision */}
            <div className="group relative bg-gradient-to-br from-white to-indigo-50/30 p-8 rounded-2xl shadow-sm border border-gray-100 hover:border-indigo-200 hover:shadow-lg transition-all duration-300 hover:-translate-y-1">
              <div className="w-12 h-12 bg-gradient-to-br from-indigo-500 to-indigo-600 rounded-xl flex items-center justify-center mb-5 shadow-sm shadow-indigo-200">
                <Eye className="w-6 h-6 text-white" />
              </div>
              <h2 className="text-xl font-bold text-gray-900 mb-3">我们的愿景</h2>
              <p className="text-gray-600 leading-relaxed">
                成为企业电商领域领先的AI智能管理服务商，以「米宝+小布」双助手模式构建行业标杆，推动千万商家的数字化转型与服务升级。
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Core Values */}
      <section className="py-20 sm:py-28 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <span className="text-sm font-semibold text-blue-600 uppercase tracking-wider">
              核心价值观
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-gray-900">
              驱动我们前行的信念
            </h2>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8 max-w-5xl mx-auto">
            {values.map((item) => (
              <div key={item.title} className="group text-center p-6 rounded-2xl hover:bg-slate-50 transition-colors duration-300">
                <div className="w-16 h-16 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-2xl flex items-center justify-center mx-auto mb-5 group-hover:from-blue-100 group-hover:to-indigo-100 group-hover:scale-110 transition-all duration-300">
                  <item.icon className="w-7 h-7 text-blue-600" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900 mb-2">
                  {item.title}
                </h3>
                <p className="text-sm text-gray-500 leading-relaxed">
                  {item.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Timeline */}
      <section className="py-20 sm:py-28 bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <span className="text-sm font-semibold text-blue-600 uppercase tracking-wider">
              发展历程
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-gray-900">
              脚踏实地，步步为营
            </h2>
          </div>

          {/* Desktop: Alternating timeline */}
          <div className="hidden md:block relative max-w-4xl mx-auto">
            {/* Center vertical line */}
            <div className="absolute left-1/2 top-0 bottom-0 w-px bg-gradient-to-b from-transparent via-blue-300 to-transparent -translate-x-px" />

            <div className="space-y-12">
              {timeline.map((item, index) => {
                const isLeft = index % 2 === 0
                return (
                  <div
                    key={item.period}
                    className={`relative flex items-center ${isLeft ? '' : 'flex-row-reverse'}`}
                  >
                    {/* Content card */}
                    <div className={`w-[calc(50%-2rem)] ${isLeft ? 'pr-8 text-right' : 'pl-8 text-left'}`}>
                      <div className="group bg-white p-6 rounded-2xl border border-gray-100 hover:border-blue-200 hover:shadow-lg transition-all duration-300 inline-block w-full">
                        <span className="inline-block px-3 py-1 rounded-full bg-blue-50 text-xs font-bold text-blue-600 mb-2">
                          {item.period}
                        </span>
                        <h3 className="text-lg font-semibold text-gray-900 mb-1">
                          {item.title}
                        </h3>
                        <p className="text-sm text-gray-500 leading-relaxed">
                          {item.description}
                        </p>
                      </div>
                    </div>

                    {/* Center dot */}
                    <div className="absolute left-1/2 -translate-x-1/2 w-4 h-4 bg-blue-600 rounded-full border-4 border-blue-100 ring-4 ring-white z-10" />

                    {/* Spacer for the other side */}
                    <div className="w-[calc(50%-2rem)]" />
                  </div>
                )
              })}
            </div>
          </div>

          {/* Mobile: Single-sided timeline */}
          <div className="md:hidden max-w-md mx-auto">
            <div className="relative pl-10">
              <div className="absolute left-4 top-1 bottom-1 w-0.5 bg-gradient-to-b from-blue-200 via-blue-400 to-blue-200" />
              <div className="space-y-10">
                {timeline.map((item) => (
                  <div key={item.period} className="relative">
                    <div className="absolute -left-10 w-8 h-8 bg-blue-600 rounded-full flex items-center justify-center z-10 ring-4 ring-slate-50">
                      <div className="w-2.5 h-2.5 bg-white rounded-full" />
                    </div>
                    <div className="bg-white p-5 rounded-xl border border-gray-100 shadow-sm">
                      <span className="text-sm font-semibold text-blue-600">
                        {item.period}
                      </span>
                      <h3 className="text-base font-semibold text-gray-900 mt-1">
                        {item.title}
                      </h3>
                      <p className="text-sm text-gray-500 mt-1">
                        {item.description}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>
    </>
  )
}
