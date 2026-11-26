import type { Metadata } from 'next'
import Link from 'next/link'
import { ArrowRight, Check, Sparkles } from 'lucide-react'
import { CallToAction } from '@/components/corporate/CorporateSection'
import { SectionIntro, ShowcaseBlock, SupportGrid } from '@/components/corporate/Showcase'
import { WorkbenchMock, featureVisuals } from '@/components/corporate/ProductVisuals'
import { capabilityDomains } from '@/components/corporate/capability-map'
import {
  advantages,
  domainIcons,
  featureBlocks,
  gbPoints,
  heroChips,
  heroFacts,
  industries,
  principles,
  steps,
  supportItems,
} from '@/components/corporate/home-content'
// 内测期隐藏自助入驻入口（issue #9066）：开关单一来源见 @/config/onboarding
import { SELF_SERVICE_ONBOARDING_OPEN } from '@/config/onboarding'

export const metadata: Metadata = {
  title: {
    absolute: '生意管家 — 布艺行业 AI 经营平台｜让经营有据可依',
  },
  description:
    '生意管家是杭州词元通达科技有限公司面向布艺 / 窗帘企业的 AI 经营平台。米宝承接顾客咨询、算料报价、下单与售后；黄金策承接商品、订单、生产、库存与财务。双 AI 分工，四端数据同源。',
}

