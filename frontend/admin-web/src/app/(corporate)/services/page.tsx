import type { Metadata } from 'next'
import Link from 'next/link'
import { ArrowRight, Check, Sparkles } from 'lucide-react'
import { CallToAction } from '@/components/corporate/CorporateSection'
import { SectionIntro, ShowcaseBlock } from '@/components/corporate/Showcase'
import { WorkbenchMock, featureVisuals } from '@/components/corporate/ProductVisuals'
import { capabilityDomains, industryDepth } from '@/components/corporate/capability-map'
import {
  deliveryItems,
  domainIcons,
  featureBlocks,
  heroChips,
  terminals,
} from '@/components/corporate/home-content'
// 内测期隐藏自助入驻入口（issue #9066）：开关单一来源见 @/config/onboarding
import { SELF_SERVICE_ONBOARDING_OPEN } from '@/config/onboarding'

export const metadata: Metadata = {
  title: '产品能力 — 顾客经营、经营决策与业务全链路',
  description:
    '生意管家产品能力：顾客侧智能客服承接咨询、算料报价、下单与售后；经营侧黄金策承接商品、订单、生产、库存与财务；管理后台、微信客服、商家小程序与员工端 H5 四个终端。',
}

export default function ServicesPage() {
  return (
    <>
      {/* ── 浅色页头 + 工作台示意 ─────────────────────────────── */}
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
                <span>产品能力 · 顾客经营 / 经营决策 / 业务全链路</span>
              </div>
              <h1 className="mt-6 text-3xl font-extrabold leading-tight tracking-tight text-neutral-900 sm:text-5xl">
                两条 AI
                <br />
                <span className="text-primary-700">共用业务底座</span>
              </h1>
              <p className="mt-5 max-w-2xl text-base leading-relaxed text-neutral-600 sm:text-lg">
                顾客侧由智能客服承接服务，经营侧由黄金策承接经营问答；商品、订单、生产、仓储与财务在同一业务系统上流转，
                管理后台、微信客服、商家小程序与员工端 H5 共用数据。
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Link
                  href="/contact"
                  className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary-600 px-7 py-3.5 text-base font-semibold text-white shadow-sm transition-colors hover:bg-primary-700"
                >
                  预约产品演示
                  <ArrowRight className="h-4 w-4" />
                </Link>
                <Link
                  href="/about"
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-neutral-300 bg-white px-7 py-3.5 text-base font-semibold text-neutral-800 transition-colors hover:bg-neutral-50"
                >
                  了解生意管家
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
            </div>
            <div className="lg:col-span-6">
              <WorkbenchMock />
            </div>
          </div>
        </div>
      </section>

      {/* ── 四个场景分节 ─────────────────────────────────────── */}
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

      {/* ── 八个能力域 ───────────────────────────────────────── */}
      <section className="bg-neutral-50 py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionIntro
            kicker="能力域"
            title="八个能力域，覆盖日常经营"
            lead="每个能力域说明解决的问题；内部菜单与页面属于交付细节，不在官网展开。"
          />
          <div className="mt-14 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {capabilityDomains.map((domain) => {
              const Icon = domainIcons[domain.key as keyof typeof domainIcons] ?? Sparkles
              return (
                <div
                  key={domain.key}
                  className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-card"
                >
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary-50">
                    <Icon className="h-5 w-5 text-primary-700" />
                  </div>
                  <h3 className="mt-4 text-base font-bold text-neutral-900">{domain.name}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-neutral-600">{domain.summary}</p>
                </div>
              )
            })}
          </div>
        </div>
      </section>

      {/* ── 行业纵深 ─────────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionIntro
            kicker="行业纵深"
            title="布艺经营的四项核心能力"
            lead="通用客服工具覆盖不到这四项能力；它们决定报价、交付与成本是否算得清。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {industryDepth.map((item) => (
              <div key={item.title} className="rounded-2xl border border-neutral-200 bg-white p-6 shadow-card">
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
          <SectionIntro
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
                <p className="mt-3 text-sm leading-relaxed text-neutral-600">{terminal.description}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 交付与开通 ───────────────────────────────────────── */}
      <section className="bg-white py-20 sm:py-28">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
          <SectionIntro
            kicker="交付与开通"
            title="无需自建基础设施"
            lead="行业模板与岗位权限已预置；开通范围与数据衔接按企业流程确认。"
          />
          <div className="mt-14 grid grid-cols-1 gap-6 md:grid-cols-3">
            {deliveryItems.map((item) => (
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
