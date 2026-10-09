'use client'

/**
 * 「配置主线」常驻面 —— `/settings/params` 的第一块（issue #6573）。
 *
 * ## 它回答的那个问题
 *
 * 用户 2026-10-08 逐字：「工艺配置那里的东西太多了，比较乱，逻辑混乱，而且太分散，
 * **没有一条清晰的路径引导用户去完成配置**」。
 * 本组件就是那条路径的**渲染面**：按**依赖顺序**列出配置步骤，每步给「状态 + 为什么 + 不配会怎样 + 去处」。
 *
 * ## 🔴 本组件**只渲染**，不取数、不判定（可被判据检查）
 *
 * 取数与判定都在页面（`frontend/admin-web/src/app/(dashboard)/settings/params/page.tsx`）：
 * 仓内口径是「**页面源码里由 `useEffect` 驱动的可执行面 = 第一屏读端点**」
 * （`tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `page_first_screen_text`，四跳现取端点码）
 * —— 把第一屏的取数藏在子组件里，`MENU_READ_ENDPOINT_ANCHORS` 那一跳就**看不见它**，
 * 于是「本页第一屏到底调了哪些码」变成一句没人能核的话。
 * `states` 由页面用 `@/lib/config-readiness` 的**纯判据**算好后传进来（单一真值）。
 *
 * ## 形态纪律（`migao-dev-flow` §31）
 *
 * - **P1 常驻面克制**：常驻 = **一行摘要**（完成数 + 缺口 + 下一步）+ 一个可点的展开按钮；
 *   逐项明细**按需展开**，且展开区 `max-h + overflow-y-auto`。🔴 **折叠态下逐项 DOM 不渲染**
 *   （`queryByTestId('readiness-item-*')` 取不到才是机器读数 —— CSS 隐藏 / `sr-only` 不算）。
 * - **P2 信息不重复**：摘要说「几项没配」，明细说「哪一项、为什么、去哪」—— 摘要**不复述**逐项文案。
 * - **P3 不摆内部标识**：上屏只有菜单名与人话，不出现权限码 / 端点 / 表名。
 * - **P4 语调**：只陈述**事实 + 该做什么**，不责备、不催促。
 */
import { useState } from 'react'
import Link from 'next/link'
import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
import { InlineMarkdown } from '@/lib/inline-markdown'
import {
  MAINLINE_STEPS,
  readinessHeadline,
  summarizeReadiness,
  type ReadinessState,
} from '@/lib/config-readiness'

export interface ConfigReadinessBarProps {
  /** 逐步骤三态（键 = `MAINLINE_STEPS[].key`；**缺键按 `unknown` 读**，不按 `todo`） */
  states: Record<string, ReadinessState>
  /** 读数是否仍在路上（**不谎报**：加载中不显示任何一步为「待配置」） */
  loading: boolean
  /**
   * 可选：给了就把「去配置」渲染成**页内跳转**（设计 G3：不把人送出页面）—— 入参 = 步骤 key。
   *
   * 为什么不直接改 `MAINLINE_STEPS[].href`：同一块主线**还被别的持有者渲染**（工艺配置页自带的
   * 就绪面），那边的去处是**跨页**的；把 href 改成页内锚点会让那边的链接**指向不存在的域**。
   * 所以这里做成**可选的渲染形态**：新页传 `onGoto`（页内），老面不传（保持跨页链接）。
   */
  onGoto?: (stepKey: string) => void
}

/** 三态徽标（**不出现第四种形态**；`unknown` 的措辞必须与 `todo` 明显不同） */
const STATE_COPY: Record<ReadinessState, { text: string; className: string }> = {
  done: { text: '已配置', className: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  todo: { text: '待配置', className: 'bg-amber-50 text-amber-700 border-amber-200' },
  unknown: { text: '读不到', className: 'bg-neutral-100 text-neutral-600 border-neutral-200' },
}

export function ConfigReadinessBar({ states, loading, onGoto }: ConfigReadinessBarProps) {
  const [open, setOpen] = useState(false)

  const entries = MAINLINE_STEPS.map((s) => ({
    key: s.key,
    blocking: s.blocking,
    state: states[s.key] ?? ('unknown' as ReadinessState),
  }))
  const summary = summarizeReadiness(entries)
  const nextStep =
    MAINLINE_STEPS.find((s) => states[s.key] === 'todo') ??
    MAINLINE_STEPS.find((s) => states[s.key] === 'unknown') ??
    null
  const headline = loading
    ? '配置主线读取中…'
    : readinessHeadline(summary, nextStep ? nextStep.label : null)

  return (
    <div data-testid="config-readiness" className="bg-white border border-neutral-200 rounded-lg">
      <button
        type="button"
        data-testid="config-readiness-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-6 py-4 text-left hover:bg-neutral-50 rounded-lg"
      >
        {open ? (
          <ChevronDown className="w-4 h-4 text-neutral-400 flex-shrink-0" />
        ) : (
          <ChevronRight className="w-4 h-4 text-neutral-400 flex-shrink-0" />
        )}
        <span className="text-sm font-medium text-neutral-900 flex-shrink-0">配置主线</span>
        <span data-testid="config-readiness-headline" className="text-sm text-neutral-600 min-w-0">
          {headline}
        </span>
      </button>

      {open && (
        <ul
          data-testid="config-readiness-list"
          className="border-t border-neutral-100 divide-y divide-neutral-100 max-h-80 overflow-y-auto"
        >
          {MAINLINE_STEPS.map((s, i) => {
            const st = states[s.key] ?? 'unknown'
            const copy = STATE_COPY[st]
            return (
              <li
                key={s.key}
                data-testid={`readiness-item-${s.key}`}
                className="px-6 py-3 flex items-start gap-3"
              >
                <span className="text-xs text-neutral-400 mt-0.5 w-4 flex-shrink-0">{i + 1}</span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium text-neutral-900">{s.label}</span>
                    <span
                      data-testid={`readiness-state-${s.key}`}
                      className={`text-xs px-1.5 py-0.5 rounded border ${copy.className}`}
                    >
                      {copy.text}
                    </span>
                  </div>
                  <p className="text-xs text-neutral-500 mt-1">
                    <InlineMarkdown text={s.why} />
                  </p>
                  {st !== 'done' && (
                    <p className="text-xs text-neutral-600 mt-1">
                      <InlineMarkdown text={s.impact} />
                    </p>
                  )}
                </div>
                {onGoto ? (
                  // 页内跳转（设计 G3）：跳到本页那个域，**不离开页面** —— 这是「一条走得完的路」的关键
                  <button
                    type="button"
                    data-testid={`readiness-goto-${s.key}`}
                    onClick={() => onGoto(s.key)}
                    className="inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:underline flex-shrink-0 mt-0.5"
                  >
                    去配置
                    <ChevronRight className="w-3 h-3" />
                  </button>
                ) : (
                  <Link
                    href={s.href}
                    data-testid={`readiness-goto-${s.key}`}
                    className="inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:underline flex-shrink-0 mt-0.5"
                  >
                    去配置
                    <ExternalLink className="w-3 h-3" />
                  </Link>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

export default ConfigReadinessBar