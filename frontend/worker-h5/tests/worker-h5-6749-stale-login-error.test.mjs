// case_ids: PG-065, BM-045, BM-006
//
// 工人端登录页：**成功后不得留下上一次失败的结论**（issue #6749）。
//
// 实测（改前 = origin/main 8874bee5b，逐字）：
//   initialState.error = null
//   ① 登录失败后  state.error = "工号或 PIN 不正确，请核对工号与 PIN 后重试"
//   ② 随后登录成功 state.error = "工号或 PIN 不正确，请核对工号与 PIN 后重试"   ← 非 null ⇒ 红字仍挂在屏上
//
// 病根：`frontend/worker-h5/src/render.mjs::reduce` 的 `case 'worker'` 只换身份、**不清错误位**，
// 而同一份 reduce 里别的成功迁移都清（`resolved` / `reportStart` / `completed` 都写 `error: null`；
// `logout` 直接回 `{ ...initialState() }`）⇒ 这是**漏网的一处**，不是有意口径。
//
// 现场影响：工人**第二次输对了 PIN**、页头已经换成「当前工人」，那句红字还留着 ⇒
// 「明明登进去了却还说我不对」——把刚成功的操作说成失败。
//
// 判据（三条，都能红）：
//   ① **state 层**：`case 'worker'`（worker 非空）后 `state.error` 必须是 `null`（把 `error: null` 撤掉 ⇒ 红）；
//   ② **屏面层**：失败红字渲染在 `#wh5-error` 之后**真跑一次成功登录**（假 DOM 点 `#wh5-login`）⇒
//      红字必须从 `innerHTML` 里消失（只清 state 不重渲染同样会红）；
//   ③ **反向钉住**：失败迁移（`case 'error'`）与登出仍按既有口径工作 ——
//      不许用「让错误位永不显示」这种改法把 ① 弄绿。
//
// 零依赖：`node --test` + 手写假 DOM / 假 fetch（不引 jsdom —— 最少代码阶梯）。
// 只 import 包内相对路径（`../src/**`）——**不静态 import 包外路径**（#6744 实证：会让部署 Docker 构建红）。

import test from 'node:test'
import assert from 'node:assert/strict'

import { createApi } from '../src/api.mjs'
import { createApp } from '../src/app.mjs'
import { reduce, initialState } from '../src/render.mjs'

/** 上一条失败留下的那句（`frontend/worker-h5/tests/worker-h5-6747-auth-failed-copy.test.mjs` 钉的就是它）。 */
const PREVIOUS_FAILURE = '工号或 PIN 不正确，请核对工号与 PIN 后重试'

const FAILED_LOGIN_BODY = { success: false, error: { code: 'AUTH_FAILED', message: '工号或 PIN 不正确' } }

/** 屏上红字（`#wh5-error` 的文本）—— 判据对象是**工人看到的那句话**，不是 state 字段。 */
const errorText = (html) => html.match(/<p class="wh5-error" id="wh5-error">([\s\S]*?)<\/p>/)?.[1]?.trim() ?? null

// ══════════════════════════════════════════════════════════════════════════════
// 夹具：假 DOM（够解析 `renderPage` 的产物即可） / 假 fetch / 内存 storage
// ══════════════════════════════════════════════════════════════════════════════

function makeStorage(seed = {}) {
  const map = new Map(Object.entries(seed))
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  }
}

