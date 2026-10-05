import type { Metadata } from 'next'
import Link from 'next/link'
import { ArrowRight, Eye, Heart, Lightbulb, Lock, Sprout, Target } from 'lucide-react'
import { CallToAction, PageHero, SectionHeading } from '@/components/corporate/CorporateSection'

export const metadata: Metadata = {
  title: '关于米高 — 布艺行业的 AI 经营平台',
  description:
    '杭州词元通达科技有限公司出品的米高平台：面向布艺 / 窗帘商家的多租户 AI 经营平台，顾客侧小布、经营侧米宝，覆盖商品、客户、交易、生产、仓储、组织六个能力域。',
}

const values = [
  {
    icon: Lightbulb,
    title: '技术驱动',
    description: '把大模型能力落到具体动作上：可查询的查询、可计算的算，超出范围的明确说明。',
  },
  {
    icon: Heart,
    title: '客户至上',
    description: '功能按商家的真实流程排定优先级，不按演示效果排定。',
  },
  {
    icon: Sprout,
    title: '行业深耕',
    description: '算料、工序、批次、计件这些布艺行业的基础环节，是投入最多的方向。',
  },
  {
    icon: Lock,
    title: '数据安全',
    description: '租户级数据隔离，员工权限逐人可配，关键操作留痕可追溯。',
  },
]

const timeline = [
  {
    period: '2024 Q1',
    title: '项目启动',
    description: '确定产品方向与技术路线：顾客侧与经营侧的 AI 助手，加多租户 SaaS 底座。',
  },
  {
    period: '2024 Q2',
    title: '核心引擎开发',
    description: '搭建双 Agent 引擎与业务工具层，两侧助手的技能与工具分工成型。',
  },
  {
    period: '2024 Q3',
    title: '平台上线',
    description: '商家管理后台发布，米宝接入后台；商品、订单、售后等基础模块服务首批商家。',
  },
  {
    period: '2024 Q4',
    title: '多渠道接入',
    description: '微信小程序上线，顾客可在小程序内完成咨询、下单与售后。',
  },
  {
    period: '2025',
    title: '能力扩展',
    description:
      '生产工序、仓储批次、财务对账与计件工资陆续上线，服务更多行业商家。',
  },
]

const principles = [
  {
    title: '数据之外不作答',
    description:
      'AI 只按店内真实数据与已发布知识作答：不编造订单、物流与金额，不报库存数量，不展示未上架商品。',
  },
  {
    title: '定价权归属商品库',
    description:
      '顾客侧成交单价取商品库权威价；经营侧改价须携带改前价并经确认卡确认，服务端按值核对。',
  },
  {
    title: '敏感事项不由 AI 决定',
    description:
      '涉及价格、折扣、退款金额、赔偿与法律诉求，AI 只做规则解释与材料收集，申请类动作一律待人工或规范流程确认。',
  },
  {
    title: '能力边界公开标注',
    description:
      '页面、对话与文档中均写明 AI 能做什么、不做什么，让商家明确可以交付给 AI 的范围。',
  },
]

