// case_ids: MC-157
//
// 机台页补「报返工」入口（issue #7992；壁达现场屏「工序返修」的对位功能）。
//
// ## 病（现取坐标）
// `frontend/worker-h5/src/machine.mjs` 的详情屏**只有【完成】一个动作** —— 而「报返工」流程
// **已经存在**（报工页 `render.mjs` 的 `#wh5-rework-action` + `api.mjs` 的 `reportRework`）。
// 结果：裁床发现这道做坏了，得退出机台页、回工人工作台、再找返工页，**扫过的这张唛还要重扫**。
//
// ## 判据（每条都能红：把对应实现改坏 ⇒ 本条红）
//   ① **入口在，且不抢主位**：详情屏出现「报返工」；主按钮**仍然是**【完成】
//      —— 唯一一个 `.wh5-machine__cta` 是「完成」，报返工是次要档 `.wh5-machine__back`
//      （§31 P1 常驻面克制：次要动作不许和主操作同等权重）；收起态原因按钮**零 DOM**。
//   ② **走既有 `reportRework`**：恰好一次 `POST /api/worker/production/rework`（不新造端点），
//      且装配层调的是 `api.reportRework(`（不在本页重写一套写面）。
//   ③ **上下文随码带出**：请求体 `token` = 刚扫到的那张码（服务端据此定位工单/部位/套号 ⇒
//      工人**不**再选一次机器）；body 是白名单（无 `worker_id` / 无 `operation_id`）；
//      展开态屏上摆「返工对象：<加工单号> · <部位>」（屏上别处没有印单号 ⇒ 不是重复信息）。
//   ④ **红证（注入式，见 PR body）**：把 `data-machine-rework` 那一个按钮从 `reportBlock` 删掉
//      ⇒ ① 必红（入口断言 + 唯一 cta 断言同时报）；本文件另内建**负控** ⑤：点【完成】仍走
//      `scan/complete`（次要动作没把主动作挤掉/接错线）。
//
// 零依赖：`node --test` + 手写假 doc / 假 fetch（不引 jsdom —— 最少代码阶梯：原生特性优先）。

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { CLIENT_REQUEST_ID_HEADER, createApi, SESSION_HEADER, STORAGE_KEY } from '../src/api.mjs'
import { createMachineApp } from '../src/machine-app.mjs'
import { MACHINE_REWORK_REASONS, reduceMachine, renderMachine, renderScan } from '../src/machine.mjs'

// ══════════════════════════════════════════════════════════════════════════════
// 夹具：假 doc（**没有 focus / activeElement**，且**文本框一个都不认** —— 本页刻意的 IME 护栏）
// ══════════════════════════════════════════════════════════════════════════════

/** 上屏 HTML 里**真**存在某个属性名（整名匹配，`data-machine-rework` 不匹配 `-open` / `-cancel`）。 */
function hasAttr(html, attr) {
  return new RegExp(`${attr}(?=[\\s>=])`).test(html)
}

/**
 * 极简假 doc：`querySelector` / `querySelectorAll` 都**按渲染出来的 HTML**回答 ——
 * 渲染里没有的元素，装不上监听（这就是「收起态零 DOM」这条判据得以成立的前提）。
 */
function fakeDoc() {
  const listeners = new Map()
  const handlers = new Map()
  const root = { innerHTML: '' }
  const bind = (sel, el) => el.addEventListener = (type, fn) => handlers.set(sel, [fn])
  return {
    root,
    getElementById: (id) => (id === 'machine-root' ? root : null),
    addEventListener: (type, fn) => listeners.set(type, [...(listeners.get(type) ?? []), fn]),
    removeEventListener: (type, fn) => listeners.set(type, (listeners.get(type) ?? []).filter((f) => f !== fn)),
    querySelectorAll(sel) {
      const attr = /^\[([a-z-]+)\]$/.exec(sel)?.[1]
      if (!attr) return []
      const out = []
      for (const m of root.innerHTML.matchAll(new RegExp(`${attr}="([^"]*)"`, 'g'))) {
        const el = { dataset: { [attr.replace(/^data-/, '').replace(/-([a-z])/g, (_, c) => c.toUpperCase())]: m[1] } }
        bind(`${attr}:${m[1]}`, el)
        out.push(el)
      }
      return out
    },
    querySelector(sel) {
      const attr = /^\[([a-z-]+)\]$/.exec(sel)?.[1]
      if (!attr) return null
      if (!hasAttr(root.innerHTML, attr)) return null
      const el = { dataset: {}, addEventListener: null }
      bind(sel, el)
      return el
    },
    /** 点一个按属性点名的元素（键 = `querySelector` 的 sel 或 `querySelectorAll` 的 `attr:值`）。 */
    click(sel) {
      for (const fn of handlers.get(sel) ?? []) fn()
    },
    /** 像 HID 键盘楔那样敲一串字符 + Enter。 */
    type(text) {
      for (const ch of [...text, 'Enter']) {
        for (const fn of listeners.get('keydown') ?? []) fn({ key: ch, preventDefault() {} })
      }
    },
  }
}

