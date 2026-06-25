import type { Metadata } from 'next'
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
  ArrowRight,
  Check,
} from 'lucide-react'

export const metadata: Metadata = {
  title: '米高 — AI驱动的新一代企业智能管理平台',
  description:
    '米高SaaS平台为每一位商家配备专属AI助手——米宝智能工作助手与小布智能客服，从内部运营到客户服务，全方位驱动业务增长。',
}

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

const partnerLogos = [
  { name: '品牌 A', letter: 'A' },
  { name: '品牌 B', letter: 'B' },
  { name: '品牌 C', letter: 'C' },
  { name: '品牌 D', letter: 'D' },
  { name: '品牌 E', letter: 'E' },
  { name: '品牌 F', letter: 'F' },
]

export default function HomePage() {
  return (
    <>
      {/* Hero Section */}
      <section className="relative bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800 text-white overflow-hidden">
        {/* Decorative gradient blobs */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute -top-40 -right-40 w-96 h-96 bg-blue-400/20 rounded-full blur-3xl" />
          <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-indigo-400/20 rounded-full blur-3xl" />
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[600px] h-[600px] bg-gradient-to-br from-blue-300/10 to-purple-300/10 rounded-full blur-2xl" />
        </div>

        <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-24 sm:py-32 lg:py-36">
          <div className="text-center max-w-3xl mx-auto">
            {/* Badge */}
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-white/15 backdrop-blur-sm border border-white/20 text-sm text-blue-100 mb-8">
              <Sparkles className="w-4 h-4" />
              <span>AI 赋能的智能电商管理平台</span>
            </div>

            <h1 className="text-3xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight leading-tight">
              AI 驱动的新一代
              <br />
              <span className="bg-gradient-to-r from-white via-blue-100 to-blue-200 bg-clip-text text-transparent">
                企业智能管理平台
              </span>
            </h1>
            <p className="mt-6 text-lg sm:text-xl text-blue-100/90 leading-relaxed max-w-2xl mx-auto">
              米高 SaaS 平台，为每一位商家配备专属AI助手——米宝智能工作助手与小布智能客服，从内部运营到客户服务，全方位驱动业务增长。
            </p>
            <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link
                href="/register"
                className="group w-full sm:w-auto inline-flex items-center gap-2 px-8 py-4 text-base font-semibold bg-white text-blue-700 rounded-xl hover:bg-blue-50 hover:shadow-xl transition-all duration-300"
              >
                立即入驻
                <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
              </Link>
              <Link
                href="/services"
                className="w-full sm:w-auto px-8 py-4 text-base font-semibold border-2 border-white/30 text-white rounded-xl hover:bg-white/10 hover:border-white/50 transition-all duration-300"
              >
                了解更多
              </Link>
            </div>
          </div>
        </div>

        {/* Decorative bottom wave */}
        <div className="absolute bottom-0 left-0 right-0">
          <svg
            viewBox="0 0 1440 120"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className="w-full h-auto"
            preserveAspectRatio="none"
          >
            <path d="M0 120V60C240 0 480 0 720 30C960 60 1200 60 1440 30V120H0Z" fill="white" />
          </svg>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-20 sm:py-28 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <span className="text-sm font-semibold text-blue-600 uppercase tracking-wider">
              功能亮点
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-gray-900">
              为企业量身打造的全方位智能管理平台
            </h2>
            <p className="mt-4 text-lg text-gray-500">
              五大核心模块，覆盖企业运营全流程
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-6">
            {features.map((feature, index) => (
              <div
                key={feature.title}
                className="group relative p-6 rounded-2xl border border-gray-100 bg-white hover:border-blue-200 hover:shadow-xl hover:shadow-blue-50 transition-all duration-300 hover:-translate-y-1"
              >
                {/* Gradient accent line on top */}
                <div className="absolute top-0 left-4 right-4 h-0.5 bg-gradient-to-r from-blue-400 to-indigo-400 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                <div className="w-12 h-12 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl flex items-center justify-center mb-4 group-hover:from-blue-100 group-hover:to-indigo-100 group-hover:scale-110 transition-all duration-300">
                  <feature.icon className="w-6 h-6 text-blue-600" />
                </div>
                <h3 className="text-base font-semibold text-gray-900 mb-2 leading-snug">
                  {feature.title}
                </h3>
                <p className="text-sm text-gray-500 leading-relaxed">
                  {feature.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Advantages Section */}
      <section className="py-20 sm:py-28 bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <span className="text-sm font-semibold text-blue-600 uppercase tracking-wider">
              为什么选择米高
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-gray-900">
              不只是管理工具，更是您的AI智能运营伙伴
            </h2>
            <p className="mt-4 text-lg text-gray-500">
              四大核心优势，构建企业智能中枢
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-5xl mx-auto">
            {advantages.map((item, index) => (
              <div
                key={item.title}
                className="group flex gap-5 p-6 bg-white rounded-2xl border border-gray-100 hover:border-blue-100 hover:shadow-lg transition-all duration-300"
              >
                <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-blue-600 rounded-xl flex items-center justify-center shrink-0 group-hover:from-blue-600 group-hover:to-indigo-600 transition-all duration-300 shadow-sm shadow-blue-200">
                  <item.icon className="w-5 h-5 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-base font-semibold text-gray-900 mb-1.5 flex items-center gap-2">
                    {item.title}
                    <Check className="w-4 h-4 text-blue-500 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </h3>
                  <p className="text-sm text-gray-500 leading-relaxed">
                    {item.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Steps Section */}
      <section className="py-20 sm:py-28 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <span className="text-sm font-semibold text-blue-600 uppercase tracking-wider">
              入驻流程
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-gray-900">
              简单三步，开启AI赋能的智能运营之旅
            </h2>
            <p className="mt-4 text-lg text-gray-500">
              从申请到开通，最快当天即可体验
            </p>
          </div>
          <div className="relative max-w-4xl mx-auto">
            {/* Connecting line (desktop) */}
            <div className="hidden md:block absolute top-14 left-[calc(16.67%+40px)] right-[calc(16.67%+40px)]">
              <div className="relative h-0.5">
                <div className="absolute inset-0 bg-gradient-to-r from-blue-200 via-blue-400 to-blue-200" />
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-blue-400 rounded-full" />
                <div className="absolute right-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-blue-400 rounded-full" />
                {/* Arrow heads */}
                <div className="absolute left-1/2 top-1/2 -translate-y-1/2 -translate-x-1/2">
                  <ArrowRight className="w-4 h-4 text-blue-400" />
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-12">
              {steps.map((item, index) => (
                <div key={item.step} className="text-center relative group">
                  {/* Step number circle */}
                  <div className="relative w-28 h-28 mx-auto mb-6">
                    <div className="absolute inset-0 bg-gradient-to-br from-blue-400 to-blue-600 rounded-full opacity-0 group-hover:opacity-100 blur-md transition-opacity duration-300" />
                    <div className="relative w-full h-full bg-gradient-to-br from-blue-50 to-indigo-50 rounded-full flex flex-col items-center justify-center border-2 border-blue-100 group-hover:border-blue-300 group-hover:shadow-lg group-hover:shadow-blue-100 transition-all duration-300">
                      <item.icon className="w-8 h-8 text-blue-600 mb-1" />
                      <span className="text-xs font-bold text-blue-500">{item.step}</span>
                    </div>
                  </div>

                  <span className="inline-block px-3 py-1 rounded-full bg-blue-50 text-xs font-bold text-blue-600 uppercase tracking-wider">
                    第{item.step}步
                  </span>
                  <h3 className="mt-3 text-lg font-semibold text-gray-900">
                    {item.title}
                  </h3>
                  <p className="mt-2 text-sm text-gray-500 leading-relaxed max-w-xs mx-auto">
                    {item.description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Partners / Brands Section */}
      <section className="py-20 sm:py-28 bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <span className="text-sm font-semibold text-blue-600 uppercase tracking-wider">
              合作品牌
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-gray-900">
              众多品牌信赖之选
            </h2>
            <p className="mt-4 text-lg text-gray-500">
              越来越多的品牌商家正在使用米高智能管理平台
            </p>
          </div>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-6 max-w-4xl mx-auto">
            {partnerLogos.map((partner, index) => (
              <div
                key={partner.name}
                className="group aspect-[3/2] bg-white rounded-xl border border-gray-100 hover:border-blue-200 hover:shadow-md flex items-center justify-center transition-all duration-300 hover:-translate-y-0.5"
              >
                <div className="text-center">
                  <div className="w-10 h-10 mx-auto mb-1.5 rounded-lg bg-gradient-to-br from-slate-100 to-slate-200 group-hover:from-blue-50 group-hover:to-indigo-50 flex items-center justify-center transition-all duration-300">
                    <span className="text-sm font-bold text-slate-400 group-hover:text-blue-500 transition-colors">
                      {partner.letter}
                    </span>
                  </div>
                  <span className="text-xs text-slate-400 group-hover:text-slate-500 transition-colors">
                    {partner.name}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Bottom CTA */}
      <section className="relative py-20 sm:py-28 bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800 text-white overflow-hidden">
        {/* Background decorative circles */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-10 right-10 w-64 h-64 bg-blue-400/10 rounded-full blur-3xl" />
          <div className="absolute bottom-10 left-10 w-48 h-48 bg-indigo-400/10 rounded-full blur-3xl" />
        </div>

        <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 text-center">
          <h2 className="text-3xl sm:text-4xl font-bold">
            准备好让AI助手驱动您的业务增长了吗？
          </h2>
          <p className="mt-4 text-lg text-blue-100/90 max-w-xl mx-auto leading-relaxed">
            立即入驻米高平台，获取专属米宝智能工作助手，开启高效运营新时代
          </p>
          <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/register"
              className="group inline-flex items-center gap-2 px-8 py-4 text-base font-semibold bg-white text-blue-700 rounded-xl hover:bg-blue-50 hover:shadow-xl transition-all duration-300"
            >
              立即入驻
              <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5 transition-transform" />
            </Link>
            <Link
              href="/contact"
              className="px-8 py-4 text-base font-semibold border-2 border-white/30 text-white rounded-xl hover:bg-white/10 hover:border-white/50 transition-all duration-300"
            >
              咨询顾问
            </Link>
          </div>
        </div>
      </section>
    </>
  )
}
