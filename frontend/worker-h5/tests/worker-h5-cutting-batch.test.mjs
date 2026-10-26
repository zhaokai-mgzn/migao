// case_ids: UI-137
//
// 工人端 H5 —— **裁剪报工确认批次**（issue #7647，用户 2026-10-24 逐字）：
//   「裁剪报工的时候需要工人裁剪的哪个批次，如果通过智能派单的就默认展示指定批次，允许工人改，
//     如果没指定批次就需要工人手输才能完成报工，并且实时更新库存」
//
// 本文件是这条契约在**工人端**的唯一机械判据，且**驱动真实装配层**（`createApp` + 假 DOM + fetch 替身）：
// 断言的是页面**实际发出的请求体**与**实际渲染出的字**，不是「render.mjs 里有没有某个函数」。
//
// 七条判据（每条都能红；红证 = 把实现改回改前形态 ⇒ 本条红）：
//   ① 裁剪 + 派工指定批次 ⇒ 批次区块出现、输入框**预填**该批次（且可改）；
//   ② 裁剪 + 没有派工批次 ⇒ 输入框**空**、报工按钮不可点（与既有禁用态同一套）+ 一句可行动提示；
//   ③ 填入批次 ⇒ 按钮可用（**就地**更新，输入框实例不变 = 不整页重绘）+ 提交体**含** `batch_no`；
//      未填 ⇒ 硬点也**一个写请求都不发**；
//   ④ 非裁剪工序（`batch_required` 缺键 / false）⇒ 批次区块**不渲染**、按钮与请求体与改前**逐字一致**（老响应零回归）；
//   ⑤ 候选批次渲染 + 点一下就填入输入框；候选为空 ⇒ 整块候选区不渲染；
//   ⑥ 回执显示「批次 X · 余量 Y 米」；`batch_shortage_meters > 0` ⇒ 追加缺口提示；
//   ⑦ 回执三键**缺键 / null** ⇒ 屏上不出现 `undefined` / `NaN` / `null`；
//   ⑧ 报工后的下一屏**只认服务端重解析**（`next_batch_*`）：下一道不要批次 ⇒ 不摆输入框；
//      仍要批次（报废不推进进度）⇒ 输入框空 + 按钮禁用；服务端给了预填值 ⇒ 预填。
//      工人手输的值**不带到下一屏**（新一屏必须重新确认，绝不静默沿用）。
//
// 零依赖（不引 jsdom / happy-dom）：假 DOM 只实现本页真正用到的那几个 API（最少代码阶梯）。

import test from 'node:test'
import assert from 'node:assert/strict'

import { createApi, STORAGE_KEY } from '../src/api.mjs'
import { createApp } from '../src/app.mjs'
import { currentBatchNo, doneNotice, initialState, reduce } from '../src/render.mjs'

// 本页用 `setTimeout` 做「闲置登出」（30 天）。断言失败时用例会在 `destroy()` 之前抛 ⇒ 定时器留在
// 事件循环 ⇒ `node --test` 不退出（红证就跑不出来）。测试侧一律 unref：只保证进程能退，不改被测语义。
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
 * 用到的那几件事：`getElementById` / `querySelectorAll` / `root.innerHTML=` / `el.value` /
 * `el.dataset` / `addEventListener('input' | 'click')` / `disabled`。
 * `input` 的 `value` 属性按真实浏览器语义回填到 `.value`（预填值能被读出来）。
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
    const el = {
      tag,
      attrs,
      dataset,
      value: tag === 'input' && attrs.value !== undefined ? attrs.value : '',
      // 像真实浏览器那样：HTML 里的 `disabled` 属性 ⇒ 元素的 `.disabled` 为真
      disabled: 'disabled' in attrs,
      textContent: '',
      listeners: {},
    }
    el.addEventListener = (type, fn) => { (el.listeners[type] ??= []).push(fn) }
    el.classList = { contains: (c) => (attrs.class ?? '').split(/\s+/).includes(c) }
    return el
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

  reindex()

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
      for (let i = 0; i < 5; i += 1) await new Promise((r) => setImmediate(r))
    },
    /** 往输入框里打字（**走真实 `input` 事件**：门禁的就地更新必须由它驱动）。 */
    async type(id, value) {
      const el = byId.get(id)
      if (!el) throw new Error(`元素 #${id} 不在当前屏上`)
      el.value = value
      for (const fn of el.listeners.input ?? []) await fn()
      for (let i = 0; i < 3; i += 1) await new Promise((r) => setImmediate(r))
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
    calls.push({ url, method: init.method ?? 'GET', body: init.body ? JSON.parse(init.body) : null, headers: init.headers ?? {} })
    const key = Object.keys(routes).find((k) => url.includes(k))
    const r = (key ? routes[key] : { status: 500, body: { success: false, error: { message: `未路由：${url}` } } })
    const resp = typeof r === 'function' ? r(calls[calls.length - 1]) : r
    return { ok: resp.status >= 200 && resp.status < 300, status: resp.status, json: async () => resp.body }
  }
  fn.calls = calls
  return fn
}

