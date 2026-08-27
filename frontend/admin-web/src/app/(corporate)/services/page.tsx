import type { Metadata } from 'next'
import {
  MessageSquare,
  Wrench,
  Zap,
  Radio,
  LayoutDashboard,
  ShoppingBag,
  Users,
  BarChart3,
  Smartphone,
  MessageCircle,
  History,
  TrendingUp,
  UserCheck,
  PieChart,
  Sparkles,
  PackageSearch,
  Truck,
  BookOpen,
  Headphones,
  MessagesSquare,
} from 'lucide-react'

export const metadata: Metadata = {
  title: '产品与服务 — 双AI助手 + 全链路管理平台',
  description:
    '米高双AI助手 — 米宝智能工作助手（内部运营提效）+ 小布AI客服（7×24客户服务），搭配商家管理后台、微信小程序、数据分析，构建企业智能闭环。',
}

// Core AI products — displayed as large featured cards
const coreProducts = [
  {
    title: '米宝 · 企业智能工作助手',
    description: '面向企业员工的AI工作搭档，深度融入日常运营，自然语言交互即可完成复杂业务操作',
    icon: Sparkles,
    gradient: 'from-purple-500 to-pink-500',
    bgGradient: 'from-purple-50 to-pink-50',
    borderColor: 'border-purple-200 hover:border-purple-300',
    shadowColor: 'hover:shadow-purple-100',
    iconBg: 'from-purple-100 to-pink-100',
    iconText: 'text-purple-600',
    badgeBg: 'bg-purple-100',
    badgeText: 'text-purple-700',
    features: [
      { icon: PackageSearch, text: '商品智能管理：语音/文字查询商品、批量操作库存、智能分类推荐' },
      { icon: Truck, text: '订单全程跟踪：一句话查订单状态、物流追踪、异常订单智能预警' },
      { icon: BookOpen, text: '知识即时检索：面料知识、工艺流程、安装指南、售后政策，问即答' },
      { icon: Headphones, text: '售后高效协同：退换货处理、客户投诉跟进、智能工单流转' },
      { icon: MessagesSquare, text: '多轮深度对话：基于上下文理解，支持复杂业务场景的连续交互' },
    ],
  },
  {
    title: '小布 · AI 智能客服',
    description: '面向消费者的7×24小时智能客服，基于大语言模型深度理解客户问题，提供专业精准的服务',
    icon: MessageSquare,
    gradient: 'from-blue-500 to-cyan-500',
    bgGradient: 'from-blue-50 to-cyan-50',
    borderColor: 'border-blue-200 hover:border-blue-300',
    shadowColor: 'hover:shadow-blue-100',
    iconBg: 'from-blue-100 to-cyan-100',
    iconText: 'text-blue-600',
    badgeBg: 'bg-blue-100',
    badgeText: 'text-blue-700',
    features: [
      { icon: Wrench, text: '基于大语言模型，精准理解客户意图，应答自然贴切有温度' },
      { icon: MessageCircle, text: '多轮对话与上下文记忆，像真人客服一样连续沟通' },
      { icon: Zap, text: '智能工具调用：商品查询、物流追踪、知识检索一键直达' },
      { icon: Radio, text: '毫秒级流式应答，所见即所得的打字机效果，体验流畅自然' },
    ],
  },
]

// Supporting products — displayed as 3-column grid
const supportingProducts = [
  {
    title: '商家管理后台',
    description: '功能完善的一站式管理平台，助您高效掌控日常业务全流程',
    icon: LayoutDashboard,
    color: 'indigo',
    features: [
      { icon: ShoppingBag, text: '商品中心：商品信息管理、加工项配置、知识库维护，商品运营一站搞定' },
      { icon: ShoppingBag, text: '交易中心：订单管理、售后处理、物流跟踪，全链路把控' },
      { icon: Users, text: '客户中心：客户档案、标签管理、行为洞察，精准运营' },
      { icon: BarChart3, text: '数据看板：经营数据一览，趋势分析，数据驱动决策' },
    ],
  },
  {
    title: '微信小程序客服',
    description: '在微信生态内为消费者提供原生体验的小布智能客服服务',
    icon: Smartphone,
    color: 'green',
    features: [
      { icon: Smartphone, text: '微信原生体验，无需额外下载，扫码即用' },
      { icon: MessageCircle, text: '富媒体消息展示，商品卡片、订单详情直观呈现' },
      { icon: History, text: '完整会话管理，历史记录随时回顾，服务连贯不断线' },
    ],
  },
  {
    title: '数据分析与报表',
    description: '全方位数据洞察能力，让数据成为业务增长的引擎',
    icon: PieChart,
    color: 'orange',
    features: [
      { icon: TrendingUp, text: '服务质量监控：响应时长、客户满意度、问题解决率全面追踪' },
      { icon: UserCheck, text: '客户行为洞察：访问路径分析、偏好画像、转化漏斗' },
      { icon: BarChart3, text: '经营数据统计：订单趋势、营收分析、库存周转一目了然' },
    ],
  },
]

