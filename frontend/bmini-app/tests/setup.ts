/**
 * 测试环境全局 setup
 *
 * 在测试框架安装之前运行（setupFiles）
 * 注意：此处不可使用 beforeEach/describe 等 Jest 全局 API
 */

/**
 * 🔴 RTL 的**异步等待预算**（issue #6645，2026-10-10 实测）。
 *
 * 默认 `asyncUtilTimeout = 1000ms` 在本仓门禁的负载下**不够**：全量档是 81 个 suite 并行
 * （门禁里还可能有别的腿同时在跑），jest worker 被调度出去几秒是常态 ⇒ 任何
 * `await waitFor(...)`（默认超时）都可能偶发红。
 *
 * 实证：`tests/worker-reprint-page.test.tsx` 在 `./verify-all.sh gate` 的 bmini 腿上偶红
 * （`reprint-step-detail` 等不到），而**同一文件不带负载连跑 5 次全绿**、**同一提交的 CI 腿也绿**；
 * 用 CPU 压满复算 ⇒ 单文件连跑 10 次**红 2 次**。那条链上 decode / lookup **全是立即 resolve
 * 的 jest mock**（无计时器 / 无网络 / 无真实解码）⇒ 卡的是 **jest worker 被调度出去**的那段时间，
 * 不是产品里的竞态。
 *
 * 所以预算按**机具最坏情况**给：`waitFor` 是**轮询**（正常仍是毫秒级返回，不是定长 sleep，
 * 不违反 §15.1「等元素而非定长 sleep」）；**断言一条都没放宽** —— 真有永不落地的状态，
 * 到点照样红（只是多等几秒）。同族护栏见
 * `tests/unit_ci_workflows/test_frontend_async_util_timeout.py`（issue #4414 已在 admin-web 落地）。
 *
 */
// 🔴 **只能**从 `@testing-library/dom` 取 `configure`（与 admin-web 同款）：
//    本文件是 `setupFiles`（在 jest 框架安装**之前**跑）。若在这里 import `@testing-library/react`，
//    它注册 auto-cleanup 时 `afterEach` 还不存在 ⇒ **静默失去自动清理** ⇒ DOM 跨用例累积
//    ⇒ 成片「Found multiple elements by: [...]」红（2026-10-10 实测踩过）。
//    `@testing-library/dom` 只提供 `configure` / 查询工具，没有这个副作用。
import { configure } from '@testing-library/dom'

configure({ asyncUtilTimeout: 5000 })

// 全局 TextEncoder/TextDecoder (jsdom 环境可能缺失)
if (typeof globalThis.TextEncoder === 'undefined') {
  const { TextEncoder, TextDecoder } = require('util')
  globalThis.TextEncoder = TextEncoder
  globalThis.TextDecoder = TextDecoder
}
