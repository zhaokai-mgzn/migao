import type { Metadata } from 'next'
import Link from 'next/link'
import {
  ArrowRight,
  BadgeCheck,
  BarChart3,
  Bot,
  Building2,
  Calculator,
  ClipboardList,
  Coins,
  Database,
  Factory,
  FileText,
  Headphones,
  Landmark,
  Layers,
  MessageSquare,
  PackageOpen,
  Rocket,
  Ruler,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  Target,
  Truck,
  Users,
  Zap,
} from 'lucide-react'
import { SectionHeading } from '@/components/corporate/CorporateSection'
import { AI_ROLES } from '@/config/ai-roles'
import {
  capabilityDomains,
  industryDepth,
  standaloneEntries,
} from '@/components/corporate/capability-map'

export const metadata: Metadata = {
  title: {
    absolute: '观星台 — 布艺行业 AI 经营平台｜把 AI 智能化技术带给中小企业',
  },
  description:
    '观星台是杭州词元通达科技有限公司面向布艺 / 窗帘企业的 AI 经营平台。元元承接顾客咨询、算料报价、下单与售后；黄金策承接商品、订单、生产、库存与财务。AI 自动甄别入驻，分钟级开通；四端协同，数据同源。',
}

/** Hero 事实标签：每一条都能在代码或文档里找到出处，不写形容词 */
const heroFacts = [
  'AI 自动甄别 · 分钟级开通',
  '租户级数据隔离',
  '四端协同 · 数据同源',
  '人机协同机制参考 GB/T 47746-2026 设计',
]

const agents = [
  {
    icon: Bot,
    name: '黄金策',
    role: AI_ROLES.mibao,
    brief: '面向经营侧：以自然语言问答交付商品、订单、生产、库存与财务信息，辅助日常经营决策。',
    highlights: [
      '经营洞察：订单量、销售额、环比与待处理事项，支持每日简报',
      '商品与价格：批量改价、批量库存调整（可撤销）、商品资料维护',
      '订单与交付：订单、物流、加工单进度与报工明细',
      '库存与成本：批次库存、库存台账、入库单与批次成本',
      '生产与计件：工序库、工艺路线、计件工资报表',
      '财务与客户：资金流水、收支汇总、应收对账、客户档案与售后工单',
    ],
    boundary:
      '可写的动作：改价、商品改名、批量改价与批量库存调整、通知标记已读、定时提醒；上下架与删除不做。改价须携带改前价并经确认卡二次确认；AI 不创建订单与商品。',
  },
  {
    icon: MessageSquare,
    name: '元元',
    role: AI_ROLES.xiaobu,
    brief: '面向顾客侧：7×24 小时接待咨询，覆盖算料报价、下单、物流查询与售后受理。',
    highlights: [
      '商品咨询：颜色、门幅、加工项，按店内已上架商品作答',
      '算料报价：按尺寸与工艺计算用料，输出估算报价',
      '下单：短信验证码校验，成交单价取商品库权威价',
      '订单与物流：订单进度、物流轨迹、收货地址',
      '售后受理：售后咨询与申请，工单恒为待商家审核',
      '知识卡片与图片识别：按已发布知识作答，支持图片解读',
    ],
    boundary:
      '不改价、不取消订单、不退款、不承诺优惠折扣，也不报库存数量；报价一律说明为估算。',
  },
]

/** 中小企业的经营课题 → 平台应对（每一项都对应真实模块） */
const businessChallenges = [
  {
    icon: Ruler,
    title: '询价与算料依赖经验',
    description: '算料规则、工艺参数与加工费组合可配置；报价依据可追溯，未定价项明确提示。',
  },
  {
    icon: ClipboardList,
    title: '订单与生产各自记账',
    description: '订单生成加工单，工序进度、报工明细与交付状态在同一链路查看。',
  },
  {
    icon: PackageOpen,
    title: '库存与成本缺少台账',
    description: '入库过账生成批次，库存变动逐笔记录，成本按移动加权平均核算。',
  },
  {
    icon: Headphones,
    title: '服务响应依赖人工',
    description: '元元 7×24 接待常规咨询；复杂诉求按规则转人工，上下文同步至坐席。',
  },
]

