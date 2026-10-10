import type { Metadata } from 'next'
import Link from 'next/link'
import {
  ArrowRight,
  Bot,
  Check,
  Globe,
  Headphones,
  MessageSquare,
  ScanLine,
  Smartphone,
  Sparkles,
  Users,
  Wallet,
} from 'lucide-react'
import { CallToAction, PageHero, SectionHeading } from '@/components/corporate/CorporateSection'
import { AI_ROLES } from '@/config/ai-roles'
import {
  capabilityDomains,
  industryDepth,
  menuItemCount,
  standaloneEntries,
} from '@/components/corporate/capability-map'

export const metadata: Metadata = {
  title: '产品与服务 — AI 客服、经营助手与全链路经营平台',
  description:
    `观星台产品全景：顾客侧元元${AI_ROLES.xiaobu}，经营侧黄金策${AI_ROLES.mibao}；管理后台、顾客小程序、商家小程序、员工端 H5 四个终端，覆盖商品、客户、交易、生产、仓储、组织六个能力域。`,
}

const coreProducts = [
  {
    title: `元元 · ${AI_ROLES.xiaobu}`,
    icon: MessageSquare,
    tagline: '顾客侧：从规格咨询到下单、物流查询与售后受理',
    features: [
      '按店内已上架商品回答颜色、门幅、加工项，不展示未上架商品',
      '按尺寸与工艺计算用料并给出估算报价，明确说明为估算而非成交价',
      '短信验证码校验后下单，成交单价取商品库权威价',
      '订单进度、物流轨迹、收货地址查询',
      '售后咨询与申请受理，工单恒为「待商家审核」',
      '按店内已发布知识卡片作答；顾客发图可识别并给出解读',
    ],
    boundary:
      '不做：改价、取消订单、退款、承诺优惠折扣、报库存数量。涉及价格与赔偿只解释规则、收集材料，落到工单由商家确认。',
  },
  {
    title: `黄金策 · ${AI_ROLES.mibao}`,
    icon: Bot,
    tagline: '经营侧：以自然语言查询账目、订单与进度',
    features: [
      '经营看板与每日简报：订单量、销售额、环比、待处理事项',
      '商品与 SKU：批量改价、批量上下架（可撤销）、分类与资料维护',
      '订单与加工单：订单查询、物流、加工单进度、工序报工明细',
      '库存与入库：批次库存、库存台账、入库单与批次成本',
      '生产与计件：工序库、工艺路线、计件工资与报工明细',
      '财务与客户：资金流水 / 收支汇总 / 应收对账问答，客户档案与售后工单',
    ],
    boundary:
      '写操作只有三类：改价、批量上下架、批量库存调整。改价须携带改前价并经确认卡二次确认；AI 不创建订单与商品。',
  },
]

const terminals = [
  {
    icon: Globe,
    title: '管理后台',
    audience: '老板 / 运营 / 客服',
    description: '浏览器打开即用，六个能力域集中在此；右上角通知中心，右下角悬浮黄金策随时提问。',
    points: ['经营看板与每日简报', '商品、订单、售后、财务', '生产、仓储、组织与权限'],
  },
  {
    icon: Smartphone,
    title: '顾客小程序',
    audience: '终端消费者',
    description: '在微信内直接咨询元元、下单、查询物流与提交售后，无需额外下载。',
    points: ['7×24 咨询与下单', '订单与物流进度', '售后申请与进度'],
  },
  {
    icon: MessageSquare,
    title: '商家小程序',
    audience: '老板 / 店长（移动端）',
    description: '移动端可用：问黄金策、看数据、处理坐席会话，并提供工人登录与拍照入库入口。',
    points: ['问黄金策 / 看数据', '坐席会话处理', '工人登录、拍照入库、补打标签'],
  },
  {
    icon: ScanLine,
    title: '员工端 H5',
    audience: '车间工人',
    description:
      '扫码即开，无需安装 App：扫码报工、拍照入库与发货；一体机提供常驻扫码的机台模式。',
    points: ['扫码报工（合格 / 返工 / 报废）', '拍照入库与发货', '断网补传，同一请求不会重复记账'],
  },
]

const delivery = [
  {
    icon: Sparkles,
    title: 'AI 自动甄别，秒级开通',
    description:
      '提交企业信息并完成手机验证后，AI 自动核验并给出结论，通过即自动开通租户与管理员账号。',
  },
  {
    icon: Headphones,
    title: '行业模板预置',
    description: '布艺行业通用知识模板已预置，开通后即可套用，再按企业话术补充。',
  },
  {
    icon: Users,
    title: '岗位权限开箱可配',
    description: '七个岗位开箱可用，员工菜单权限逐人可调，权限树即后台菜单本身。',
  },
  {
    icon: Wallet,
    title: '价格与合同另行沟通',
    description:
      '本页面不公示价格；套餐、开通范围与交付内容请在入驻申请中说明，由团队与您确认。',
  },
]

