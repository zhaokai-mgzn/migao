import type { Metadata } from 'next'
import Link from 'next/link'
import { ArrowRight, Check, Sparkles } from 'lucide-react'
import { CallToAction, SectionHeading } from '@/components/corporate/CorporateSection'
import { capabilityDomains, industryDepth } from '@/components/corporate/capability-map'
import {
  advantages,
  capabilityLines,
  enterpriseTypes,
  gbPoints,
  guarantees,
  heroFacts,
  principles,
  steps,
  valuePoints,
} from '@/components/corporate/home-content'
// 内测期隐藏自助入驻入口（issue #9066）：开关单一来源见 @/config/onboarding
import { SELF_SERVICE_ONBOARDING_OPEN } from '@/config/onboarding'

export const metadata: Metadata = {
  title: {
    absolute: '生意管家 — 布艺行业 AI 经营平台｜让 AI 成为每一家企业的经营能力',
  },
  description:
    '生意管家是杭州词元通达科技有限公司面向布艺 / 窗帘企业的 AI 经营平台。米宝承接顾客咨询、算料报价、下单与售后；黄金策承接商品、订单、生产、库存与财务。双 AI 分工，四端数据同源。',
}

export default function HomePage() {
  return (
    <>
      {/* ── Hero：产品定位 + 管家每天处理的三件事 ───────────────── */}
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
                让 AI 成为
                <br />
                <span className="bg-gradient-to-r from-gold-300 via-gold-500 to-accent-300 bg-clip-text text-transparent">
                  每一家企业的经营能力
                </span>
              </h1>

              <p className="mt-6 max-w-2xl text-base leading-relaxed text-neutral-300 sm:text-lg">
                生意管家是词元通达面向布艺 / 窗帘企业的 AI 经营平台。顾客侧由米宝承接咨询、算料报价、
                下单与售后；经营侧由黄金策承接商品、订单、生产、库存与财务。两侧读取同源经营数据。
              </p>

              <div className="mt-9 flex flex-col gap-3 sm:flex-row">
                {SELF_SERVICE_ONBOARDING_OPEN && (
                  <Link
                    href="/register"
                    className="group inline-flex items-center justify-center gap-2 rounded-xl bg-white px-7 py-3.5 text-base font-semibold text-neutral-900 transition-colors hover:bg-neutral-100"
                  >
                    免费开通
                    <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                  </Link>
                )}
                <Link
                  href="/contact"
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-white px-7 py-3.5 text-base font-semibold text-neutral-900 transition-colors hover:bg-neutral-100"
                >
                  预约产品演示
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

            {/* 右侧：管家每天处理的三件事 */}
            <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-6 backdrop-blur-sm lg:col-span-5">
              <p className="text-sm font-semibold tracking-wide text-gold-300">管家每天处理的三件事</p>
              <div className="mt-5 space-y-5">
                {[
                  ['接客', '米宝 7×24 接待常规咨询；复杂诉求按规则交人工，记录同步。'],
                  ['管货', '商品、订单、生产与库存串在同一链路，进度可查。'],
                  ['看账', '经营数据、批次成本、计件工资与应收逐笔可核对。'],
                ].map(([title, description]) => (
                  <div key={title} className="flex gap-3.5">
                    <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-gold-300 to-gold-600 text-sm font-bold text-neutral-900">
                      {title.slice(0, 1)}
                    </span>
                    <div>
                      <p className="text-base font-semibold">{title}</p>
                      <p className="mt-1 text-sm leading-relaxed text-neutral-400">{description}</p>
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-6 border-t border-white/10 pt-4 text-xs leading-relaxed text-neutral-500">
                管理后台、顾客小程序、商家小程序与员工端 H5 共用数据底座。
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ── 经营价值：四件耗人的日常 ─────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="经营价值"
            title="四件耗人的事，交给管家"
            lead="询价、跟单、盘货、对账是布艺经营的日常。生意管家把重复动作收进系统，经营者只处理判断。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
            {valuePoints.map((item) => (
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

      {/* ── 产品能力：三条能力线 ─────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="产品能力"
            title="两条 AI，共用业务底座"
            lead="米宝服务顾客，黄金策服务经营；商品、订单、生产、仓储与财务由同一业务系统承载。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 lg:grid-cols-3">
            {capabilityLines.map((line) => (
              <div
                key={line.title}
                className="flex flex-col rounded-2xl border border-neutral-200 bg-white p-7 shadow-card"
              >
                <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-primary-700">
                  <line.icon className="h-6 w-6 text-white" />
                </div>
                <h3 className="mt-5 text-lg font-bold text-neutral-900">{line.title}</h3>
                <p className="mt-1 text-xs font-medium text-accent-600">{line.subtitle}</p>
                <p className="mt-4 text-sm leading-relaxed text-neutral-600">{line.description}</p>
                <ul className="mt-5 flex-1 space-y-2.5 border-t border-neutral-100 pt-5">
                  {line.points.map((point) => (
                    <li key={point} className="flex items-start gap-2.5 text-sm text-neutral-700">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary-600" />
                      <span>{point}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
          <div className="mt-10 text-center">
            <Link
              href="/services"
              className="inline-flex items-center gap-2 text-sm font-semibold text-primary-700 transition-colors hover:text-primary-800"
            >
              查看完整产品能力
              <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>

      {/* ── 为什么选择生意管家 ───────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="为什么选择生意管家"
            title="行业原生，数据同源，边界清楚"
            lead="通用工具能回答通用问题；布艺经营的算料、工序、批次与计件，需要按现场长出来的系统。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
            {advantages.map((item) => (
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

      {/* ── 能力域（只列域，不展开内部菜单）───────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="能力域"
            title="八个能力域，覆盖日常经营"
            lead="从顾客服务到组织权限，后台按能力域组织。官网只说明每个域解决什么，不展开内部菜单。"
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

      {/* ── 行业纵深 + 适用企业 ─────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="行业纵深"
            title="布艺生意的四道关口，系统原生处理"
            lead="通用客服工具覆盖不到这四项能力；它们决定报价、交付与成本是否算得清。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
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

          <div className="mt-12 flex flex-wrap items-center justify-center gap-3 rounded-2xl border border-neutral-200 bg-neutral-50/60 px-6 py-5">
            <span className="text-sm font-semibold text-neutral-700">适用企业</span>
            {enterpriseTypes.map((item) => (
              <span
                key={item.name}
                className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1.5 text-sm text-neutral-700 ring-1 ring-neutral-200"
              >
                <item.icon className="h-3.5 w-3.5 text-accent-600" />
                {item.name}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* ── 能力边界 + 平台保障 ─────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="能力边界"
            title="把 AI 能做什么、不能做什么写在明处"
            lead="AI 只依据店内真实数据与已发布知识作答；价格、退款与赔偿不由模型决定。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-3">
            {principles.map((item) => (
              <div
                key={item.title}
                className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-card"
              >
                <item.icon className="h-6 w-6 text-accent-600" />
                <h3 className="mt-4 text-base font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{item.description}</p>
              </div>
            ))}
          </div>

          <div className="mt-10 grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-neutral-200 bg-white p-7">
              <p className="text-sm font-semibold tracking-wide text-primary-600">遵循国家标准</p>
              <h3 className="mt-2 text-xl font-bold text-neutral-900">
                GB/T 47746-2026 · 人机协同机制有据可依
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-neutral-600">
                《顾客联络服务 人工与智能客户服务协同要求》为推荐性国家标准。生意管家按其中的协同机制设计能力：
              </p>
              <ul className="mt-5 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                {gbPoints.map((point) => (
                  <li key={point} className="flex items-start gap-2 text-sm text-neutral-700">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary-600" />
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-5 border-t border-neutral-100 pt-4 text-xs leading-relaxed text-neutral-500">
                「遵循 / 对标 GB/T 47746-2026」指米宝智能客服的人机协同机制功能设计参考该推荐性国家标准；
                该标准为推荐性标准、无认证或备案机制，本页面不构成任何认证、检测或备案结论。
              </p>
            </div>

            <div className="rounded-2xl border border-neutral-200 bg-white p-7">
              <p className="text-sm font-semibold tracking-wide text-primary-600">平台保障</p>
              <h3 className="mt-2 text-xl font-bold text-neutral-900">企业级底座：隔离、权限与审计</h3>
              <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
                {guarantees.map((item) => (
                  <div key={item.title} className="flex gap-3">
                    <item.icon className="mt-0.5 h-5 w-5 shrink-0 text-accent-600" />
                    <div>
                      <p className="text-sm font-semibold text-neutral-900">{item.title}</p>
                      <p className="mt-1 text-xs leading-relaxed text-neutral-600">
                        {item.description}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── 开通流程 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionHeading
            kicker="开通流程"
            title="三步开通，按您的流程落地"
            lead="内测期由团队与您确认开通范围与交付内容，不承诺未经确认的能力。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-3">
            {steps.map((step, index) => (
              <div
                key={step.title}
                className="rounded-2xl border border-neutral-200 bg-neutral-50/60 p-7"
              >
                <span className="text-sm font-bold tracking-widest text-accent-600">
                  0{index + 1}
                </span>
                <h3 className="mt-3 text-lg font-bold text-neutral-900">{step.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{step.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <CallToAction
        title="把 AI 带进经营现场"
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
            预约产品演示
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