// ============================================================ 服务端形状（逐字照契约）

/** 改前既有形状（**没有任何批次键**）—— 老后端 / 非裁剪工序的零回归基线。 */
const BASE_VIEW = {
  granularity: 'set_position',
  order_id: 'o-1',
  processing_order_no: 'JG20261024001',
  set_no: 3,
  set_index: 2,
  position: { order_item_id: 'oi-cloth', position_kind: '布帘', position_name: '布帘' },
  operation: {
    operation_id: 'op-cut', logical_name: '裁剪', position: '布帘', unit: '米', qty: 10,
    unit_price: 2.5, seq: 1, status: 'pending', determined_by: 'inferred', rerouted: false,
  },
  alternatives: [],
  set_progress: { total: 2, done: 0, percent: 0 },
  set_overview: {
    set_no: 3,
    positions: [
      {
        order_item_id: 'oi-cloth',
        position_kind: '布帘',
        position_name: '布帘',
        operations: [
          { operation_id: 'op-cut', logical_name: '裁剪', position: '布帘', seq: 1, qty: 10, unit: '米', unit_price: 2.5, status: 'pending', done_qty: 0 },
        ],
      },
    ],
  },
  completed: false,
  completed_at: null,
  needs_selection: [],
}

/** 裁剪 + 派工指定批次 + 候选批次（契约三键齐全）。 */
const VIEW_ASSIGNED = {
  ...BASE_VIEW,
  batch_required: true,
  batch_no: 'PC-20261020-0007',
  batch_candidates: [
    { batch_no: 'PC-20261020-0007', remaining_meters: 42.5, enough: true },
    { batch_no: 'PC-20261018-0002', remaining_meters: 3, enough: false },
  ],
}

/** 裁剪 + **没有**派工批次（工人必须手输）。 */
const VIEW_UNASSIGNED = {
  ...BASE_VIEW,
  batch_required: true,
  batch_no: null,
  batch_candidates: [],
}

/** 老后端 / 非裁剪工序：三键**全缺**。 */
const VIEW_LEGACY = { ...BASE_VIEW }

/** 服务端明确说「这一行不要批次」。 */
const VIEW_NOT_REQUIRED = { ...BASE_VIEW, batch_required: false }

/** 报工回执（逐字照契约的键；批次三键按场景覆盖）。 */
const receipt = (over = {}) => ({
  status: 200,
  body: {
    success: true,
    data: {
      operation_id: 'op-cut', done_qty: 10, status: 'done', order_completed: false,
      worker_id: 'w-1', worker_name: '张三', identity_source: 'server_session',
      set_no: 3, position: { order_item_id: 'oi-cloth', position_name: '布帘' }, rerouted: false,
      set_progress: { total: 2, done: 1, percent: 50 }, set_completed: false,
      next_operation: { operation_id: 'op-sew', logical_name: '车位', position: '布帘', qty: 10, unit: '米' },
      // 下一屏批次判据（issue #7647）：默认「下一道 = 车位」⇒ 不需要批次
      next_batch_required: false, next_batch_no: null, next_batch_candidates: [],
      ...over,
    },
  },
})

