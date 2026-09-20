// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5 报工页 —— **扫码完成主闭环**（issue #4792）。
//
// 本文件是「工人页改走 `POST /api/worker/production/scan/complete`」这条改动的**唯一**机械判据，
// 且**驱动真实装配层**（`createApp` + 假 DOM + fetch 替身）：断言的是**页面实际发出的请求**
// （URL / body / 请求头），不是「api.mjs 里有没有某个方法」。
//
// 🔴 为什么必须走真实装配层：本单要治的病正是「页面调的是哪个端点」——
//   改前页面 POST `/orders/{orderId}/operations/{operationId}/report`（URL 强制带 operationId、
//   **不带 token**）⇒ 防呆④（非本部位码）/ 防呆⑤（工序必须确定）/ 一次事务 / `done_at` 全都不生效。
//   只测纯函数（reduce/renderPage）**测不出这件事**：端点写死在 `app.mjs` 的事件处理器里。
//
// 零依赖（不引 jsdom/happy-dom）：假 DOM 只实现本页真正用到的那几个 API（最少代码阶梯）。
//
// 七条硬约束（每条都有对应断言，每条都能红）：
//   ① 默认提交 **body 只带 token** ⇒ 哪道工序由**系统**定（防呆⑤；客户端不再定工序）；
//   ② 一键改（`alternatives`）才带 `operation_id` ⇒ 归属由**服务端**校验（防呆④）；
//   ③ 幂等键：**同一屏复用同一个键**（重试 = 回放，不重复计件）；成功换屏 ⇒ 换新键；
//   ④ 回执驱动一屏：`set_completed` / `next_operation` ⇒ 接着做下一道 / 本套完工（不再重复提交）；
//   ⑤ 旧码（`granularity:"order"`）⇒ **一个写请求都不发**（不硬塞 `set_id`/`order_item_id`）；
//   ⑥ 未登录 ⇒ 无【完成】按钮，且硬点也**不发请求**（fail-closed）；
//   ⑦ 工序未确定（`operation == null`）⇒ 页面**不崩**且不出现报工按钮。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { createApi, STORAGE_KEY } from '../src/api.mjs'
import { createApp } from '../src/app.mjs'

// 本页用 `setTimeout` 做「闲置登出」定时器（15 分钟）。生产里它由 `app.destroy()` 清掉，
// 但**断言失败**的用例会在 destroy 之前抛 ⇒ 定时器留在事件循环 ⇒ `node --test` 不退出
// （红证根本跑不出来 —— 这是测试基础设施的坑，不是被测逻辑的）。测试侧把定时器一律 unref：
// 只保证进程能退，不改被测语义（`clearTimeout` 对 unref 的定时器照常有效）。
const realSetTimeout = globalThis.setTimeout
globalThis.setTimeout = (...args) => {
  const t = realSetTimeout(...args)
  t.unref?.()
  return t
}

// ============================================================ 假 DOM（只实现本页用到的 API）

/**
 * 造一个假 `document`。
 *
 * 本页真正用到的 DOM API 只有：`getElementById` / `querySelectorAll`（三个选择器）/
 * `addEventListener('visibilitychange')` / `root.innerHTML = …` / `input.value` / `el.dataset`。
 * ⇒ 不需要 jsdom（最少代码阶梯：原生特性优先，不引依赖）。
 */
