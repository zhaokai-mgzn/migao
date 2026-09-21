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
//   ⑤ 旧码（`granularity:"order"`）⇒ 未选定前**一个写请求都不发**；选完套 + 部位后
//      **能报工**（issue #4794 收口：body 带 `set_id` + `order_item_id`，仍**不带** `operation_id`）；
//   ⑥ 未登录 ⇒ 无【开工】按钮，且硬点也**不发请求**（fail-closed）；
//   ⑦ 工序未确定（`operation == null`）⇒ 页面**不崩**且不出现报工按钮。
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { createApi, STORAGE_KEY } from '../src/api.mjs'
import { createApp, PENDING_REQUEST_KEY } from '../src/app.mjs'

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
  // 本套工序明细（issue #4967 交付物 2；逐字照 ProductionScanService#setOverview 的形状）
  set_overview: {
    set_no: 14,
    set_index: 13,
    positions: [
      {
        order_item_id: 'oi-cloth',
        position_kind: '布帘',
        position_name: '布帘',
        operations: [
          { operation_id: 'op-cloth', logical_name: '定型', position: '布帘', seq: 1, qty: 11, unit: '米', unit_price: 3.5, status: 'pending', done_qty: 0 },
          { operation_id: 'op-cloth-3', logical_name: '打卷', position: '布帘', seq: 2, qty: 1, unit: '套', unit_price: null, status: 'pending', done_qty: 0 },
        ],
      },
      {
        order_item_id: 'oi-gauze',
        position_kind: '纱帘',
        position_name: '纱帘',
        operations: [
          { operation_id: 'op-gauze', logical_name: '定型', position: '纱帘', seq: 1, qty: 4, unit: '米', unit_price: 2, status: 'done', done_qty: 4 },
        ],
      },
    ],
  },
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

