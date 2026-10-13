// case_ids: UI-097
// 实例判据（issue #6799 ②）：`performance.measure` **不得**因「负时间戳」把页面打成 pageerror。
//
// ## 真栈读数（修前，偶发）
//   [pageerror] TypeError: Failed to execute 'measure' on 'Performance':
//               '​ProcessingRedirectPage' cannot have a negative time stamp.
// 发起方 = React 19 开发态的组件渲染埋点（`logComponentRender` ⇒
// `performance.measure('\u200b'+名, { start: actualStartTime, end: pendingEffectsRenderEndTime })`），
// 不是产品代码（`src/` 里 0 处 `performance.measure`）。
//
// ## 判据怎么取红（注入式，形态与浏览器同款）
// jsdom 的 `performance.measure` **不**校验区间（不会抛）⇒ 必须把它换成**真栈同款**的桩：
//   `end < start` ⇒ 抛 `TypeError: … cannot have a negative time stamp`。
// 在这个桩上：① 不装守卫 ⇒ 抛（这就是"修前"）；② 装上守卫 ⇒ 不抛，且**合法区间仍然被透传**
// （否则就是"靠不记录换不报错"，那是假修）。
//
// ## 边界（照实登记，§19.1）
// - 判的是"非法区间不会把页面打成 pageerror"，不是"埋点数据完整"（非法那一次**有意丢弃**）；
// - 真栈上触发它的时序（`actualStartTime > pendingEffectsRenderEndTime`）无法在单测里复现
//   —— 本判据注入的是**同一形态**（负区间），不是同一个时序现场；
// - 生产构建不启用该 React 埋点，故这个问题只在 dev 可见（见 issue #6799 的读数出处）。

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

/**
 * 以「数字时间戳」的三参形态调用 `performance.measure`（**运行时**合法：Chrome 接受
 * `measure(name, startTime, endTime)`；而 TS 的 DOM 声明只给 `(name, startMark?, endMark?)`
 * 字符串形态与 options 形态 ⇒ 调用点必须显式转型，否则 `tsc --noEmit` 判红）。
 * 每次调用**现取** `performance.measure`，因此守卫的装卸对它同样生效。
 */
function measureWithTimestamps(name: string, start: number, end: number): void {
  const fn = performance.measure as unknown as (n: string, s: number, e: number) => PerformanceMeasure
  fn(name, start, end)
}

/** 真栈同款的浏览器行为桩：负区间 ⇒ 抛 TypeError（jsdom 原生不抛，必须显式换掉）。 */
function installBrowserLikeMeasureStub(): { calls: Array<[string, unknown, unknown]>; restore: () => void } {
  const calls: Array<[string, unknown, unknown]> = []
  const native = performance.measure.bind(performance) as unknown as (
    n: string,
    s?: string | number | PerformanceMeasureOptions,
    e?: string,
  ) => PerformanceMeasure
  const stub = (name: string, startOrOptions?: unknown, endMark?: unknown) => {
    calls.push([name, startOrOptions, endMark])
    const start = typeof startOrOptions === 'number'
      ? startOrOptions
      : (startOrOptions as { start?: number } | undefined)?.start
    const end = typeof endMark === 'number' ? endMark : (startOrOptions as { end?: number } | undefined)?.end
    if (typeof start === 'number' && typeof end === 'number' && end < start) {
      throw new TypeError(`Failed to execute 'measure' on 'Performance': '${name}' cannot have a negative time stamp.`)
    }
    return native(name as string, startOrOptions as string | number | PerformanceMeasureOptions, endMark as string)
  }
  performance.measure = stub as Performance['measure']
  return { calls, restore: () => { performance.measure = native as Performance['measure'] } }
}

/** 以"干净模块"重新 import 守卫（模块顶层会自己装一次 ⇒ 也必须能卸掉）。 */
async function freshGuard() {
  vi.resetModules()
  return await import('@/lib/user-timing-guard')
}

describe('performance.measure 区间守卫（issue #6799 ②）', () => {
  let stub: ReturnType<typeof installBrowserLikeMeasureStub>
  let guard: typeof import('@/lib/user-timing-guard')

  beforeEach(async () => {
    stub = installBrowserLikeMeasureStub()
    guard = await freshGuard()
  })

  afterEach(() => {
    guard.uninstallUserTimingGuard()
    stub.restore()
  })

  it('修前形态：不装守卫时，React 埋点同款的「负区间」调用会把页面打成 pageerror', () => {
    guard.uninstallUserTimingGuard()
    expect(() => measureWithTimestamps('\u200bProcessingRedirectPage', 100, 90)).toThrow(/negative time stamp/)
  })

  it('装上守卫后：负区间不再抛（该次埋点被丢弃，页面不再出 pageerror）', () => {
    expect(() => measureWithTimestamps('\u200bProcessingRedirectPage', 100, 90)).not.toThrow()
    expect(() => performance.measure('\u200bProcessingRedirectPage', { start: 100, end: 90, detail: {} })).not.toThrow()
  })

  it('负控：合法区间必须**照旧透传**（不是"靠不记录换不报错"）', () => {
    const before = stub.calls.length
    measureWithTimestamps('\u200bOkComponent', 100, 120)
    performance.measure('\u200bOkComponent', { start: 100, end: 120 })
    performance.measure('只有名字')
    expect(stub.calls.length, '合法调用必须到达底层 measure').toBe(before + 3)
    expect(stub.calls.slice(before).map((c) => c[0])).toEqual(['\u200bOkComponent', '\u200bOkComponent', '只有名字'])
  })

  it('等值区间（end === start）合法：不得被误丢', () => {
    const before = stub.calls.length
    measureWithTimestamps('\u200bZeroLength', 100, 100)
    expect(stub.calls.length).toBe(before + 1)
  })

  it('幂等：重复安装不会套娃（第二次返回 false，且合法调用仍只到达底层一次）', () => {
    expect(guard.installUserTimingGuard(), '第二次安装应返回 false（已装）').toBe(false)
    const before = stub.calls.length
    measureWithTimestamps('\u200bOnce', 1, 2)
    expect(stub.calls.length).toBe(before + 1)
  })

  it('卸载后可再装：`uninstall` 把原生 measure 还原（判据之间不互相污染）', () => {
    guard.uninstallUserTimingGuard()
    expect(() => measureWithTimestamps('\u200bX', 100, 90)).toThrow(/negative time stamp/)
    expect(guard.installUserTimingGuard()).toBe(true)
    expect(() => measureWithTimestamps('\u200bX', 100, 90)).not.toThrow()
  })
})
