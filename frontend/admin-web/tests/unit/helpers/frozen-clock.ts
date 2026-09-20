// case_ids: FN-004
/**
 * 冻结墙钟的**导入期**夹具（issue #4761）。
 *
 * 为什么必须是独立模块（不能写在测试文件里）：ES 模块的 `import` 声明会被提升到文件顶部
 * ⇒ 测试文件里「先 `vi.useFakeTimers()`、后 `import Page`」**不成立**（`import` 先求值），
 * 而被测页面（`finance/page.tsx`）的 `CURRENT_PERIOD` 是**模块级**求值 ⇒ 它在导入那一刻就
 * 按**真实墙钟**定格，冻结根本来不及生效。
 * ⇒ 把冻结放进一个**被最先导入**的模块：本模块顶层代码先跑完，页面模块才开始求值。
 *
 * 用法（顺序即语义，勿调换）：
 * ```ts
 * import { FROZEN_NOW } from './helpers/frozen-clock'   // ① 先冻结
 * import FinancePage from '@/app/(dashboard)/finance/page' // ② 后导入（此时已是冻结时钟）
 * ```
 * 调用方仍须在 `afterEach` 里 `vi.useRealTimers()` 还原（不污染同进程的其它用例）。
 */
import { vi } from 'vitest'

/**
 * 冻结时刻：**月中 10:00**（远离午夜/月首/月末边界）。
 * ⚠️ 刻意不用 23:59/00:xx：假钟随真实耗时前移（`shouldAdvanceTime: true`），挑边界时刻
 * 等于把「跨边界」重新引入 —— 只是把概率窗口从 1ms 挪到「文件耗时」。
 */
export const FROZEN_NOW = new Date('2026-09-15T10:00:00')

// `shouldAdvanceTime: true`：`waitFor` / `userEvent` 内部的定时器仍能推进（否则死锁），
// 同时 `Date` 读数被钉在 FROZEN_NOW 附近。
vi.useFakeTimers({ shouldAdvanceTime: true })
vi.setSystemTime(FROZEN_NOW)
