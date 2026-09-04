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
  Zap,
  Rocket,
  ArrowRight,
  Check,
  Factory,
  Sofa,
  Shirt,
  ShoppingBag,
  Landmark,
  BadgeCheck,
} from 'lucide-react'

export const metadata: Metadata = {
  title: '米高 — AI驱动的新一代企业智能管理平台',
  description:
    '杭州词元通达科技有限公司出品的米高智能管理平台，为每位商家配备双AI助手——米宝企业智能工作助手与小布智能客服。从内部运营到客户服务，AI 自动甄别入驻，秒级开通，全方位驱动业务增长。',
}

const agents = [
  {
    icon: Bot,
    name: '米宝',
    role: '企业智能工作助手',
    description:
      '您的专属AI工作搭档，7×24小时在线处理商品管理、订单跟踪、库存盘点、售后协调，把运营人员从重复劳动中解放出来，让日常经营事半功倍。',
    highlights: ['商品 · 订单 · 库存智能管理', '售后协调与异常预警', '经营数据即问即答'],
  },
  {
    icon: MessageSquare,
    name: '小布',
    role: 'AI 智能客服',
    description:
      '面向您客户的7×24小时AI客服，基于大模型深度理解客户意图，智能应答产品咨询、物流追踪、退换货等问题，大幅降低客服成本，提升客户满意度。',
    highlights: ['微信小程序等多渠道接入', '商品·订单·物流实时查询应答', '自动判断复杂诉求，转人工客服兜底'],
  },
]

const features = [
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
    description:
      '支持企业上传与管理产品知识、服务话术，AI 应答基于实时业务数据，不编造事实（知识库检索能力按版本开放）',
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
    description: '填写企业信息并完成手机验证，全程仅需几分钟',
  },
  {
    icon: Zap,
    step: '02',
    title: 'AI 智能甄别',
    description: 'AI 自动核验企业信息与合规性，秒级返回审核结果，无需人工等待',
  },
  {
    icon: Rocket,
    step: '03',
    title: '即刻开通',
    description: '审核通过即刻获得管理后台、米宝助手与小布客服，开启智能运营',
  },
]

const industries = [
  { icon: Factory, name: '布艺纺织' },
  { icon: Sofa, name: '家居建材' },
  { icon: Shirt, name: '服装服饰' },
  { icon: ShoppingBag, name: '电商零售' },
]

