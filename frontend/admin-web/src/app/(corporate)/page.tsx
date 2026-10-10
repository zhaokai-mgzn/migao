import type { Metadata } from 'next'
import Link from 'next/link'
import {
  ArrowRight,
  BadgeCheck,
  BookOpen,
  Bot,
  Calculator,
  Check,
  ClipboardList,
  Factory,
  FileText,
  Landmark,
  MessageSquare,
  PackageOpen,
  Rocket,
  Ruler,
  ShieldCheck,
  ShoppingBag,
  Shirt,
  Sofa,
  Sparkles,
  Truck,
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
  title: '观星台 — 布艺行业 AI 经营平台：顾客服务与生产管理',
  description:
    '观星台是面向布艺 / 窗帘商家的多租户 AI 经营平台。顾客侧由元元提供 7×24 智能客服，覆盖算料报价、下单、物流查询与售后受理；经营侧由黄金策覆盖商品、订单、生产、库存与财务。入驻申请 AI 自动甄别，通过后秒级开通；人机协同机制参考 GB/T 47746-2026 设计。',
}

/** Hero 事实标签：每一条都能在代码或文档里找到出处，不写形容词 */
const heroFacts = [
  'AI 自动甄别 · 秒级开通',
  '租户级数据隔离',
  '微信小程序 + 商家小程序 + 员工端 H5',
  '人机协同机制参考 GB/T 47746-2026 设计',
]

const agents = [
  {
    icon: Bot,
    name: '黄金策',
    role: AI_ROLES.mibao,
    brief: '面向企业生产与经营：以自然语言问答交付商品、订单、生产、库存与财务的日常经营信息。',
    highlights: [
      '经营看板与每日简报：订单量、销售额、环比、待处理事项',
      '商品与 SKU：批量改价、批量上下架（可撤销）、分类与资料维护',
      '订单与加工单：订单查询、物流、加工单进度与报工明细',
      '库存与入库：批次库存、库存台账、入库单与批次成本',
      '生产与计件：工序库、工艺路线、计件工资报表',
      '财务与客户：资金流水 / 收支汇总 / 应收对账问答，客户档案与售后工单',
    ],
    boundary:
      '写操作只有三类：改价、批量上下架、批量库存调整。改价须携带改前价并经确认卡二次确认；AI 不创建订单与商品。',
  },
  {
    icon: MessageSquare,
    name: '元元',
    role: AI_ROLES.xiaobu,
    brief: '面向终端顾客：7×24 小时在线接待，覆盖规格咨询、下单、物流查询与售后受理。',
    highlights: [
      '商品咨询：颜色、门幅、加工项，按店内已上架商品作答',
      '窗帘算料报价：按尺寸与工艺算用料，给出估算报价',
      '下单：短信验证码校验后下单，单价取商品库权威价',
      '订单与物流：订单进度、物流轨迹、收货地址',
      '售后受理：售后咨询与申请，工单恒为待商家审核',
      '知识卡片与图片识别：按店内已发布知识作答，顾客发图可识别解读',
    ],
    boundary:
      '不改价、不取消订单、不退款、不承诺优惠折扣，也不报库存数量；报价一律说明为估算。',
  },
]

/** 订单全流程 —— 布艺行业纵深（每一步都有对应模块或接口） */
const orderJourney = [
  {
    step: '01',
    icon: Ruler,
    title: '询价与算料',
    description:
      '按尺寸、褶皱与工艺计算用料并给出估算报价；加工项与加工费组合（元 / 米）单独定价，未定价项单独提示。',
  },
  {
    step: '02',
    icon: ShoppingBag,
    title: '下单',
    description:
      '规格覆盖颜色 × 售卖方式 × 门幅；下单须通过短信验证码校验，成交单价取商品库权威价，AI 不自行定价。',
  },
  {
    step: '03',
    icon: Factory,
    title: '生产',
    description:
      '订单生成加工单（按套），工艺路线驱动工序：裁剪（裁床）→ 车位（缝制）→ 后整（烫工及后整）；工人扫码报工，首道工序报满自动开工。',
  },
  {
    step: '04',
    icon: PackageOpen,
    title: '入库',
    description:
      '入库单先建草稿（不动库存）；过账后自动生成批次号、增加库存，并按移动加权平均记成本。期初建账支持 Excel 批量导入，逐行给出校验报告。',
  },
  {
    step: '05',
    icon: Truck,
    title: '发货',
    description:
      '发货单记录来源（工人拍照 / 工人手工 / 商家）与实发数量，支持按真实尺寸 A4 补打；发货方式区分「物流发货」与「无需物流」。',
  },
  {
    step: '06',
    icon: Calculator,
    title: '售后与对账',
    description:
      '售后工单分退货 / 换货 / 维修 / 退款 / 投诉 / 其他六类，支持超时下钻；财务侧提供资金流水、收支汇总、应收对账三张账。',
  },
]