export default function HomePage() {
  return (
    <>
      {/* ── Hero：浅色产品页头 + 工作台示意 ───────────────────── */}
      <section className="relative overflow-hidden bg-gradient-to-b from-primary-50 via-neutral-50 to-white">
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute -left-24 top-10 h-80 w-80 rounded-full bg-primary-200/40 blur-3xl" />
          <div className="absolute right-0 top-24 h-96 w-96 rounded-full bg-accent-200/30 blur-3xl" />
          <div className="absolute bottom-0 left-1/3 h-72 w-72 rounded-full bg-gold-300/20 blur-3xl" />
        </div>

        <div className="relative mx-auto max-w-7xl px-4 pb-20 pt-16 sm:px-6 sm:pb-24 sm:pt-20 lg:px-8">
          <div className="grid grid-cols-1 items-center gap-12 lg:grid-cols-12">
            <div className="lg:col-span-6">
              <div className="inline-flex items-center gap-2 rounded-full bg-white/80 px-4 py-1.5 text-xs text-primary-700 shadow-sm ring-1 ring-primary-200 backdrop-blur sm:text-sm">
                <Sparkles className="h-4 w-4 text-gold-600" />
                <span>杭州词元通达科技有限公司 · 企业级 AI 经营平台</span>
              </div>

              <h1 className="mt-6 text-3xl font-extrabold leading-tight tracking-tight text-neutral-900 sm:text-5xl lg:text-6xl">
                让经营有据可依
                <br />
                <span className="text-primary-700">让生意每天向前</span>
              </h1>

              <p className="mt-5 max-w-2xl text-base leading-relaxed text-neutral-600 sm:text-lg">
                生意管家是词元通达面向布艺 / 窗帘企业的 AI 经营平台。米宝接待顾客、算料报价、下单与售后；
                黄金策看经营、跟进度、处理商品与财务。两侧读取同源经营数据。
              </p>

              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                {SELF_SERVICE_ONBOARDING_OPEN && (
                  <Link
                    href="/register"
                    className="group inline-flex items-center justify-center gap-2 rounded-xl bg-primary-600 px-7 py-3.5 text-base font-semibold text-white shadow-sm transition-colors hover:bg-primary-700"
                  >
                    免费开通
                    <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                  </Link>
                )}
                <Link
                  href="/contact"
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary-600 px-7 py-3.5 text-base font-semibold text-white shadow-sm transition-colors hover:bg-primary-700"
                >
                  预约产品演示
                  <ArrowRight className="h-4 w-4" />
                </Link>
                <Link
                  href="/services"
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-neutral-300 bg-white px-7 py-3.5 text-base font-semibold text-neutral-800 transition-colors hover:bg-neutral-50"
                >
                  查看产品能力
                </Link>
              </div>

              <div className="mt-8 grid grid-cols-2 gap-2 sm:grid-cols-3">
                {heroChips.map((chip) => (
                  <span
                    key={chip}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-200 bg-white/80 px-3 py-2 text-xs text-neutral-700 sm:text-sm"
                  >
                    <Check className="h-3.5 w-3.5 text-primary-600" />
                    {chip}
                  </span>
                ))}
              </div>

              <div className="mt-6 flex flex-wrap gap-x-4 gap-y-2 text-xs text-neutral-500">
                {heroFacts.map((fact) => (
                  <span key={fact} className="inline-flex items-center gap-1.5">
                    <span className="h-1 w-1 rounded-full bg-accent-500" />
                    {fact}
                  </span>
                ))}
              </div>
            </div>

            <div className="lg:col-span-6">
              <WorkbenchMock />
            </div>
          </div>
        </div>
      </section>

      {/* ── 八个经营场景 ─────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionIntro
            kicker="能力域"
            title="八个能力域，覆盖一家布艺企业的日常"
            lead="从顾客服务到组织权限，后台按能力域组织。官网只说明每个域解决什么，不展开内部菜单。"
          />
          <div className="mt-14 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {capabilityDomains.map((domain) => {
              const Icon = domainIcons[domain.key as keyof typeof domainIcons] ?? Sparkles
              return (
                <div
                  key={domain.key}
                  className="rounded-2xl border border-neutral-200 bg-neutral-50/60 p-5 transition-colors hover:bg-white hover:shadow-card"
                >
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white ring-1 ring-neutral-200">
                    <Icon className="h-5 w-5 text-primary-600" />
                  </div>
                  <h3 className="mt-4 text-base font-bold text-neutral-900">{domain.name}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-neutral-600">{domain.summary}</p>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      {/* ── 四个场景分节：左文右图 / 左图右文 ─────────────────── */}
      {featureBlocks.map((block, index) => {
        const Visual = featureVisuals[block.visual]
        return (
          <ShowcaseBlock
            key={block.id}
            id={block.id}
            kicker={block.kicker}
            title={block.title}
            cardTitle={block.cardTitle}
            lead={block.lead}
            tabs={block.tabs}
            tabDetails={block.tabDetails}
            bullets={block.bullets}
            visual={<Visual />}
            reverse={index % 2 === 1}
            tone={index % 2 === 1 ? 'linen' : 'white'}
          />
        )
      })}

      {/* ── 为什么选择生意管家 ───────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionIntro
            kicker="为什么选择生意管家"
            title="行业原生，数据同源，边界清楚"
            lead="通用工具能回答通用问题；布艺经营的算料、工序、批次与计件，需要按现场长出来的系统。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
            {advantages.map((item) => (
              <div key={item.title} className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-card">
                <item.icon className="h-6 w-6 text-primary-600" />
                <h3 className="mt-4 text-base font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{item.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 平台保障 / 全面服务 ─────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionIntro
            kicker="平台保障"
            title="企业级底座，交付前就把边界写清"
            lead="正规主体、租户隔离、岗位权限与操作审计；行业模板与常用岗位预置，开通即可使用。"
          />
          <SupportGrid items={supportItems} />
        </div>
      </section>

      {/* ── 适用企业 ─────────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionIntro
            kicker="适用企业"
            title="深耕布艺，服务三类经营形态"
            lead="从定制门店到加工厂与批零一体企业，按真实现场组织能力，不用通用模板硬套。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-3">
            {industries.map((item) => (
              <div key={item.name} className="overflow-hidden rounded-3xl border border-neutral-200 bg-white shadow-card">
                <div className="relative h-32 overflow-hidden bg-gradient-to-br from-primary-600 via-primary-700 to-primary-800">
                  <div className="absolute inset-0 opacity-30" aria-hidden="true">
                    <div className="absolute -right-6 -top-6 h-24 w-24 rounded-full border border-white/30" />
                    <div className="absolute bottom-4 left-6 h-16 w-40 rounded-full border border-white/20" />
                    <div className="absolute bottom-0 right-10 h-20 w-20 rounded-full bg-gold-400/30 blur-xl" />
                  </div>
                  <item.icon className="absolute bottom-5 left-6 h-9 w-9 text-gold-300" />
                </div>
                <div className="p-6">
                  <h3 className="text-lg font-bold text-neutral-900">{item.name}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-neutral-600">{item.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 交付流程 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionIntro
            kicker="交付流程"
            title="三步开通，按您的流程落地"
            lead="内测期由团队与您确认开通范围与交付内容，不承诺未经确认的能力。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-3">
            {steps.map((step, index) => (
              <div key={step.title} className="rounded-2xl border border-neutral-200 bg-neutral-50/60 p-7">
                <span className="text-sm font-bold tracking-widest text-accent-600">0{index + 1}</span>
                <h3 className="mt-3 text-lg font-bold text-neutral-900">{step.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{step.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 能力边界 + 国标 ─────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionIntro
            kicker="能力边界"
            title="把 AI 能做什么、不能做什么写在明处"
            lead="AI 只依据店内真实数据与已发布知识作答；价格、退款与赔偿不由模型决定。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-3">
            {principles.map((item) => (
              <div key={item.title} className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-card">
                <item.icon className="h-6 w-6 text-accent-600" />
                <h3 className="mt-4 text-base font-semibold text-neutral-900">{item.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-neutral-600">{item.description}</p>
              </div>
            ))}
          </div>

          <div className="mt-8 rounded-3xl border border-neutral-200 bg-white p-7">
            <p className="text-sm font-semibold tracking-wide text-primary-600">遵循国家标准</p>
            <h3 className="mt-2 text-xl font-bold text-neutral-900">
              GB/T 47746-2026 · 人机协同机制有据可依
            </h3>
            <p className="mt-3 text-sm leading-relaxed text-neutral-600">
              《顾客联络服务 人工与智能客户服务协同要求》为推荐性国家标准。生意管家按其中的协同机制设计能力：
            </p>
            <ul className="mt-5 grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
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
