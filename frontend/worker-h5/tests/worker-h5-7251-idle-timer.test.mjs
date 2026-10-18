// case_ids: PG-089
//
// 工人端 H5 闲置登出定时器溢出（issue #7251）—— 只钉**调度**，不改 30 天口径。
//
// 病灶（issue 里的本机实测，不是推断）：
//   `frontend/worker-h5/src/app.mjs` 的 `armIdle()` 用
//   `setTimeout(..., Math.max(1, minutes) * 60_000)`，而 `minutes` 默认 43200（30 天）
//   ⇒ 2,592,000,000 ms **超过 2^31-1（2,147,483,647）** ⇒ 浏览器 / Node 把延时钳成 ~1ms
//   （`TimeoutOverflowWarning ... Timeout duration was set to 1`）⇒ **立刻触发**：
//     ① 「闲置 30 天自动登出」从未按 30 天排期（节流分支不重排 ⇒ 之后不再有闲置登出）；
//     ② 每次 `armIdle()`（登录成功 / `resolved` / 每次 `checkAlive` 成功）多打一轮
//        `current-user` + `/api/worker/me`。
//
// 本文件钉六条（每条都能红；红证 = 改回「单次超长定时器」形态 ⇒ 读数见 PR body）：
//   ① `idleMinutes = 43200` 的**每一次入队**（含续排的后续分片）都 ≤ 2^31-1，分片之和仍 = 30 天；
//   ② 装配后**第一帧（1ms）内**不得发起对账（旧形态被平台钳成 1ms ⇒ 当场多打一轮）；
//   ③ 闲置**到期才**发起**恰好一轮**对账（`current-worker` + `/me` 各一次）；
//   ④ 可配区间边界（2^31-1 ms 的两侧：35791 / 35792 分钟）；
//   ⑤ 降级路径（响应没带 `idle_minutes`）兜底 30 天同样不得溢出；
//   ⑥ 类级：服务端**全区间 5~43200 分钟**逐个成立（每片 ≤ 2^31-1、和 = 总延时、超过上限才分片）。
//
// 🔴 测试侧替身**按平台规范钳制**：延时 > 2^31-1 ⇒ 按 1ms 处理（MDN / Node `TimeoutOverflowWarning`）。
//    这不是"帮被测对象制造 bug"，而是**复现平台真实行为** —— 真实读数见 issue #7251 的
//    `node -e` 输出（`fired after 3 ms`）。替身只替换 `setTimeout` / `clearTimeout`，
//    不碰被测逻辑，也不依赖真实长延时（否则 `node --test` 会被 30 天的句柄挂住）。
//
// 🔴 为什么必须覆盖「第一帧」而不是只断言"源码里没有超长延时"：真实后果是**多发请求**与
//    **不再排期**，只有把平台钳制行为建模进来，判据才会在旧形态下真的红（否则是空断言）。

import test from 'node:test'
import assert from 'node:assert/strict'

import { createApp, idleSlices, MAX_TIMER_DELAY_MS } from '../src/app.mjs'
import { DEFAULT_WORKER_IDLE_MINUTES } from '../src/render.mjs'

/** 30 天折算成毫秒：2,592,000,000 ms（> 2^31-1）。 */
const IDLE_43200_MS = 43200 * 60_000

/** 一轮对账 = 服务端两个读面（顺序与 `app.mjs::checkAlive` 一致）。 */
const CURRENT_WORKER = 'GET /api/worker/production/current-worker'
const ME = 'GET /api/worker/me'

const sum = (xs) => xs.reduce((a, b) => a + b, 0)

/**
 * 假时钟：记录**每一次入队的原始延时**，并按平台规范模拟「超限 ⇒ 1ms」。
 *
 * - `requested` = 原始入队延时（判据直接读它 ⇒ 与真实时钟无关）；
 * - `advance(ms)` = 推进假时钟、按到期顺序执行回调（回调里新排的定时器照常参与）。
 */
function installFakeClock() {
  const real = { setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout }
  let now = 0
  let seq = 0
  const timers = new Map()
  const requested = []

  const setTimeoutFake = (fn, ms = 0) => {
    const raw = Number(ms)
    requested.push(raw)
    // 平台规范：delay > 2^31-1 ⇒ 按 1ms 处理（Node: TimeoutOverflowWarning；浏览器: 静默钳制）
    const delay = raw > MAX_TIMER_DELAY_MS ? 1 : Math.max(0, raw)
    const id = ++seq
    timers.set(id, { at: now + delay, fn })
    return id
  }
  const clearTimeoutFake = (id) => { timers.delete(id) }

  const advance = (ms) => {
    const target = now + ms
    for (;;) {
      let next = null
      for (const [id, t] of timers) {
        if (t.at <= target && (!next || t.at < next[1].at)) next = [id, t]
      }
      if (!next) break
      timers.delete(next[0])
      now = next[1].at
      next[1].fn()
    }
    now = target
  }

  globalThis.setTimeout = setTimeoutFake
  globalThis.clearTimeout = clearTimeoutFake
  return {
    requested,
    advance,
    restore() {
      globalThis.setTimeout = real.setTimeout
      globalThis.clearTimeout = real.clearTimeout
    },
  }
}

