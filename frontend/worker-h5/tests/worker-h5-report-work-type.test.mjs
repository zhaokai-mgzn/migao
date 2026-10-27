// case_ids: BM-006
//
// 工人端 H5 报工页 —— **报工三态**（正常 / 返工 / 报废，issue #5652 第二刀）。
//
// 用户裁定（逐字）：服务端**已支持** `production_work_logs.work_type ∈ {normal, rework, scrap}`，
// 端侧只做**接线**；**不许新开端点**（仍是 `POST /api/worker/production/scan/complete`）；
// **不许动计件聚合**（服务端已排除 rework/scrap —— 后端 Java 一个字节都不改）。
//
// 本文件是这条接线的**唯一**机械判据，且**驱动真实装配层**（`createApp` + 假 DOM + fetch 替身）：
// 断言的是**页面实际发出的请求体**（URL / body / 请求头），不是「api.mjs 里有没有某个参数」。
// 🔴 为什么必须走真实装配层：本单要治的病正是「`api.completeByScan` **收得到** `workType`、
//   而**页面从来不传**」—— 只测 API 客户端（`tests/worker-h5-api.test.mjs` 已经在测它）
//   对「工人物理上能不能报返工/报废」**零判别力**（那正是改前的绿灯形态）。
//
// 零依赖（不引 jsdom/happy-dom）：假 DOM 只实现本页真正用到的那几个 API（最少代码阶梯）。
//
// 六条判据（每条都有对应断言，每条都能红）：
//   ① 默认 = **正常**，且屏上看得见这个默认（`is-on` + `aria-pressed="true"`）；
//   ② 选「正常」⇒ 请求体**没有** `work_type` 键（逐字节等于改前，零回归）且 `qualified_qty` 也**不出现**；
//   ③ 选「返工」⇒ `work_type:'rework'` + **`qualified_qty:0`**（数量诚实）；
//   ④ 选「报废」⇒ `work_type:'scrap'` + **`qualified_qty:0`**；
//   ⑤ 端点与幂等键一字不变：仍 POST `/api/worker/production/scan/complete`、仍带 `X-Client-Request-Id`；
//   ⑥ 选择**活过** in-flight 重绘（提交在飞时屏上仍是「报废」），且**报工成功后就地复位为「正常」**
//      （绝不把报废悄悄留给下一笔）。
//
// 🔴 为什么 `qualified_qty:0` 是硬判据（不是"顺手加一个 0"）：服务端
//    `ProductionScanCompleteService` 解析 `qualified_qty` 的缺省 = `qty`
//    （`BigDecimal qualifiedQty = rawQualified == null ? qty : …`）⇒ 只送 `work_type`
//    会把**报废**那一笔记成**满额合格**（合格率与计件口径双错）。
import test from 'node:test'
import assert from 'node:assert/strict'

import { createApi, STORAGE_KEY } from '../src/api.mjs'
import { createApp } from '../src/app.mjs'

// 本页用 `setTimeout` 做「闲置登出」定时器（15 分钟）。生产里它由 `app.destroy()` 清掉，
// 但**断言失败**的用例会在 destroy 之前抛 ⇒ 定时器留在事件循环 ⇒ `node --test` 不退出
// （红证根本跑不出来 —— 这是测试基础设施的坑，不是被测逻辑的）。测试侧把定时器一律 unref。
// （与 tests/worker-h5-scan-complete.test.mjs **同一把**处理，本文件不另创一套。）
const realSetTimeout = globalThis.setTimeout
globalThis.setTimeout = (...args) => {
  const t = realSetTimeout(...args)
  t.unref?.()
  return t
}

// ============================================================ 假 DOM（只实现本页用到的 API）

/**
 * 造一个假 `document`（与 tests/worker-h5-scan-complete.test.mjs 逐字同款的最小实现）。
 *
 * 本页真正用到的 DOM API 只有：`getElementById` / `querySelectorAll` / `root.innerHTML = …` /
 * `dataset` / `classList` —— 不需要 jsdom（最少代码阶梯：原生特性优先，不引依赖）。
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

  reindex() // 初始就挂上 `#worker-h5-root`（index.html 里那个 `<main id="worker-h5-root">`）

  return {
    get visibilityState() { return 'visible' },
    getElementById: (id) => byId.get(id),
    querySelectorAll: (sel) => all.filter((el) => matches(el, sel)),
    addEventListener(type, fn) { (docListeners.get(type) ?? docListeners.set(type, []).get(type)).push(fn) },
    removeEventListener() {},
    /** 点某个**有 id** 的元素（处理器是 async ⇒ 必须 await）。 */
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
    // 🔴 允许路由值是 **async**（⑥ 用「扣住应答」模拟弱网下的「提交在飞」）——
    //    不 await 的话 `resp` 是个 Promise，`resp.status` = undefined ⇒ 请求会**立刻失败**，
    //    判据就变成对着错误形态断言（实测踩过）。
    const resp = typeof r === 'function' ? await r(call) : r
    return { ok: resp.status >= 200 && resp.status < 300, status: resp.status, json: async () => resp.body }
  }
  fn.calls = calls
  return fn
}

