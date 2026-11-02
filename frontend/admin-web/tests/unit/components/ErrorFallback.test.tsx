// case_ids: UI-145
/**
 * 白屏出口（`ErrorFallback` + 四个 `error.tsx` 边界，issue #8203 · P0-03）。
 *
 * ## 病（改前，durable 读数）
 * `grep -rn "Sentry|window.onerror|unhandledrejection" frontend --include=*.ts --include=*.tsx` ⇒ 0 命中；
 * 58 个页面里**只有** `(dashboard)/customers/error.tsx` 一个错误边界 ⇒ 其余页面渲染期异常全部落到
 * Next.js 默认错误页：**整页白屏、没有重试出口、线上无人知道**。
 *
 * ## 判据面（每条都带「会红」的注入形态）
 * | # | 判据 | 会红的注入 |
 * |---|---|---|
 * | 1 | **重试出口在**：点「重试」调用 Next 注入的 `reset()`（白屏的直接出口） | 去掉 onClick ⇒ 红 |
 * | 2 | **回入口在**：`href` 是可用地址，且各边界的落点**按病因选择**（见下） | 全部写成 `/dashboard` ⇒ 红（工作台 layout 崩了会二次白屏） |
 * | 3 | **上报一次**：同一 error 对象只报一次（StrictMode 双 effect / 重渲染不重复） | 去掉 ref 守卫 ⇒ 红 |
 * | 4 | 上报器自己抛也不许把错误页打挂 | 不 try/catch ⇒ 红 |
 * | 5 | `digest` 存在才展示（它是可检索编号；没有就不编一个） | 无 digest 也渲染 ⇒ 红 |
 * | 6 | `global-error.tsx` 必须自带 `<html>` / `<body>`（Next.js 硬约束，替换整个 root layout） | 少一层 ⇒ 红 |
 *
 * ## 落点口径（判据 2 的依据，不是审美）
 * - `app/error.tsx`（无自有边界的路由 + 路由组 layout 自身崩）⇒ 回 `/login`
 *   （它可能正是被「工作台 layout 崩了」触发的，回 `/dashboard` 会立刻再崩一次）；
 * - `(dashboard)/error.tsx` ⇒ 回 `/dashboard`；
 * - `(corporate)/error.tsx`（未登录访客面）⇒ 回站点根 `/`；
 * - `global-error.tsx`（root layout 崩）⇒ 回 `/`。
 */
