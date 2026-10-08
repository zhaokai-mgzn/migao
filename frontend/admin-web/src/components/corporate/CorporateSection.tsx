import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * 官网（企业站）共用版式（issue #6291）。
 *
 * 为什么共用：首页 / 产品与服务 / 关于我们 / 联系我们 四页此前各写一遍
 * `bg-gradient-to-br from-blue-600 via-blue-700 to-indigo-800` 的页头与
 * `text-sm font-semibold text-primary-600 uppercase` 的小标签 —— 4 份副本必然漂移。
 *
 * 视觉口径 = 产品自身的「织物质感」token（`frontend/admin-web/tailwind.config.ts`）：
 * 暖亚麻底 neutral-50/100、靛蓝 primary、陶土 accent，配 Logo 的织金；不再用通用蓝色渐变模板。
 */

/** 区块小标签 + 标题 + 导语（四页统一） */
export function SectionHeading({
  kicker,
  title,
  lead,
  align = 'center',
}: {
  kicker: string
  title: ReactNode
  lead?: ReactNode
  align?: 'center' | 'left'
}) {
  return (
    <div
      className={cn(
        'max-w-3xl',
        align === 'center' ? 'mx-auto text-center' : 'text-left'
      )}
    >
      <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent-600">
        {kicker}
      </span>
      <h2 className="mt-3 text-2xl sm:text-3xl lg:text-4xl font-bold tracking-tight text-neutral-900">
        {title}
      </h2>
      {lead ? (
        <p className="mt-4 text-base sm:text-lg leading-relaxed text-neutral-600">{lead}</p>
      ) : null}
    </div>
  )
}

/** 内页页头（产品与服务 / 关于我们 / 联系我们 共用；首页有自己的 Hero） */
export function PageHero({
  kicker,
  title,
  lead,
  chips = [],
}: {
  kicker: string
  title: string
  lead: ReactNode
  chips?: string[]
}) {
  return (
    <section className="relative overflow-hidden bg-neutral-900 text-white">
      {/* 织物质感底纹：靛蓝 / 陶土 / 织金三团柔光 */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -top-24 -right-16 h-72 w-72 rounded-full bg-primary-500/25 blur-3xl" />
        <div className="absolute -bottom-28 -left-20 h-72 w-72 rounded-full bg-accent-500/20 blur-3xl" />
        <div className="absolute top-1/3 left-1/2 h-56 w-56 -translate-x-1/2 rounded-full bg-[#d48806]/10 blur-3xl" />
      </div>
      <div className="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-14 sm:py-20">
        <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent-300">
          {kicker}
        </span>
        <h1 className="mt-3 text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight">
          {title}
        </h1>
        <p className="mt-4 max-w-3xl text-base sm:text-lg leading-relaxed text-neutral-200">
          {lead}
        </p>
        {chips.length > 0 && (
          <div className="mt-8 flex flex-wrap gap-2.5">
            {chips.map((chip) => (
              <span
                key={chip}
                className="inline-flex items-center rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs sm:text-sm text-neutral-200"
              >
                {chip}
              </span>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}

/** 结论条：用于每页收口的单一行动号召 */
export function CallToAction({
  title,
  lead,
  primary,
  secondary,
}: {
  title: string
  lead: ReactNode
  primary?: ReactNode
  secondary?: ReactNode
}) {
  return (
    <section className="bg-neutral-900 text-white">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 py-16 sm:py-20 text-center">
        <h2 className="text-2xl sm:text-3xl font-bold tracking-tight">{title}</h2>
        <p className="mt-4 mx-auto max-w-2xl text-base leading-relaxed text-neutral-300">{lead}</p>
        {(primary || secondary) && (
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            {primary}
            {secondary}
          </div>
        )}
      </div>
    </section>
  )
}