const trustPoints = [
  {
    icon: BadgeCheck,
    title: 'AI 自动合规甄别',
    description: '入驻申请由 AI 自动审查，合法合规、无敏感信息即刻通过',
  },
  {
    icon: Landmark,
    title: '正规运营主体',
    description: '杭州词元通达科技有限公司，为您提供长期稳定的产品服务',
  },
  {
    icon: ShieldCheck,
    title: '多重风控防护',
    description: '租户级数据隔离、防重复提交与恶意刷量防护，平台安全合规',
  },
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
              <span>杭州词元通达科技有限公司 · 双 AI 助手智能管理平台</span>
            </div>

            <h1 className="text-3xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight leading-tight">
              米宝 × 小布
              <br />
              <span className="bg-gradient-to-r from-white via-blue-100 to-blue-200 bg-clip-text text-transparent">
                AI 员工 × AI 客服
              </span>
            </h1>
            <p className="mt-6 text-lg sm:text-xl text-blue-100/90 leading-relaxed max-w-2xl mx-auto">
              米宝替您打理内部——订单、库存、售后件件有着落；小布替您接待客户——咨询、物流、退换样样有回应。
              入驻由 AI 自动甄别，合规即刻开通，最快几分钟就能让生意跑起来。
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

      {/* 双 Agent Section */}
      <section className="py-20 sm:py-28 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <span className="text-sm font-semibold text-primary-600 uppercase tracking-wider">
              双 AI 助手
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-neutral-900">
              一位管好内部运营，一位服务您的客户
            </h2>
            <p className="mt-4 text-lg text-neutral-500">
              米宝 + 小布，两大 AI 助手协同，为您的生意全程护航
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-5xl mx-auto">
            {agents.map((agent, index) => (
              <div
                key={agent.name}
                className="group relative p-8 rounded-2xl border border-neutral-100 bg-gradient-to-br from-slate-50 to-white hover:border-blue-200 hover:shadow-xl hover:shadow-blue-50 transition-all duration-300 hover:-translate-y-1"
              >
                <div className="absolute top-0 left-4 right-4 h-0.5 bg-gradient-to-r from-blue-400 to-indigo-400 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                <div className="flex items-center gap-4 mb-5">
                  <div className="w-14 h-14 bg-gradient-to-br from-primary-500 to-primary-600 rounded-2xl flex items-center justify-center shadow-sm shadow-blue-200">
                    <agent.icon className="w-7 h-7 text-white" />
                  </div>
                  <div>
                    <h3 className="text-xl font-bold text-neutral-900">
                      {agent.name}
                      <span className="ml-2 text-sm font-medium text-primary-600">{agent.role}</span>
                    </h3>
                  </div>
                </div>
                <p className="text-sm text-neutral-500 leading-relaxed mb-5">
                  {agent.description}
                </p>
                <ul className="space-y-2">
                  {agent.highlights.map((item) => (
                    <li key={item} className="flex items-center gap-2 text-sm text-neutral-600">
                      <Check className="w-4 h-4 text-blue-500 shrink-0" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 国家标准合规宣称 Section（GB/T 47746-2026，issue #2787） */}
      <section className="py-20 sm:py-28 bg-gradient-to-b from-white via-blue-50/40 to-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <span className="text-sm font-semibold text-primary-600 uppercase tracking-wider">
              遵循国家标准
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-neutral-900">
              让人工与智能客服协同更可靠
            </h2>
            <p className="mt-4 text-lg text-neutral-500">
              对标推荐性国标 <span className="font-semibold text-neutral-700">GB/T 47746-2026</span>
              《顾客联络服务 人工与智能客户服务协同要求》（2026-09-01 实施），设计顾客服务协同机制
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-5xl mx-auto">
            {[
              {
                icon: Sparkles,
                title: '自动识别复杂诉求转人工',
                description: '情绪化、多轮未解决、涉赔偿/法律等超范围诉求，AI 自动建议或直接转接人工客服——先 AI 应答，人工兜底。',
              },
              {
                icon: Zap,
                title: '转人工规则可配置',
                description: '顾客可直接提出转人工，商家还可自定义触发关键词，转接规则随业务灵活调整。',
              },
              {
                icon: MessageSquare,
                title: '转人工即同步上下文',
                description: '转人工后自动创建人工会话与工单并通知坐席，顾客与 AI 的沟通记录同步给人工客服，无需重复描述；原对话即可继续沟通（非营业时间自动转为留言）。',
              },
              {
                icon: ShieldCheck,
                title: 'AI 严格承诺边界',
                description: '涉及价格、折扣、退款金额等敏感事项，AI 只做规则解释与材料收集，申请类动作一律待人工客服或规范流程审核确认。',
              },
            ].map((item, index) => (
              <div
                key={item.title}
                className="group flex gap-4 p-6 bg-white rounded-2xl border border-neutral-100 hover:border-blue-200 hover:shadow-lg hover:shadow-blue-50 transition-all duration-300"
              >
                <div className="w-11 h-11 bg-gradient-to-br from-primary-500 to-primary-600 rounded-xl flex items-center justify-center shrink-0 shadow-sm shadow-blue-200">
                  <item.icon className="w-5 h-5 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-base font-semibold text-neutral-900 mb-1.5">
                    {item.title}
                  </h3>
                  <p className="text-sm text-neutral-500 leading-relaxed">
                    {item.description}
                  </p>
                </div>
              </div>
            ))}
          </div>

          <p className="mt-10 text-center text-xs text-neutral-400 max-w-3xl mx-auto leading-relaxed">
            「遵循/对标 GB/T 47746-2026」指小布智能客服的人机协同机制功能设计参考该推荐性国家标准；
            该标准为推荐性标准、无认证或备案机制，本页面不构成任何认证、检测或备案结论。
          </p>
        </div>
      </section>

      {/* Features Section */}
      <section className="py-20 sm:py-28 bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <span className="text-sm font-semibold text-primary-600 uppercase tracking-wider">
              核心能力
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-neutral-900">
              覆盖企业经营全流程的智能模块
            </h2>
            <p className="mt-4 text-lg text-neutral-500">
              商品、订单、知识库三大模块，配合双 AI 助手高效运转
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 max-w-4xl mx-auto">
            {features.map((feature, index) => (
              <div
                key={feature.title}
                className="group relative p-6 rounded-2xl border border-neutral-100 bg-white hover:border-blue-200 hover:shadow-xl hover:shadow-blue-50 transition-all duration-300 hover:-translate-y-1"
              >
                {/* Gradient accent line on top */}
                <div className="absolute top-0 left-4 right-4 h-0.5 bg-gradient-to-r from-blue-400 to-indigo-400 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                <div className="w-12 h-12 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl flex items-center justify-center mb-4 group-hover:from-blue-100 group-hover:to-indigo-100 group-hover:scale-110 transition-all duration-300">
                  <feature.icon className="w-6 h-6 text-primary-600" />
                </div>
                <h3 className="text-base font-semibold text-neutral-900 mb-2 leading-snug">
                  {feature.title}
                </h3>
                <p className="text-sm text-neutral-500 leading-relaxed">
                  {feature.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Advantages Section */}
      <section className="py-20 sm:py-28 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <span className="text-sm font-semibold text-primary-600 uppercase tracking-wider">
              为什么选择米高
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-neutral-900">
              不只是管理工具，更是您的AI智能运营伙伴
            </h2>
            <p className="mt-4 text-lg text-neutral-500">
              四大核心优势，构建企业智能中枢
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-5xl mx-auto">
            {advantages.map((item, index) => (
              <div
                key={item.title}
                className="group flex gap-5 p-6 bg-slate-50 rounded-2xl border border-neutral-100 hover:border-blue-100 hover:shadow-lg transition-all duration-300"
              >
                <div className="w-12 h-12 bg-gradient-to-br from-primary-500 to-primary-600 rounded-xl flex items-center justify-center shrink-0 group-hover:from-blue-600 group-hover:to-indigo-600 transition-all duration-300 shadow-sm shadow-blue-200">
                  <item.icon className="w-5 h-5 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-base font-semibold text-neutral-900 mb-1.5 flex items-center gap-2">
                    {item.title}
                    <Check className="w-4 h-4 text-blue-500 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
                  </h3>
                  <p className="text-sm text-neutral-500 leading-relaxed">
                    {item.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Steps Section */}
      <section className="py-20 sm:py-28 bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <span className="text-sm font-semibold text-primary-600 uppercase tracking-wider">
              入驻流程
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-neutral-900">
              三步开启，AI 秒审即刻上线
            </h2>
            <p className="mt-4 text-lg text-neutral-500">
              提交申请后由 AI 自动甄别，无需等待人工审核
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
                    <div className="absolute inset-0 bg-gradient-to-br from-blue-400 to-primary-600 rounded-full opacity-0 group-hover:opacity-100 blur-md transition-opacity duration-300" />
                    <div className="relative w-full h-full bg-gradient-to-br from-blue-50 to-indigo-50 rounded-full flex flex-col items-center justify-center border-2 border-blue-100 group-hover:border-blue-300 group-hover:shadow-lg group-hover:shadow-blue-100 transition-all duration-300">
                      <item.icon className="w-8 h-8 text-primary-600 mb-1" />
                      <span className="text-xs font-bold text-blue-500">{item.step}</span>
                    </div>
                  </div>

                  <span className="inline-block px-3 py-1 rounded-full bg-blue-50 text-xs font-bold text-primary-600 uppercase tracking-wider">
                    第{item.step}步
                  </span>
                  <h3 className="mt-3 text-lg font-semibold text-neutral-900">
                    {item.title}
                  </h3>
                  <p className="mt-2 text-sm text-neutral-500 leading-relaxed max-w-xs mx-auto">
                    {item.description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* 适用行业 & 合规保障 Section */}
      <section className="py-20 sm:py-28 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <span className="text-sm font-semibold text-primary-600 uppercase tracking-wider">
              适用行业与合规保障
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-neutral-900">
              面向多行业商家，安全合规地智能升级
            </h2>
            <p className="mt-4 text-lg text-neutral-500">
              源自布艺纺织行业实践，服务各类成长型商家
            </p>
          </div>

          {/* 适用行业 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6 max-w-3xl mx-auto mb-16">
            {industries.map((industry, index) => (
              <div
                key={industry.name}
                className="group aspect-[3/2] bg-slate-50 rounded-xl border border-neutral-100 hover:border-blue-200 hover:shadow-md flex items-center justify-center transition-all duration-300 hover:-translate-y-0.5"
              >
                <div className="text-center">
                  <div className="w-10 h-10 mx-auto mb-1.5 rounded-lg bg-gradient-to-br from-slate-100 to-slate-200 group-hover:from-blue-50 group-hover:to-indigo-50 flex items-center justify-center transition-all duration-300">
                    <industry.icon className="w-5 h-5 text-slate-400 group-hover:text-blue-500 transition-colors" />
                  </div>
                  <span className="text-xs text-slate-500 group-hover:text-neutral-700 transition-colors">
                    {industry.name}
                  </span>
                </div>
              </div>
            ))}
          </div>

          {/* 合规保障 */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-5xl mx-auto">
            {trustPoints.map((point, index) => (
              <div
                key={point.title}
                className="group flex gap-4 p-6 bg-white rounded-2xl border border-neutral-100 hover:border-blue-100 hover:shadow-lg transition-all duration-300"
              >
                <div className="w-11 h-11 bg-gradient-to-br from-primary-500 to-primary-600 rounded-xl flex items-center justify-center shrink-0 shadow-sm shadow-blue-200">
                  <point.icon className="w-5 h-5 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-base font-semibold text-neutral-900 mb-1">
                    {point.title}
                  </h3>
                  <p className="text-sm text-neutral-500 leading-relaxed">
                    {point.description}
                  </p>
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
            立即入驻米高平台，AI 自动甄别秒级通过，即刻获取米宝工作助手与小布智能客服
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