/** 平台四层：交互 / 智能 / 业务 / 数据与安全 */
const platformLayers = [
  {
    icon: Layers,
    name: '交互层',
    description: '管理后台、顾客小程序、商家小程序与员工端 H5，按角色提供入口与权限。',
  },
  {
    icon: Bot,
    name: '智能层',
    description: '元元与黄金策理解业务意图，调用工具完成查询、分析与受控写入。',
  },
  {
    icon: Database,
    name: '业务层',
    description: '八个能力域覆盖客户服务、交易、生产、质量、仓储、财务、供应链与组织管理。',
  },
  {
    icon: ShieldCheck,
    name: '数据与安全层',
    description: '多租户隔离、行级安全、岗位权限与操作审计构成统一底座。',
  },
]

/** 订单全流程 —— 布艺行业纵深（每一步都有对应模块或接口） */
const orderJourney = [
  {
    step: '01',
    icon: Ruler,
    title: '询价与算料',
    description:
      '按尺寸、褶皱与工艺计算用料，输出估算报价；加工项与加工费组合单独定价，未定价项明确提示。',
  },
  {
    step: '02',
    icon: ShoppingBag,
    title: '下单',
    description:
      '规格覆盖颜色、售卖方式与门幅；短信验证码校验后下单，成交单价取商品库权威价，AI 不自行定价。',
  },
  {
    step: '03',
    icon: Factory,
    title: '生产',
    description:
      '订单生成加工单，工艺路线驱动裁剪（裁床）→ 车位（缝制）→ 后整（烫工及后整）；工人扫码报工，进度实时可见。',
  },
  {
    step: '04',
    icon: PackageOpen,
    title: '入库',
    description:
      '入库单先建草稿，不动库存；过账后生成批次、增加库存，并按移动加权平均记录成本。',
  },
  {
    step: '05',
    icon: Truck,
    title: '发货',
    description:
      '发货单记录来源与实发数量，支持按真实尺寸 A4 补打；区分物流发货与无需物流。',
  },
  {
    step: '06',
    icon: Calculator,
    title: '售后与对账',
    description:
      '售后工单覆盖退货、换货、维修、退款、投诉与其他六类；财务提供资金流水、收支汇总与应收对账。',
  },
]

/** 经营价值：只写可核对、可追溯的形态，不写百分比 */
const valuePoints = [
  {
    icon: Calculator,
    title: '报价有依据',
    description: '算料公式、工艺参数与未定价项均有记录，报价过程可复核。',
  },
  {
    icon: Truck,
    title: '交付有进度',
    description: '订单、加工单与报工进度在同源链路可查，异常可定位。',
  },
  {
    icon: BarChart3,
    title: '库存有台账',
    description: '批次、缸号、成本与余料变动逐笔记录，差异可追溯。',
  },
  {
    icon: Coins,
    title: '计件有明细',
    description: '报工、返工与报废记录可核对；返工与报废不计件。',
  },
]

/** 适用企业：收窄到真实现阶段的布艺 / 窗帘经营形态 */
const enterpriseTypes = [
  {
    icon: Ruler,
    name: '窗帘定制商',
    description: '定制规格多，询价与算料频繁，需要统一的报价口径。',
  },
  {
    icon: Factory,
    name: '布艺加工厂',
    description: '订单、工序与计件管理复杂，需要透明的生产进度。',
  },
  {
    icon: ShoppingBag,
    name: '批零一体企业',
    description: '销售、库存与财务需要同源，减少跨系统对账。',
  },
  {
    icon: Building2,
    name: '品牌与渠道商',
    description: '多终端服务与统一数据，支撑渠道协同。',
  },
]

/** 产品原则（关于词元通达） */
const principles = [
  {
    icon: Target,
    title: '从现场出发',
    description: '先解决算料、工序、批次与计件等具体问题，再谈平台化。',
  },
  {
    icon: BarChart3,
    title: '以数据为准',
    description: 'AI 的回答与后台记录一致，经营数据同源。',
  },
  {
    icon: ShieldCheck,
    title: '把边界写明',
    description: 'AI 能做什么、不能做什么，在页面与产品中明确标注。',
  },
]

const platformGuarantees = [
  {
    icon: BadgeCheck,
    title: '智能准入审核',
    description:
      '入驻申请由 AI 自动审查：敏感信息与非法内容先经规则层过滤，再给出结论；通过后自动开通租户与管理员账号。',
  },
  {
    icon: ShieldCheck,
    title: '租户级数据隔离',
    description: '租户身份仅取自登录凭证，查询自动按租户过滤；跨租户访问一律返回 404。',
  },
  {
    icon: Landmark,
    title: '正规运营主体',
    description: '由杭州词元通达科技有限公司提供，保障产品与服务的长期稳定。',
  },
  {
    icon: ClipboardList,
    title: '操作全程可追溯',
    description:
      'AI 的工具调用与关键业务操作全程留有记录可查，身份取自登录账号，敏感信息脱敏保存。',
  },
  {
    icon: Users,
    title: '岗位权限可控',
    description:
      '管理员、客服、运营、销售、财务、商品管理员、知识编辑等岗位，菜单权限逐人可配。',
  },
  {
    icon: Layers,
    title: '四端数据同源',
    description: '管理后台、顾客小程序、商家小程序、员工端 H5 共用数据底座，不各自建账。',
  },
]