const resolveOk = (data) => ({ status: 200, body: { success: true, data } })

// ============================================================ 装配一个已登录的页面

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
async function scan(doc, code = 'tok-cut') {
  await doc.app.scan(code)
}

/** 点一个**没有 id** 的元素（候选批次这类按钮只有 data-*）。 */
async function fireEl(el) {
  assert.ok(el, '要点的元素不在当前屏上')
  for (const fn of el.listeners.click ?? []) await fn()
  for (let i = 0; i < 3; i += 1) await new Promise((r) => setImmediate(r))
}

/** 一次性搭好「已登录 + 已扫到指定视图」的页面。 */
async function pageFor({ view = VIEW_ASSIGNED, receiptBody = receipt() } = {}) {
  const doc = fakeDom()
  const f = routeFetch({
    '/api/worker/production/scan?': resolveOk(view),
    '/api/worker/production/scan/complete': receiptBody,
  })
  const app = bootPage({ doc, f })
  await scan(doc)
  return { doc, f, app }
}

const posts = (f) => f.calls.filter((c) => c.method === 'POST')
const inputHtml = (html) => html.match(/<input id="wh5-batch-input"[^>]*>/)?.[0] ?? ''
/** 屏上**文字**（去标签）—— 「不印 undefined」这类判据必须对着文字判，不能对着属性名判。 */
const textOf = (html) => html.replace(/<[^>]*>/g, ' ')
/** 回执那一句（`#wh5-notice`）的文字。 */
const noticeText = (html) => (html.match(/<p class="wh5-notice" id="wh5-notice">([\s\S]*?)<\/p>/)?.[1] ?? '')

// ============================================================ ① 有派工批次 ⇒ 预填、可改