function fakeDom() {
  let html = ''
  const byId = new Map()
  let all = []
  const docListeners = new Map()

  const parseAttrs = (raw) => {
    const attrs = {}
    const re = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*"([^"]*)")?/g
    let m
    while ((m = re.exec(raw))) attrs[m[1]] = m[2] ?? ''
    return attrs
  }

  const mkEl = (tag, attrs) => {
    const dataset = {}
    for (const [k, v] of Object.entries(attrs)) {
      if (k.startsWith('data-')) dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = v
    }
    return {
      tag,
      attrs,
      dataset,
      value: '',
      listeners: {},
      addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn) },
      classList: { contains: (c) => (attrs.class ?? '').split(/\s+/).includes(c) },
    }
  }

  const root = {
    get innerHTML() { return html },
    set innerHTML(v) { html = v; reindex() },
  }

  function reindex() {
    byId.clear()
    all = []
    const tagRe = /<([a-zA-Z][\w-]*)((?:"[^"]*"|[^>"])*)>/g
    let m
    while ((m = tagRe.exec(html))) {
      const el = mkEl(m[1], parseAttrs(m[2]))
      all.push(el)
      if (el.attrs.id) byId.set(el.attrs.id, el)
    }
    byId.set('worker-h5-root', root)
  }

  const matches = (el, sel) => {
    const classPart = sel.match(/^\.([\w-]+)/)
    if (classPart && !el.classList.contains(classPart[1])) return false
    const attrPart = sel.match(/\[([\w-]+)\]/)
    if (attrPart && !(attrPart[1] in el.attrs)) return false
    return true
  }

  reindex() // 初始就挂上 #worker-h5-root（index.html 里那个 `<main id="worker-h5-root">`）

  return {
    get visibilityState() { return 'visible' },
    getElementById: (id) => byId.get(id),
    querySelectorAll: (sel) => all.filter((el) => matches(el, sel)),
    addEventListener(type, fn) { (docListeners.get(type) ?? docListeners.set(type, []).get(type)).push(fn) },
    removeEventListener(type, fn) {
      const l = docListeners.get(type) ?? []
      const i = l.indexOf(fn)
      if (i >= 0) l.splice(i, 1)
    },
    /** 点某个元素（跑它当前挂着的处理器；处理器是 async ⇒ 必须 await）。 */
    async fire(id, type = 'click') {
      const el = byId.get(id)
      if (!el) throw new Error(`元素 #${id} 不在当前屏上（渲染里没出现它）`)
      for (const fn of el.listeners[type] ?? []) await fn()
    },
    get html() { return html },
  }
}

// ============================================================ 替身：storage / fetch

function memStorage(seed = {}) {
  const map = new Map(Object.entries(seed))
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  }
}

const SESSION = { sessionId: 'sess-1', workerId: 'w-1', workerNo: 'A017', workerName: '张三', idleMinutes: 15 }

/** 路由式 fetch 替身：按 URL 子串命中，记录每一次调用（URL / method / body / 请求头）。 */
function routeFetch(routes) {
  const calls = []
  const fn = async (url, init = {}) => {
    const call = { url, method: init.method ?? 'GET', body: init.body ? JSON.parse(init.body) : null, headers: init.headers ?? {} }
    calls.push(call)
    const key = Object.keys(routes).find((k) => url.includes(k))
    const r = (key ? routes[key] : { status: 500, body: { success: false, error: { message: `未路由：${url}` } } })
    const resp = typeof r === 'function' ? r(call) : r
    return { ok: resp.status >= 200 && resp.status < 300, status: resp.status, json: async () => resp.body }
  }
  fn.calls = calls
  return fn
}

// ============================================================ 服务端形状（逐字照 ProductionScanService / ProductionScanCompleteService）

/** 新码（套 × 部位）：布帘的码 ⇒ 推断出布帘的「定型」。 */
const CLOTH_VIEW = {
  granularity: 'set_position',
  order_id: 'o-1',
  processing_order_no: 'JG20260920001',
  set_no: 14,
  set_index: 13,
  position: { order_item_id: 'oi-cloth', position_kind: '布帘', position_name: '布帘' },
  operation: {
    operation_id: 'op-cloth', logical_name: '定型', position: '布帘', unit: '米', qty: 11,
    unit_price: 3.5, seq: 1, status: 'pending', determined_by: 'inferred', rerouted: false,
  },
  alternatives: [
    { operation_id: 'op-cloth-2', logical_name: '打卷', position: '布帘', seq: 2, qty: 11, unit: '米' },
  ],
  set_progress: { total: 3, done: 1, percent: 33 },
  completed: false,
  completed_at: null,
  needs_selection: [],
}

/** 一键改之后的解析结果（`determined_by:"picked"`）。 */
const PICKED_VIEW = {
  ...CLOTH_VIEW,
  operation: { ...CLOTH_VIEW.operation, operation_id: 'op-cloth-2', logical_name: '打卷', determined_by: 'picked' },
}

/** 旧码降级形态（逐字照 `ProductionScanService.degradedView`）。 */
const DEGRADED_VIEW = {
  granularity: 'order',
  order_id: 'o-1',
  processing_order_no: 'JG20260920001',
  set_no: null,
  set_index: null,
  position: null,
  operation: null,
  alternatives: [],
  set_progress: null,
  completed: null,
  completed_at: null,
  needs_selection: ['set', 'position'],
  selections: [
    { set_id: 'set-1', set_no: 1, set_index: 0, positions: [{ order_item_id: 'oi-1', position_name: '布帘' }] },
    { set_id: 'set-2', set_no: 2, set_index: 1, positions: [{ order_item_id: 'oi-2', position_name: '纱帘' }] },
  ],
}

