/**
 * `performance.measure` 的**区间守卫**（issue #6799 ②）。
 *
 * ## 病灶（真栈偶发，逐字）
 *
 * ```
 * [pageerror] TypeError: Failed to execute 'measure' on 'Performance':
 *             '​ProcessingRedirectPage' cannot have a negative time stamp.
 * ```
 *
 * 发起 `measure` 的**不是**产品代码（`grep performance.measure frontend/admin-web/src` = 0 命中），
 * 而是 **React 19 开发态的组件渲染埋点** `react-dom` 的 `logComponentRender`：它把
 * `performance.measure('\u200b' + 组件名, { start: fiber.actualStartTime, end: pendingEffectsRenderEndTime, … })`
 * 交给浏览器（`react-dom/cjs/react-dom-client.development.js` 的 `reassembleComponentOptions` 附近，
 * 名称前面的零宽字符 `\u200b` 正是真栈读数里那个看不见的首字符）。
 * 两个时间戳来自**不同的采样点**：`actualStartTime` 在渲染阶段起表（`startProfilerTimer`），
 * `pendingEffectsRenderEndTime` 在渲染**完成**时取；极端时序下后者小于前者
 * ⇒ 浏览器按规范抛 `TypeError`，被冒烟收成 `pageerror` ⇒ 整个旅程判红（"偶发"就是这么来的）。
 *
 * ## 为什么守在外面而不是改发起方
 * ① 发起方在 `node_modules` 里（React 内部埋点），改它 = 改依赖；
 * ② 这条埋点是**纯开发者观测面**（User Timing 只喂 DevTools Performance 面板），
 *    非法区间**扔掉**不改变任何产品行为（合法区间照旧原样透传）；
 * ③ 浏览器对"负区间"的唯一合法反应就是抛错 —— 唯一合法的处置就是不发起这次 measure。
 *
 * ## 判据为什么可信（会红）
 * `frontend/admin-web/tests/unit/user-timing-guard.test.ts`：
 * - 把 `performance.measure` 换成**真栈同款**的桩（`end < start` ⇒ 抛 `cannot have a negative time stamp`），
 *   不装守卫 ⇒ 抛（红）；装了 ⇒ 不抛且**合法区间仍被透传**（否则就是"用不记录来换不报错"）；
 * - `frontend/admin-web/tests/unit/user-timing-guard-wiring.test.ts`：`src/app/layout.tsx` 必须在
 *   模块顶层 import 本模块（否则守卫不会被装上 —— 判据 0 命中即红）。
 *
 * ## 边界（照实登记，§19.1）
 * - 只拦「区间非法」这一种形态（`end < start` / `end < 0` / 缺省 start=0 的正常形态不动）；
 * - 不拦 `performance.mark/clearMarks`（它们不抛）；
 * - 判不了"这条埋点该不该有"（那是 React 的事）；也不为本节的读数背书"生产环境没有同类问题"
 *   —— 生产构建里 `logComponentRender` 不启用（React 的 `ProfileMode` 只在开发态生效），
 *   真栈读数只在 dev 可见。
 */

/** 浏览器 `Performance.measure` 的三种签名（与 DOM 规范一致）。 */
type MeasureFn = (
  name: string,
  startOrOptions?: string | number | PerformanceMeasureOptions,
  endMark?: string,
) => PerformanceMeasure

let original: MeasureFn | null = null

/**
 * 这次 `measure` 会不会**被浏览器判为非法**（= 抛 `cannot have a negative time stamp`）。
 *
 * 🔴 **判据订正（issue #6946；2026-10-15 真栈逐字实测，Chromium）**：抛错的**充要条件是「任一时间戳为负」**，
 * **不是**「`end < start`」——旧实现判的是后者 ⇒ 真栈上**恒为 false**，守卫即便装上，那条 pageerror 也一条都拦不住：
 *
 * | 调用 | 真栈行为 |
 * |---|---|
 * | `measure('X', { start: -1, end: 10 })` | **抛** `'X' cannot have a negative time stamp.` |
 * | `measure('X', { start: 5, end: -1 })`  | **抛**（同上） |
 * | `measure('X', { start: 100, end: 90 })` | **不抛**（负**时长**合法，浏览器照收） |
 * | `measure('X', { start: 0, end: 0 })` | 不抛 |
 *
 * ⇒ 只按「会不会抛」判；负时长**照旧透传**（不替浏览器做它没做的判断，免得凭空丢埋点）。
 */
export function isInvalidMeasureRange(startOrOptions?: string | number | PerformanceMeasureOptions, endMark?: string): boolean {
  if (typeof endMark === 'number') {
    // `measure(name, startTime, endTime)`：起点若是**字符串**（mark 名），它解析成哪个时刻这里判不了 —— 只判拿得到的两个数
    return endMark < 0 || (typeof startOrOptions === 'number' && startOrOptions < 0)
  }
  if (startOrOptions && typeof startOrOptions === 'object') {
    const { start, end } = startOrOptions as PerformanceMeasureOptions
    return (typeof start === 'number' && start < 0) || (typeof end === 'number' && end < 0)
  }
  return false
}

/**
 * 装上守卫（幂等；`typeof window === 'undefined'` 时是空操作 —— SSR 面没有 `performance.measure` 埋点）。
 * 返回本次是否真的装上了（判据读它，避免"没装上却报绿"）。
 */
export function installUserTimingGuard(): boolean {
  if (typeof window === 'undefined') return false
  const perf = window.performance as (Performance & { __userTimingGuardInstalled?: boolean }) | undefined
  if (!perf || typeof perf.measure !== 'function' || perf.__userTimingGuardInstalled) return false
  original = perf.measure.bind(perf) as MeasureFn
  const installed: MeasureFn = (name, startOrOptions, endMark) => {
    if (isInvalidMeasureRange(startOrOptions, endMark)) {
      // 丢掉这次（浏览器会抛负时间戳）—— 合法区间不受影响
      return undefined as unknown as PerformanceMeasure
    }
    return original!(name, startOrOptions, endMark)
  }
  perf.measure = installed
  perf.__userTimingGuardInstalled = true
  return true
}

/** 判据用：卸下守卫并还原原生 `measure`（避免污染同进程的其它用例）。 */
export function uninstallUserTimingGuard(): void {
  if (typeof window === 'undefined') return
  const perf = window.performance as (Performance & { __userTimingGuardInstalled?: boolean }) | undefined
  if (!perf || !perf.__userTimingGuardInstalled) return
  if (original) perf.measure = original as Performance['measure']
  original = null
  delete perf.__userTimingGuardInstalled
}

// 装上：本模块由 `src/components/UserTimingGuard.tsx`（`'use client'`）**模块顶层** import ——
// ⚠️ **不要**改回「由 `src/app/layout.tsx` 直接 import 本模块」：`layout.tsx` 是 Server Component，
//    那句 import 只在 **Node 侧**执行，浏览器里守卫根本装不上（issue #6946 实测：`__userTimingGuardInstalled === false`、
//    `measure` 仍是 `[native code]`）。走客户端组件 ⇒ 随客户端 bundle 加载、早于 React 首次 commit 埋点。
installUserTimingGuard()