test('🔴 ① 裁剪 + 派工指定批次 ⇒ 批次区块出现，输入框**预填**该批次（工人可改）', async () => {
  const { doc, app } = await pageFor()
  try {
    const html = doc.html
    assert.match(html, /id="wh5-batch"/, '裁剪工序必须有「批次」区块')
    assert.match(inputHtml(html), /value="PC-20261020-0007"/, '派工指定批次必须**预填**在输入框里（用户裁定：默认展示指定批次）')
    assert.match(inputHtml(html), /inputmode="text"/, '批次是文本（字母 + 数字 + 连字符）')
    assert.match(inputHtml(html), /autocomplete="off"/, '批次不许被浏览器自动填充（填错批次 = 记错库存）')
    assert.match(inputHtml(html), /placeholder="/, '必须给格式示例（工人不知道批次长什么样）')
    assert.ok(!/id="wh5-batch-input"[^>]*\bdisabled\b/.test(html), '输入框必须可改（用户逐字：「允许工人改」）')
    // 按钮：预填非空 ⇒ 可点（不是禁用的）
    assert.match(html, /<button id="wh5-report" class="wh5-primary" type="button">报 工<\/button>/)
  } finally {
    app.destroy()
  }
})

// ============================================================ ② 无派工批次 ⇒ 空 + 门禁

test('🔴 ② 裁剪 + 没有派工批次 ⇒ 输入框为空，报工按钮不可点 + 一句可行动提示', async () => {
  const { doc, app } = await pageFor({ view: VIEW_UNASSIGNED })
  try {
    const html = doc.html
    assert.match(html, /id="wh5-batch"/)
    assert.match(inputHtml(html), /value=""/, '没指定批次 ⇒ 输入框必须**空**（不许编一个值，也不许留 undefined）')
    assert.match(html, /<button id="wh5-report" class="wh5-primary" type="button" disabled>报 工<\/button>/,
      '没填批次 ⇒ 按钮不可点（与既有禁用态同一套形态）')
    assert.match(html, /id="wh5-batch-hint"[^>]*>请先填批次号再报工/, '必须给一句可行动提示（不能只是灰掉按钮）')
    // 候选为空 ⇒ 整块候选区不渲染（不摆空壳），且说明**不许**承诺一个屏上不存在的动作
    assert.ok(!html.includes('id="wh5-batch-candidates"'), '候选为空时整块候选区不渲染')
    assert.ok(!html.includes('候选'), '候选为空时说明里不许提「候选」（不能让工人去找一个不存在的按钮）')
  } finally {
    app.destroy()
  }
})

// ============================================================ ③ 填入 ⇒ 可点 + 请求体带 batch_no

test('🔴 ③ 填入批次 ⇒ 按钮可用（**就地**更新、输入框实例不变）+ 提交体**含** `batch_no`', async () => {
  const { doc, f, app } = await pageFor({ view: VIEW_UNASSIGNED })
  try {
    const before = doc.getElementById('wh5-batch-input')
    await doc.type('wh5-batch-input', 'PC-20261020-0009')
    // 🔴 输入过程中**不得**整页重渲染：重建输入框 = 焦点丢失、光标跳走（现场「打不进字」）
    assert.equal(doc.getElementById('wh5-batch-input'), before, '输入事件不得整页重渲染（输入框元素必须还是同一个）')
    assert.equal(doc.getElementById('wh5-report').disabled, false, '填入后按钮必须立刻可点（就地更新禁用态）')

    await doc.fire('wh5-report')

    const post = posts(f)[0]
    assert.ok(post, '填了批次点报工必须发请求')
    assert.equal(post.body.batch_no, 'PC-20261020-0009', '提交体必须带工人确认的批次')
    assert.equal(post.body.token, 'tok-cut', '写入口不变（唯一写入口 = scan/complete）')
  } finally {
    app.destroy()
  }
})

test('🔴 ③-b 未填批次 ⇒ 硬点【报工】也**一个写请求都不发**（前端先拦，服务端硬闸之外还有一道）', async () => {
  const { doc, f, app } = await pageFor({ view: VIEW_UNASSIGNED })
  try {
    await doc.fire('wh5-report') // 假 DOM 不模拟 `disabled` 的点击屏蔽 ⇒ 直接跑处理器（最坏情况）
    assert.equal(posts(f).length, 0, '没填批次时不得发出任何写请求')
    assert.match(doc.html, /id="wh5-error"[^>]*>请先填批次号再报工/, '拦住之后必须说清怎么办')
  } finally {
    app.destroy()
  }
})

// ============================================================ ④ 非裁剪 ⇒ 零回归

test('🔴 ④ 非裁剪工序（`batch_required` 缺键 / false）⇒ 批次区块**不渲染**、按钮与请求体与改前**逐字一致**', async () => {
  for (const [name, view] of [['缺键（老后端）', VIEW_LEGACY], ['服务端说不用', VIEW_NOT_REQUIRED]]) {
    const { doc, f, app } = await pageFor({ view })
    try {
      assert.ok(!doc.html.includes('wh5-batch'), `${name}：非裁剪工序不得出现任何批次区块`)
      assert.match(doc.html, /<button id="wh5-report" class="wh5-primary" type="button">报 工<\/button>/,
        `${name}：报工按钮必须与改前逐字节相同`)
      await doc.fire('wh5-report')
      assert.deepEqual(posts(f)[0].body, { token: 'tok-cut' }, `${name}：请求体必须与改前逐字一致（不许带 batch_no）`)
    } finally {
      app.destroy()
    }
  }
})

// ============================================================ ⑤ 候选批次：渲染 + 点了就填

test('🔴 ⑤ 候选批次渲染（带本批余量）+ 点一下就填入输入框', async () => {
  const { doc, app } = await pageFor({ view: VIEW_ASSIGNED })
  try {
    const html = doc.html
    assert.match(html, /data-batch-no="PC-20261020-0007"/, '候选批次必须是可点的快捷项（不引依赖，纯 button）')
    assert.match(html, /data-batch-no="PC-20261018-0002"/)
    assert.match(html, /余 42\.50 米/, '候选要带本批余量（工人据此看这一批够不够裁）')
    assert.match(html, /余量不足/, '服务端说不够（enough:false）⇒ 必须显式标出来')

    const pick = doc.querySelectorAll('[data-batch-no]').find((el) => el.dataset.batchNo === 'PC-20261018-0002')
    await fireEl(pick)
    assert.equal(doc.getElementById('wh5-batch-input').value, 'PC-20261018-0002', '点候选 = 直接填入输入框')
    assert.equal(doc.getElementById('wh5-report').disabled, false, '点完候选按钮必须可点')
  } finally {
    app.destroy()
  }
})

// ============================================================ ⑥ 回执：批次 + 余量 + 缺口

test('🔴 ⑥ 回执显示「批次 X · 余量 Y 米」；缺口 > 0 ⇒ 追加缺口提示（不责备、不惊叹号）', async () => {
  const { doc, app } = await pageFor({
    view: VIEW_UNASSIGNED,
    receiptBody: receipt({ batch_no: 'PC-20261020-0009', batch_remaining: 32.5, batch_shortage_meters: null }),
  })
  try {
    await doc.type('wh5-batch-input', 'PC-20261020-0009')
    await doc.fire('wh5-report')
    assert.match(doc.html, /批次 PC-20261020-0009 · 余量 32\.50 米/, '回执必须显示本次批次 + 该批次记账后余量')
    assert.ok(!/缺口/.test(doc.html), '没有缺口 ⇒ 不许提缺口')
  } finally {
    app.destroy()
  }

  const shortage = await pageFor({
    view: VIEW_UNASSIGNED,
    receiptBody: receipt({ batch_no: 'PC-20261020-0009', batch_remaining: -3.5, batch_shortage_meters: 3.5 }),
  })
  try {
    await shortage.doc.type('wh5-batch-input', 'PC-20261020-0009')
    await shortage.doc.fire('wh5-report')
    assert.match(shortage.doc.html, /批次 PC-20261020-0009 · 余量 -3\.50 米/)
    assert.match(shortage.doc.html, /本批余量不足，缺口 3\.50 米已如实记账/, '缺口 > 0 ⇒ 必须显式给缺口米数（不静默少扣）')
    assert.ok(!/缺口[^<]*[!！]/.test(shortage.doc.html), '业务文案不责备、不惊叹号')
  } finally {
    shortage.app.destroy()
  }
})

// ============================================================ ⑦ 缺键 / null ⇒ 不印 undefined / NaN

test('🔴 ⑦ 回执三键缺键 / null ⇒ 屏上不出现 `undefined` / `NaN` / `null`（缺键就缺）', async () => {
  for (const [name, over] of [
    ['三键缺键', {}],
    ['三键全 null', { batch_no: null, batch_remaining: null, batch_shortage_meters: null }],
    ['余量缺键', { batch_no: 'PC-20261020-0009', batch_shortage_meters: null }],
  ]) {
    const { doc, app } = await pageFor({ view: VIEW_UNASSIGNED, receiptBody: receipt(over) })
    try {
      await doc.type('wh5-batch-input', 'PC-20261020-0009')
      await doc.fire('wh5-report')
      const html = doc.html
      const text = textOf(html)
      for (const bad of ['undefined', 'NaN', 'null']) {
        assert.ok(!new RegExp(`\\b${bad}\\b`).test(text), `${name}：屏上文字出现了 \`${bad}\`（缺键必须整句不渲染）`)
      }
      const notice = noticeText(html)
      if (name === '三键缺键' || name === '三键全 null') {
        assert.ok(!notice.includes('批次') && !notice.includes('余量'), `${name}：回执里一句批次相关的话都不许出现（实际：${notice}）`)
      }
      if (name === '余量缺键') {
        assert.match(notice, /批次 PC-20261020-0009/, '批次在、余量缺 ⇒ 只显示批次')
        assert.ok(!notice.includes('余量'), '余量缺键 ⇒ 不渲染余量（不编 0）')
      }
    } finally {
      app.destroy()
    }
  }

  // 纯函数的判别力自证：缺键 / null 都不该产出任何批次文案
  assert.equal(doneNotice({}), '已报工')
  assert.equal(doneNotice({ batchNo: null, batchRemaining: null, batchShortageMeters: null }), '已报工')
  assert.equal(doneNotice({ batchNo: 'PC-1', batchRemaining: Number.NaN }), '已报工 · 批次 PC-1')
})

// ============================================================ ⑧ 新一屏不带走上一笔的批次

test('🔴 ⑧ 报工成功后的下一屏 ⇒ 下一道不要批次时**不摆**输入框（服务端 next_batch_required=false）', async () => {
  const { doc, app } = await pageFor({
    view: VIEW_ASSIGNED,
    receiptBody: receipt({
      batch_no: 'PC-20261020-0007', batch_remaining: 32.5, batch_shortage_meters: null,
      // 下一道 = 打包（不是「裁剪」）⇒ 服务端明确回 false
      next_batch_required: false, next_batch_no: null, next_batch_candidates: [],
    }),
  })
  try {
    await doc.fire('wh5-report') // 预填值直接提交
    const html = doc.html
    assert.ok(!html.includes('id="wh5-batch"'), '下一道不要求批次 ⇒ 批次区块一个字节都不出现')
    assert.match(html, /<button id="wh5-report" class="wh5-primary" type="button">报 工<\/button>/,
      '下一道照常可报（不能被上一屏的判据禁死）')
  } finally {
    app.destroy()
  }
})

test('🔴 ⑧′ 下一道**仍要**批次（报废不推进进度 ⇒ 仍是裁剪）⇒ 输入框空 + 按钮禁用 + 候选来自服务端', async () => {
  const { doc, app } = await pageFor({
    view: VIEW_ASSIGNED,
    receiptBody: receipt({
      batch_no: 'PC-20261020-0007', batch_remaining: 32.5, batch_shortage_meters: null,
      next_batch_required: true, next_batch_no: null,
      next_batch_candidates: [{ batch_no: 'PC-20261020-0007', remaining_meters: 32.5, enough: true }],
    }),
  })
  try {
    await doc.fire('wh5-report') // 预填值直接提交
    const html = doc.html
    assert.match(html, /id="wh5-batch"/, '下一道仍要确认批次')
    assert.match(inputHtml(html), /value=""/, '下一笔的输入框必须空（绝不把上一笔的批次留在框里）')
    assert.match(html, /<button id="wh5-report" class="wh5-primary" type="button" disabled>报 工<\/button>/)
    assert.match(html, /data-batch-no="PC-20261020-0007"/, '候选由服务端重解析下发')
  } finally {
    app.destroy()
  }
})

test('⑧″ 下一道仍要批次且服务端给了预填值 ⇒ 输入框预填（按钮可点）', async () => {
  const { doc, app } = await pageFor({
    view: VIEW_ASSIGNED,
    receiptBody: receipt({
      batch_no: 'PC-20261020-0007', batch_remaining: 32.5, batch_shortage_meters: null,
      next_batch_required: true, next_batch_no: 'PC-20261020-0007', next_batch_candidates: [],
    }),
  })
  try {
    await doc.fire('wh5-report')
    const html = doc.html
    assert.match(inputHtml(html), /value="PC-20261020-0007"/)
    assert.match(html, /<button id="wh5-report" class="wh5-primary" type="button">报 工<\/button>/)
  } finally {
    app.destroy()
  }
})

test('⑧-b 重扫 / 切屏（`resolved`）⇒ 手输的批次清回服务端预填值', () => {
  const state = { ...initialState(), worker: { workerName: '张三' }, batchNo: 'TYPED-BY-WORKER' }
  assert.equal(currentBatchNo(state, VIEW_ASSIGNED), 'TYPED-BY-WORKER')
  const next = reduce(state, { type: 'resolved', view: VIEW_ASSIGNED })
  assert.equal(next.batchNo, null, '新一屏必须回到「没动过输入框」')
  assert.equal(currentBatchNo(next, VIEW_ASSIGNED), 'PC-20261020-0007', '预填值重新来自服务端')
  // 登出回初值（换人 ⇒ 批次不跨界）
  assert.equal(reduce(next, { type: 'logout' }).batchNo, null)
  // 换人（`worker` 动作）**不**清：对账 `checkAlive` 也发这个动作，清掉会把工人正打在框里的批次抹掉
  assert.equal(reduce(state, { type: 'worker', worker: { workerName: '张三' } }).batchNo, 'TYPED-BY-WORKER')
})