function fakeStorage(seed = {}) {
  const map = new Map(Object.entries(seed))
  return {
    map,
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  }
}

const once = () => new Promise((resolve) => setTimeout(resolve, 0))
const SESSION = JSON.stringify({ sessionId: 'sess-1', workerId: 'worker-zhang', workerName: '张三' })

/** 服务端一屏（与 `WorkerCuttingHeightService` 的键逐字同形；只要够定位「哪一单的哪一件」）。 */
function screen() {
  return {
    granularity: 'set_position',
    scanned: { order_item_id: 'it-cloth', position_kind: '布帘' },
    order: {
      order_id: 'order-1',
      order_no: 'SO20260929001',
      customer_name: '张女士',
      processing_order_no: 'JG20260929001',
      set_no: '1',
      set_index: 1,
      set_count: 3,
    },
    positions: [
      {
        order_item_id: 'it-cloth',
        position_kind: '布帘',
        position_name: '布帘',
        scanned: true,
        brand: '观星台',
        product_name: '全遮光布窗帘',
        width: 3.5,
        height: 2.7,
        craft: '韩褶',
        curtain_type: '布帘',
        open_count: null,
        cutting_mode: '定高买宽',
        fullness: 2,
        position_remark: '左窗',
        fabric_meters: 8.1,
        base: 2.7,
        cutting_height: 3.028,
        rounding: { mode: 'half_up', digits: 3 },
        hits: [{ key: 'jiaxian', name: '加线', value: 0.0625, direction: 'add', height_join: false }],
        misses: [],
        missing: [],
        missing_reason: null,
      },
    ],
  }
}

/** 返工回执（`ProductionReworkService` 的冻结键，见 api.mjs 的 `reportRework`）。 */
function reworkReceipt(overrides = {}) {
  return {
    rework_no: 'RW20261103001',
    operation_name: '裁剪',
    qty: 1,
    done_qty: 10,
    status: 'pending',
    order_completed: false,
    ...overrides,
  }
}

/**
 * 造一个机台页：假 doc + 记录请求的假 fetch。
 *
 * @param {object} [opts]
 * @param {object} [opts.rework] 报返工结果：缺省成功；`{fail:true, status, code, message}` = 失败
 */
function machineApp({ screenData = screen(), rework = null } = {}) {
  const doc = fakeDoc()
  const storage = fakeStorage({ [STORAGE_KEY]: SESSION })
  const calls = []
  const fetchImpl = async (url, opts) => {
    calls.push({
      url,
      method: opts?.method ?? 'GET',
      body: opts?.body === undefined ? null : JSON.parse(opts.body),
      headers: opts?.headers ?? {},
    })
    if (url.startsWith('/api/worker/production/rework')) {
      if (rework?.fail) {
        return {
          status: rework.status ?? 422,
          ok: false,
          json: async () => ({ success: false, error: { code: rework.code ?? 'VALIDATION_ERROR', message: rework.message } }),
        }
      }
      return { status: 200, ok: true, json: async () => ({ success: true, data: reworkReceipt(rework?.receipt) }) }
    }
    if (url.startsWith('/api/worker/production/scan/complete')) {
      return {
        status: 200,
        ok: true,
        json: async () => ({ success: true, data: { operation_id: 'op-2', next_operation: null, set_completed: false } }),
      }
    }
    return { status: 200, ok: true, json: async () => ({ success: true, data: screenData }) }
  }
  const api = createApi({ fetchImpl, storage, baseUrl: '' })
  const app = createMachineApp({ doc, api, location: 'https://7.app.migaozn.com/machine', storage })
  app.dispatch({ type: 'worker', worker: { workerName: '张三', workerId: 'worker-zhang' } })
  return { doc, app, calls, storage }
}

/** 扫一次 + 等一个微任务（走真实的全局 keydown ⇒ api 这条链）。 */
async function scan(app, doc, raw = 'https://7.app.migaozn.com/s/7K3M9QP2') {
  doc.type(raw)
  await once()
}

/** 读一份源码（判据 ② 的「不是新写一套」按源码面钉住）。 */
function src(name) {
  return readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8')
}

// ══════════════════════════════════════════════════════════════════════════════
// ① 入口在，且**不抢主位**（§31 P1：次要动作不许和【完成】同等权重）
// ══════════════════════════════════════════════════════════════════════════════

