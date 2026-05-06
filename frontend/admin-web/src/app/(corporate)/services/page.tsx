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

const products = [
  {
    title: '米宝 · 企业智能工作助手',
    description: '面向企业员工的AI工作搭档，深度融入日常运营，自然语言交互即可完成复杂业务操作',
    icon: Sparkles,
    color: 'purple',
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
    color: 'blue',
    features: [
      { icon: Wrench, text: '基于通义千问大语言模型，深度理解自然语言语义' },
      { icon: MessageCircle, text: '多轮对话与上下文记忆，对话自然流畅有温度' },
      { icon: Zap, text: '智能工具调用：商品查询、物流追踪、知识库检索一键触达' },
      { icon: Radio, text: 'SSE 流式响应，实时打字机效果，交互体验极佳' },
    ],
  },
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

const colorMap: Record<string, { bg: string; icon: string; border: string }> = {
  purple: { bg: 'bg-purple-50', icon: 'text-purple-600', border: 'border-purple-100' },
  blue: { bg: 'bg-blue-50', icon: 'text-blue-600', border: 'border-blue-100' },
  indigo: { bg: 'bg-indigo-50', icon: 'text-indigo-600', border: 'border-indigo-100' },
  green: { bg: 'bg-green-50', icon: 'text-green-600', border: 'border-green-100' },
  orange: { bg: 'bg-orange-50', icon: 'text-orange-600', border: 'border-orange-100' },
}

export default function ServicesPage() {
  return (
    <>
      {/* Page Header */}
      <section className="bg-gradient-to-br from-blue-600 to-blue-800 text-white py-16 sm:py-20">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 text-center">
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight">
            产品与服务
          </h1>
          <p className="mt-4 text-lg text-blue-100 max-w-2xl mx-auto">
            双AI助手 + 全链路管理平台，为企业构建从内部运营到客户服务的智能闭环
          </p>
        </div>
      </section>

      {/* Products */}
      <section className="py-20 sm:py-24">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 space-y-16">
          {products.map((product, index) => {
            const colors = colorMap[product.color]
            return (
              <div
                key={product.title}
                className={`rounded-2xl border ${colors.border} p-8 sm:p-10 ${index % 2 === 0 ? 'bg-white' : 'bg-gray-50'}`}
              >
                <div className="flex items-start gap-5 mb-8">
                  <div className={`w-14 h-14 ${colors.bg} rounded-xl flex items-center justify-center shrink-0`}>
                    <product.icon className={`w-7 h-7 ${colors.icon}`} />
                  </div>
                  <div>
                    <h2 className="text-xl sm:text-2xl font-bold text-gray-900">
                      {product.title}
                    </h2>
                    <p className="mt-2 text-gray-600">
                      {product.description}
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {product.features.map((feature) => (
                    <div
                      key={feature.text}
                      className="flex items-start gap-3 p-4 bg-white rounded-lg border border-gray-100"
                    >
                      <feature.icon className={`w-5 h-5 ${colors.icon} shrink-0 mt-0.5`} />
                      <span className="text-sm text-gray-700 leading-relaxed">
                        {feature.text}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </section>
    </>
  )
}