export default function AboutPage() {
  return (
    <>
      <PageHero
        kicker="关于我们"
        title="关于米高"
        lead="米高是杭州词元通达科技有限公司旗下的 AI 经营平台。产品目标明确：由 AI 承接门店接待，并协助经营者掌握商品、订单、生产、库存与账目。"
        chips={['杭州词元通达科技有限公司', '布艺 / 窗帘行业', '多租户 SaaS']}
      />

      {/* ── 我们是谁 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-3xl space-y-6 text-base leading-relaxed text-neutral-600 sm:text-lg">
            <p>
              布艺商家的日常经营与标准品零售差异明显：一款窗帘要按颜色 × 售卖方式 × 门幅组合出几十个规格，
              加工费按米与套计算，订单下完还要排工序、派单、报工、计件，布料入库有批次与缸号，裁剪之后还有余料。
              这些环节一旦依赖 Excel 与微信群接力，信息就会分散在十几个人的手中。
            </p>
            <p>
              米高的产品形态是多租户 SaaS 底座，加上顾客侧的小布与经营侧的米宝。顾客侧由小布 7×24 小时接待咨询、
              算料报价、下单、物流查询与售后受理；经营侧由米宝以自然语言问答查询订单、加工单进度、库存批次、
              计件工资与应收对账。两侧读取的数据与后台所见一致。
            </p>
            <p>
              米高不将 AI 描述为万能：可查询的查询，可计算的算，可落成工单的落成工单；超出范围的请求，
              AI 会明确说明，边界同时标注在页面上。这是产品交付的前提。
            </p>
          </div>
        </div>
      </section>

      {/* ── 使命与愿景 ───────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto grid max-w-4xl grid-cols-1 gap-6 md:grid-cols-2">
            <div className="rounded-2xl border border-neutral-200 bg-white p-8 shadow-card">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-primary-700">
                <Target className="h-6 w-6 text-white" />
              </div>
              <h2 className="mt-5 text-xl font-bold text-neutral-900">我们的使命</h2>
              <p className="mt-3 leading-relaxed text-neutral-600">
                把智能化能力的成本与门槛降到中小企业可承受的水平，让布艺商家用得起、也用得上 AI。
              </p>
            </div>

            <div className="rounded-2xl border border-neutral-200 bg-white p-8 shadow-card">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-accent-500 to-accent-700">
                <Eye className="h-6 w-6 text-white" />
              </div>
              <h2 className="mt-5 text-xl font-bold text-neutral-900">我们的愿景</h2>
              <p className="mt-3 leading-relaxed text-neutral-600">
                让智能化与 AI 走进中小企业。米高从布艺行业做起，把过去只有中大型企业才用得起的经营能力，
                交到中小商家手上。
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── 产品原则 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="产品原则"
            title="米高的产品原则"
            lead="这四条原则界定了米高 AI 的能力范围与行为方式。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 sm:grid-cols-2">
            {principles.map((item) => (
              <div key={item.title} className="rounded-2xl border border-neutral-200 bg-neutral-50/60 p-7">
                <h3 className="text-base font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-2.5 text-sm leading-relaxed text-neutral-600">{item.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 核心价值观 ───────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading kicker="核心价值观" title="驱动我们前行的信念" />
          <div className="mx-auto mt-14 grid max-w-5xl grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {values.map((item) => (
              <div
                key={item.title}
                className="rounded-2xl border border-neutral-200 bg-white p-6 text-center shadow-card"
              >
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-neutral-100">
                  <item.icon className="h-6 w-6 text-accent-600" />
                </div>
                <h3 className="mt-4 text-base font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{item.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 发展历程 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading kicker="发展历程" title="按业务模块逐步落地" />

          <div className="mx-auto mt-14 max-w-3xl">
            <ol className="relative space-y-8 border-l border-neutral-200 pl-8">
              {timeline.map((item) => (
                <li key={item.period} className="relative">
                  <span className="absolute -left-[41px] top-1.5 flex h-5 w-5 items-center justify-center rounded-full border-4 border-white bg-primary-600 ring-1 ring-neutral-200" />
                  <div className="rounded-2xl border border-neutral-200 bg-neutral-50/60 p-6">
                    <span className="inline-block rounded-full bg-primary-50 px-3 py-1 text-xs font-bold text-primary-700">
                      {item.period}
                    </span>
                    <h3 className="mt-3 text-base font-semibold text-neutral-900">{item.title}</h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-neutral-600">
                      {item.description}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      <CallToAction
        title="了解米高在您的门店如何运行"
        lead="提交入驻申请，AI 自动甄别后即刻开通；也欢迎先留言说明业务场景，我们将按您的流程安排演示。"
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
            留言咨询
          </Link>
        }
      />
    </>
  )
}
