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
import {
  capabilityDomains,
  industryDepth,
  standaloneEntries,
} from '@/components/corporate/capability-map'

export const metadata: Metadata = {
  title: '米高 — 布艺行业的 AI 经营平台：小布接客，米宝管店',
  description:
    '米高是面向布艺 / 窗帘商家的多租户 AI 经营平台：小布 7×24 接待顾客，能算料报价、下单、查物流、受理售后；米宝打理商品、订单、生产、库存与财务，问一句就答。AI 自动甄别、秒级开通，人机协同机制参考 GB/T 47746-2026 设计。',
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
    name: '米宝',
    role: '企业智能工作助手',
    brief: '面向店里的人：把商品、订单、生产、库存、财务的日常问题，变成一句问话。',
    highlights: [
      '经营看板与每日简报：订单量、销售额、环比、待处理事项',
      '商品与 SKU：批量改价、批量上下架（可撤销）、分类与资料维护',
      '订单与加工单：一句话查订单、物流、加工单进度与报工明细',
      '库存与入库：批次库存、库存台账、入库单与批次成本',
      '生产与计件：工序库、工艺路线、计件工资报表',
      '财务与客户：资金流水 / 收支汇总 / 应收对账问答，客户档案与售后工单',
    ],
    boundary:
      '写操作只有三类：改价、批量上下架、批量库存调整。改价必须带改前价并点确认卡；建单、建品 AI 不做。',
  },
  {
    icon: MessageSquare,
    name: '小布',
    role: 'AI 智能客服',
    brief: '面向顾客的人：7×24 在店里接待，从问规格到下单、查物流、报售后。',
    highlights: [
      '商品咨询：颜色、门幅、加工项，按店内已上架商品回答',
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

/** 一条订单跑完全程 —— 布艺行业纵深（每一步都有对应模块或接口） */
const orderJourney = [
  {
    step: '01',
    icon: Ruler,
    title: '询价与算料',
    description:
      '按尺寸、褶皱与工艺算用料，给出估算报价；加工项与加工费组合（元 / 米）单独定价，未定价项会单独标出。',
  },
  {
    step: '02',
    icon: ShoppingBag,
    title: '下单',
    description:
      '规格覆盖颜色 × 售卖方式 × 门幅；下单需短信验证码校验，成交单价取商品库权威价，AI 不自行定价。',
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
      '入库单先建草稿（不动库存），过账后自动生成批次号、增加库存并按移动加权平均记成本；期初建账支持 Excel 批量导入并逐行给出校验报告。',
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
      '售后工单分退货 / 换货 / 维修 / 退款 / 投诉 / 其他六类并带超时下钻；财务这边是三张账：资金流水、收支汇总、应收对账。',
  },
]

const platformGuarantees = [
  {
    icon: BadgeCheck,
    title: 'AI 自动合规甄别',
    description:
      '入驻申请由 AI 自动审查：敏感信息与非法内容先过规则层，再给出结论；通过后自动开通租户与管理员账号。',
  },
  {
    icon: ShieldCheck,
    title: '租户级数据隔离',
    description: '租户身份只来自登录凭证，查询自动按租户过滤；跨租户访问一律 404。',
  },
  {
    icon: Landmark,
    title: '正规运营主体',
    description: '杭州词元通达科技有限公司，为您提供长期稳定的产品服务。',
  },
  {
    icon: ClipboardList,
    title: '操作可追溯',
    description: 'AI 工具调用与关键业务操作落库审计，身份取自登录上下文，敏感参数脱敏记录。',
  },
  {
    icon: BookOpen,
    title: '岗位权限可控',
    description:
      '管理员 / 客服 / 运营 / 销售 / 财务 / 商品管理员 / 知识编辑七个岗位，员工菜单权限逐人可配。',
  },
  {
    icon: Zap,
    title: '多渠道同一套数据',
    description:
      '管理后台、顾客小程序、商家小程序、员工端 H5 共用同一套业务数据，AI 看到的就是店里真实的账。',
  },
]

const industries = [
  { icon: Factory, name: '布艺纺织', note: '定制规格多，询价与算料繁琐' },
  { icon: Sofa, name: '家居建材', note: '产品参数多，需专业应答' },
  { icon: Shirt, name: '服装服饰', note: '上新快、退换咨询高频' },
  { icon: ShoppingBag, name: '电商零售', note: '私域询单集中，需统一管理' },
]

const steps = [
  {
    icon: FileText,
    step: '01',
    title: '提交申请',
    description: '填写企业信息并完成手机验证，全程仅需几分钟。',
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
    description: '开通即获得管理后台与两位 AI，小布与米宝立即在岗。',
  },
]

const handoffSteps: Array<[string, string]> = [
  ['客户咨询', '顾客通过微信小程序或网页发起咨询'],
  ['小布 AI 应答', '商品、订单、物流、售后实时应答'],
  ['自动转人工', '识别复杂诉求，或顾客主动要求转人工'],
  ['人工接续', '自动创建会话与工单，上下文同步，无需重复描述'],
  ['留言兜底', '非营业时间留言，人工上班后接续处理'],
]

const gbPoints = [
  {
    icon: Sparkles,
    title: '自动识别复杂诉求转人工',
    description:
      '情绪化、多轮未解决、涉赔偿 / 法律等超范围诉求，AI 自动建议或直接转接人工客服 —— 先 AI 应答，人工兜底。',
  },
  {
    icon: Zap,
    title: '转人工规则可配置',
    description: '顾客可直接提出转人工，商家还可自定义触发关键词，转接规则随业务灵活调整。',
  },
  {
    icon: MessageSquare,
    title: '转人工即同步上下文',
    description:
      '转人工后自动创建人工会话与工单并通知坐席，顾客与 AI 的沟通记录同步给人工客服，无需重复描述；原对话即可继续沟通（非营业时间自动转为留言）。',
  },
  {
    icon: ShieldCheck,
    title: 'AI 严格承诺边界',
    description:
      '涉及价格、折扣、退款金额等敏感事项，AI 只做规则解释与材料收集，申请类动作一律待人工客服或规范流程审核确认。',
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
          <div className="absolute left-1/3 top-1/4 h-72 w-72 rounded-full bg-[#d48806]/10 blur-3xl" />
        </div>

        <div className="relative mx-auto max-w-7xl px-4 pb-24 pt-20 sm:px-6 sm:pb-32 sm:pt-28 lg:px-8">
          <div className="grid grid-cols-1 gap-14 lg:grid-cols-12 lg:items-center">
            <div className="lg:col-span-7">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-4 py-1.5 text-xs text-neutral-200 sm:text-sm">
                <Sparkles className="h-4 w-4 text-[#e8b04b]" />
                <span>杭州词元通达科技有限公司 · 布艺行业 AI 经营平台</span>
              </div>

              <h1 className="mt-7 text-3xl font-extrabold leading-tight tracking-tight sm:text-5xl lg:text-[3.4rem]">
                两个 AI，把一间窗帘店
                <br />
                <span className="bg-gradient-to-r from-[#f6d27a] via-[#e8b04b] to-accent-300 bg-clip-text text-transparent">
                  从询价管到发货
                </span>
              </h1>

              <p className="mt-6 max-w-2xl text-base leading-relaxed text-neutral-300 sm:text-lg">
                小布接待顾客：应答咨询、算料报价、下单、查物流、受理售后；
                米宝打理经营：商品、订单、生产、库存、财务，老板问一句就答。
                两位 AI 共用同一套业务数据，谁都不会答出一个店里不存在的数。
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
                  看完整能力
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

            {/* 右侧：两个 AI 的一句话分工 */}
            <div className="space-y-4 lg:col-span-5">
              {agents.map((agent) => (
                <div
                  key={agent.name}
                  className="rounded-2xl border border-white/10 bg-white/[0.04] p-6 backdrop-blur-sm"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-[#f6d27a] to-[#d48806]">
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
                米宝入口：管理后台右下角悬浮助手，也支持商家小程序「问米宝」；小布入口：顾客微信小程序。
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── 两个 AI 的完整分工 ───────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="双 AI 分工"
            title="一位打理店内经营，一位接待您的顾客"
            lead="两位 AI 都基于大语言模型理解业务意图，7×24 在岗，共用同一业务数据后台；能力边界写在明处，做不到的事 AI 会直说。"
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

      {/* ── 一条订单跑完全程 ─────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="行业纵深"
            title="一条窗帘订单，跑完这六步"
            lead="通用客服只答「有没有货、什么时候到」；布艺生意的难点在算料、工序、批次与计件 —— 这六步，米高每一步都有对应模块。"
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
                <item.icon className="h-6 w-6 text-[#e8b04b]" />
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
            title="一个后台，六个能力域"
            lead="商品、客户、交易、生产、仓储、组织，全部长在同一套数据上 —— 这也是两位 AI 能答得准的原因。"
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
            title="AI 先应答，人工来兜底"
            lead="日常咨询由小布直接解决；复杂诉求自动转人工，会话记录与上下文随行，顾客无需重复描述。（协同机制参考推荐性国标 GB/T 47746-2026 设计）"
          />

          <div className="mt-14 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-neutral-200 bg-neutral-50/60 p-7">
              <h3 className="text-base font-semibold text-neutral-900">一次咨询怎么走完</h3>
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
              title="让人工与智能客服协同更可靠"
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
              「遵循 / 对标 GB/T 47746-2026」指小布智能客服的人机协同机制功能设计参考该推荐性国家标准；该标准为推荐性标准、无认证或备案机制，本页面不构成任何认证、检测或备案结论。
            </p>
          </div>
        </div>
      </section>

      {/* ── 平台保障 ─────────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="平台保障"
            title="正规运营，数据隔离，每一步可追溯"
            lead="把生意交给 AI 之前，先把边界交代清楚。"
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
            title="适合这些行业的商家"
            lead="行业属性可按需配置，最适合服务咨询高频、规格复杂的商家。"
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
            title="三步，开始使用"
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
                <span className="mt-5 inline-block text-xs font-bold uppercase tracking-[0.18em] text-accent-600">
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
            几分钟开通，两位 AI 即刻开始工作
          </h2>
          <p className="mx-auto mt-4 max-w-2xl text-base leading-relaxed text-neutral-300">
            AI 自动甄别秒级返回结果；开通后即可使用管理后台，小布与米宝立即在岗，共用店里同一套业务数据。
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
              留言咨询
            </Link>
          </div>
        </div>
      </section>
    </>
  )
}
