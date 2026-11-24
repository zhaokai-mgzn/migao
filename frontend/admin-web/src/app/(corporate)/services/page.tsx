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
} from 'lucide-react'
import { CallToAction, PageHero, SectionHeading } from '@/components/corporate/CorporateSection'
import { AI_ROLES } from '@/config/ai-roles'
// 内测期隐藏自助入驻入口（issue #9066）：开关单一来源见 @/config/onboarding
import { SELF_SERVICE_ONBOARDING_OPEN } from '@/config/onboarding'
import { capabilityDomains, industryDepth } from '@/components/corporate/capability-map'

export const metadata: Metadata = {
  title: '产品能力 — 顾客经营、经营决策与业务全链路',
  description:
    `生意管家产品能力：顾客侧米宝${AI_ROLES.xiaobu}，经营侧黄金策${AI_ROLES.mibao}；管理后台、顾客小程序、商家小程序、员工端 H5 四个终端，覆盖客户服务、订单/商品、生产、质量、仓储、财务、供应链与组织八个能力域。`,
}

const coreProducts = [
  {
    title: `米宝 · ${AI_ROLES.xiaobu}`,
    icon: MessageSquare,
    tagline: '顾客侧：从规格咨询到下单、物流查询与售后受理',
    features: [
      '按店内已上架商品回答颜色、门幅与加工项，不展示未上架商品',
      '按尺寸与工艺计算用料并给出估算报价，明确说明为估算而非成交价',
      '短信验证码校验后下单，成交单价取商品库权威价',
      '订单进度、物流轨迹与收货地址查询',
      '售后咨询与申请受理，工单恒为「待商家审核」',
      '按店内已发布知识作答；顾客发图可识别并给出解读',
    ],
    boundary:
      '不做：改价、取消订单、退款、承诺优惠折扣、报库存数量。涉及价格与赔偿只解释规则、收集材料，落到工单由商家确认。',
  },
  {
    title: `黄金策 · ${AI_ROLES.mibao}`,
    icon: Bot,
    tagline: '经营侧：用自然语言查账、跟进度、处理经营事项',
    features: [
      '经营看板与每日简报：订单量、销售额、环比与待处理事项',
      '商品与 SKU：批量改价、批量库存调整（可撤销）、商品改名与资料维护',
      '订单与加工单：订单查询、物流、加工单进度与工序报工明细',
      '库存与入库：批次库存、库存台账、入库单与批次成本',
      '生产与计件：工序库、工艺路线、计件工资与报工明细',
      '财务与客户：资金流水、收支汇总、应收对账、客户档案与售后工单',
    ],
    boundary:
      '可写：改价、商品改名、批量改价与批量库存调整、通知标记已读、定时提醒；上下架与删除不做。改价须携带改前价并经确认卡确认；AI 不创建订单与商品。',
  },
]

const terminals = [
  {
    icon: Globe,
    title: '管理后台',
    audience: '老板 / 运营 / 客服',
    description: '浏览器打开即用，经营数据与业务功能集中在后台；右下角可随时向黄金策提问。',
  },
  {
    icon: Smartphone,
    title: '顾客小程序',
    audience: '终端消费者',
    description: '在微信内直接咨询米宝、下单、查询物流与提交售后，无需额外下载。',
  },
  {
    icon: MessageSquare,
    title: '商家小程序',
    audience: '老板 / 员工 / 工人',
    description: '移动端问黄金策、看数据、处理会话，并提供工人登录与拍照入库入口。',
  },
  {
    icon: ScanLine,
    title: '员工端 H5',
    audience: '车间工人',
    description: '扫码即开，无需安装 App：扫码报工、拍照入库与发货；一体机提供常驻扫码的机台模式。',
  },
]

const delivery = [
  {
    icon: Sparkles,
    title: '行业模板预置',
    description: '布艺行业通用知识模板已预置，开通后即可套用，再按企业话术补充。',
  },
  {
    icon: Users,
    title: '岗位权限预置可调',
    description: '常用岗位开箱可用，员工菜单权限逐人可调，权限树与后台菜单同源。',
  },
  {
    icon: Headphones,
    title: '按场景确认交付',
    description: '开通模块、数据衔接与培训方式按企业流程逐项确认；价格与合同另行沟通。',
  },
]

export default function ServicesPage() {
  return (
    <>
      <PageHero
        kicker="产品能力"
        title="两条 AI，共用业务底座"
        lead="顾客侧由米宝承接服务，经营侧由黄金策承接经营问答；商品、订单、生产、仓储与财务在同一业务系统上流转，四个终端共用数据。"
        chips={[
          `2 个 AI：米宝与黄金策`,
          `${capabilityDomains.length} 个能力域`,
          '4 个终端',
          '算料 · 工序 · 批次 · 计件',
        ]}
      />

      {/* ── 双 AI ────────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="双 AI 分工"
            title="米宝服务顾客，黄金策服务经营"
            lead="两侧读取同源经营数据：顾客问到的商品、订单与库存，与经营者在后台看到的保持一致。"
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

      {/* ── 能力域 ───────────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="能力域"
            title="八个能力域，覆盖日常经营"
            lead="每个能力域说明解决的问题；内部菜单与页面属于交付细节，不在官网展开。"
          />
          <div className="mt-14 grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-4">
            {capabilityDomains.map((domain) => (
              <div
                key={domain.key}
                className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-card"
              >
                <h3 className="text-base font-bold text-neutral-900">{domain.name}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{domain.summary}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 行业纵深 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="行业纵深"
            title="布艺经营的四项核心能力"
            lead="通用客服工具覆盖不到这四项能力；它们决定报价、交付与成本是否算得清。"
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

      {/* ── 四个终端 ─────────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="四个终端"
            title="四类角色，四个入口"
            lead="同一企业、同源数据，按角色提供入口与权限；车间工人无需使用管理后台。"
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
            title="无需自建基础设施"
            lead="行业模板与岗位权限已预置；开通范围与数据衔接按企业流程确认。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-3">
            {delivery.map((item) => (
              <div key={item.title} className="rounded-2xl border border-neutral-200 bg-neutral-50/60 p-6">
                <item.icon className="h-6 w-6 text-primary-600" />
                <h3 className="mt-4 text-base font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{item.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <CallToAction
        title="了解生意管家是否适配您的业务"
        lead={
          SELF_SERVICE_ONBOARDING_OPEN
            ? '提交入驻申请，AI 自动甄别后即可开通；也可先留言说明业务场景，我们将按您的流程安排演示。'
            : '可先预约演示并说明业务场景，我们将按您的流程逐项确认；套餐与开通方式由团队与您确认。'
        }
        primary={
          SELF_SERVICE_ONBOARDING_OPEN ? (
            <Link
              href="/register"
              className="group inline-flex items-center gap-2 rounded-xl bg-white px-7 py-3.5 text-base font-semibold text-neutral-900 transition-colors hover:bg-neutral-100"
            >
              立即入驻
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </Link>
          ) : undefined
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