// ============================================================ 服务端形状（逐字照 ProductionScanService）

/** 新码（套 × 部位）：布帘的码 ⇒ 推断出布帘的「定型」（11 米）。 */
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
  alternatives: [],
  set_progress: { total: 3, done: 1, percent: 33 },
  completed: false,
  completed_at: null,
  needs_selection: [],
}

/** 回执（逐字照 `applyScanComplete` 的键）。 */
const receipt = (over = {}) => ({
  status: 200,
  body: {
    success: true,
    data: {
      operation_id: 'op-cloth', done_qty: 11, status: 'done', order_completed: false,
      set_no: 14, position: { order_item_id: 'oi-cloth', position_name: '布帘' },
      set_progress: { total: 3, done: 2, percent: 66 }, set_completed: false,
      next_operation: { operation_id: 'op-cloth-2', logical_name: '打卷', position: '布帘', qty: 11, unit: '米' },
      ...over,
    },
  },
})

const resolveOk = (data) => ({ status: 200, body: { success: true, data } })

/** 装配一个已登录的页面（与 tests/worker-h5-scan-complete.test.mjs 同一把）。 */
function bootPage({ doc, f }) {
  const storage = memStorage({ [STORAGE_KEY]: JSON.stringify(SESSION) })
  const api = createApi({ fetchImpl: f, storage, baseUrl: '' })
  const app = createApp({ doc, api, location: 'https://app.migaozn.com/w/', storage })
  // issue #7845：页面里的手输短码框已撤 ⇒ 单测走装配层暴露的 `app.scan(code)`（与扫码落地 `?t=` 同一条 doScan）。
  doc.app = app
  app.dispatch({ type: 'worker', worker: { workerName: '张三', workerNo: 'A017', idleMinutes: 15 } })
  return app
}

// 扫一次码（程序化入口，issue #7845：手输框已撤；与 URL 落地 `?t=` 完全同一条 `doScan`）。
async function scan(doc, code) {
  await doc.app.scan(code)
}

/** 点一个**没有 id** 的元素（三态按钮只有 `data-work-type`）。 */
async function fireEl(el) {
  assert.ok(el, '要点的元素不在当前屏上')
  for (const fn of el.listeners.click ?? []) await fn()
}

/** 屏上的三态按钮（按 `data-work-type` 取；取法本身就是「控件真的在屏上吗」的判据）。 */
const workTypeBtn = (doc, type) => doc.querySelectorAll('[data-work-type]').find((el) => el.dataset.workType === type)

/** 拼一次 POST 的完整调用（**只看写请求**；解析面是 GET，混进来会让"发了几次"失真）。 */
const posts = (f) => f.calls.filter((c) => c.method === 'POST')

// ============================================================ ① 默认 = 正常，且看得见

test('🔴 ① 报工屏出现三态选择器：正常/返工/报废三选一，默认选中「正常」且选中态可见', async () => {
  const doc = fakeDom()
  const f = routeFetch({ '/api/worker/production/scan?': resolveOk(CLOTH_VIEW) })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')

  assert.match(doc.html, /id="wh5-work-type"/, '报工屏必须出现三态选择器（容器 id 稳定可定位）')
  assert.equal(doc.querySelectorAll('[data-work-type]').length, 3, '恰好三态：正常 / 返工 / 报废')
  assert.match(
    doc.html,
    /<button data-work-type="normal" class="wh5-choice is-on" aria-pressed="true" type="button">正常<\/button>/,
    '默认必须是「正常」，且选中态要写在屏上（is-on + aria-pressed）—— 不是只记在内存里',
  )
  for (const [type, label] of [['rework', '返工'], ['scrap', '报废']]) {
    assert.match(doc.html, new RegExp(`data-work-type="${type}"`), `必须能选「${label}」`)
  }
  // 选中态**唯一**：默认屏上只有「正常」是 is-on
  assert.equal(doc.querySelectorAll('[data-work-type]').filter((el) => el.classList.contains('is-on')).length, 1)
  app.destroy()
})

// ============================================================ ② 正常 = 逐字节等于改前

