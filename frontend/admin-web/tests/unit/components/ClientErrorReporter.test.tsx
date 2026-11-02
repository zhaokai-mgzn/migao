// case_ids: UI-146
/**
 * 全局错误上报的**客户端接线点**（`frontend/admin-web/src/components/ClientErrorReporter.tsx`，issue #8203）。
 *
 * ## 为什么单测这个「返回 null 的组件」
 * 它是 `window` 监听的**唯一接线面**：`src/app/layout.tsx` 是 Server Component ⇒ 在那边 `import`
 * 一个只在浏览器里有效的守卫只会跑在 Node 侧（同族实测 issue #6946：浏览器里 `__userTimingGuardInstalled`
 * 一直是 `false`）。所以接线必须是一个 `'use client'` 组件，**在模块顶层**调用
 * `installClientErrorHandlers()` —— 早于 React 首次 commit（覆盖 hydration 期崩溃）。
 *
 * 判据绿 ≠ 接线在（`migao-dev-flow` §28.2）：本文件断言的是**真 window 上真的装上了、事件真的被转成请求**，
 * 不是「组件被渲染过」。
 *
 * ## 判据（会红才算）
 * 1. `'use client'` 模块顶层即安装（导入完成时 `window.__migaoClientErrorHandlersInstalled === true`）⇒
 *    把安装挪进 `useEffect` 或删掉 `'use client'` 的顶层调用 ⇒ 红；
 * 2. 组件渲染 `null`（不占位、不影响任何页面布局）；
 * 3. 真 `window.dispatchEvent('error')` ⇒ 真的发出一次上报（source=`window.onerror`）；
 * 4. 多次渲染**不叠加**监听（两次不同错误 ⇒ 恰好两次上报，不是四次）。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'

import ClientErrorReporter from '@/components/ClientErrorReporter'
import { __resetClientErrorReporterForTests } from '@/lib/clientErrorReporter'

type FetchMock = ReturnType<typeof vi.fn>

let fetchMock: FetchMock

function lastBody(): Record<string, unknown> {
  const call = fetchMock.mock.calls[fetchMock.mock.calls.length - 1]
  return JSON.parse(String((call[1] as RequestInit).body))
}

/** 派发一个带额外字段的 window 事件（jsdom 的 `ErrorEvent` / `PromiseRejectionEvent` 不全，用 Event 挂字段）。 */
function dispatchWithField(type: string, field: string, value: unknown): void {
  const event = new Event(type) as Event & Record<string, unknown>
  event[field] = value
  window.dispatchEvent(event)
}

beforeEach(() => {
  __resetClientErrorReporterForTests()
  fetchMock = vi.fn(() => Promise.resolve({ ok: true, status: 204 } as Response))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  __resetClientErrorReporterForTests()
})

describe('全局错误上报的客户端接线（issue #8203）', () => {
  it('模块导入即安装（早于 React commit —— hydration 期崩溃也要被上报）', () => {
    // 本模块在文件头被 import ⇒ 顶层安装已执行
    expect((window as unknown as Record<string, unknown>).__migaoClientErrorHandlersInstalled).toBe(true)
  })

  it('渲染 null（不占位、不改变任何页面布局）', () => {
    const { container } = render(<ClientErrorReporter />)
    expect(container.childNodes).toHaveLength(0)
    expect(container.textContent).toBe('')
  })

  it('真 window 上的 error 事件被转成一次上报（source=window.onerror）', () => {
    render(<ClientErrorReporter />)
    dispatchWithField('error', 'error', new Error('hydration mismatch'))

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(lastBody()).toMatchObject({
      source: 'window.onerror',
      message: 'hydration mismatch',
      // path 永远只留 pathname（jsdom 默认 `/`）
      path: '/',
    })
  })

  it('unhandledrejection（未捕获的 Promise）同样被上报', () => {
    render(<ClientErrorReporter />)
    dispatchWithField('unhandledrejection', 'reason', new Error('promise blew up'))

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(lastBody()).toMatchObject({ source: 'unhandledrejection', message: 'promise blew up' })
  })

  it('多次渲染不叠加监听（两次不同错误 ⇒ 恰好两条上报）', () => {
    render(<ClientErrorReporter />)
    render(<ClientErrorReporter />)
    dispatchWithField('error', 'error', new Error('first'))
    dispatchWithField('error', 'error', new Error('second'))

    expect(fetchMock).toHaveBeenCalledTimes(2)
    const messages = fetchMock.mock.calls.map(
      (call) => JSON.parse(String((call[1] as RequestInit).body)).message,
    )
    expect(messages).toEqual(['first', 'second'])
  })
})
