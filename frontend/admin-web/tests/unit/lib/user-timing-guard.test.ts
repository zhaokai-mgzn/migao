// case_ids: UI-099
// 实例判据（issue #6799 ② 的守卫；判据本身经 issue #6946 订正）：
// `performance.measure` **不得**因「负时间戳」把页面打成 pageerror。
//
// ## 真栈读数（修前，偶发）
//   [pageerror] TypeError: Failed to execute 'measure' on 'Performance':
//               '​ProcessingRedirectPage' cannot have a negative time stamp.
// 发起方 = React 19 开发态的组件渲染埋点（`logComponentRender` ⇒
// `performance.measure('\u200b'+名, { start: actualStartTime, end: pendingEffectsRenderEndTime })`），
// 不是产品代码（`src/` 里 0 处 `performance.measure`）。
//
// ## 🔴 判据订正（issue #6946，2026-10-15 真栈逐字实测）
// 旧判据把「非法」桩成 **`end < start` ⇒ 抛** —— **与真浏览器不符**（桩的是判据自己的假设）：
//   · `measure('X', { start: -1, end: 10 })` ⇒ **抛** `'X' cannot have a negative time stamp.`
//   · `measure('X', { start: 5,  end: -1 })` ⇒ **抛**（同上）
//   · `measure('X', { start: 100, end: 90 })` ⇒ **不抛**（负**时长**合法）
// ⇒ 现在桩按「**任一时间戳为负 ⇒ 抛**」实现，与浏览器同款；并**新增**一条判别力对照：
//   「负时长（`100 → 90`，两个时间戳都非负）」必须**照旧透传**（旧守卫会误丢它，那种"修"是拿丢埋点换不报错）。
//
// ## 判据怎么取红（注入式）
// jsdom 的 `performance.measure` **不**校验（不会抛）⇒ 必须换成上表的**真栈同款**桩：
//   ① 不装守卫 ⇒ 负时间戳那次抛（这就是"修前"）；
//   ② 装上守卫 ⇒ 不抛，且**合法调用与负时长调用仍然被透传**。
//
// ## 边界（照实登记，§19.1）
// - 判的是"负时间戳不会把页面打成 pageerror"，不是"埋点数据完整"（负时间戳那一次**有意丢弃**）；
// - 真栈上触发它的时序（React 把 `actualStartTime` 取成负值）无法在单测里复现 —— 本判据注入的是
//   **同一判据（浏览器会不会抛）**，不是同一个时序现场；
// - 生产构建不启用该 React 埋点，故这个问题只在 dev 可见（见 issue #6799 的读数出处）。

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

/**
 * 以「数字时间戳」的三参形态调用 `performance.measure`（**运行时**合法：Chrome 接受
 * `measure(name, startTime, endTime)`；而 TS 的 DOM 声明只给 `(name, startMark?, endMark?)` 字符串形态与 options 形态
 * ⇒ 调用点必须显式转型，否则 `tsc --noEmit` 判红）。
 */
function measureWithTimestamps(name: string, start: number, end: number): void {
  const fn = performance.measure as unknown as (n: string, s: number, e: number) => PerformanceMeasure
  fn(name, start, end)
}