export default function ServicesPage() {
  return (
    <>
      <PageHero
        kicker="产品与服务"
        title="元元与黄金策，以及全链路经营平台"
        lead="顾客侧由元元承接服务，经营侧由黄金策承接管理；后端由商品、客户、交易、生产、仓储、组织六个能力域支撑，四个终端共用数据底座。"
        chips={[
          '2 个 AI：元元与黄金策',
          `6 个能力域 · ${menuItemCount} 项功能`,
          '4 个终端',
          '算料 · 工序 · 批次 · 计件',
        ]}
      />

      {/* ── 元元与黄金策 ──────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="核心 AI 产品"
            title="元元服务顾客，黄金策管理经营"
            lead="元元与黄金策读取真实经营数据：顾客问到的商品、订单与库存，与经营者在后台看到的完全一致。"
          />

          <div className="mt-14 space-y-8">
            {coreProducts.map((product) => (
              <div
                key={product.title}
                className="rounded-3xl border border-neutral-200 bg-neutral-50/60 p-8 sm:p-10"
              >
                <div className="flex flex-col gap-8 lg:flex-row">
                  <div className="lg:w-80 lg:shrink-0">
                    <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-primary-700">
                      <product.icon className="h-7 w-7 text-white" />
                    </div>
                    <h2 className="mt-5 text-2xl font-bold text-neutral-900">{product.title}</h2>
                    <p className="mt-2 text-sm font-medium text-accent-600">{product.tagline}</p>
                    <p className="mt-5 rounded-xl border border-neutral-200 bg-white px-4 py-3 text-xs leading-relaxed text-neutral-600">
                      <span className="font-semibold text-neutral-800">能力边界：</span>
                      {product.boundary}
                    </p>
                  </div>

                  <div className="grid flex-1 grid-cols-1 gap-3 sm:grid-cols-2">
                    {product.features.map((feature) => (
                      <div
                        key={feature}
                        className="flex items-start gap-3 rounded-xl border border-neutral-200 bg-white p-4"
                      >
                        <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary-600" />
                        <span className="text-sm leading-relaxed text-neutral-700">{feature}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 四个终端 ─────────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="四个终端"
            title="四类角色，四个入口"
            lead="同一租户、同源数据，按角色提供不同入口与权限，车间工人无需使用管理后台。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {terminals.map((terminal) => (
              <div
                key={terminal.title}
                className="flex flex-col rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
              >
                <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-neutral-100">
                  <terminal.icon className="h-6 w-6 text-primary-600" />
                </div>
                <h3 className="mt-5 text-lg font-bold text-neutral-900">{terminal.title}</h3>
                <p className="mt-1 text-xs font-medium text-accent-600">{terminal.audience}</p>
                <p className="mt-3 text-sm leading-relaxed text-neutral-600">
                  {terminal.description}
                </p>
                <ul className="mt-5 flex-1 space-y-2 border-t border-neutral-100 pt-5">
                  {terminal.points.map((point) => (
                    <li key={point} className="flex items-start gap-2 text-xs text-neutral-600">
                      <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary-600" />
                      <span className="leading-relaxed">{point}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 六个能力域 ───────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="能力清单"
            title="六个能力域，逐项展开"
            lead="以下每一项都是后台中可打开的功能入口。"
          />
          <div className="mt-14 space-y-6">
            {capabilityDomains.map((domain) => (
              <div
                key={domain.key}
                className="rounded-2xl border border-neutral-200 bg-neutral-50/60 p-6 sm:p-8"
              >
                <div className="flex flex-col gap-2 sm:flex-row sm:items-baseline sm:justify-between">
                  <h3 className="text-lg font-bold text-neutral-900">{domain.name}</h3>
                  <p className="text-sm text-neutral-500">{domain.summary}</p>
                </div>
                <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
                  {domain.items.map((item) => (
                    <div
                      key={item.name}
                      className="flex items-start gap-3 rounded-xl border border-neutral-200 bg-white p-4"
                    >
                      <item.icon className="mt-0.5 h-5 w-5 shrink-0 text-accent-600" />
                      <div>
                        <p className="text-sm font-semibold text-neutral-900">{item.name}</p>
                        <p className="mt-1 text-sm leading-relaxed text-neutral-600">
                          {item.detail}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {standaloneEntries.map((item) => (
                <div
                  key={item.name}
                  className="flex items-start gap-3 rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
                >
                  <item.icon className="mt-0.5 h-5 w-5 shrink-0 text-primary-600" />
                  <div>
                    <p className="text-sm font-semibold text-neutral-900">{item.name}</p>
                    <p className="mt-1 text-sm leading-relaxed text-neutral-600">{item.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── 行业纵深 ─────────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="行业纵深"
            title="布艺经营的四项核心能力"
            lead="通用客服机器人难以覆盖这四项能力，而它们正是观星台产品设计的起点。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {industryDepth.map((item) => (
              <div
                key={item.title}
                className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
              >
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-neutral-900">
                  <item.icon className="h-5 w-5 text-gold-500" />
                </div>
                <h3 className="mt-5 text-base font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{item.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 交付与开通 ───────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="交付与开通"
            title="开通流程简单，无需自建基础设施"
            lead="无需自备服务器与 IT 人员：提交申请、AI 自动甄别、即刻开通，行业模板与岗位权限均已预置。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {delivery.map((item) => (
              <div
                key={item.title}
                className="rounded-2xl border border-neutral-200 bg-neutral-50/60 p-6"
              >
                <item.icon className="h-6 w-6 text-primary-600" />
                <h3 className="mt-4 text-base font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{item.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <CallToAction
        title="了解观星台是否适配您的业务"
        lead="提交入驻申请，AI 自动甄别后即刻开通；也可先留言说明业务场景，我们将按您的流程安排演示。"
        primary={
          <Link
            href="/register"
            className="group inline-flex items-center gap-2 rounded-xl bg-white px-7 py-3.5 text-base font-semibold text-neutral-900 transition-colors hover:bg-neutral-100"
          >
            立即入驻
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        }
        secondary={
          <Link
            href="/contact"
            className="inline-flex items-center gap-2 rounded-xl border border-white/25 px-7 py-3.5 text-base font-semibold text-white transition-colors hover:bg-white/10"
          >
            联系我们
          </Link>
        }
      />
    </>
  )
}