test('① 详情屏出现「报返工」入口，主按钮**仍然是**【完成】（唯一一个主色 CTA）', async () => {
  const { doc, app } = machineApp()
  await scan(app, doc)

  const html = doc.root.innerHTML
  assert.match(html, /data-machine-rework>报返工</, '机台详情屏必须有「报返工」入口（issue #7992）')

  // 🔴 负控：主按钮**没有被次要动作挤掉** —— 主色 CTA 有且只有「完成」一个
  const ctas = [...html.matchAll(/class="wh5-machine__cta"[^>]*>([^<]*)</g)].map((m) => m[1])
  assert.deepEqual(ctas, ['完成'], '主按钮位仍然只给【完成】；报返工不得升格成 .wh5-machine__cta')
  assert.match(
    html,
    /class="wh5-machine__back" data-machine-rework>报返工</,
    '报返工走次要档（.wh5-machine__back）—— 与【完成】同屏但不抢主位',
  )
})

test('①′ 收起态原因按钮**零 DOM**（常驻面不随条数增长）；没扫码时连入口都没有', async () => {
  const { doc, app } = machineApp()
  await scan(app, doc)

  assert.ok(!doc.root.innerHTML.includes('data-machine-rework-reason'), '原因按钮默认不渲染（不是 CSS 隐藏）')
  assert.ok(!doc.root.innerHTML.includes('data-machine-rework-open'), '展开块默认不渲染')

  // 没扫到码 ⇒ 没有可返工的对象 ⇒ 不给死按钮（只有 scan 态）
  const idle = renderScan({ mode: 'scan', worker: { workerName: '张三' } })
  assert.ok(!idle.includes('data-machine-rework'), '等扫码态不给「报返工」死按钮')
})

// ══════════════════════════════════════════════════════════════════════════════
// ② 走**既有** reportRework（不新造端点 / 不新写一套）
// ══════════════════════════════════════════════════════════════════════════════

test('② 点原因按钮 ⇒ 恰好一次 POST /api/worker/production/rework（既有端点）', async () => {
  const { doc, app, calls } = machineApp()
  await scan(app, doc)

  doc.click('[data-machine-rework]')
  assert.ok(doc.root.innerHTML.includes('data-machine-rework-reason="布面污渍"'), '点入口先展开原因条')

  doc.click(`data-machine-rework-reason:${MACHINE_REWORK_REASONS[0]}`)
  await once()

  const posts = calls.filter((c) => c.method === 'POST')
  assert.equal(posts.length, 1, '报返工只发一次写请求')
  assert.equal(posts[0].url, '/api/worker/production/rework', '🔴 复用既有唯一写入口，不新造端点')
  assert.equal(posts[0].body.reason, MACHINE_REWORK_REASONS[0])
  assert.equal(posts[0].headers[SESSION_HEADER], 'sess-1', '身份载体 = 服务端解的 session 头')
  assert.equal(app.state.reworkSubmitting, false)
})