import { StrictMode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import ErrorFallback from '@/components/common/ErrorFallback'
import type { ErrorFallbackProps } from '@/components/common/ErrorFallback'
import GlobalError from '@/app/global-error'
import AppError from '@/app/error'
import DashboardError from '@/app/(dashboard)/error'
import CorporateError from '@/app/(corporate)/error'

function makeError(message = 'boom', digest?: string): Error & { digest?: string } {
  const error = new Error(message) as Error & { digest?: string }
  if (digest !== undefined) error.digest = digest
  return error
}

/** 上报入参 / 返回值的类型 = 组件 props 上的那一份（不另写一份会漂的口径）。 */
type ReportFn = NonNullable<ErrorFallbackProps['report']>

/** 统一的上报桩（`ReportResult` 的 sent=false 形态；本文件只关心「被调了几次」）。 */
function reportSpy() {
  return vi.fn<ReportFn>(() => ({
    sent: false,
    event: {
      path: '/x',
      name: 'Error',
      message: 'boom',
      stack: '',
      digest: '',
      at: '2026-10-31T00:00:00.000Z',
      ua: '',
      source: 'error-boundary',
    },
    reason: 'not-browser',
  }))
}

describe('1-2. 出口：重试 + 回入口', () => {
  it('点「重试」调用 reset()（白屏的直接出口）', () => {
    const reset = vi.fn()
    render(<ErrorFallback error={makeError()} reset={reset} report={reportSpy()} />)

    fireEvent.click(screen.getByTestId('error-retry'))
    expect(reset).toHaveBeenCalledTimes(1)
  })

  it('回入口默认 /dashboard，可按 props 覆盖（且用整页跳转的原生 <a>，不依赖已坏的 SPA router）', () => {
    const { unmount } = render(
      <ErrorFallback error={makeError()} reset={vi.fn()} report={reportSpy()} />,
    )
    const home = screen.getByTestId('error-home')
    expect(home.tagName).toBe('A')
    expect(home).toHaveAttribute('href', '/dashboard')
    unmount()

    render(
      <ErrorFallback
        error={makeError()}
        reset={vi.fn()}
        report={reportSpy()}
        homeHref="/login"
        homeLabel="回到登录页"
      />,
    )
    expect(screen.getByTestId('error-home')).toHaveAttribute('href', '/login')
    expect(screen.getByText('回到登录页')).toBeInTheDocument()
  })

  it('标题 / 说明可覆盖；默认文案只陈述事实 + 该做什么（不摆内部标识）', () => {
    const { unmount } = render(
      <ErrorFallback error={makeError()} reset={vi.fn()} report={reportSpy()} />,
    )
    expect(screen.getByText('页面加载出错')).toBeInTheDocument()
    expect(screen.getByTestId('error-fallback').textContent).not.toMatch(
      /\b[a-z][a-z_]*:[a-z][a-z_]*\b/,
    )
    unmount()

    render(
      <ErrorFallback
        error={makeError()}
        reset={vi.fn()}
        report={reportSpy()}
        title="客户管理页加载出错"
        description="客户数据暂时没能加载出来"
      />,
    )
    expect(screen.getByText('客户管理页加载出错')).toBeInTheDocument()
    expect(screen.getByText('客户数据暂时没能加载出来')).toBeInTheDocument()
  })
})

describe('3-4. 上报：一次、不重复、自己挂了也不影响页面', () => {
  it('同一 error 对象只上报一次（StrictMode 双 effect 下仍然只有一次）', () => {
    const report = reportSpy()
    const error = makeError('dup-effect', 'digest-1')
    const { rerender } = render(
      <StrictMode>
        <ErrorFallback error={error} reset={vi.fn()} report={report} />
      </StrictMode>,
    )
    rerender(
      <StrictMode>
        <ErrorFallback error={error} reset={vi.fn()} report={report} />
      </StrictMode>,
    )
    expect(report).toHaveBeenCalledTimes(1)
    expect(report.mock.calls[0][0]).toMatchObject({
      source: 'error-boundary',
      digest: 'digest-1',
    })
  })

  it('换成一个新的 error 对象 ⇒ 视为新错误，再报一次', () => {
    const report = reportSpy()
    const { rerender } = render(
      <ErrorFallback error={makeError('first')} reset={vi.fn()} report={report} />,
    )
    rerender(<ErrorFallback error={makeError('second')} reset={vi.fn()} report={report} />)
    expect(report).toHaveBeenCalledTimes(2)
    expect(report.mock.calls[1][0]).toMatchObject({ error: expect.objectContaining({ message: 'second' }) })
  })

  it('上报器自己抛异常 ⇒ 错误页照常渲染（把错误页打挂 = 二次白屏）', () => {
    const report = vi.fn(() => {
      throw new Error('reporter exploded')
    })
    render(
      <ErrorFallback
        error={makeError()}
        reset={vi.fn()}
        report={report as unknown as ReportFn}
      />,
    )
    expect(report).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('error-fallback')).toBeInTheDocument()
    expect(screen.getByTestId('error-retry')).toBeInTheDocument()
  })

  it('source 可覆盖（global-error / 各边界共用同一形态）', () => {
    const report = reportSpy()
    render(
      <ErrorFallback
        error={makeError()}
        reset={vi.fn()}
        report={report}
        source="window.onerror"
      />,
    )
    expect(report.mock.calls[0][0]).toMatchObject({ source: 'window.onerror' })
  })
})

describe('5. digest：有就展示（可检索编号），没有就不编', () => {
  it('有 digest ⇒ 展示；无 digest ⇒ 不渲染那一块', () => {
    const { unmount } = render(
      <ErrorFallback error={makeError('x', 'digest-abc')} reset={vi.fn()} report={reportSpy()} />,
    )
    expect(screen.getByTestId('error-digest')).toHaveTextContent('digest-abc')
    unmount()

    render(<ErrorFallback error={makeError('y')} reset={vi.fn()} report={reportSpy()} />)
    expect(screen.queryByTestId('error-digest')).toBeNull()
  })
})

describe('6. 各路由组边界：同一形态、不同落点', () => {
  const cases = [
    { name: 'app/error', Component: AppError, href: '/login', label: '回到登录页' },
    { name: '(dashboard)/error', Component: DashboardError, href: '/dashboard', label: '回到工作台' },
    { name: '(corporate)/error', Component: CorporateError, href: '/', label: '回到首页' },
  ] as const

  for (const { name, Component, href, label } of cases) {
    it(`${name}：重试可用 + 回入口 = ${href}`, () => {
      vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true, status: 204 } as Response)))
      const reset = vi.fn()
      try {
        render(<Component error={makeError()} reset={reset} />)
        expect(screen.getByTestId('error-home')).toHaveAttribute('href', href)
        expect(screen.getByText(label)).toBeInTheDocument()
        fireEvent.click(screen.getByTestId('error-retry'))
        expect(reset).toHaveBeenCalledTimes(1)
      } finally {
        vi.unstubAllGlobals()
      }
    })
  }

  it('global-error：自带 <html lang> / <body> 并委派给 ErrorFallback（Next.js 硬约束）', () => {
    const element = GlobalError({ error: makeError('root-layout', 'd1'), reset: vi.fn() }) as {
      type: unknown
      props: { lang?: string; children: { type: unknown; props: { children: unknown } } }
    }
    expect(element.type).toBe('html')
    expect(element.props.lang).toBe('zh-CN')
    expect(element.props.children.type).toBe('body')
    expect(element.props.children.props.children).toMatchObject({ type: ErrorFallback })
  })
})