const supportingColorMap: Record<string, { bg: string; icon: string; border: string; badge: string; badgeText: string }> = {
  indigo: { bg: 'bg-indigo-50', icon: 'text-indigo-600', border: 'border-indigo-100 hover:border-indigo-200', badge: 'bg-indigo-50', badgeText: 'text-indigo-700' },
  green: { bg: 'bg-green-50', icon: 'text-green-600', border: 'border-green-100 hover:border-green-200', badge: 'bg-green-50', badgeText: 'text-green-700' },
  orange: { bg: 'bg-orange-50', icon: 'text-orange-600', border: 'border-orange-100 hover:border-orange-200', badge: 'bg-orange-50', badgeText: 'text-orange-700' },
}

export default function ServicesPage() {
  return (
    <>
      {/* Page Header */}
      <section className="relative bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800 text-white py-16 sm:py-20 overflow-hidden">
        <div
          className="absolute inset-0 opacity-10"
          style={{
            backgroundImage: 'radial-gradient(circle, rgba(255,255,255,0.8) 1px, transparent 1px)',
            backgroundSize: '24px 24px',
          }}
        />
        <div className="absolute -top-24 -right-24 w-80 h-80 bg-blue-400/15 rounded-full blur-3xl" />
        <div className="absolute -bottom-24 -left-24 w-64 h-64 bg-indigo-400/15 rounded-full blur-3xl" />

        <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 text-center">
          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight">
            产品与服务
          </h1>
          <p className="mt-4 text-lg sm:text-xl text-blue-100/90 max-w-2xl mx-auto leading-relaxed">
            双AI助手 + 全链路管理平台，为企业构建从内部运营到客户服务的智能闭环
          </p>
        </div>
      </section>

      {/* Core AI Products — Featured large cards */}
      <section className="py-20 sm:py-28 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <span className="text-sm font-semibold text-blue-600 uppercase tracking-wider">
              核心AI产品
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-gray-900">
              AI 双助手，一个对内提效，一个对外服务
            </h2>
            <p className="mt-4 text-lg text-gray-500 max-w-2xl mx-auto">
              米宝赋能企业运营，小布服务终端客户，双轮驱动业务增长
            </p>
          </div>

          <div className="space-y-12">
            {coreProducts.map((product, index) => (
              <div
                key={product.title}
                className={`group relative rounded-3xl border ${product.borderColor} bg-gradient-to-br ${product.bgGradient} p-8 sm:p-12 transition-all duration-300 ${product.shadowColor} hover:shadow-xl hover:-translate-y-1`}
              >
                {/* Glow accent */}
                <div className={`absolute top-0 right-0 w-64 h-64 bg-gradient-to-bl ${product.gradient} opacity-[0.04] rounded-bl-full pointer-events-none`} />

                <div className="relative flex flex-col lg:flex-row lg:items-start gap-8">
                  {/* Product header */}
                  <div className="lg:w-80 shrink-0">
                    <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-full ${product.badgeBg} ${product.badgeText} text-xs font-semibold mb-4`}>
                      <Sparkles className="w-3.5 h-3.5" />
                      AI 助手
                    </div>
                    <div className={`w-16 h-16 rounded-2xl bg-gradient-to-br ${product.iconBg} flex items-center justify-center mb-4`}>
                      <product.icon className={`w-8 h-8 ${product.iconText}`} />
                    </div>
                    <h2 className="text-2xl sm:text-3xl font-bold text-gray-900">
                      {product.title}
                    </h2>
                    <p className="mt-3 text-base text-gray-600 leading-relaxed">
                      {product.description}
                    </p>
                  </div>

                  {/* Feature list */}
                  <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {product.features.map((feature) => (
                      <div
                        key={feature.text}
                        className="flex items-start gap-3 p-4 bg-white/80 backdrop-blur-sm rounded-xl border border-white/60 hover:bg-white hover:shadow-sm transition-all duration-200"
                      >
                        <feature.icon className={`w-5 h-5 ${product.iconText} shrink-0 mt-0.5`} />
                        <span className="text-sm text-gray-700 leading-relaxed">
                          {feature.text}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Supporting Products — 3-column grid */}
      <section className="py-20 sm:py-28 bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <span className="text-sm font-semibold text-blue-600 uppercase tracking-wider">
              支撑产品
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-gray-900">
              全链路管理能力
            </h2>
            <p className="mt-4 text-lg text-gray-500 max-w-2xl mx-auto">
              从后台管理到客户触点，覆盖业务全场景
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {supportingProducts.map((product) => {
              const colors = supportingColorMap[product.color]
              return (
                <div
                  key={product.title}
                  className={`group bg-white rounded-2xl border ${colors.border} p-6 sm:p-8 transition-all duration-300 hover:shadow-lg hover:-translate-y-1`}
                >
                  <div className={`w-12 h-12 ${colors.bg} rounded-xl flex items-center justify-center mb-5 group-hover:scale-110 transition-transform duration-300`}>
                    <product.icon className={`w-6 h-6 ${colors.icon}`} />
                  </div>
                  <h3 className="text-xl font-bold text-gray-900 mb-2">
                    {product.title}
                  </h3>
                  <p className="text-sm text-gray-500 leading-relaxed mb-6">
                    {product.description}
                  </p>

                  <ul className="space-y-3">
                    {product.features.map((feature) => (
                      <li key={feature.text} className="flex items-start gap-2.5">
                        <feature.icon className={`w-4 h-4 ${colors.icon} shrink-0 mt-0.5`} />
                        <span className="text-sm text-gray-600 leading-relaxed">
                          {feature.text}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )
            })}
          </div>
        </div>
      </section>
    </>
  )
}