test('🔴 ② 默认「正常」⇒ 请求体**没有** work_type（也没有 qualified_qty）：与改前逐字节相同', async () => {
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt(),
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')
  await doc.fire('wh5-report')

  const [call] = posts(f)
  assert.equal(posts(f).length, 1, '点一次【报工】= 一次请求')
  // 🔴 这两条是**零回归**判据（改前就是这个 body）：多出任何一个键都要红
  assert.ok(!('work_type' in call.body), '「正常」不得送 work_type 键（送了 = 改前行为的字节级改变）')
  assert.ok(!('qualified_qty' in call.body), '「正常」不得送 qualified_qty（数量仍由服务端取「剩余应做」）')
  assert.deepEqual(Object.keys(call.body).sort(), ['token'], '正常路径的请求体只有 token（防呆⑤：工序/数量都由服务端定）')
  app.destroy()
})

// ============================================================ ③④ 返工 / 报废：逐值断言

for (const [raw, label] of [['rework', '返工'], ['scrap', '报废']]) {
  test(`🔴 ③④ 选「${label}」⇒ POST body = work_type:'${raw}' + **qualified_qty:0**（不把不合格的数量算成合格）`, async () => {
    const doc = fakeDom()
    const f = routeFetch({
      '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
      '/api/worker/production/scan/complete': receipt(),
    })
    const app = bootPage({ doc, f })
    await scan(doc, 'tok-cloth')

    await fireEl(workTypeBtn(doc, raw)) // 工人点「${label}」
    assert.match(
      doc.html,
      new RegExp(`<button data-work-type="${raw}" class="wh5-choice is-on" aria-pressed="true"`),
      `点完「${label}」⇒ 选中态必须换到它（看得见）`,
    )

    await doc.fire('wh5-report')
    const [call] = posts(f)
    assert.equal(posts(f).length, 1, '选择本身**不发请求**（三态是纯状态动作）；发请求的只有【报工】')
    assert.equal(call.body.work_type, raw, `「${label}」必须原样送出闭词表里的值`)
    assert.equal(call.body.qualified_qty, 0,
      '🔴 必须显式送 0：服务端 qualified_qty 缺省 = qty ⇒ 缺这个键会把不合格的数量记成满额合格')
    assert.ok(!('qty' in call.body), '不得编一个 qty：推进数量仍由服务端取「剩余应做」')
    app.destroy()
  })
}

// ============================================================ ⑤ 端点 / 幂等键不变

test('🔴 ⑤ 三态任一选择都仍是 POST /api/worker/production/scan/complete + 带 X-Client-Request-Id（不新开端点）', async () => {
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': receipt(),
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')
  await fireEl(workTypeBtn(doc, 'scrap'))
  await doc.fire('wh5-report')

  const [call] = posts(f)
  assert.match(call.url, /\/api\/worker\/production\/scan\/complete$/, '写入口必须还是这个既有端点（本单不新开端点）')
  assert.ok(!/\/report/.test(call.url), '不得回落到旧 /report 写路径（它不带码 ⇒ 防呆④⑤ 不生效）')
  assert.ok(call.headers['X-Client-Request-Id'], '幂等键必须照旧带上（三态不改变幂等契约）')
  assert.equal(call.headers['X-Worker-Session-Id'], 'sess-1', '身份仍只由 session 头解（body 里没有 worker_id）')
  assert.ok(!('worker_id' in call.body) && !('worker_name' in call.body), '身份不得进请求体')
  app.destroy()
})

// ============================================================ ⑥ 活过重绘 + 成功后复位

test('🔴 ⑥ 选择活过 in-flight 重绘（提交在飞时屏上仍是「报废」），报工成功后就地复位为「正常」', async () => {
  const doc = fakeDom()
  let release = null
  const held = new Promise((r) => { release = r })
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(CLOTH_VIEW),
    '/api/worker/production/scan/complete': async () => {
      await held // 扣住应答 = 模拟弱网下的「提交在飞」
      return receipt()
    },
  })
  const app = bootPage({ doc, f })
  await scan(doc, 'tok-cloth')
  await fireEl(workTypeBtn(doc, 'scrap'))

  const inflight = doc.fire('wh5-report') // 不 await：请求被扣住，屏上进入「提交中…」
  for (let i = 0; i < 5; i += 1) await new Promise((r) => setImmediate(r))

  assert.match(doc.html, /提交中…/, '前提没满足：重绘没发生')
  assert.match(
    doc.html,
    /<button data-work-type="scrap" class="wh5-choice is-on" aria-pressed="true"/,
    '🔴 in-flight 重绘不得把选择吃掉（吃掉了 ⇒ 工人以为自己在报废，其实那笔按「正常」报的）',
  )
  assert.equal(workTypeBtn(doc, 'scrap').listeners.click?.length ?? 0, 1, '重绘后三态按钮必须重新挂上委派（否则点了没反应）')

  release()
  await inflight

  // 报工已成功 ⇒ 屏上换成回执给的「下一道」，且三态**复位为正常**（不把报废留给下一笔）
  assert.match(
    doc.html,
    /<button data-work-type="normal" class="wh5-choice is-on" aria-pressed="true"/,
    '🔴 报工成功 ⇒ 必须复位为「正常」（否则下一笔正常做出来的活会被记成报废）',
  )
  assert.ok(
    !/data-work-type="scrap"[^>]*is-on/.test(doc.html),
    '🔴 成功后「报废」不得仍是选中态 —— 它是**下一笔**的选择，不是常驻口径',
  )
  app.destroy()
})