function makeDom(rootId) {
  let html = ''
  const byId = new Map()
  let all = []

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

  const root = { get innerHTML() { return html }, set innerHTML(v) { html = v; reindex() } }
  const attrRe = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*"([^"]*)")?/g

  function reindex() {
    byId.clear()
    all = []
    const tagRe = /<([a-zA-Z][\w-]*)((?:"[^"]*"|[^>"])*)>/g
    let m
    while ((m = tagRe.exec(html))) {
      const attrs = {}
      attrRe.lastIndex = 0
      let a
      while ((a = attrRe.exec(m[2]))) attrs[a[1]] = a[2] ?? ''
      const el = mkEl(m[1], attrs)
      all.push(el)
      if (el.attrs.id) byId.set(el.attrs.id, el)
    }
    byId.set(rootId, root)
  }

  reindex()

  return {
    get html() { return html },
    get visibilityState() { return 'visible' },
    getElementById: (id) => byId.get(id),
    querySelector: (sel) => all.find((e) => e.attrs.id === sel.replace(/^#/, '')) ?? null,
    querySelectorAll: () => [],
    addEventListener() {},
    removeEventListener() {},
    async click(sel) {
      const el = byId.get(sel.replace(/^#/, ''))
      if (!el) throw new Error(`假 DOM 里找不到可点元素：${sel}`)
      for (const fn of el.listeners.click ?? []) await fn({ preventDefault() {} })
      return el
    },
    setValue(id, v) {
      const el = byId.get(id)
      if (!el) throw new Error(`假 DOM 里找不到 #${id}`)
      el.value = String(v)
    },
  }
}

/** 记录请求的 fetch 替身；答复按 URL 归一成**具名键**从可变 `routes` 取（测试可中途换答复）。 */
const keyOf = (url) => {
  if (url.endsWith('/api/worker/login')) return 'login'
  if (url.endsWith('/api/worker/me')) return 'me'
  if (url.endsWith('/api/worker/production/current-worker')) return 'worker'
  return url
}

function makeFetch(routes) {
  const calls = []
  const fn = async (url, init = {}) => {
    calls.push({ url, body: init.body ? JSON.parse(init.body) : null })
    const r = routes[keyOf(url)] ?? { status: 200, body: { success: true, data: {} } }
    return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body }
  }
  fn.calls = calls
  return fn
}

// ══════════════════════════════════════════════════════════════════════════════
// ① state 层：成功迁移必须清错误位
// ══════════════════════════════════════════════════════════════════════════════

test("🔴 ① `case 'worker'`（登录成功）后 `state.error` 必须是 null（撤掉 error: null ⇒ 本条必红）", () => {
  const failed = reduce({ ...initialState(), mode: 'login' }, { type: 'error', error: PREVIOUS_FAILURE })
  assert.equal(failed.error, PREVIOUS_FAILURE, '前置：失败迁移自己必须把 error 写上（否则本判据测不到东西）')
  const ok = reduce(failed, { type: 'worker', worker: { workerName: '张三', workerNo: 'w1', idleMinutes: 43200 } })
  assert.equal(ok.error, null, `登录成功后不得留着上一次失败的结论（实测 ${JSON.stringify(ok.error)}）`)
  assert.equal(ok.worker?.workerName, '张三', '前置：身份确实换上了（不是把整个 state 重置才"清干净"）')
})

test('🔴 ① 其它成功迁移的同族口径没有被本单改坏（清错误位不是"只有 worker 特例"）', () => {
  const failed = reduce({ ...initialState(), mode: 'login' }, { type: 'error', error: PREVIOUS_FAILURE })
  assert.equal(reduce(failed, { type: 'reportStart' }).error, null, 'reportStart 仍清（#6667 既有口径）')
  assert.equal(reduce(failed, { type: 'resolved', view: null }).error, null, 'resolved 仍清')
  assert.equal(reduce(failed, { type: 'completed', view: { id: 'v' } }).error, null, 'completed 仍清')
  assert.equal(reduce(failed, { type: 'logout' }).error, null, 'logout 回初值仍清')
})

// ══════════════════════════════════════════════════════════════════════════════
// ② 屏面层：真跑一次「失败 → 点登录成功」⇒ 红字必须从屏上消失
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ② 真装配层：失败红字上屏后第二次登录成功 ⇒ 屏上必须没有 `#wh5-error`（只清 state 不重渲染也红）', async () => {
  // 同一份假 DOM、同一个 app 实例、**同一条真按钮路径**（`#wh5-login` → `api.login` → `fail()`）：
  //   第一次 ⇒ 服务端 401（红字上屏）  第二次 ⇒ 服务端 200（登录成功）
  // 用**n 发式**答复（第 1 次 401、第 2 次 200）驱动真实错误路径，而不是手工 dispatch 一个 action。
  const loginBodies = [
    { status: 401, body: FAILED_LOGIN_BODY },
    {
      status: 200,
      body: { success: true, data: { session_id: 's-1', worker_id: 'w1', worker_no: 'wuitest', worker_name: '张三', idle_minutes: 43200 } },
    },
  ]
  const simple = {
    me: { status: 200, body: { success: true, data: { worker_id: 'w1', worker_name: '张三', pages: ['report'] } } },
    worker: { status: 200, body: { success: true, data: { worker_id: 'w1', worker_no: 'wuitest', worker_name: '张三' } } },
  }
  let loginIdx = 0
  const base = makeFetch(simple)
  /** 登录：第 1 次 401、第 2 次 200；其余端点走 `simple`。 */
  const statefulFetch = async (url, init = {}) => {
    if (!url.endsWith('/api/worker/login')) return base(url, init)
    const r = loginBodies[Math.min(loginIdx++, loginBodies.length - 1)]
    return { ok: r.status >= 200 && r.status < 300, status: r.status, json: async () => r.body }
  }
  const doc = makeDom('worker-h5-root')
  const api = createApi({ storage: makeStorage(), fetchImpl: statefulFetch })
  const app = createApp({ doc, api, location: { href: 'https://app.migaozn.com/w/', replace() {} }, storage: makeStorage() })
  app.dispatch({ type: 'notice', notice: null }) // 触发一次 draw ⇒ bind() 挂上按钮
  doc.setValue('wh5-worker-no', 'wuitest')
  doc.setValue('wh5-pin', 'wrongpin')
  doc.setValue('wh5-enterprise-code', 'migao')
  await doc.click('#wh5-login')

  assert.equal(errorText(doc.html), PREVIOUS_FAILURE, '前置：失败红字必须先真的渲上屏（否则下面的断言是空断言）')

  // 第二次：工人改对了 PIN ⇒ 服务端放行
  doc.setValue('wh5-pin', 'correctpin')
  await doc.click('#wh5-login')

  assert.equal(errorText(doc.html), null, `登录成功后屏上不得还留着上次失败的红字（实测 ${JSON.stringify(errorText(doc.html))}）`)
  assert.equal(doc.html.includes('wh5-error'), false, '整块 `#wh5-error` 都必须消失，不只是文本变空')
  assert.ok(doc.html.includes('wh5-current-worker'), '前置：这次确实登录成功了（页头换成「当前工人」）')
})

