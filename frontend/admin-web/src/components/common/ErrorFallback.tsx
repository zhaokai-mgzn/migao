'use client'

/**
 * 错误页的**唯一形态**（issue #8203 · P0-03）。
 *
 * 所有 `error.tsx` / `global-error.tsx` 都渲染它 ⇒ 四个路由组 / 根级重试页长得一样、
 * 行为一样（少一处「这个页面忘了加上报」的裂缝）。
 *
 * 三件必须做的事（审计 P0-03 的验收标准 1 / 3）：
 * 1. **重试**（`reset()`）—— 白屏的出口；
 * 2. **回首页 / 回工作台** —— 重试也失败时的第二出口（不把用户困在错误页上）；
 * 3. **上报一次**（`useEffect` + ref 守卫 ⇒ 同一 error 对象只报一次，StrictMode 双调用不重复）。
 *
 * 文案口径（`migao-dev-flow` §31）：只陈述**事实 + 该做什么**，不摆内部标识
 * （不打印错误码以外的栈；`digest` 是 React 给的**可检索编号**，客服/研发据此查日志，故展示）；
 * 不用大幅告警块 —— 这页是「用户此刻的出口」，不是运维看板。
 */
import { useEffect, useRef } from 'react'
import Button from '@/components/ui/Button'
import { reportClientError } from '@/lib/clientErrorReporter'
import type { ClientErrorSource, ReportResult } from '@/lib/clientErrorReporter'

export interface ErrorFallbackProps {
  /** Next.js 注入的错误对象（含 `digest`）。 */
  error: Error & { digest?: string }
  /** Next.js 注入的重试函数。 */
  reset: () => void
  /** 标题（默认「页面加载出错」）。 */
  title?: string
  /** 一句话说明（默认「请重试一次；仍不行就回工作台」）。 */
  description?: string
  /** 回入口的地址（默认 `/dashboard`）。 */
  homeHref?: string
  /** 回入口的文案（默认「回到工作台」）。 */
  homeLabel?: string
  /** 上报来源（默认 `error-boundary`）。 */
  source?: ClientErrorSource
  /** 判据注入点：默认用真实上报器（测试传 `vi.fn()` 断言「被调用一次」）。 */
  report?: (input: { source: ClientErrorSource; error: unknown; digest?: string }) => ReportResult
}

export default function ErrorFallback({
  error,
  reset,
  title = '页面加载出错',
  description = '这个页面暂时没能加载出来。可以重试一次；仍然不行就回到工作台继续操作。',
  homeHref = '/dashboard',
  homeLabel = '回到工作台',
  source = 'error-boundary',
  report = reportClientError as ErrorFallbackProps['report'],
}: ErrorFallbackProps) {
  const reported = useRef<unknown>(null)

  useEffect(() => {
    // 同一个 error 对象只报一次（React 18 StrictMode 会双调用 effect；Next 的 reset 也可能重挂）
    if (reported.current === error) return
    reported.current = error
    try {
      report?.({ source, error, digest: error?.digest })
    } catch {
      // 上报器本身就挂了也**不能**把错误页打挂（页面已经处于故障态）
    }
  }, [error, report, source])

  const digest = typeof error?.digest === 'string' ? error.digest : ''

  return (
    <div
      data-testid="error-fallback"
      className="flex min-h-[400px] flex-col items-center justify-center px-6 py-12 text-center"
    >
      <h2 className="text-lg font-semibold text-neutral-900">{title}</h2>
      <p className="mt-2 max-w-md text-sm leading-6 text-neutral-500">{description}</p>

      {digest ? (
        // 错误编号 = 可检索凭据（客服/研发据此查服务端日志）；它是 React 生成的短摘要，不含内部标识
        <p className="mt-3 text-xs text-neutral-400" data-testid="error-digest">
          错误编号：{digest}
        </p>
      ) : null}

      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        <Button variant="primary" onClick={reset} data-testid="error-retry">
          重试
        </Button>
        {/* 用原生 <a>（**不是** next/link）：错误页上 SPA router 可能已经坏了，
            整页跳转是最后一条可靠出口。
            ⚠️ **不手拼控件铬**（`h-9` + `rounded-lg` + `border-neutral-300` 三位一体）：
            `tests/unit/design-system-form-fields.test.tsx` 的「控件铬只许住在共享原语里」会判红
            （业务面自拼一份 = 第二套设计语言；存量台账**只许缩短** ⇒ 不许加条目）。
            故回入口渲染成**文字链接**（原生 `<a href>`，无边框/底色/padding），
            主操作只留「重试」一个按钮 —— 动作层级清楚，也不与共享原语分叉。 */}
        <a
          href={homeHref}
          data-testid="error-home"
          className="text-sm font-medium text-primary-600 underline-offset-4 transition-colors hover:text-primary-700 hover:underline focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2"
        >
          {homeLabel}
        </a>
      </div>
    </div>
  )
}