/** 旧码 + 工人选了（第 2 套 · 纱帘）⇒ 服务端**重新解析**出的部位级视图（逐字照 `setPositionView`）。 */
const LEGACY_RESOLVED_VIEW = {
  ...CLOTH_VIEW,
  set_no: 2,
  set_index: 1,
  position: { order_item_id: 'oi-2', position_kind: '纱帘', position_name: '纱帘' },
  operation: { ...CLOTH_VIEW.operation, operation_id: 'op-gauze', logical_name: '定型' },
  alternatives: [],
  needs_selection: [],
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

/**
 * 装配一个已登录的页面。
 *
 * `storage` 可注入 ⇒ 能让「同一台设备上的两次页面装载」共享同一份 localStorage
 * （= 工人刷新页面：**新页面实例、`state` 全丢**，只有 storage 活下来）—— ⑧ 的判据靠它。
 */
function bootPage({ doc, f, loggedIn = true, storage = memStorage(loggedIn ? { [STORAGE_KEY]: JSON.stringify(SESSION) } : {}) }) {
  const api = createApi({ fetchImpl: f, storage, baseUrl: '' })
  const app = createApp({ doc, api, location: 'https://app.migaozn.com/w/', storage })
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

test('🔴 ① 扫新码 ⇒ 点【开工】⇒ POST /api/worker/production/scan/complete，body **只带 token**（工序由系统定 = 防呆⑤）', async () => {
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt(),
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')

  // 一屏就绪：显示码给出的套号/部位/工序 + 【开工】（issue #4967 改判后的按钮文案）
  assert.match(doc.html, /第\s*14\s*套/)
  assert.match(doc.html, /布帘/)
  assert.match(doc.html, /定型/)

  await doc.fire('wh5-report')

  const posts = f.calls.filter((c) => c.method === 'POST')
  assert.equal(posts.length, 1, '点一次【开工】只能发**一个**写请求')
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

test('🔴 ④ 回执 `set_completed:true` ⇒ 显示本套工序都已被领走，且【开工】按钮消失（不再重复提交）', async () => {
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt({ set_completed: true, next_operation: null }),
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')
  await doc.fire('wh5-report')

  assert.match(doc.html, /本套工序都已被领走/, '本套没有待领工序 ⇒ 必须显式告知')
  assert.ok(!/id="wh5-report"/.test(doc.html), '本套工序都已被领走 ⇒ 不得再出现开工按钮')
  app.destroy()
})

// ============================================================ ⑤ 旧码：选完套 + 部位 ⇒ 能报工（issue #4794）

test('🔴 ⑤ 旧码：未选定前**一个写请求都不发**（不硬塞 set_id/order_item_id、不退回客户端定工序的 /report）', async () => {
  const doc = fakeDom()
  const f = routeFetch({ '/api/worker/production/scan?': resolveOk(DEGRADED_VIEW) })
  const app = bootPage({ doc, f })
  await scan(doc, 'JG20260920001')

  assert.match(doc.html, /选套/, '旧码仍必须让工人显式选套')
  assert.ok(!/id="wh5-report"/.test(doc.html), '旧码未选定 ⇒ 不得出现报工按钮')
  assert.equal(f.calls.filter((c) => c.method === 'POST').length, 0, '未选定 ⇒ 一个写请求都不许发')
  app.destroy()
})

test('🔴 ⑤ 旧码端到端：扫码 ⇒ 选套 ⇒ 选部位 ⇒ **报工成功**（一次事务；改前停在这一屏，无路可走）', async () => {
  const doc = fakeDom()
  const f = routeFetch({
    // 旧码：无选择的解析 ⇒ 降级形态；带（套 + 部位）的解析 ⇒ 部位级视图（服务端推断工序）
    '/api/worker/production/scan?': (call) =>
      call.url.includes('set_id=set-2') && call.url.includes('order_item_id=oi-2')
        ? resolveOk(LEGACY_RESOLVED_VIEW)
        : resolveOk(DEGRADED_VIEW),
    '/api/worker/production/scan/complete': receipt({
      set_no: 2, position: { order_item_id: 'oi-2', position_name: '纱帘' },
    }),
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'JG20260920001')

  // 两跳都是工人显式动作：选套 ⇒ 出现该套的部位；选部位 ⇒ 重新解析 ⇒ 可报工
  await fireEl(doc.querySelectorAll('[data-set-id]')[1])
  await fireEl(doc.querySelectorAll('[data-order-item-id]')[0])
  await waitFor(() => doc.html.includes('id="wh5-report"'), '旧码选完套 + 部位后的报工按钮')

  const gets = f.calls.filter((c) => c.method === 'GET')
  assert.equal(gets.length, 2, '选完部位必须**再解析一次**（服务端按 (码, 套, 部位) 推断工序）')
  assert.match(gets[1].url, /[?&]set_id=set-2(&|$)/, '重新解析必须把 set_id 交给服务端（前端不猜套）')
  assert.match(gets[1].url, /[?&]order_item_id=oi-2(&|$)/, '重新解析必须把 order_item_id 交给服务端')

  await doc.fire('wh5-report')

  const posts = f.calls.filter((c) => c.method === 'POST')
  assert.equal(posts.length, 1, '点一次【开工】= 一个写请求（一次事务由服务端保证）')
  assert.match(posts[0].url, /\/api\/worker\/production\/scan\/complete$/)
  assert.ok(!posts[0].url.includes('/report'), '不得退回客户端定工序的 /report')
  // 🔴 旧码收口：body 带（套 + 部位）⇒ 服务端重解析**同一部位**；
  // **不带** operation_id ⇒ 工序仍由**系统**推断（防呆⑤ 在旧码路径同样成立）
  assert.deepEqual(posts[0].body, { token: 'JG20260920001', set_id: 'set-2', order_item_id: 'oi-2' })
  assert.ok(!('operation_id' in posts[0].body), '旧码默认路径不得由客户端定工序（防呆⑤）')
  assert.ok(!('worker_id' in posts[0].body), '身份仍只来自 X-Worker-Session-Id')
  assert.match(doc.html, /已领活/, '领活成功必须给回执文案（issue #4967 语义改判后）')
  app.destroy()
})

// ============================================================ ⑥ 未登录：fail-closed

test('🔴 ⑥ 未登录 ⇒ 无【开工】按钮；即使硬点也不发任何请求（不降级 body 口径）', async () => {
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

test('🔴 ⑦ 扫到「本套工序都已被领走」的新码（completed=true, operation=null）⇒ 不崩 + 显式告知', () => {
  const doc = fakeDom()
  const f = routeFetch({})
  const app = bootPage({ doc, f })
  app.dispatch({
    type: 'resolved',
    view: { ...CLOTH_VIEW, operation: null, alternatives: [], completed: true, needs_selection: [] },
  })
  assert.match(doc.html, /本套工序都已被领走/)
  assert.ok(!/id="wh5-report"/.test(doc.html))
  app.destroy()
})

// ============================================================ ⑨ 按套展示工序细节（issue #4967 交付物 2）

/**
 * 判据（每条都能红）：
 *   ① 扫码后屏上出现**本套工序明细**（本套 → 部位 → 工序：逻辑名 / 应做数量+单位 / 单价 / 状态 / 已报数量）；
 *   ② 已完成的那道**也在**（工人要看到「这一套还有哪几道没做」⇒ 不能只列待做）；
 *   ③ `unit_price` 为 `null` ⇒ 显式「未定价」（≠ 0 元，V90 / #4696）；
 *   ④ 🔴 **缺值不渲染**：`set_overview` 缺失 / `positions` 为空 ⇒ 整块不出现
 *      （绝不渲染「undefined 米 / ¥NaN」这种假数据）。
 */
test('🔴 ⑨ 扫码后按套展示工序细节：本套各部位的工序明细（逻辑名/应做+单位/单价/状态/已报）', async () => {
  const doc = fakeDom()
  const f = routeFetch({ '/api/worker/production/scan?': resolveOk(CLOTH_VIEW) })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')

  assert.match(doc.html, /id="wh5-set-overview"/, '扫码后必须出现本套工序明细块')
  // 本套两个部位
  assert.match(doc.html, /布帘/)
  assert.match(doc.html, /纱帘/)
  // 待做的那道：逻辑名 + 应做数量+单位 + 单价 + 状态 + 已报数量
  assert.match(doc.html, /定型/)
  assert.match(doc.html, /应做\s*11\.00\s*米/)
  assert.match(doc.html, /3\.50\s*元\/米/)
  assert.match(doc.html, /待领/)
  assert.match(doc.html, /已报\s*0\.00\s*米/)
  // ② 已完成的那道**也在**（不是只列待做），且状态是「已领」
  assert.match(doc.html, /已报\s*4\.00\s*米/, '已完成的那道必须也在清单里（工人要看「还有哪几道没做」）')
  assert.match(doc.html, /已领/)
  app.destroy()
})

test('🔴 ⑨-b 未定价的工序在明细里显式写「未定价」（≠ 0 元，V90/#4696）', async () => {
  const doc = fakeDom()
  const f = routeFetch({ '/api/worker/production/scan?': resolveOk(CLOTH_VIEW) })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')

  assert.match(doc.html, /未定价/, 'unit_price 为 null 的工序必须显式标注，不得折成 0 元')
  assert.ok(!/0\.00\s*元\/套/.test(doc.html), '未定价不得被渲染成 0 元')
  app.destroy()
})

test('🔴 ⑨-c 缺值不渲染：set_overview 缺失 / positions 为空 ⇒ 明细块一个字节都不出现', () => {
  const doc = fakeDom()
  const f = routeFetch({})
  const app = bootPage({ doc, f })

  // ① 整个键缺失（= 改前形态）
  const { set_overview: _drop, ...withoutOverview } = CLOTH_VIEW
  app.dispatch({ type: 'resolved', view: { ...withoutOverview, needs_selection: [] } })
  assert.ok(!/id="wh5-set-overview"/.test(doc.html), 'set_overview 缺失 ⇒ 不得渲染明细块')
  assert.ok(!/undefined/.test(doc.html), '缺值不得渲染成 undefined')

  // ② 键在但清单为空
  app.dispatch({ type: 'resolved', view: { ...CLOTH_VIEW, set_overview: { set_no: 14, positions: [] } } })
  assert.ok(!/id="wh5-set-overview"/.test(doc.html), 'positions 为空 ⇒ 不得渲染空壳明细块')

  // ③ 部位在但工序为空 / 工序缺 operation_id
  app.dispatch({
    type: 'resolved',
    view: { ...CLOTH_VIEW, set_overview: { set_no: 14, positions: [{ position_name: '布帘', operations: [] }] } },
  })
  assert.ok(!/id="wh5-set-overview"/.test(doc.html), '工序为空 ⇒ 不得渲染空壳明细块')
  assert.ok(!/NaN/.test(doc.html), '缺值不得渲染成 NaN')
  app.destroy()
})

test('🔴 ⑨-d 领活回执也带本套明细（工人不必再请求一次就看得到「还有哪几道没做」）', async () => {
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt({ set_overview: CLOTH_VIEW.set_overview }),
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')
  await doc.fire('wh5-report')

  assert.match(doc.html, /id="wh5-set-overview"/, '领活成功后本套明细必须仍在屏上（回执也带它）')
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

// ============================================================ ⑧ 幂等键跨刷新（issue #4814）

/**
 * 与 ③ 的分工：③ 判「**同一屏**重试复用同一个键」（内存里就够）；
 * ⑧ 判「**刷新/重开页面**（`state` 全丢）后重扫同一张码，仍然复用同一个键」。
 *
 * 🔴 为什么必须有 ⑧：断网是车间常态（设计 §9.3 D5）。改前刷新后键就没了 ⇒ 服务端把重扫当成
 * **新的一次报工**；而重扫时「待做工序」已推进到下一道 ⇒ 那一笔满额计件记在**没做的活**上
 * （ProductionScanCompleteServiceTest 有对应的服务端读数：换键 ⇒ 第二行 work_log）。
 */
test('🔴 ⑧ 断网（响应丢失）后**刷新重扫**同一张码 ⇒ 复用同一个幂等键（服务端回放，绝不二次记账）', async () => {
  // 同一台设备的 localStorage：`state` 会随刷新丢失，storage 不会
  const storage = memStorage({ [STORAGE_KEY]: JSON.stringify(SESSION) })

  // ── 第一次装载：解析成功；点【开工】时**传输层失败**（服务端到底落没落库，前端无从得知）
  const doc1 = fakeDom()
  const f1 = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': () => { throw new TypeError('Failed to fetch') },
  })
  const app1 = bootPage({ doc: doc1, f: f1, storage })
  await scan(doc1, 'tok-cloth')
  await doc1.fire('wh5-report')

  const firstPosts = f1.calls.filter((c) => c.method === 'POST')
  assert.equal(firstPosts.length, 1, '点一次【开工】= 一次请求（页面不静默重试）')
  const firstKey = firstPosts[0].headers['X-Client-Request-Id']
  assert.ok(firstKey, '写请求必须带幂等键')
  const saved = JSON.parse(storage.getItem(PENDING_REQUEST_KEY) ?? 'null')
  assert.equal(saved?.requestId, firstKey, '🔴 未确认提交必须落盘（不落盘 ⇒ 刷新后无据可查、只能换新键）')
  assert.equal(saved?.token, 'tok-cloth', '落盘的记录必须绑**这张码**')
  app1.destroy()

  // ── 第二次装载 = 工人刷新/重开页面：新页面实例、`state` 全丢（`__requestId` 随之消失）
  const doc2 = fakeDom()
  const f2 = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt({ replayed: true }),
  })
  const app2 = bootPage({ doc: doc2, f: f2, storage })
  await scan(doc2, 'tok-cloth')
  assert.match(doc2.html, /上次提交/, '重扫时必须告诉工人「重扫是安全的」（否则他不知道这一下会不会再记一笔）')

  await doc2.fire('wh5-report')
  const secondPosts = f2.calls.filter((c) => c.method === 'POST')
  assert.equal(secondPosts.length, 1)
  assert.equal(secondPosts[0].headers['X-Client-Request-Id'], firstKey,
    '🔴 刷新/重开后重扫同一张码必须复用**同一个**键 —— 换新键 = 服务端当成新报工（多记一笔计件）')
  assert.match(doc2.html, /没有新增计件/, '回执必须如实告诉工人这一笔没有新增计件')
  app2.destroy()
})

test('🔴 ⑧ 成功之后**不得**复用旧键（复用 = 下一道被服务端回放掉 ⇒ 静默漏计件）', async () => {
  const storage = memStorage({ [STORAGE_KEY]: JSON.stringify(SESSION) })
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt(),
  })
  const app = bootPage({ doc, f, storage })
  await scan(doc, 'tok-cloth')
  await doc.fire('wh5-report')   // 第一次：服务端已答复（成功）⇒ 这一笔有结论了
  await doc.fire('wh5-report')   // 屏上已是回执给的「下一道」= 新的一笔

  const keys = f.calls.filter((c) => c.method === 'POST').map((c) => c.headers['X-Client-Request-Id'])
  assert.equal(keys.length, 2)
  assert.notEqual(keys[0], keys[1],
    '🔴 成功之后必须换新键（复用 ⇒ 下一道被回放成「已报过」= 工人的活白干）')
  assert.equal(storage.getItem(PENDING_REQUEST_KEY), null, '服务端已答复 ⇒ 未确认记录必须清掉')
  app.destroy()
})

test('🔴 ⑧ 共用 PAD：另一个工人不得复用上一个人的未确认键（否则本人的活被回放成「已报过」）', async () => {
  const storage = memStorage({
    [STORAGE_KEY]: JSON.stringify(SESSION), // 现在这台设备上是 w-1（张三）
    [PENDING_REQUEST_KEY]: JSON.stringify({ token: 'tok-cloth', workerId: 'w-9', requestId: 'key-of-w-9' }),
  })
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt(),
  })
  const app = bootPage({ doc, f, storage })
  await scan(doc, 'tok-cloth')
  await doc.fire('wh5-report')

  const key = f.calls.find((c) => c.method === 'POST')?.headers['X-Client-Request-Id']
  assert.notEqual(key, 'key-of-w-9',
    '🔴 未确认记录必须绑**工人**：跨人复用的键会让第二个人的报工被回放成第一个人那次（漏记计件）')
  app.destroy()
})