const steps = [
  {
    icon: FileText,
    step: '01',
    title: '提交申请',
    description: '填写企业信息并完成手机验证，全程约几分钟。',
  },
  {
    icon: Zap,
    step: '02',
    title: 'AI 智能甄别',
    description: 'AI 自动核验企业信息与合规性，秒级返回结果，无需等待人工审核。',
  },
  {
    icon: Rocket,
    step: '03',
    title: '即刻开通',
    description: '开通后即获得管理后台，元元与黄金策同步上线。',
  },
]

const handoffSteps: Array<[string, string]> = [
  ['客户咨询', '顾客通过微信小程序或网页发起咨询'],
  ['元元 AI 应答', '商品、订单、物流、售后实时应答'],
  ['自动转人工', '识别复杂诉求，或顾客主动要求转人工'],
  ['人工接续', '自动创建会话与工单，上下文同步，无需重复描述'],
  ['留言受理', '非营业时间留言，人工上线后接续处理'],
]

const gbPoints = [
  {
    icon: Sparkles,
    title: '自动识别复杂诉求转人工',
    description:
      '情绪化表达、多轮未解决、涉及赔偿或法律等超范围诉求，AI 自动建议或直接转接人工客服，由人工承接。',
  },
  {
    icon: Zap,
    title: '转人工规则可配置',
    description: '顾客可直接提出转人工，商家亦可自定义触发关键词，转接规则可随业务调整。',
  },
  {
    icon: MessageSquare,
    title: '转人工即同步上下文',
    description:
      '转人工后自动创建人工会话与工单并通知坐席，顾客与 AI 的沟通记录同步给人工客服，无需重复描述；原对话可直接继续沟通，非营业时间自动转为留言。',
  },
  {
    icon: ShieldCheck,
    title: 'AI 承诺边界明确',
    description:
      '涉及价格、折扣、退款金额等敏感事项，AI 只做规则解释与材料收集；申请类动作一律待人工客服或规范流程审核确认。',
  },
]

