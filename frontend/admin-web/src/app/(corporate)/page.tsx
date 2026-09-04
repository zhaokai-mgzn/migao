import type { Metadata } from 'next'
import Link from 'next/link'
import {
  Bot,
  MessageSquare,
  Package,
  ClipboardList,
  BookOpen,
  Sparkles,
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
    '米高为企业提供 AI 客服与经营平台：小布 7×24 应答客户咨询、复杂诉求自动转人工，米宝处理订单、库存、售后并提供经营数据问答；AI 自动甄别入驻、秒级开通，人机协同参考 GB/T 47746-2026 设计。',
}

const heroFacts = [
  'AI 自动甄别 · 秒级开通',
  '参考 GB/T 47746-2026 人机协同设计',
  '租户级数据隔离',
  '微信小程序等多渠道接入',
]

const agents = [
  {
    icon: Bot,
    name: '米宝',
    role: '企业智能工作助手',
    brief: '7×24 处理商品、订单、库存与售后的日常事务。',
    highlights: [
      '商品管理：行业特有属性、多规格与检索',
      '订单跟踪与异常提醒',
      '库存盘点与智能预警',
      '售后协调与跟进',
      '经营数据即问即答',
    ],
  },
  {
    icon: MessageSquare,
    name: '小布',
    role: 'AI 智能客服',
    brief: '7×24 接待客户咨询，应答商品、订单、物流与退换问题。',
    highlights: [
      '商品、价格与优惠咨询应答',
      '订单进度与物流实时查询',
      '退换货引导与处理',
      '微信小程序等多渠道接入',
      '复杂诉求自动转人工，上下文随行',
    ],
  },
]

const workFlow = [
  { step: '01', title: '客户咨询', description: '顾客通过微信小程序或网页发起咨询' },
  { step: '02', title: '小布 AI 应答', description: '商品、订单、物流、退换实时应答' },
  { step: '03', title: '自动转人工', description: '识别复杂诉求，或顾客主动要求转人工' },
  { step: '04', title: '人工接续', description: '自动创建会话与工单，上下文同步，无需重复描述' },
  { step: '05', title: '留言兜底', description: '非营业时间留言，人工上班后接续处理' },
]