/**
 * 真栈同款的浏览器行为桩：**任一时间戳为负 ⇒ 抛 TypeError**（与 Chromium 实测逐字一致；
 * jsdom 原生不校验，必须显式换掉）。`end < start`（负时长）**不抛** —— 这正是旧桩判错的地方。
 */
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
    const negative = (typeof start === 'number' && start < 0) || (typeof end === 'number' && end < 0)
    if (negative) {
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

describe('performance.measure 区间守卫（issue #6799 ② / 判据订正 #6946）', () => {
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

  it('修前形态：不装守卫时，React 埋点同款的「负时间戳」调用会把页面打成 pageerror', () => {
    guard.uninstallUserTimingGuard()
    expect(() => measureWithTimestamps('\u200bProcessingRedirectPage', -1, 10)).toThrow(/negative time stamp/)
    expect(() => performance.measure('\u200bProcessingRedirectPage', { start: 5, end: -1 })).toThrow(/negative time stamp/)
  })

  it('装上守卫后：负时间戳不再抛（该次埋点被丢弃，页面不再出 pageerror）', () => {
    expect(() => measureWithTimestamps('\u200bProcessingRedirectPage', -1, 10)).not.toThrow()
    expect(() => performance.measure('\u200bProcessingRedirectPage', { start: 5, end: -1, detail: {} })).not.toThrow()
    expect(() => performance.measure('\u200bProcessingRedirectPage', { start: -5, end: -1 })).not.toThrow()
  })

  it('🔴 判别力对照：**负时长**（两个时间戳都非负）必须照旧透传 —— 浏览器不抛，守卫不许替它丢', () => {
    const before = stub.calls.length
    expect(() => measureWithTimestamps('\u200bNegativeDuration', 100, 90)).not.toThrow()
    expect(() => performance.measure('\u200bNegativeDuration', { start: 100, end: 90 })).not.toThrow()
    expect(stub.calls.length, '负时长调用必须到达底层 measure（旧守卫会在这里少一次 ⇒ 判据会红）').toBe(before + 2)
  })

  it('负控：合法区间必须**照旧透传**（不是"靠不记录换不报错"）', () => {
    const before = stub.calls.length
    measureWithTimestamps('\u200bOkComponent', 100, 120)
    performance.measure('\u200bOkComponent', { start: 100, end: 120 })
    performance.measure('只有名字')
    expect(stub.calls.length, '合法调用必须到达底层 measure').toBe(before + 3)
    expect(stub.calls.slice(before).map((c) => c[0])).toEqual(['\u200bOkComponent', '\u200bOkComponent', '只有名字'])
  })

  it('等值区间（end === start）与零起点合法：不得被误丢', () => {
    const before = stub.calls.length
    measureWithTimestamps('\u200bZeroLength', 100, 100)
    performance.measure('\u200bZeroStart', { start: 0, end: 0 })
    expect(stub.calls.length).toBe(before + 2)
  })

  it('幂等：重复安装不会套娃（第二次返回 false，且合法调用仍只到达底层一次）', () => {
    expect(guard.installUserTimingGuard(), '第二次安装应返回 false（已装）').toBe(false)
    const before = stub.calls.length
    measureWithTimestamps('\u200bOnce', 1, 2)
    expect(stub.calls.length).toBe(before + 1)
  })

  it('卸载后可再装：`uninstall` 把原生 measure 还原（判据之间不互相污染）', () => {
    guard.uninstallUserTimingGuard()
    expect(() => measureWithTimestamps('\u200bX', -1, 10)).toThrow(/negative time stamp/)
    expect(guard.installUserTimingGuard()).toBe(true)
    expect(() => measureWithTimestamps('\u200bX', -1, 10)).not.toThrow()
  })

  it('谓词自身（不依赖桩）：与浏览器实测逐条对齐', () => {
    expect(guard.isInvalidMeasureRange({ start: -1, end: 10 })).toBe(true)
    expect(guard.isInvalidMeasureRange({ start: 5, end: -1 })).toBe(true)
    expect(guard.isInvalidMeasureRange({ start: -5, end: -1 })).toBe(true)
    expect(guard.isInvalidMeasureRange({ start: 100, end: 90 }), '负时长合法 ⇒ 不得判非法').toBe(false)
    expect(guard.isInvalidMeasureRange({ start: 0, end: 0 })).toBe(false)
    expect(guard.isInvalidMeasureRange(undefined)).toBe(false)
    expect(guard.isInvalidMeasureRange('markName')).toBe(false)
    expect(guard.isInvalidMeasureRange({ start: 'markName', end: -1 }), 'end 为负 ⇒ 非法').toBe(true)
  })
})
