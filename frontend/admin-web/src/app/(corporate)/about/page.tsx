import type { Metadata } from 'next'
import Link from 'next/link'
import { ArrowRight, Eye, Heart, Lightbulb, Lock, Sprout, Target } from 'lucide-react'
import { CallToAction, PageHero, SectionHeading } from '@/components/corporate/CorporateSection'

export const metadata: Metadata = {
  title: '关于米高 — 把一间布艺店的经营装进 AI',
  description:
    '杭州词元通达科技有限公司出品的米高平台：面向布艺 / 窗帘商家的多租户 AI 经营平台，顾客侧小布、经营侧米宝，覆盖商品、客户、交易、生产、仓储、组织六个能力域。',
}

const values = [
  {
    icon: Lightbulb,
    title: '技术驱动',
    description: '把大模型能力落到具体动作上：能查的查、能算的算、不能做的明确说不能做。',
  },
  {
    icon: Heart,
    title: '客户至上',
    description: '功能按商家的真实流程排优先级，不按演示效果好不好看排。',
  },
  {
    icon: Sprout,
    title: '行业深耕',
    description: '算料、工序、批次、计件这些布艺行业的粗活，恰恰是我们花力气最多的地方。',
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
    description: '确定产品方向与技术路线：顾客侧与经营侧两位 AI 助手，加多租户 SaaS 底座。',
  },
  {
    period: '2024 Q2',
    title: '核心引擎开发',
    description: '搭建双 Agent 引擎与业务工具层，两位助手的技能与工具分工成型。',
  },
  {
    period: '2024 Q3',
    title: '平台上线',
    description: '商家管理后台发布，米宝接入后台；商品、订单、售后等基础模块跑通首批商家。',
  },
  {
    period: '2024 Q4',
    title: '多渠道接入',
    description: '微信小程序上线，顾客在小程序内完成咨询、下单与售后。',
  },
  {
    period: '2025',
    title: '能力进化',
    description:
      '持续接入更深的能力：生产工序、仓储批次、财务对账与计件工资陆续上线，服务更多行业商家。',
  },
]

const principles = [
  {
    title: '答不出的，明说答不出',
    description:
      'AI 只按店内真实数据与已发布知识作答：不编造订单、物流、金额，不报库存数量，不展示未上架商品。',
  },
  {
    title: '价格这件事，不由模型说了算',
    description:
      '顾客侧成交单价取商品库权威价；经营侧改价必须带上改前价并点确认卡，服务端按值核对。',
  },
  {
    title: '敏感事项不做决定',
    description:
      '涉及价格、折扣、退款金额、赔偿与法律诉求，AI 只做规则解释与材料收集，申请类动作一律待人工或规范流程确认。',
  },
  {
    title: '能力边界写在明处',
    description:
      '页面、对话与文档里都写清楚 AI 能做什么、不做什么 —— 让商家知道把哪一段交给 AI 是安全的。',
  },
]

export default function AboutPage() {
  return (
    <>
      <PageHero
        kicker="关于我们"
        title="关于米高"
        lead="米高是杭州词元通达科技有限公司旗下的 AI 经营平台。我们做的事很具体：让一位 AI 在店里接待顾客，让另一位 AI 帮老板把商品、订单、生产、库存和账目看住。"
        chips={['杭州词元通达科技有限公司', '布艺 / 窗帘行业', '多租户 SaaS']}
      />

      {/* ── 我们是谁 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-3xl space-y-6 text-base leading-relaxed text-neutral-600 sm:text-lg">
            <p>
              布艺商家的日常，和标准品零售很不一样：一款窗帘要按颜色 × 售卖方式 × 门幅组合出几十个规格，
              加工费要按米和套算，订单下完还要排工序、派单、报工、计件，布料入库有批次和缸号，裁剪之后还有余料。
              这些环节一旦靠 Excel 和微信群接力，信息就会散在十几个人手里。
            </p>
            <p>
              米高把这套流程装进了一件事里：一套多租户 SaaS，两个 AI 助手。顾客侧是小布 —— 7×24 接待咨询、
              算料报价、下单、查物流、受理售后；经营侧是米宝 —— 用一句问话查订单、查加工单进度、查库存批次、
              查计件工资、查应收对账。两位 AI 共用同一套业务数据，看到的和后台里的一致。
            </p>
            <p>
              我们不试图把 AI 说成万能：能查的查、能算的算、能落成工单的落成工单；做不到的，AI 会直说做不到，
              并把边界交代在页面上。这是我们把产品交付出去的前提。
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
                让中小布艺商家也能用得起一套完整的经营系统：把客服、订单、生产、库存和账目交给 AI 与系统，
                把时间还给人。
              </p>
            </div>

            <div className="rounded-2xl border border-neutral-200 bg-white p-8 shadow-card">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-accent-500 to-accent-700">
                <Eye className="h-6 w-6 text-white" />
              </div>
              <h2 className="mt-5 text-xl font-bold text-neutral-900">我们的愿景</h2>
              <p className="mt-3 leading-relaxed text-neutral-600">
                成为布艺行业最懂业务的 AI 经营平台：通用客服做不了的那一段 —— 算料、工序、批次、计件 ——
                正是我们的护城河。
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
            title="我们怎么理解「让 AI 做客服」"
            lead="这四条决定了米高的 AI 长什么样 —— 也决定了它不会长成什么样。"
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
          <SectionHeading kicker="发展历程" title="一步一个模块，把流程跑通" />

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
        title="想看看它在你的店里是什么样？"
        lead="提交入驻申请，AI 自动甄别后即刻开通；也欢迎先留言说明业务场景，我们按你的流程演示一遍。"
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