// ============================================================ ⑦ 选择器与按钮同生同灭

test('🔴 ⑦ 报工按钮不出现时（工序未确定 / 本套已完工）三态选择器也**一个字节都不出现**', async () => {
  const doc = fakeDom()
  const f = routeFetch({ '/api/worker/production/scan?': resolveOk(CLOTH_VIEW) })
  const app = bootPage({ doc, f })

  // 工序未确定（防呆⑤：记账判据的同一把）⇒ 无按钮、也无选择器
  app.dispatch({ type: 'resolved', view: { ...CLOTH_VIEW, operation: null, completed: true } })
  assert.ok(!/id="wh5-report"/.test(doc.html), '前提：工序未确定时不得出现报工按钮')
  assert.ok(!/id="wh5-work-type"/.test(doc.html), '没有报工按钮却出现三态选择器 = 半截形态（选了也报不了）')
  app.destroy()
})

// ============================================================ ⑧ 工人面**不得**出现成品帘质检判定入口

test('🔴 ⑧ 没开「质检」页的工人：只报数量归属（正常/返工/报废），无质检判定入口', async () => {
  const doc = fakeDom()
  const f = routeFetch({ '/api/worker/production/scan?': resolveOk(CLOTH_VIEW) })
  const app = bootPage({ doc, f })
  // 2026-10-27 改判（issue #7945）：质检判定只在 `inspect` ∈ 页面集的工人屏上出现
  app.dispatch({ type: 'pages', pages: ['report'] })
  app.dispatch({ type: 'resolved', view: CLOTH_VIEW })

  // 前提自证：屏上**真的**有报工三态（不是「整屏没渲染」造成的空判）
  assert.match(doc.html, /id="wh5-work-type"/, '前提：报工三态选择器必须在屏上')
  assert.match(doc.html, /data-work-type="scrap"/, '前提：三态之一「报废」必须在屏上')

  // 🔴 判据：没有 inspect 权限 ⇒ 质检区块 / 入口 / 表单一个都不出现（不看文案，看结构锚）
  for (const forbidden of [/id="wh5-quality"/, /id="wh5-quality-entry"/, /wh5-quality-form/,
    /data-inspection/, /inspection-result/]) {
    assert.ok(!forbidden.test(doc.html), `未开质检页的工人屏不得出现质检判定入口（命中 ${forbidden}）`)
  }

  // 负例自证（判别力）：同一把判据喂一条真会出现的质检面 HTML ⇒ 必须命中
  const inspectorFace = '<button id="wh5-quality-entry">质检</button>'
  assert.ok(/id="wh5-quality-entry"/.test(inspectorFace), '判别力自证：质检面 HTML 必须被同一把判据命中')

  app.destroy()
})

test('🔴 ⑧b 开了「质检」页的工人：页头出现「质检」入口 + 当前件质检块（做工判定）', async () => {
  const doc = fakeDom()
  const f = routeFetch({ '/api/worker/production/scan?': resolveOk(CLOTH_VIEW) })
  const app = bootPage({ doc, f })
  app.dispatch({ type: 'pages', pages: ['report', 'inspect'] })
  app.dispatch({ type: 'resolved', view: CLOTH_VIEW })

  assert.match(doc.html, /id="wh5-worker-entries"[\s\S]*id="wh5-quality-entry"/, '质检入口必须在页头动作栏')
  assert.match(doc.html, /id="wh5-quality"[^>]*>/, '质检块必须渲染（做工判定）')
  // 报工三态仍在（质检 ≠ 报工，两者并列）
  assert.match(doc.html, /id="wh5-work-type"/, '报工三态不得被质检入口挤掉')

  app.destroy()
})