test('②′ 装配层调的是既有 `api.reportRework(`（本页不重写写面、不出现端点字面量）', () => {
  // 只判**代码**：注释里写端点名是文档（本仓注释风格本来就带路径），不是第二份实现
  const code = src('machine-app.mjs').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
  assert.match(code, /api\.reportRework\(/, '报返工必须走 api.mjs 的既有方法')
  assert.ok(!/production\/rework(?![\w-])/.test(code), '装配层不许出现端点字面量（那是 api.mjs 的唯一职责）')

  const api = src('api.mjs').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
  assert.equal((api.match(/async reportRework\(/g) ?? []).length, 1, 'reportRework 只有一份实现（不新写一套）')
  assert.equal((api.match(/\/api\/worker\/production\/rework(?![-\w])/g) ?? []).length, 1, '端点只有一处（口径单一源；`rework-orders` 是另一条读面，不算）')
})

// ══════════════════════════════════════════════════════════════════════════════
// ③ 上下文随码带出（工人不再选一次机器 / 工单）
// ══════════════════════════════════════════════════════════════════════════════

test('③ 请求体 = 刚扫到的那张码 + 原因（白名单；无 worker_id / 无 operation_id）', async () => {
  const { doc, app, calls } = machineApp()
  await scan(app, doc)
  assert.equal(app.state.token, '7K3M9QP2', '上下文就是扫到的这张码')

  doc.click('[data-machine-rework]')
  doc.click(`data-machine-rework-reason:${MACHINE_REWORK_REASONS[1]}`)
  await once()

  const post = calls.find((c) => c.method === 'POST')
  assert.equal(post.body.token, '7K3M9QP2', '🔴 上下文随码带出：不再让工人选一次机器/工单')
  assert.deepEqual(Object.keys(post.body).sort(), ['reason', 'token'], '🔴 白名单：身份/工序/数量一个都不许带')
  assert.ok(!('worker_id' in post.body), '身份只由 X-Worker-Session-Id 解')
})

test('③′ 展开态摆出返工对象（加工单号 · 部位）—— 本屏别处没有印单号，所以不是重复信息', async () => {
  const { doc, app } = machineApp()
  await scan(app, doc)

  doc.click('[data-machine-rework]')
  const html = doc.root.innerHTML
  assert.match(html, /id="wh5-machine-rework-target"[^>]*>返工对象：JG20260929001 · 布帘</, '点原因前必须能确认「返的是哪一单的哪一件」')
})

test('③″ 换一张码 ⇒ 返工态不跨码携带（返的是这一件）', () => {
  const first = renderMachine({ ...baseState(), reworkOpen: true, reworkSubmitting: true })
  assert.ok(first.includes('data-machine-rework-open'), '前提：展开态确实渲染')

  const next = renderMachine(reduceMachine(renderState({ reworkOpen: true, reworkSubmitting: true }), {
    type: 'scanned',
    data: screen(),
    token: 'OTHER',
  }))
  assert.ok(!next.includes('data-machine-rework-open'), '新码必须收起上一次的返工展开态')
})

// ══════════════════════════════════════════════════════════════════════════════
// ④ 失败 / 成功两态：失败大字显式（不假装成功），成功摆服务端的返工单号
// ══════════════════════════════════════════════════════════════════════════════

test('④ 服务端 422 ⇒ 大字显式 + 原因条保持展开（换一个原因是合法动作）', async () => {
  const { doc, app } = machineApp({ rework: { fail: true, message: '报返工必须写明原因（哪件、什么问题）' } })
  await scan(app, doc)

  doc.click('[data-machine-rework]')
  doc.click(`data-machine-rework-reason:${MACHINE_REWORK_REASONS[0]}`)
  await once()

  const html = doc.root.innerHTML
  assert.match(html, /报返工失败：报返工必须写明原因/, '失败必须大字显式（服务端业务文案原样显示）')
  assert.match(html, /data-machine-rework-open/, '失败后原因条保持展开')
  assert.ok(!html.includes('data-machine-rework-done'), '绝不留下看起来像成功的回执')
  assert.equal(app.state.reworkSubmitting, false)
})

test('④′ 成功 ⇒ 摆服务端给的返工单号，入口变「返工已登记」', async () => {
  const { doc, app } = machineApp()
  await scan(app, doc)

  doc.click('[data-machine-rework]')
  doc.click(`data-machine-rework-reason:${MACHINE_REWORK_REASONS[2]}`)
  await once()

  const html = doc.root.innerHTML
  assert.match(html, /data-machine-rework-done>✅ 返工已登记 · 返工单 RW20261103001/, '返工单号由服务端给，前端不拼')
  assert.match(html, /class="wh5-machine__back" data-machine-rework disabled>返工已登记</, '成功后入口不可再点（防重复开单）')
  assert.match(html, /class="wh5-machine__cta"[^>]*>完成</, '🔴 报完返工后主按钮仍然是【完成】')
  assert.ok(!doc.root.innerHTML.includes('data-machine-rework-reason'), '成功后原因条收起')
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑤ 负控：次要动作没把主动作挤掉/接错线 —— 点【完成】仍走 scan/complete
// ══════════════════════════════════════════════════════════════════════════════

test('⑤ 负控：点【完成】仍走 scan/complete（报返工入口不改变主链）', async () => {
  const { doc, app, calls } = machineApp()
  await scan(app, doc)

  doc.click('[data-machine-report]')
  await once()

  const posts = calls.filter((c) => c.method === 'POST')
  assert.equal(posts.length, 1)
  assert.equal(posts[0].url, '/api/worker/production/scan/complete')
  assert.deepEqual(Object.keys(posts[0].body), ['token'])
  assert.ok(!calls.some((c) => c.url.includes('/production/rework')), '点【完成】不许连带发返工请求')
  assert.equal(app.state.reworkReceipt, null)
})

// ══════════════════════════════════════════════════════════════════════════════
// 夹具（③″ 用）：最小可用 state
// ══════════════════════════════════════════════════════════════════════════════

function renderState(overrides = {}) {
  return { ...baseState(), ...overrides }
}

function baseState() {
  return {
    mode: 'detail',
    worker: { workerName: '张三' },
    token: '7K3M9QP2',
    data: screen(),
    positionIndex: 0,
    unchecked: [],
    notice: null,
    error: null,
    reporting: false,
    receipt: null,
    reportError: null,
    reworkOpen: false,
    reworkSubmitting: false,
    reworkReceipt: null,
    reworkError: null,
  }
}