// ══════════════════════════════════════════════════════════════════════════════
// ③ 反向钉住：不许用「让错误位永不显示」把 ①② 弄绿
// ══════════════════════════════════════════════════════════════════════════════

test('🔴 ③ 失败迁移仍把红字放上屏（本单只清"成功之后"的残留，不许把错误面一起关掉）', async () => {
  const f = makeFetch({ login: { status: 401, body: FAILED_LOGIN_BODY } })
  const doc = makeDom('worker-h5-root')
  const api = createApi({ storage: makeStorage(), fetchImpl: f })
  const app = createApp({ doc, api, location: { href: 'https://app.migaozn.com/w/', replace() {} }, storage: makeStorage() })
  app.dispatch({ type: 'notice', notice: null })
  doc.setValue('wh5-worker-no', 'wuitest')
  doc.setValue('wh5-pin', 'wrongpin')
  await doc.click('#wh5-login')
  assert.equal(errorText(doc.html), PREVIOUS_FAILURE, '失败面的红字照旧上屏（#6747 的文案一字不动）')
})

test('🔴 ③ 登出后错误位仍是初值（清得掉、也回得来；不许把 state.error 变成永久 null）', () => {
  const failed = reduce({ ...initialState(), mode: 'login' }, { type: 'error', error: PREVIOUS_FAILURE })
  const out = reduce(failed, { type: 'logout' })
  assert.equal(out.error, null, '登出回初值')
  const again = reduce(out, { type: 'error', error: '又一次失败' })
  assert.equal(again.error, '又一次失败', '错误位仍可被写上（不是被改成永不显示）')
})