/** 回执（逐字照 `applyReport` 的键 + 切片② 追加的键）。 */
const receipt = (over = {}) => ({
  status: 200,
  body: {
    success: true,
    data: {
      operation_id: 'op-cloth', done_qty: 11, status: 'done', order_completed: false,
      worker_id: 'w-1', worker_name: '张三', identity_source: 'server_session',
      set_no: 14, position: { order_item_id: 'oi-cloth', position_name: '布帘' }, rerouted: false,
      set_progress: { total: 3, done: 2, percent: 66 }, set_completed: false,
      next_operation: { operation_id: 'op-cloth-2', logical_name: '打卷', position: '布帘', qty: 11, unit: '米' },
      ...over,
    },
  },
})

const resolveOk = (data) => ({ status: 200, body: { success: true, data } })

// ============================================================ 装配一个已登录的页面

function bootPage({ doc, f, loggedIn = true }) {
  const storage = memStorage(loggedIn ? { [STORAGE_KEY]: JSON.stringify(SESSION) } : {})
  const api = createApi({ fetchImpl: f, storage, baseUrl: '' })
  const app = createApp({ doc, api, location: 'https://app.migaozn.com/w/' })
  app.dispatch({ type: 'worker', worker: loggedIn ? { workerName: '张三', workerNo: 'A017', idleMinutes: 15 } : null })
  return app
}

/** 扫一次码（把码值填进输码框再点【确定】）。 */
async function scan(doc, code) {
  doc.getElementById('wh5-code').value = code
  await doc.fire('wh5-scan')
}

/** 点一个**没有 id** 的元素（部位/一键改这类按钮只有 data-*）。 */
async function fireEl(el) {
  assert.ok(el, '要点的元素不在当前屏上')
  for (const fn of el.listeners.click ?? []) await fn()
}

/**
 * 等某个条件成立（**等元素/等请求，不定长 sleep**）。
 *
 * 一键改的接线是 `() => { void doScan(...) }`（app.mjs）—— 处理器立刻返回，解析请求在后台飞，
 * 所以点完必须等它落地才能断言（定长 sleep 在慢机器上会假红，在快机器上白等）。
 */
async function waitFor(pred, label) {
  for (let i = 0; i < 50; i += 1) {
    if (pred()) return
    await new Promise((r) => setImmediate(r))
  }
  throw new Error(`等「${label}」超时`)
}

// ============================================================ ① 主路径：走 scan/complete，body 只带 token

test('🔴 ① 扫新码 ⇒ 点【完成】⇒ POST /api/worker/production/scan/complete，body **只带 token**（工序由系统定 = 防呆⑤）', async () => {
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt(),
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')

  // 一屏就绪：显示码给出的套号/部位/工序 + 【完成】
  assert.match(doc.html, /第\s*14\s*套/)
  assert.match(doc.html, /布帘/)
  assert.match(doc.html, /定型/)

  await doc.fire('wh5-report')

  const posts = f.calls.filter((c) => c.method === 'POST')
  assert.equal(posts.length, 1, '点一次【完成】只能发**一个**写请求')
  assert.match(posts[0].url, /\/api\/worker\/production\/scan\/complete$/)
  // 🔴 本单的核心：URL 里**没有** orderId/operationId（改前 `/orders/{orderId}/operations/{operationId}/report` 有）
  assert.ok(!posts[0].url.includes('/report'), '工人页不得再走 /report（那条路径不带 token）')
  // 🔴 默认 body **只带 token**：工序由**服务端**推断（防呆⑤），数量由服务端取「剩余应做」
  assert.deepEqual(posts[0].body, { token: 'tok-cloth' })
  assert.equal(posts[0].headers['X-Worker-Session-Id'], 'sess-1')
  assert.ok(posts[0].headers['X-Client-Request-Id'], '写请求必须带幂等键')
  app.destroy()
})

test('① 登录态是计件归属的唯一根：写请求 body **不含** worker_id / worker_name / unit_price / factor', async () => {
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt(),
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')
  await doc.fire('wh5-report')

  const body = f.calls.find((c) => c.method === 'POST').body
  for (const forbidden of ['worker_id', 'worker_name', 'unit_price', 'factor', 'set_id', 'order_item_id']) {
    assert.ok(!(forbidden in body), `写请求 body 不得携带 ${forbidden}`)
  }
  app.destroy()
})

// ============================================================ ② 一键改：才带 operation_id（归属由服务端校验）

