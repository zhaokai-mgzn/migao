import Link from 'next/link'
import {
  Bot,
  MessageSquare,
  Package,
  ClipboardList,
  BookOpen,
  Sparkles,
  Brain,
  Smartphone,
  ShieldCheck,
  FileText,
  Search,
  Rocket,
} from 'lucide-react'

const features = [
  {
    icon: Bot,
    title: '米宝 · 企业智能助手',
    description: '您的专属AI工作搭档，智能处理商品管理、订单跟踪、库存盘点、售后协调，让日常运营事半功倍',
  },
  {
    icon: MessageSquare,
    title: '小布 · AI 智能客服',
    description: '7×24小时在线，基于大模型深度理解客户意图，智能应答产品咨询、物流追踪、售后问题',
  },
  {
    icon: Package,
    title: '商品管理',
    description: '一站式商品信息管理，支持行业特有属性配置，多维度分类检索，库存智能预警',
  },
  {
    icon: ClipboardList,
    title: '订单管理',
    description: '从下单到交付的全流程可视化管理，实时物流追踪，异常订单智能预警',
  },
  {
    icon: BookOpen,
    title: '知识库',
    description: 'AI自动学习商品知识与服务话术，持续进化，服务越用越精准',
  },
]

const advantages = [
  {
    icon: Sparkles,
    title: '双AI助手赋能',
    description: '为企业配备米宝工作助手 + 小布智能客服，内部提效与客户服务双轮驱动',
  },
  {
    icon: Brain,
    title: '大模型深度理解',
    description: '基于大语言模型，不是简单问答机器人，真正理解业务场景与客户需求',
  },
  {
    icon: Smartphone,
    title: '多渠道统一管理',
    description: '微信小程序、网页等多渠道接入，一个后台管理所有客户触点',
  },
  {
    icon: ShieldCheck,
    title: '数据安全可靠',
    description: '租户级数据隔离，独立数据空间，确保企业核心数据安全无虞',
  },
]

const steps = [
  {
    icon: FileText,
    step: '01',
    title: '提交申请',
    description: '填写企业信息，最快几分钟即可完成提交',
  },
  {
    icon: Search,
    step: '02',
    title: '平台审核',
    description: '1-3个工作日内完成审核，专人对接跟进',
  },
  {
    icon: Rocket,
    step: '03',
    title: '开通使用',
    description: '审核通过即刻获得管理后台与米宝AI助手，开启智能运营',
  },
]

export default function HomePage() {
  return (
    <>
      {/* Hero Section */}
      <section className="relative bg-gradient-to-br from-blue-600 to-blue-800 text-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-24 sm:py-32">
          <div className="text-center max-w-3xl mx-auto">
            <h1 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight leading-tight">
              AI 驱动的新一代
              <br />
              企业智能管理平台
            </h1>
            <p className="mt-6 text-lg sm:text-xl text-blue-100 leading-relaxed">
              米高 SaaS 平台，为每一位商家配备专属AI助手——米宝智能工作助手与小布智能客服，从内部运营到客户服务，全方位驱动业务增长。
            </p>
            <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link
                href="/register"
                className="w-full sm:w-auto px-8 py-3.5 text-base font-semibold bg-white text-blue-700 rounded-lg hover:bg-blue-50 transition-colors shadow-lg"
              >
                立即入驻
              </Link>
              <Link
                href="/services"
                className="w-full sm:w-auto px-8 py-3.5 text-base font-semibold border-2 border-white/30 text-white rounded-lg hover:bg-white/10 transition-colors"
              >
                了解更多
              </Link>
            </div>
          </div>
        </div>
        {/* Decorative bottom wave */}
        <div className="absolute bottom-0 left-0 right-0 h-16 bg-white" style={{ clipPath: 'ellipse(60% 100% at 50% 100%)' }} />
      </section>

      {/* Features Section */}
      <section className="py-20 sm:py-24 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <h2 className="text-2xl sm:text-3xl font-bold text-gray-900">
              功能亮点
            </h2>
            <p className="mt-4 text-gray-600">
              为企业量身打造的全方位智能电商管理平台
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-8">
            {features.map((feature) => (
              <div
                key={feature.title}
                className="p-6 rounded-xl border border-gray-100 hover:border-blue-100 hover:shadow-lg transition-all group"
              >
                <div className="w-12 h-12 bg-blue-50 rounded-lg flex items-center justify-center mb-4 group-hover:bg-blue-100 transition-colors">
                  <feature.icon className="w-6 h-6 text-blue-600" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900 mb-2">
                  {feature.title}
                </h3>
                <p className="text-sm text-gray-600 leading-relaxed">
                  {feature.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Advantages Section */}
      <section className="py-20 sm:py-24 bg-gray-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <h2 className="text-2xl sm:text-3xl font-bold text-gray-900">
              为什么选择米高
            </h2>
            <p className="mt-4 text-gray-600">
              不只是管理工具，更是您的AI智能运营伙伴
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-8 max-w-4xl mx-auto">
            {advantages.map((item) => (
              <div key={item.title} className="flex gap-4 p-6 bg-white rounded-xl shadow-sm">
                <div className="w-11 h-11 bg-blue-50 rounded-lg flex items-center justify-center shrink-0">
                  <item.icon className="w-5 h-5 text-blue-600" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-gray-900 mb-1">
                    {item.title}
                  </h3>
                  <p className="text-sm text-gray-600 leading-relaxed">
                    {item.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Steps Section */}
      <section className="py-20 sm:py-24 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <h2 className="text-2xl sm:text-3xl font-bold text-gray-900">
              入驻流程
            </h2>
            <p className="mt-4 text-gray-600">
              简单三步，开启AI赋能的智能运营之旅
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-4xl mx-auto">
            {steps.map((item, index) => (
              <div key={item.step} className="text-center relative">
                {index < steps.length - 1 && (
                  <div className="hidden md:block absolute top-10 left-[60%] w-[80%] h-0.5 bg-blue-100" />
                )}
                <div className="w-20 h-20 bg-blue-50 rounded-full flex items-center justify-center mx-auto mb-5">
                  <item.icon className="w-8 h-8 text-blue-600" />
                </div>
                <span className="text-xs font-bold text-blue-600 uppercase tracking-wider">
                  第{item.step}步
                </span>
                <h3 className="mt-2 text-lg font-semibold text-gray-900">
                  {item.title}
                </h3>
                <p className="mt-2 text-sm text-gray-600">
                  {item.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Bottom CTA */}
      <section className="py-20 sm:py-24 bg-gray-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 text-center">
          <h2 className="text-2xl sm:text-3xl font-bold text-gray-900">
            准备好让AI助手驱动您的业务增长了吗？
          </h2>
          <p className="mt-4 text-gray-600 max-w-xl mx-auto">
            立即入驻米高平台，获取专属米宝智能工作助手，开启高效运营新时代
          </p>
          <Link
            href="/register"
            className="mt-8 inline-block px-8 py-3.5 text-base font-semibold text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors shadow-sm"
          >
            立即入驻
          </Link>
        </div>
      </section>
    </>
  )
}
