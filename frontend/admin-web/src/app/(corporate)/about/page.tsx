import type { Metadata } from 'next'
import Link from 'next/link'
import {
  ArrowRight,
  BarChart3,
  Bot,
  Heart,
  Layers,
  Lightbulb,
  Lock,
  Sprout,
  Target,
} from 'lucide-react'
import { CallToAction, PageHero, SectionHeading } from '@/components/corporate/CorporateSection'
// 内测期隐藏自助入驻入口（issue #9066）：开关单一来源见 @/config/onboarding
import { SELF_SERVICE_ONBOARDING_OPEN } from '@/config/onboarding'

export const metadata: Metadata = {
  title: '关于生意管家 — 布艺行业的 AI 经营平台',
  description:
    '杭州词元通达科技有限公司出品的生意管家平台：面向布艺 / 窗帘企业的 AI 经营平台，顾客侧智能客服、经营侧黄金策，覆盖商品、客户、交易、生产、仓储与组织等能力域。',
}

const principles = [
  {
    icon: Lightbulb,
    title: '数据之外不作答',
    description:
      'AI 只依据店内真实数据与已发布知识作答：不编造订单、物流与金额，不报库存数量，不展示未上架商品。',
  },
  {
    icon: Lock,
    title: '定价权归属商品库',
    description:
      '顾客侧成交单价取商品库权威价；经营侧改价须带出改前价并经确认卡确认，系统逐项核对。',
  },
  {
    icon: Heart,
    title: '敏感事项不由 AI 决定',
    description:
      '价格、折扣、退款金额、赔偿与法律诉求，AI 只做规则解释与材料收集；申请类动作交由人工或规范流程确认。',
  },
  {
    icon: Target,
    title: '能力边界公开标注',
    description: '页面、对话与文档中均写明 AI 能做什么、不做什么，让商家清楚可以交付给 AI 的范围。',
  },
]

const choices = [
  {
    icon: Layers,
    title: '行业先行',
    description:
      '先把布艺的算料、工序、批次与计件做成可执行的功能，再谈平台化；不追通用的演示效果。',
  },
  {
    icon: BarChart3,
    title: '数据同源',
    description:
      '顾客、经营者与工人看到同一经营数据；AI 的回答能落回系统里的真实记录。',
  },
  {
    icon: Bot,
    title: '边界公开',
    description:
      '没有做「什么都能聊」的通用助手；换来的是答复背后的依据可查，能力边界写在明面上。',
  },
]

export default function AboutPage() {
  return (
    <>
      <PageHero
        kicker="关于我们"
        title="关于生意管家"
        lead="生意管家是杭州词元通达科技有限公司旗下的 AI 经营平台。以布艺行业为起点，把 AI 数智化做成中小企业可负担、可依赖的经营基础设施。"
        chips={['杭州词元通达科技有限公司', '布艺 / 窗帘行业', '企业级 AI 经营平台']}
      />

      {/* ── 我们是谁 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <div className="mx-auto grid max-w-5xl grid-cols-1 gap-12 lg:grid-cols-12">
            <div className="lg:col-span-4">
              <span className="corporate-kicker">我们是谁</span>
              <h2 className="mt-3 text-2xl font-bold tracking-tight text-neutral-900 sm:text-3xl">
                从经营现场长出来的 AI
              </h2>
            </div>
            <div className="space-y-5 text-base leading-relaxed text-neutral-600 sm:text-lg lg:col-span-8">
              <p>
                布艺经营的多数知识，至今仍存放在人身上：算料靠经验系数，排产靠车间里的判断，
                报价靠对客户的了解；系统里留下的，往往只有开单与记账。人员流动、订单增长与规模扩张，
                都会让这些知识流失。
              </p>
              <p>
                所以生意管家先做的是把算料、工序、批次与计件做成可执行的功能，再让 AI 站上去：
                智能客服在顾客侧、黄金策在经营侧，回答都取自同源数据，也都要能落回系统里的真实记录。
              </p>
              <p>
                公司名为词元通达：词元是 AI 的底座，通达是把能力送到经营现场。
                生意管家是这条路径上的产品品牌，也是企业日常经营里可以随时唤起的管家。
              </p>
            </div>
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
                以可负担的成本，让 AI 数智化成为布艺企业经营的基本能力。
              </p>
            </div>
            <div className="rounded-2xl border border-neutral-200 bg-white p-8 shadow-card">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-accent-500 to-accent-700">
                <Sprout className="h-6 w-6 text-white" />
              </div>
              <h2 className="mt-5 text-xl font-bold text-neutral-900">我们的愿景</h2>
              <p className="mt-3 leading-relaxed text-neutral-600">
                让每一家中小企业，都拥有与大企业同等的经营能力。生意管家从布艺行业起步，
                把 AI 数智化带向更多行业，让规模不再是经营能力的边界。
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
            title="AI 的边界与授权"
            lead="能力越大，越需要把授权与边界写清楚。以下四条同时约束产品设计、对话口径与页面文字。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2">
            {principles.map((item) => (
              <div
                key={item.title}
                className="rounded-2xl border border-neutral-200 bg-neutral-50/60 p-6"
              >
                <item.icon className="h-6 w-6 text-accent-600" />
                <h3 className="mt-4 text-base font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{item.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 我们的选择 ───────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="我们的选择"
            title="行业先行，数据同源，边界公开"
            lead="这些选择有代价：不做通用助手，也不承诺超出产品能力的事；换来的是每个答复都有据可查。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-3">
            {choices.map((item) => (
              <div
                key={item.title}
                className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
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
        title="了解生意管家在您的企业如何运行"
        lead={
          SELF_SERVICE_ONBOARDING_OPEN
            ? '提交入驻申请，AI 自动甄别后即可开通；也可先预约演示，按您的业务流程逐项确认。'
            : '预约演示，按您的业务流程逐项确认；套餐与开通方式由团队与您确认。'
        }
        primary={
          <Link
            href="/contact"
            className="group inline-flex items-center gap-2 rounded-xl bg-white px-7 py-3.5 text-base font-semibold text-neutral-900 transition-colors hover:bg-neutral-100"
          >
            联系我们
            <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        }
        secondary={
          <Link
            href="/services"
            className="inline-flex items-center gap-2 rounded-xl border border-white/25 px-7 py-3.5 text-base font-semibold text-white transition-colors hover:bg-white/10"
          >
            查看产品能力
          </Link>
        }
      />
    </>
  )
}