test('🔴 ② 一键改（alternatives）⇒ body 带 operation_id（防呆④ 的归属校验在**服务端**，不在前端）', async () => {
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': (call) =>
      call.url.includes('operation_id=op-cloth-2') ? resolveOk(PICKED_VIEW) : resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt(),
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')

  // 「不是这道？」⇒ 工人显式指定打卷（一键改）
  await fireEl(doc.querySelectorAll('.wh5-alt[data-operation-id]')[0])
  // 接线是 `void doScan(...)` ⇒ 等**新的一屏**落地（等元素，不定长 sleep）。
  // ⚠️ 判据必须是「打卷 · 布帘」这种**只在新的主屏上**才有的串：改前的 `alternatives` 里
  // 本来就有「打卷」⇒ 拿它当判据会立刻通过（假绿）。
  await waitFor(() => doc.html.includes('打卷 · 布帘'), '一键改后的一屏')
  assert.equal(f.calls.filter((c) => c.method === 'GET').length, 2, '一键改 = 再解析一次（GET /scan?operation_id=…）')

  await doc.fire('wh5-report')
  const posts = f.calls.filter((c) => c.method === 'POST')
  assert.equal(posts.length, 1)
  // 显式指定 ⇒ 带 operation_id；服务端会校验它属不属于本次扫码的部位（不属于 ⇒ 422，零写入）
  assert.deepEqual(posts[0].body, { token: 'tok-cloth', operation_id: 'op-cloth-2' })
  app.destroy()
})

// ============================================================ ③ 幂等键

test('🔴 ③ 幂等：同一屏重试**复用同一个** X-Client-Request-Id（重试=回放，绝不重复计件）', async () => {
  const doc = fakeDom()
  let attempt = 0
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': () => {
      attempt += 1
      // 第一次：服务端 500（网络/后端抖动）⇒ 工人再点一次
      return attempt === 1 ? { status: 500, body: { success: false, error: { message: '服务端开小差' } } } : receipt()
    },
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')

  await doc.fire('wh5-report')
  await doc.fire('wh5-report')

  const posts = f.calls.filter((c) => c.method === 'POST')
  assert.equal(posts.length, 2, '两次点击 = 两次请求（页面不静默重试）')
  assert.equal(posts[0].headers['X-Client-Request-Id'], posts[1].headers['X-Client-Request-Id'],
    '🔴 同一屏重试必须复用同一个幂等键 —— 每次点击新造一个键 = 一次重试就是第二笔报工（静默重复计件）')
  app.destroy()
})

test('③ 成功后屏换成下一道 ⇒ 下一次提交是**新**幂等键（同一次扫码只算一次，下一道是新的一笔）', async () => {
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt(),
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')
  await doc.fire('wh5-report')
  await doc.fire('wh5-report')

  const posts = f.calls.filter((c) => c.method === 'POST')
  assert.equal(posts.length, 2)
  assert.notEqual(posts[0].headers['X-Client-Request-Id'], posts[1].headers['X-Client-Request-Id'],
    '下一道是新的一笔 ⇒ 必须是新键（否则第二道会被回放成「已报过」）')
  app.destroy()
})

test('🔴 ③ 回放（replayed:true）⇒ 页面如实告诉工人「没有新增计件」，不谎报一笔新报工', async () => {
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt({ replayed: true }),
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')
  await doc.fire('wh5-report')

  assert.match(doc.html, /没有新增计件/, 'replayed ⇒ 必须显式告知（否则工人以为报了两次）')
  app.destroy()
})

// ============================================================ ④ 回执驱动一屏

test('🔴 ④ 回执 `next_operation` ⇒ 屏上换成下一道（工人接着做，不必重扫）', async () => {
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt(),
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')
  await doc.fire('wh5-report')

  assert.match(doc.html, /打卷/, '回执里的「下一道」必须上屏')
  assert.match(doc.html, /id="wh5-report"/, '还有下一道 ⇒ 仍可报工')
  app.destroy()
})

test('🔴 ④ 回执 `set_completed:true` ⇒ 显示本套已完工，且【完成】按钮消失（不再重复提交）', async () => {
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt({ set_completed: true, next_operation: null }),
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')
  await doc.fire('wh5-report')

  assert.match(doc.html, /本套已完成/, '本套工序都做完 ⇒ 必须显式告知')
  assert.ok(!/id="wh5-report"/.test(doc.html), '本套已完工 ⇒ 不得再出现报工按钮')
  app.destroy()
})

// ============================================================ ⑤ 旧码：不硬塞 set_id/order_item_id