const platformGuarantees = [
  {
    icon: BadgeCheck,
    title: 'AI 自动合规甄别',
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
    title: '操作可追溯',
    description: 'AI 的工具调用与关键业务操作全程留有记录可查，身份取自登录账号，敏感信息脱敏保存。',
  },
  {
    icon: BookOpen,
    title: '岗位权限可控',
    description:
      '管理员 / 客服 / 运营 / 销售 / 财务 / 商品管理员 / 知识编辑七个岗位，员工菜单权限逐人可配。',
  },
  {
    icon: Zap,
    title: '多渠道统一数据',
    description:
      '管理后台、顾客小程序、商家小程序、员工端 H5 共用数据底座，不各自建账。',
  },
]

const industries = [
  { icon: Factory, name: '布艺纺织', note: '定制规格多，询价与算料环节繁琐' },
  { icon: Sofa, name: '家居建材', note: '产品参数多，需要专业应答' },
  { icon: Shirt, name: '服装服饰', note: '上新频繁，退换咨询高频' },
  { icon: ShoppingBag, name: '电商零售', note: '私域询单集中，需要统一管理' },
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
      {/* ── Hero ─────────────────────────────────────────────── */}
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
                <span>杭州词元通达科技有限公司 · 布艺行业 AI 经营平台</span>
              </div>

              <h1 className="mt-7 text-3xl font-extrabold leading-tight tracking-tight sm:text-5xl lg:text-[3.4rem]">
                AI 客服与经营系统
                <br />
                <span className="bg-gradient-to-r from-gold-300 via-gold-500 to-accent-300 bg-clip-text text-transparent">
                  覆盖布艺经营全流程
                </span>
              </h1>

              <p className="mt-6 max-w-2xl text-base leading-relaxed text-neutral-300 sm:text-lg">
                顾客侧由元元承接：咨询应答、算料报价、下单、物流查询与售后受理；
                经营侧由黄金策承接：商品、订单、生产、库存与财务，以自然语言问答交付。
                元元与黄金策读取的是真实经营数据，回答与后台记录一致。
              </p>

              <div className="mt-9 flex flex-col gap-3 sm:flex-row">
                <Link
                  href="/register"
                  className="group inline-flex items-center justify-center gap-2 rounded-xl bg-white px-7 py-3.5 text-base font-semibold text-neutral-900 transition-colors hover:bg-neutral-100"
                >
                  立即入驻
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                </Link>
                <Link
                  href="/services"
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/25 px-7 py-3.5 text-base font-semibold text-white transition-colors hover:bg-white/10"
                >
                  查看产品能力
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
                黄金策入口：管理后台右下角悬浮助手，也支持商家小程序「问黄金策」；元元入口：顾客微信小程序。
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── 元元与黄金策的完整分工 ─────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="双 AI 分工"
            title="顾客侧服务，经营侧管理"
            lead="元元与黄金策均基于大语言模型理解业务意图，7×24 小时在线，读取真实经营数据；能力边界在页面中明确标注，超出范围的请求由 AI 直接说明。"
          />
          <div className="mx-auto mt-14 grid max-w-6xl grid-cols-1 gap-6 md:grid-cols-2">
            {agents.map((agent) => (
              <div
                key={agent.name}
                className="flex flex-col rounded-2xl border border-neutral-200 bg-white p-8 shadow-card transition-shadow hover:shadow-card-hover"
              >
                <div className="flex items-center gap-4">
                  <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700">
                    <agent.icon className="h-7 w-7 text-white" />
                  </div>
                  <h3 className="text-xl font-bold text-neutral-900">
                    {agent.name}
                    <span className="ml-2 text-sm font-medium text-accent-600">{agent.role}</span>
                  </h3>
                </div>

                <p className="mt-5 text-sm leading-relaxed text-neutral-600">{agent.brief}</p>

                <ul className="mt-6 flex-1 space-y-3">
                  {agent.highlights.map((item) => (
                    <li key={item} className="flex items-start gap-2.5 text-sm text-neutral-700">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary-600" />
                      <span className="leading-relaxed">{item}</span>
                    </li>
                  ))}
                </ul>

                <p className="mt-6 rounded-xl border border-accent-100 bg-accent-50 px-4 py-3 text-xs leading-relaxed text-accent-800">
                  <span className="font-semibold">能力边界：</span>
                  {agent.boundary}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 销售与生产的闭环（原「一条订单跑完全程」；issue #6379 改为能力口径）── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="行业纵深"
            title="销售与生产的闭环"
            lead="布艺经营的核心难点集中在算料、工序、批次与计件；从询价、下单到生产、入库、发货与售后对账，各环节均有对应功能模块支撑。"
          />
          <div className="mx-auto mt-14 grid max-w-6xl grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {orderJourney.map((item) => (
              <div
                key={item.step}
                className="rounded-2xl border border-neutral-200 bg-neutral-50/60 p-6 transition-all hover:border-primary-200 hover:bg-white hover:shadow-card"
              >
                <div className="flex items-center justify-between">
                  <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-neutral-200 bg-white">
                    <item.icon className="h-5 w-5 text-primary-600" />
                  </div>
                  <span className="text-sm font-bold tracking-wider text-neutral-300">
                    {item.step}
                  </span>
                </div>
                <h3 className="mt-5 text-base font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{item.description}</p>
              </div>
            ))}
          </div>

          <div className="mx-auto mt-14 grid max-w-6xl grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {industryDepth.map((item) => (
              <div key={item.title} className="rounded-2xl bg-neutral-900 p-6 text-white">
                <item.icon className="h-6 w-6 text-gold-500" />
                <h3 className="mt-4 text-base font-semibold">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-300">{item.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 能力地图 ─────────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="管理后台"
            title="覆盖经营全链路的能力域"
            lead="商品、客户、交易、生产、仓储、组织六个能力域数据互通，这也是 AI 答复准确的基础。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            {capabilityDomains.map((domain) => (
              <div
                key={domain.key}
                className="rounded-2xl border border-neutral-200 bg-white p-7 shadow-card"
              >
                <h3 className="text-lg font-bold text-neutral-900">{domain.name}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-500">{domain.summary}</p>
                <ul className="mt-5 space-y-3">
                  {domain.items.map((item) => (
                    <li key={item.name} className="flex items-start gap-3">
                      <item.icon className="mt-0.5 h-4 w-4 shrink-0 text-accent-600" />
                      <span className="text-sm text-neutral-700">{item.name}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>

          <div className="mx-auto mt-6 grid max-w-6xl grid-cols-1 gap-5 sm:grid-cols-2">
            {standaloneEntries.map((item) => (
              <div
                key={item.name}
                className="flex items-start gap-4 rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
              >
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-neutral-100">
                  <item.icon className="h-5 w-5 text-primary-600" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-neutral-900">{item.name}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-neutral-600">{item.detail}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 人机协同 + 国标（宣称口径见 docs/wiki/gb47746-2026-compliance.md）── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="人机协同"
            title="AI 优先应答，人工按规则接续"
            lead="日常咨询由元元直接处理；复杂诉求按规则转接人工，会话记录与上下文同步至坐席，顾客无需重复描述。（协同机制参考推荐性国标 GB/T 47746-2026 设计）"
          />

          <div className="mt-14 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-neutral-200 bg-neutral-50/60 p-7">
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

          <div className="mt-12 rounded-2xl border border-neutral-200 bg-neutral-50/60 p-8 sm:p-10">
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

      {/* ── 平台保障 ─────────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="平台保障"
            title="正规运营，数据隔离，全程可追溯"
            lead="平台的合规、隔离与审计能力逐项说明如下。"
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

      {/* ── 适合行业 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="适合行业"
            title="适用行业"
            lead="行业属性可按需配置，适用于咨询高频、规格复杂的商家。"
          />
          <div className="mx-auto mt-14 grid max-w-5xl grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {industries.map((industry) => (
              <div
                key={industry.name}
                className="rounded-2xl border border-neutral-200 bg-white p-6 text-center transition-shadow hover:shadow-card-hover"
              >
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-neutral-100">
                  <industry.icon className="h-6 w-6 text-accent-600" />
                </div>
                <h3 className="mt-4 text-base font-semibold text-neutral-900">{industry.name}</h3>
                <p className="mt-1.5 text-xs leading-relaxed text-neutral-500">{industry.note}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 三步开始 ─────────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="开始使用"
            title="三步开通"
            lead="提交申请 → AI 自动核验 → 即刻开通，全程无需等待人工审核。"
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
                <span className="corporate-kicker mt-5 inline-block">
                  第 {item.step} 步
                </span>
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
            数分钟内完成开通，元元与黄金策同步上线
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-base leading-relaxed text-neutral-300">
            入驻申请经 AI 自动甄别后秒级返回结果；开通后即可使用管理后台，元元与黄金策随即可用。
          </p>
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              href="/register"
              className="group inline-flex items-center gap-2 rounded-xl bg-white px-7 py-3.5 text-base font-semibold text-neutral-900 transition-colors hover:bg-neutral-100"
            >
              立即入驻
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
            <Link
              href="/contact"
              className="inline-flex items-center gap-2 rounded-xl border border-white/25 px-7 py-3.5 text-base font-semibold text-white transition-colors hover:bg-white/10"
            >
              联系我们
            </Link>
          </div>
        </div>
      </section>
    </>
  )
}