/** 让 `checkAlive()` 的 await 链跑完（`setImmediate` 不被本文件替换）。 */
const flush = () => new Promise((resolve) => setImmediate(resolve))

/**
 * 装配一个**只到「会话就绪」为止**的报工页（零网络、零真实定时器）。
 *
 * `resolved` 是 `armIdle()` 的真实触发点之一（登录成功 / 首屏 `boot` / 扫码解析都走它），
 * 所以用它装配 = 复现生产装配路径，而不是绕开装配层直接调内部函数。
 */
function mountWorkerPage({ idleMinutes } = {}) {
  const calls = []
  let html = ''
  const root = {
    get innerHTML() { return html },
    set innerHTML(v) { html = v },
  }
  const element = () => ({
    addEventListener() {},
    value: '',
    dataset: {},
    classList: { contains: () => false },
  })
  const doc = {
    getElementById: (id) => (id === 'worker-h5-root' ? root : element()),
    querySelectorAll: () => [],
    addEventListener() {},
    removeEventListener() {},
    visibilityState: 'visible',
  }
  const api = {
    sessionId: () => 'sess-1',
    worker: () => ({ workerId: 'w-1' }),
    async currentWorker() {
      calls.push(CURRENT_WORKER)
      return { workerName: '张三', workerNo: 'A017' }
    },
    async readMe() {
      calls.push(ME)
      return { pages: ['report'] }
    },
  }
  const app = createApp({ doc, api, location: 'https://app.migaozn.com/w/' })
  app.dispatch({
    type: 'worker',
    worker: { workerName: '张三', workerNo: 'A017', ...(idleMinutes === undefined ? {} : { idleMinutes }) },
  })
  return { app, calls }
}

/**
 * 触发一次 `armIdle()`，并**逐片推进到到期前一刻**（不推进最后一片）。
 *
 * 返回这一次 `armIdle()` 排出的**全部分片**（含续排出来的后续片）与它们的和；
 * 推进过程中持续断言「闲置未到期 ⇒ 零对账」。
 */
function armAndCollectChunks(clock, app, calls, totalMs) {
  const chunks = []
  let mark = clock.requested.length
  app.dispatch({ type: 'resolved', view: null })
  for (;;) {
    const fresh = clock.requested.slice(mark)
    assert.ok(fresh.length > 0, 'armIdle 没有排任何定时器')
    for (const ms of fresh) {
      assert.ok(ms <= MAX_TIMER_DELAY_MS, `单次 setTimeout 入队超过 2^31-1ms（平台会钳成 ~1ms）：${ms}`)
    }
    chunks.push(...fresh)
    assert.ok(chunks.length <= 4, `分片数异常（${chunks.length} 片）：排期链没有收敛`)
    if (sum(chunks) >= totalMs) return { chunks, total: sum(chunks) }
    mark = clock.requested.length
    clock.advance(fresh.at(-1)) // 分片到期 = 续排（或最后一片才真的对账）
    assert.deepEqual(calls, [], `闲置未到期就发起了对账：${calls.join(' + ')}`)
  }
}

// ── 判据 ①：任何一次入队不得超 2^31-1（分片之和仍 = 30 天）────────────────────

test('🔴 ① idleMinutes=43200（30 天）：每一次入队 ≤ 2^31-1，分片之和 = 30 天', () => {
  const clock = installFakeClock()
  const { app, calls } = mountWorkerPage({ idleMinutes: 43200 })
  try {
    const { chunks, total } = armAndCollectChunks(clock, app, calls, IDLE_43200_MS)
    assert.ok(chunks.length >= 2, `30 天必须分片（单次上限装不下）：实际 ${chunks.length} 个定时器`)
    assert.equal(total, IDLE_43200_MS, '分片之和必须 = 43200 分钟（30 天口径不变）')
    assert.deepEqual(calls, [], '推进到到期前一刻仍不得发起对账')
  } finally {
    app.destroy()
    clock.restore()
  }
})

// ── 判据 ②：第一帧不得立即对账（旧形态被钳成 1ms）──────────────────────────────