test('🔴 ⑤ 旧码（granularity:"order"）⇒ 一个写请求都不发 + 不硬塞 set_id/order_item_id + 给指路文案', async () => {
  const doc = fakeDom()
  const f = routeFetch({ '/api/worker/production/scan?': resolveOk(DEGRADED_VIEW) })
  const app = bootPage({ doc, f })
  await scan(doc, 'JG20260920001')

  assert.match(doc.html, /选套/, '旧码仍必须让工人显式选套')
  assert.ok(!/id="wh5-report"/.test(doc.html), '旧码未选定 ⇒ 不得出现报工按钮')
  // 选套 + 选部位（两跳都是工人显式动作）
  await fireEl(doc.querySelectorAll('[data-set-id]')[1])
  await fireEl(doc.querySelectorAll('[data-order-item-id]')[0])

  // 🔴 D1（未闭）：选完套+部位后**没有可再解析的键**（selections 里没有 operation_id）⇒
  // 页面**不得**硬塞 set_id/order_item_id 去调 scan/complete，也不得退回客户端定工序的 /report。
  assert.equal(f.calls.filter((c) => c.method === 'POST').length, 0, '旧码路径一个写请求都不许发')
  assert.match(doc.html, /重新打印/, '旧码无法一次扫码完工 ⇒ 必须给工人指路（fail-closed 而不是死路）')
  app.destroy()
})

// ============================================================ ⑥ 未登录：fail-closed

test('🔴 ⑥ 未登录 ⇒ 无【完成】按钮；即使硬点也不发任何请求（不降级 body 口径）', async () => {
  const doc = fakeDom()
  const f = routeFetch({})
  const app = bootPage({ doc, f, loggedIn: false })

  assert.ok(!/id="wh5-report"/.test(doc.html), '未登录不得出现报工按钮')
  // 页面根本没有该元素 ⇒ 「点它」这件事不可能发生（fail-closed 的第一道闸）
  await assert.rejects(() => doc.fire('wh5-report'), /不在当前屏上/)
  assert.equal(f.calls.length, 0, '未登录 ⇒ 一个请求都不发')
  app.destroy()
})

test('🔴 ⑥ 未登录 + 已有解析结果 ⇒ completeByScan 仍被拒且**一个请求都不发**（页面闸不是唯一闸）', async () => {
  const f = routeFetch({})
  const api = createApi({ fetchImpl: f, storage: memStorage(), baseUrl: '' })
  await assert.rejects(() => api.completeByScan({ token: 'tok-cloth' }), /登录/)
  assert.equal(f.calls.length, 0)
})

// ============================================================ ⑦ 工序未确定：不崩、不可报工

test('🔴 ⑦ 工序未确定（operation == null 且未完工）⇒ 页面不崩且不出现报工按钮', () => {
  const doc = fakeDom()
  const f = routeFetch({})
  const app = bootPage({ doc, f })
  app.dispatch({
    type: 'resolved',
    view: { ...CLOTH_VIEW, operation: null, alternatives: [], completed: false, needs_selection: [] },
  })
  assert.ok(!/id="wh5-report"/.test(doc.html), '工序未确定不得出现报工按钮（防呆⑤）')
  assert.match(doc.html, /重扫/, '页面必须仍可用（改前这里 TypeError：mainView 直接读 operation.unit_price）')
  app.destroy()
})

test('🔴 ⑦ 扫到「本套已完工」的新码（completed=true, operation=null）⇒ 不崩 + 显示本套已完成', () => {
  const doc = fakeDom()
  const f = routeFetch({})
  const app = bootPage({ doc, f })
  app.dispatch({
    type: 'resolved',
    view: { ...CLOTH_VIEW, operation: null, alternatives: [], completed: true, needs_selection: [] },
  })
  assert.match(doc.html, /本套已完成/)
  assert.ok(!/id="wh5-report"/.test(doc.html))
  app.destroy()
})

// ============================================================ 静态红线：工人页唯一写入口

test('🔴 静态红线：页面源码里**没有** /report 写入口（唯一写入口 = scan/complete）', () => {
  const src = ['src/app.mjs', 'src/api.mjs', 'src/render.mjs']
    .map((p) => readFileSync(new URL(`../${p}`, import.meta.url), 'utf8'))
    .join('\n')
  // 判据形态：看**代码**（剥掉注释行）—— 注释里「提到」/report（本单要讲清分工）不算
  // （与 case_ids 声明同族口径：正文提及 ≠ 声明）。
  const code = src.split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n')
  assert.ok(!/\/report/.test(code), '工人页不得再有 /report 写路径（它不带 token ⇒ 防呆④⑤ 不生效）')
  assert.ok(!/api\.report\(/.test(code), 'api.report 已下线（唯一写入口 = completeByScan）')
  assert.match(code, /\/api\/worker\/production\/scan\/complete/, '写入口必须是 scan/complete')
})