const compareRows = [
  { dim: '服务时间', manual: '上班时间，节假日难覆盖', robot: '可 7×24，但答不了业务细节', migao: '7×24，大模型理解业务' },
  { dim: '复杂诉求', manual: '能处理，人力成本高', robot: '常答非所问，需人工介入', migao: '自动转人工 + 上下文同步' },
  { dim: '店内经营数据', manual: '靠人工翻系统', robot: '无法接入业务数据', migao: 'AI 即问即答' },
  { dim: '上线与成本', manual: '招聘、培训、按月发薪', robot: '接入简单，效果有限', migao: '分钟级开通，按年订阅' },
  { dim: '敏感事项边界', manual: '靠制度约束', robot: '缺少边界设计', migao: '敏感事项 AI 不做决定，转人工确认' },
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

const industries = [
  { icon: Factory, name: '布艺纺织', note: '定制规格多，询价与计价繁琐' },
  { icon: Sofa, name: '家居建材', note: '产品参数多，需专业应答' },
  { icon: Shirt, name: '服装服饰', note: '上新快、退换咨询高频' },
  { icon: ShoppingBag, name: '电商零售', note: '私域询单集中，需统一管理' },
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
    description: '开通即获得管理后台与两位 AI，7×24 即刻开始工作',
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

        <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 pt-24 pb-48 sm:pt-32 sm:pb-56 lg:pt-36 lg:pb-60">
          <div className="text-center max-w-4xl mx-auto">
            {/* Badge */}
            <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-white/15 backdrop-blur-sm border border-white/20 text-sm text-blue-100 mb-8">
              <Sparkles className="w-4 h-4" />
              <span>杭州词元通达科技有限公司 · 企业级 AI 客服与经营平台</span>
            </div>

            <h1 className="text-3xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight leading-tight">
              7×24 客服在线
              <br />
              <span className="bg-gradient-to-r from-white via-blue-100 to-blue-200 bg-clip-text text-transparent">
                经营数据一问即答
              </span>
            </h1>
            <p className="mt-6 text-lg sm:text-xl text-blue-100/90 leading-relaxed max-w-3xl mx-auto">
              米宝——企业 AI 工作助手：7×24 处理商品、订单、库存与售后；小布——AI 智能客服：7×24 应答咨询、物流与退换，复杂诉求自动转人工。
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

            {/* Factual trust chips */}
            <div className="mt-14 flex flex-wrap items-center justify-center gap-3">
              {heroFacts.map((item) => (
                <span
                  key={item}
                  className="inline-flex items-center rounded-xl bg-white/10 backdrop-blur-sm border border-white/15 px-4 py-2 text-sm text-blue-50"
                >
                  {item}
                </span>
              ))}
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

      {/* 产品区：米宝与小布 */}
      <section className="py-20 sm:py-28 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <span className="text-sm font-semibold text-primary-600 uppercase tracking-wider">
              米宝 · 小布
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-neutral-900">
              一位打理店内经营，一位接待您的客户
            </h2>
            <p className="mt-4 text-lg text-neutral-500">
              两位 AI 均基于大语言模型理解业务意图，7×24 在岗，共用同一业务数据后台。
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8 max-w-5xl mx-auto">
            {agents.map((agent) => (
              <div
                key={agent.name}
                className="group relative p-8 rounded-2xl border border-neutral-100 bg-gradient-to-br from-slate-50 to-white hover:border-blue-200 hover:shadow-xl hover:shadow-blue-50 transition-all duration-300 hover:-translate-y-1"
              >
                <div className="absolute top-0 left-4 right-4 h-0.5 bg-gradient-to-r from-blue-400 to-indigo-400 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                <div className="flex items-center gap-4 mb-4">
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
                <p className="text-sm text-neutral-600 mb-5">{agent.brief}</p>
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

      {/* 人机协同工作流程 */}
      <section className="py-20 sm:py-28 bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <span className="text-sm font-semibold text-primary-600 uppercase tracking-wider">
              人机协同
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-neutral-900">
              AI 先应答，人工来兜底
            </h2>
            <p className="mt-4 text-lg text-neutral-500">
              日常咨询由小布直接解决；复杂诉求自动转人工，会话记录与上下文随行，顾客无需重复描述。（协同机制参考推荐性国标 GB/T 47746-2026 设计）
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 max-w-6xl mx-auto">
            {workFlow.map((item) => (
              <div
                key={item.step}
                className="group p-5 rounded-2xl border border-neutral-100 bg-white hover:border-blue-200 hover:shadow-lg hover:shadow-blue-50 transition-all duration-300"
              >
                <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-50 to-indigo-50 border-2 border-blue-100 flex items-center justify-center mb-3">
                  <span className="text-sm font-bold text-blue-500">{item.step}</span>
                </div>
                <h3 className="text-base font-semibold text-neutral-900 mb-1.5">{item.title}</h3>
                <p className="text-sm text-neutral-500 leading-relaxed">{item.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 对比表 */}
      <section className="py-20 sm:py-28 bg-white">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-12">
            <span className="text-sm font-semibold text-primary-600 uppercase tracking-wider">
              为什么不同
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-neutral-900">
              和自招客服、普通问答机器人差在哪
            </h2>
            <p className="mt-4 text-lg text-neutral-500">同一笔预算，可以这样对比。</p>
          </div>
          <div className="overflow-x-auto rounded-2xl border border-neutral-100">
            <table className="w-full min-w-[720px] text-sm bg-white">
              <thead>
                <tr className="bg-slate-50 border-b border-neutral-100">
                  <th className="text-left px-6 py-4 font-semibold text-neutral-500">对比维度</th>
                  <th className="text-left px-6 py-4 font-semibold text-neutral-700">自招人工客服</th>
                  <th className="text-left px-6 py-4 font-semibold text-neutral-700">普通客服机器人</th>
                  <th className="text-left px-6 py-4 font-semibold text-primary-600">米高（AI 客服 + 经营助手）</th>
                </tr>
              </thead>
              <tbody>
                {compareRows.map((row) => (
                  <tr key={row.dim} className="border-b border-neutral-50 last:border-0">
                    <td className="px-6 py-4 font-medium text-neutral-900 whitespace-nowrap">{row.dim}</td>
                    <td className="px-6 py-4 text-neutral-500">{row.manual}</td>
                    <td className="px-6 py-4 text-neutral-500">{row.robot}</td>
                    <td className="px-6 py-4 text-neutral-800 font-medium">{row.migao}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* 平台模块 */}
      <section className="py-20 sm:py-28 bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <span className="text-sm font-semibold text-primary-600 uppercase tracking-wider">
              管理后台
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-neutral-900">
              商品、订单、知识库，一个后台统一管理
            </h2>
            <p className="mt-4 text-lg text-neutral-500">
              两位 AI 与人工共用同一份业务数据；支持行业特有属性配置、多维度检索与库存智能预警。
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 max-w-4xl mx-auto">
            {features.map((feature) => (
              <div
                key={feature.title}
                className="group relative p-6 rounded-2xl border border-neutral-100 bg-white hover:border-blue-200 hover:shadow-xl hover:shadow-blue-50 transition-all duration-300 hover:-translate-y-1"
              >
                <div className="absolute top-0 left-4 right-4 h-0.5 bg-gradient-to-r from-blue-400 to-indigo-400 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                <div className="w-12 h-12 bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl flex items-center justify-center mb-4 group-hover:from-blue-100 group-hover:to-indigo-100 group-hover:scale-110 transition-all duration-300">
                  <feature.icon className="w-6 h-6 text-primary-600" />
                </div>
                <h3 className="text-base font-semibold text-neutral-900 mb-2 leading-snug">{feature.title}</h3>
                <p className="text-sm text-neutral-500 leading-relaxed">{feature.description}</p>
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
              对标推荐性国标{' '}
              <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 border border-blue-100 px-3 py-1 text-sm font-bold text-primary-600 align-middle">
                GB/T 47746-2026
              </span>{' '}
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
            ].map((item) => (
              <div
                key={item.title}
                className="group flex gap-4 p-6 bg-white rounded-2xl border border-neutral-100 hover:border-blue-200 hover:shadow-lg hover:shadow-blue-50 transition-all duration-300"
              >
                <div className="w-11 h-11 bg-gradient-to-br from-primary-500 to-primary-600 rounded-xl flex items-center justify-center shrink-0 shadow-sm shadow-blue-200">
                  <item.icon className="w-5 h-5 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-base font-semibold text-neutral-900 mb-1.5">{item.title}</h3>
                  <p className="text-sm text-neutral-500 leading-relaxed">{item.description}</p>
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

      {/* 平台保障 */}
      <section className="py-20 sm:py-28 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <span className="text-sm font-semibold text-primary-600 uppercase tracking-wider">
              平台保障
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-neutral-900">
              正规运营，数据隔离，风控兜底
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-5xl mx-auto">
            {trustPoints.map((point) => (
              <div
                key={point.title}
                className="group flex gap-4 p-6 bg-slate-50 rounded-2xl border border-neutral-100 hover:border-blue-100 hover:shadow-lg transition-all duration-300"
              >
                <div className="w-11 h-11 bg-gradient-to-br from-primary-500 to-primary-600 rounded-xl flex items-center justify-center shrink-0 shadow-sm shadow-blue-200">
                  <point.icon className="w-5 h-5 text-white" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-base font-semibold text-neutral-900 mb-1">{point.title}</h3>
                  <p className="text-sm text-neutral-500 leading-relaxed">{point.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 适合行业 */}
      <section className="py-20 sm:py-28 bg-slate-50">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-14">
            <span className="text-sm font-semibold text-primary-600 uppercase tracking-wider">
              适合行业
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-neutral-900">
              适合这些行业的商家
            </h2>
            <p className="mt-4 text-lg text-neutral-500">
              行业属性可按需配置，服务咨询高频、规格复杂的商家。
            </p>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5 max-w-5xl mx-auto">
            {industries.map((industry) => (
              <div
                key={industry.name}
                className="group p-6 bg-white rounded-2xl border border-neutral-100 hover:border-blue-200 hover:shadow-md transition-all duration-300 hover:-translate-y-0.5 text-center"
              >
                <div className="w-12 h-12 mx-auto mb-3 rounded-xl bg-gradient-to-br from-slate-100 to-slate-200 group-hover:from-blue-50 group-hover:to-indigo-50 flex items-center justify-center transition-all duration-300">
                  <industry.icon className="w-6 h-6 text-slate-400 group-hover:text-blue-500 transition-colors" />
                </div>
                <h3 className="text-base font-semibold text-neutral-900 mb-1">{industry.name}</h3>
                <p className="text-xs text-slate-500 leading-relaxed">{industry.note}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 三步开始 */}
      <section className="py-20 sm:py-28 bg-white">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="text-center max-w-2xl mx-auto mb-16">
            <span className="text-sm font-semibold text-primary-600 uppercase tracking-wider">
              开始使用
            </span>
            <h2 className="mt-3 text-3xl sm:text-4xl font-bold text-neutral-900">
              三步，开始使用
            </h2>
            <p className="mt-4 text-lg text-neutral-500">
              提交申请 → AI 自动核验 → 即刻开通，全程无需等待人工审核。
            </p>
          </div>
          <div className="relative max-w-4xl mx-auto">
            {/* Connecting line (desktop) */}
            <div className="hidden md:block absolute top-14 left-[calc(16.67%+40px)] right-[calc(16.67%+40px)]">
              <div className="relative h-0.5">
                <div className="absolute inset-0 bg-gradient-to-r from-blue-200 via-blue-400 to-blue-200" />
                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-blue-400 rounded-full" />
                <div className="absolute right-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-blue-400 rounded-full" />
                <div className="absolute left-1/2 top-1/2 -translate-y-1/2 -translate-x-1/2">
                  <ArrowRight className="w-4 h-4 text-blue-400" />
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-12">
              {steps.map((item) => (
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
                  <h3 className="mt-3 text-lg font-semibold text-neutral-900">{item.title}</h3>
                  <p className="mt-2 text-sm text-neutral-500 leading-relaxed max-w-xs mx-auto">{item.description}</p>
                </div>
              ))}
            </div>
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
            几分钟开通，两位 AI 即刻开始工作
          </h2>
          <p className="mt-4 text-lg text-blue-100/90 max-w-xl mx-auto leading-relaxed">
            AI 自动甄别秒级通过；开通后即可使用管理后台，米宝与小布 7×24 在岗。
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