test('🔴 ② 装配后第一帧（1ms）不得发起对账（超限延时会被平台钳成 ~1ms ⇒ 旧形态当场多打一轮）', async () => {
  const clock = installFakeClock()
  const { app, calls } = mountWorkerPage({ idleMinutes: 43200 })
  try {
    app.dispatch({ type: 'resolved', view: null })
    assert.deepEqual(calls, [], '装配完成那一刻（同步）就发起了对账')
    clock.advance(1)
    await flush()
    assert.deepEqual(calls, [], `装配后 1ms 内就发起了对账：${calls.join(' + ')}`)
  } finally {
    app.destroy()
    clock.restore()
  }
})

// ── 判据 ③：到期才发起恰好一轮 ────────────────────────────────────────────────

test('🔴 ③ 首片到期 ≠ 闲置到期：到期前一刻不得对账；到期时恰好发起一轮（current-worker + /me）', async () => {
  const clock = installFakeClock()
  const { app, calls } = mountWorkerPage({ idleMinutes: 43200 })
  try {
    const { chunks } = armAndCollectChunks(clock, app, calls, IDLE_43200_MS)
    // armAndCollectChunks 已推进到「最后一片之外」的全部分片 ⇒ 此刻距到期 = 最后一片
    clock.advance(chunks.at(-1) - 1)
    await flush()
    assert.deepEqual(calls, [], `闲置未到期就发起了对账：${calls.join(' + ')}`)
    clock.advance(1)
    await flush()
    assert.deepEqual(calls, [CURRENT_WORKER, ME], '到期必须恰好发起一轮对账（两个读面各一次）')
  } finally {
    app.destroy()
    clock.restore()
  }
})

// ── 判据 ④：2^31-1 ms 的两侧边界 ──────────────────────────────────────────────

test('🔴 ④ 可配区间边界：2^31-1ms 两侧（35791 ≤ 上限 / 35792 > 上限）分片判定正确', () => {
  const below = 35791 * 60_000 // 2,147,460,000 ≤ 2^31-1
  const above = 35792 * 60_000 // 2,147,520,000 > 2^31-1
  assert.ok(below <= MAX_TIMER_DELAY_MS && above > MAX_TIMER_DELAY_MS, '边界值的算术前置不成立（判据本身失效）')

  const ok = idleSlices(35791)
  assert.deepEqual(ok, [below], '未超过 2^31-1 的延时必须保持**单次**入队（与改前同形）')

  const chunked = idleSlices(35792)
  assert.ok(chunked.length >= 2, `超过 2^31-1 必须分片：实际 ${chunked.length} 片`)
  assert.ok(chunked.every((ms) => ms <= MAX_TIMER_DELAY_MS), `分片仍超上限：${chunked.join(', ')}`)
  assert.equal(sum(chunked), above, '分片之和必须 = 总延时')
})

// ── 判据 ⑤：降级路径（没带 idle_minutes）兜底 30 天同样不得溢出 ─────────────────

test('🔴 ⑤ 降级路径（响应没带 idle_minutes）⇒ 兜底 30 天同样不得溢出', () => {
  const clock = installFakeClock()
  const { app, calls } = mountWorkerPage() // 不带 idleMinutes ⇒ 走 DEFAULT_WORKER_IDLE_MINUTES
  try {
    const { chunks, total } = armAndCollectChunks(clock, app, calls, IDLE_43200_MS)
    assert.equal(DEFAULT_WORKER_IDLE_MINUTES, 43200, '兜底常量必须仍是服务端同源的 30 天')
    assert.equal(total, IDLE_43200_MS, '兜底必须仍是 30 天')
    assert.ok(chunks.length >= 2, '兜底路径同样必须分片（30 天 > 2^31-1ms）')
  } finally {
    app.destroy()
    clock.restore()
  }
})

// ── 判据 ⑥：类级 —— 服务端全区间 5~43200 分钟逐个成立 ─────────────────────────

test('🔴 ⑥ 类级：idleMinutes ∈ [5, 43200] 每个值都「每片 ≤ 2^31-1 且和 = 总延时」（不是只钉 43200）', () => {
  for (let minutes = 5; minutes <= 43200; minutes += 1) {
    const total = minutes * 60_000
    const chunks = idleSlices(minutes)
    assert.ok(chunks.length >= 1, `idleMinutes=${minutes}：没有排出任何定时器`)
    const over = chunks.filter((ms) => ms > MAX_TIMER_DELAY_MS)
    assert.deepEqual(over, [], `idleMinutes=${minutes}：单次入队超 2^31-1：${over.join(', ')}`)
    assert.equal(sum(chunks), total, `idleMinutes=${minutes}：分片之和 ≠ 总延时（调度改了闲置口径）`)
    assert.equal(chunks.length > 1, total > MAX_TIMER_DELAY_MS, `idleMinutes=${minutes}：分片判定与 2^31-1 边界不符`)
  }
})