export default function HomePage() {
  return (
    <>
      {/* ── Hero：企业使命 + 产品定位 ─────────────────────────── */}
      <section className="relative overflow-hidden bg-neutral-900 text-white">
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute -top-32 right-0 h-96 w-96 rounded-full bg-primary-500/25 blur-3xl" />
          <div className="absolute -bottom-40 -left-24 h-96 w-96 rounded-full bg-accent-500/20 blur-3xl" />
          <div className="absolute left-1/3 top-1/4 h-72 w-72 rounded-full bg-gold-600/10 blur-3xl" />
        </div>

        <div className="relative mx-auto max-w-7xl px-4 pb-24 pt-20 sm:px-6 sm:pb-32 sm:pt-28 lg:px-8">
          <div className="grid grid-cols-1 gap-14 lg:grid-cols-12 lg:items-center">
            <div className="lg:col-span-7">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-4 py-1.5 text-xs text-neutral-200 sm:text-sm">
                <Sparkles className="h-4 w-4 text-gold-500" />
                <span>杭州词元通达科技有限公司 · 企业级 AI 经营平台</span>
              </div>

              <h1 className="mt-7 text-3xl font-extrabold leading-tight tracking-tight sm:text-5xl lg:text-[3.4rem]">
                把 AI 智能化技术
                <br />
                <span className="bg-gradient-to-r from-gold-300 via-gold-500 to-accent-300 bg-clip-text text-transparent">
                  带给每一家中小企业
                </span>
              </h1>

              <p className="mt-6 max-w-2xl text-base leading-relaxed text-neutral-300 sm:text-lg">
                观星台是词元通达面向布艺 / 窗帘企业的 AI 经营平台。元元承接顾客咨询、算料报价、下单与售后；
                黄金策承接商品、订单、生产、库存与财务。两者读取同源经营数据，回答与后台记录一致。
              </p>

              <div className="mt-9 flex flex-col gap-3 sm:flex-row">
                <Link
                  href="/register"
                  className="group inline-flex items-center justify-center gap-2 rounded-xl bg-white px-7 py-3.5 text-base font-semibold text-neutral-900 transition-colors hover:bg-neutral-100"
                >
                  免费开通
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                </Link>
                <Link
                  href="/contact"
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/25 px-7 py-3.5 text-base font-semibold text-white transition-colors hover:bg-white/10"
                >
                  预约产品演示
                </Link>
              </div>

              <div className="mt-10 flex flex-wrap gap-2.5">
                {heroFacts.map((item) => (
                  <span
                    key={item}
                    className="inline-flex items-center rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-neutral-300 sm:text-sm"
                  >
                    {item}
                  </span>
                ))}
              </div>
            </div>

            {/* 右侧：元元与黄金策的分工 */}
            <div className="space-y-4 lg:col-span-5">
              {agents.map((agent) => (
                <div
                  key={agent.name}
                  className="rounded-2xl border border-white/10 bg-white/[0.04] p-6 backdrop-blur-sm"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-gold-300 to-gold-600">
                      <agent.icon className="h-6 w-6 text-neutral-900" />
                    </div>
                    <div>
                      <p className="text-lg font-bold">{agent.name}</p>
                      <p className="text-xs text-neutral-400">{agent.role}</p>
                    </div>
                  </div>
                  <p className="mt-4 text-sm leading-relaxed text-neutral-300">{agent.brief}</p>
                </div>
              ))}
              <p className="px-1 text-xs leading-relaxed text-neutral-500">
                管理后台、顾客小程序、商家小程序与员工端 H5 共用数据底座。
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── 经营课题：为什么现在 ─────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="中小企业智能化"
            title="AI 的价值，要落在经营现场"
            lead="中小企业的智能化，最终要落到询价、下单、生产与服务这些真实环节：数据同源、流程可追踪、责任可界定。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
            {businessChallenges.map((item) => (
              <div
                key={item.title}
                className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
              >
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary-50">
                  <item.icon className="h-5 w-5 text-primary-700" />
                </div>
                <h3 className="mt-4 text-base font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{item.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 平台架构：四层 ───────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="平台架构"
            title="智能、业务与数据，共用同一底座"
            lead="四个终端承载不同角色，元元与黄金策作为智能入口，八个能力域承载业务，多租户与审计构成底座。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
            {platformLayers.map((layer) => (
              <div
                key={layer.name}
                className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-primary-700">
                    <layer.icon className="h-5 w-5 text-white" />
                  </div>
                  <h3 className="text-base font-semibold text-neutral-900">{layer.name}</h3>
                </div>
                <p className="mt-4 text-sm leading-relaxed text-neutral-600">{layer.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 双 AI 分工 ───────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="双 AI 分工"
            title="顾客侧服务，经营侧管理"
            lead="元元与黄金策基于大语言模型理解业务意图，读取同源经营数据；能力边界在页面中明确标注。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 lg:grid-cols-2">
            {agents.map((agent) => (
              <div
                key={agent.name}
                className="rounded-2xl border border-neutral-200 bg-white p-7 shadow-card"
              >
                <div className="flex items-center gap-3">
                  <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-primary-700">
                    <agent.icon className="h-6 w-6 text-white" />
                  </div>
                  <div>
                    <p className="text-lg font-bold text-neutral-900">{agent.name}</p>
                    <p className="text-xs text-neutral-500">{agent.role}</p>
                  </div>
                </div>
                <p className="mt-4 text-sm leading-relaxed text-neutral-600">{agent.brief}</p>
                <ul className="mt-5 space-y-2.5">
                  {agent.highlights.map((item) => (
                    <li key={item} className="flex gap-2.5 text-sm leading-relaxed text-neutral-700">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-accent-500" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-5 rounded-xl bg-neutral-50 p-4 text-xs leading-relaxed text-neutral-500">
                  {agent.boundary}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 行业纵深：询价到交付 ─────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="行业纵深"
            title="从询价到交付，经营链路完整贯通"
            lead="布艺经营的关键在算料、工序、批次与计件。观星台把这些环节纳入同一平台，减少跨系统对账与重复录入。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            {orderJourney.map((item) => (
              <div
                key={item.step}
                className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
              >
                <div className="flex items-center justify-between">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-accent-500 to-accent-700">
                    <item.icon className="h-5 w-5 text-white" />
                  </div>
                  <span className="text-xs font-semibold tracking-wider text-neutral-400">
                    {item.step}
                  </span>
                </div>
                <h3 className="mt-4 text-base font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{item.description}</p>
              </div>
            ))}
          </div>

          <div className="mt-16">
            <SectionHeading
              kicker="行业能力"
              title="布艺经营的四项核心能力"
              lead="通用客服工具难以覆盖这四项能力，而它们正是观星台产品设计的起点。"
            />
            <div className="mt-10 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
              {industryDepth.map((item) => (
                <div
                  key={item.title}
                  className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
                >
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-neutral-100">
                    <item.icon className="h-5 w-5 text-accent-600" />
                  </div>
                  <h3 className="mt-4 text-base font-semibold text-neutral-900">{item.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-neutral-600">
                    {item.description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── 能力地图 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="能力地图"
            title="覆盖经营全链路的能力域"
            lead="以下每一项都是后台中可打开的功能入口；菜单名与产品侧边栏同源。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2">
            {capabilityDomains.map((domain) => (
              <div
                key={domain.key}
                className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
              >
                <div className="flex items-center justify-between gap-3">
                  <h3 className="text-lg font-bold text-neutral-900">{domain.name}</h3>
                  <span className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs text-neutral-500">
                    {domain.items.length} 项
                  </span>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-neutral-500">{domain.summary}</p>
                <ul className="mt-4 flex flex-wrap gap-1.5">
                  {domain.items.map((item) => (
                    <li
                      key={item.name}
                      className="rounded-md bg-neutral-50 px-2 py-1 text-xs text-neutral-600"
                    >
                      {item.name}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="mt-8 flex flex-wrap items-center gap-2 rounded-2xl border border-neutral-200 bg-neutral-50/60 px-5 py-4">
            <span className="mr-1 text-xs font-semibold tracking-wide text-neutral-500">
              独立入口
            </span>
            {standaloneEntries.map((item) => (
              <span
                key={item.name}
                className="rounded-md bg-white px-2.5 py-1 text-xs text-neutral-700"
              >
                {item.name}
              </span>
            ))}
          </div>

          <div className="mt-8 text-center">
            <Link
              href="/services"
              className="inline-flex items-center gap-2 text-sm font-semibold text-primary-700 transition-colors hover:text-primary-800"
            >
              查看完整能力清单
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>

      {/* ── 经营价值 ─────────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="经营价值"
            title="让经营数据可核对、可追溯"
            lead="平台把经营信息整理到可核对、可追溯的状态，判断仍由经营者完成。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
            {valuePoints.map((point) => (
              <div
                key={point.title}
                className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
              >
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary-50">
                  <point.icon className="h-5 w-5 text-primary-700" />
                </div>
                <h3 className="mt-4 text-base font-semibold text-neutral-900">{point.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">
                  {point.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 适用企业 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="适用企业"
            title="深耕布艺，服务不同经营形态"
            lead="当前聚焦布艺 / 窗帘企业；行业模板、算料参数与岗位权限可按企业实际配置。"
          />
          <div className="mx-auto mt-14 grid max-w-5xl grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {enterpriseTypes.map((item) => (
              <div
                key={item.name}
                className="rounded-2xl border border-neutral-200 bg-white p-6 text-center transition-shadow hover:shadow-card-hover"
              >
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-neutral-100">
                  <item.icon className="h-6 w-6 text-accent-600" />
                </div>
                <h3 className="mt-4 text-base font-semibold text-neutral-900">{item.name}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-neutral-500">
                  {item.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 关于词元通达：使命 + 产品原则 ─────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="关于词元通达"
            title="让 AI 成为中小企业的经营能力"
            lead="杭州词元通达科技有限公司专注于中小企业智能化经营。AI 不应只属于大型企业：通过产品化、可配置、可审计的方式，把大模型能力带到真实经营现场。"
          />
          <div className="mx-auto mt-12 grid max-w-5xl grid-cols-1 gap-6 md:grid-cols-3">
            {principles.map((principle) => (
              <div
                key={principle.title}
                className="rounded-2xl border border-neutral-200 bg-white p-6"
              >
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-50">
                  <principle.icon className="h-5 w-5 text-primary-700" />
                </div>
                <h3 className="mt-4 text-base font-semibold text-neutral-900">
                  {principle.title}
                </h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">
                  {principle.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 平台保障 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="平台保障"
            title="企业级底座，保障数据与权限"
            lead="从入驻审核到日常操作，平台在隔离、权限与审计上提供企业级保障。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            {platformGuarantees.map((point) => (
              <div
                key={point.title}
                className="flex gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
              >
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-primary-700">
                  <point.icon className="h-5 w-5 text-white" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-neutral-900">{point.title}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-neutral-600">
                    {point.description}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 人机协同 + 国标（宣称口径见 docs/wiki/gb47746-2026-compliance.md）── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="人机协同"
            title="AI 优先应答，人工按规则接续"
            lead="日常咨询由元元直接处理；复杂诉求按规则转接人工，会话记录与上下文同步至坐席，顾客无需重复描述。（协同机制参考推荐性国标 GB/T 47746-2026 设计）"
          />

          <div className="mt-14 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-neutral-200 bg-white p-7">
              <h3 className="text-base font-semibold text-neutral-900">从咨询到人工的流转</h3>
              <ol className="mt-5 space-y-4">
                {handoffSteps.map(([title, description], index) => (
                  <li key={title} className="flex gap-4">
                    <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary-600 text-xs font-bold text-white">
                      {index + 1}
                    </span>
                    <div>
                      <p className="text-sm font-semibold text-neutral-900">{title}</p>
                      <p className="mt-0.5 text-sm leading-relaxed text-neutral-600">
                        {description}
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {gbPoints.map((item) => (
                <div
                  key={item.title}
                  className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
                >
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-600">
                    <item.icon className="h-5 w-5 text-white" />
                  </div>
                  <h3 className="mt-4 text-sm font-semibold text-neutral-900">{item.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-neutral-600">
                    {item.description}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-12 rounded-2xl border border-neutral-200 bg-white p-8 sm:p-10">
            <SectionHeading
              kicker="遵循国家标准"
              title="人工与智能客服协同，机制有据可依"
              lead={
                <>
                  对标推荐性国标{' '}
                  <span className="inline-flex items-center rounded-full border border-primary-200 bg-primary-50 px-3 py-1 align-middle text-sm font-bold text-primary-700">
                    GB/T 47746-2026
                  </span>{' '}
                  《顾客联络服务 人工与智能客户服务协同要求》（2026-09-01 实施），设计顾客服务协同机制。
                </>
              }
            />
            <p className="mx-auto mt-8 max-w-3xl text-center text-xs leading-relaxed text-neutral-400">
              「遵循 / 对标 GB/T 47746-2026」指元元智能客服的人机协同机制功能设计参考该推荐性国家标准；该标准为推荐性标准、无认证或备案机制，本页面不构成任何认证、检测或备案结论。
            </p>
          </div>
        </div>
      </section>

      {/* ── 三步开始 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="开始使用"
            title="三步开通，快速上线"
            lead="提交申请、AI 自动甄别、即刻开通；无需自建服务器与 IT 团队。"
          />
          <div className="mx-auto mt-14 grid max-w-5xl grid-cols-1 gap-6 md:grid-cols-3">
            {steps.map((item) => (
              <div
                key={item.step}
                className="rounded-2xl border border-neutral-200 bg-white p-7 text-center shadow-card"
              >
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700">
                  <item.icon className="h-6 w-6 text-white" />
                </div>
                <span className="corporate-kicker mt-5 inline-block">第 {item.step} 步</span>
                <h3 className="mt-2 text-lg font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{item.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 底部 CTA ─────────────────────────────────────────── */}
      <section className="relative overflow-hidden bg-neutral-900 py-20 text-white sm:py-24">
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute -top-20 right-10 h-72 w-72 rounded-full bg-primary-500/20 blur-3xl" />
          <div className="absolute -bottom-24 left-10 h-64 w-64 rounded-full bg-accent-500/15 blur-3xl" />
        </div>
        <div className="relative mx-auto max-w-7xl px-4 text-center sm:px-6 lg:px-8">
          <h2 className="text-2xl font-bold tracking-tight sm:text-4xl">
            把 AI 带进经营现场
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-base leading-relaxed text-neutral-300">
            提交申请，AI 自动甄别后即可开通；也可以预约演示，按您的业务流程逐项确认。
          </p>
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href="/register"
              className="group inline-flex items-center gap-2 rounded-xl bg-white px-7 py-3.5 text-base font-semibold text-neutral-900 transition-colors hover:bg-neutral-100"
            >
              免费开通
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
            <Link
              href="/contact"
              className="inline-flex items-center gap-2 rounded-xl border border-white/25 px-7 py-3.5 text-base font-semibold text-white transition-colors hover:bg-white/10"
            >
              预约演示
            </Link>
          </div>
        </div>
      </section>
    </>
  )
}
