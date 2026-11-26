import Link from 'next/link'
import type { ReactNode } from 'react'
import { ArrowRight, Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import { FeatureTabs } from './FeatureTabs'

/** 居中的章节标题（对齐参考站的分节节奏，但只用本仓的色板与字号） */
export function SectionIntro({
  kicker,
  title,
  lead,
  className,
}: {
  kicker: string
  title: ReactNode
  lead?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('mx-auto max-w-3xl text-center', className)}>
      <span className="corporate-kicker">{kicker}</span>
      <h2 className="mt-3 text-2xl font-bold tracking-tight text-neutral-900 sm:text-3xl lg:text-4xl">
        {title}
      </h2>
      {lead ? <p className="mt-4 text-base leading-relaxed text-neutral-600 sm:text-lg">{lead}</p> : null}
    </div>
  )
}

/**
 * 产品能力分节：标题 + 标签 + 左文右图（或反向）。
 *
 * 参考站的核心版式 = 每个经营场景一节，标签是场景内的子能力，
 * 卡片里左侧讲“解决什么”，右侧放产品界面。这里保留这套节奏，
 * 但配色 / 字号 / 圆角全部走本仓 design-baseline。
 */
export function ShowcaseBlock({
  id,
  kicker,
  title,
  cardTitle,
  lead,
  tabs,
  tabDetails,
  bullets,
  visual,
  reverse = false,
  tone = 'white',
}: {
  id?: string
  kicker: string
  title: string
  cardTitle?: string
  lead: string
  tabs: string[]
  tabDetails?: string[]
  bullets: string[]
  visual: ReactNode
  reverse?: boolean
  tone?: 'white' | 'linen'
}) {
  return (
    <section id={id} className={cn('py-20 sm:py-28', tone === 'linen' ? 'bg-neutral-50' : 'bg-white')}>
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <SectionIntro kicker={kicker} title={title} lead={lead} />

        <FeatureTabs tabs={tabs} details={tabDetails ?? tabs.map(() => lead)} />

        <div className="mt-10 overflow-hidden rounded-3xl border border-neutral-200 bg-white p-5 shadow-card sm:p-8 lg:p-10">
          <div className="grid grid-cols-1 gap-8 lg:grid-cols-12 lg:items-center">
            <div className={cn('lg:col-span-5', reverse ? 'lg:order-2' : 'lg:order-1')}>
              <h3 className="text-xl font-bold text-neutral-900 sm:text-2xl">{cardTitle ?? title}</h3>
              <p className="mt-3 text-sm leading-relaxed text-neutral-600">{lead}</p>
              <ul className="mt-6 space-y-3">
                {bullets.map((bullet) => (
                  <li key={bullet} className="flex items-start gap-2.5 text-sm leading-relaxed text-neutral-700">
                    <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary-600" />
                    <span>{bullet}</span>
                  </li>
                ))}
              </ul>
              <Link
                href="/services"
                className="mt-7 inline-flex items-center gap-2 text-sm font-semibold text-primary-700 transition-colors hover:text-primary-800"
              >
                了解产品能力
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>

            <div className={cn('lg:col-span-7', reverse ? 'lg:order-1' : 'lg:order-2')}>{visual}</div>
          </div>
        </div>
      </div>
    </section>
  )
}

/** 六格服务支持（参考站「全面服务支持」的节奏，内容只写真实能力） */
export function SupportGrid({
  items,
}: {
  items: { icon: React.ComponentType<{ className?: string }>; title: string; description: string }[]
}) {
  return (
    <div className="mt-12 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => (
        <div key={item.title} className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-card">
          <item.icon className="h-5 w-5 text-primary-600" />
          <h3 className="mt-3 text-sm font-semibold text-neutral-900">{item.title}</h3>
          <p className="mt-1.5 text-sm leading-relaxed text-neutral-600">{item.description}</p>
        </div>
      ))}
    </div>
  )
}
