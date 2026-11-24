'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'

/**
 * 场景内标签：参考站的可切换 pills；只切换**一句说明**，不换产品示意，
 * 避免把「示意」做成需要真实数据的交互。
 */
export function FeatureTabs({ tabs, details }: { tabs: string[]; details: string[] }) {
  const [active, setActive] = useState(0)
  const current = details[active] ?? details[0] ?? ''
  return (
    <div className="mt-8">
      <div className="flex flex-wrap items-center justify-center gap-2" role="tablist">
        {tabs.map((tab, index) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={index === active}
            onClick={() => setActive(index)}
            className={cn(
              'inline-flex whitespace-nowrap rounded-full border px-4 py-1.5 text-sm transition-colors',
              index === active
                ? 'border-primary-600 bg-primary-600 font-medium text-white'
                : 'border-neutral-200 bg-white text-neutral-600 hover:border-primary-200 hover:text-primary-700'
            )}
          >
            {tab}
          </button>
        ))}
      </div>
      <p className="mx-auto mt-4 max-w-2xl text-center text-sm leading-relaxed text-neutral-500">
        {current}
      </p>
    </div>
  )
}
