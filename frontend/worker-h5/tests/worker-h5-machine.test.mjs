// case_ids: PG-018, BM-006, DF-017
//
// 一体机「机台模式」判据（母单 #5161；设计 docs/design/cutting-height-config-and-terminal.md §2.6
// + 2026-09-29 追加裁定「一体机本期要做报工，且是一条链」）。
//
// 六条判据（每条都能红：把对应实现改坏 ⇒ 本条红）：
//   ① **扫一次码 ⇒ 同一屏出 订单详情 + 裁高值大字 + 【完成】按钮**：全局 keydown
//      （**不依赖 focus**）喂进一串字符 + Enter ⇒ 一个 GET ⇒ 详情字段出现（缺的键显示「—」，不猜）。
//   ② **未配置取值（「画线」形态）不计入、且显式标黄报出**（不按 0 算）。
//   ③ **取整三位小数**：3.0275 ⇒ 3.028（half_up，digits=3）。
//   ④ 🔴 **不写机器**：扫码/切部位/手改全程零写请求；组件源码里没有串口 / Modbus / 蓝牙写面。
//   ⑤ **扫码输入不依赖 focus**（假 doc 没有 focus/activeElement）；CR+LF / 双 Enter / 输入法都不出错。
//   ⑥ **报工 = 既有 `POST /api/worker/production/scan/complete`**，且**报工值不得被前端改写**：
//      请求体**只有** `token`（幂等键走 `X-Client-Request-Id` 头）—— 数量/工序/身份全由服务端定；
//      手改的裁高取舍**不进**报工请求；失败大字显式、不假装成功；成功显示「已报工 · 下一道 = X」。
//
// 零依赖：`node --test` + 手写假 doc / 假 fetch（不引 jsdom —— 最少代码阶梯：原生特性优先）。

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { CLIENT_REQUEST_ID_HEADER, createApi, SESSION_HEADER, STORAGE_KEY } from '../src/api.mjs'
import { createMachineApp } from '../src/machine-app.mjs'
import { PENDING_REQUEST_KEY } from '../src/app.mjs'
import {
  createScanBuffer,
  hitRows,
  machineTotal,
  reduceMachine,
  renderCalc,
  renderMachine,
  resumePending,
  unresolvedRows,
} from '../src/machine.mjs'

// ══════════════════════════════════════════════════════════════════════════════
// 夹具：假 doc（**没有 focus / activeElement** —— 这正是判据⑤要钉的东西）/ 假 fetch / 假 storage
// ══════════════════════════════════════════════════════════════════════════════

/** 极简假 doc：只提供本包真正用到的三件事（getElementById / addEventListener / querySelector）。 */
function fakeDoc() {
  const listeners = new Map()
  const handlers = new Map()
  const root = { innerHTML: '', dataset: {} }
  return {
    root,
    getElementById: (id) => (id === 'machine-root' ? root : null),
    addEventListener: (type, fn) => listeners.set(type, [...(listeners.get(type) ?? []), fn]),
    removeEventListener: (type, fn) => listeners.set(type, (listeners.get(type) ?? []).filter((f) => f !== fn)),
    querySelectorAll: () => [],
    // 每次重渲染后旧元素已不存在 ⇒ 同名选择器**覆盖**（不是追加）
    querySelector: (sel) => ({ addEventListener: (type, fn) => handlers.set(sel, [fn]) }),
    click: (sel) => { for (const fn of handlers.get(sel) ?? []) fn() },
    /** 像 HID 键盘楔那样敲一串字符 + 终结符（每下都是一次独立事件）。 */
    type(text, { terminator = ['Enter'] } = {}) {
      const events = []
      for (const ch of text) events.push({ key: ch })
      for (const key of terminator) events.push({ key })
      return events.map((event) => {
        const record = { ...event, prevented: 0, preventDefault() { this.prevented++ } }
        for (const fn of listeners.get('keydown') ?? []) fn(record)
        return record
      })
    },
    composition(type) {
      for (const fn of listeners.get(type) ?? []) fn({})
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

/** 服务端一屏（与 WorkerCuttingHeightService 的键逐字同形）。 */
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
        brand: '米高',
        product_name: '全遮光布窗帘',
        width: 3.5,
        height: 2.7,
        craft: '韩褶',
        curtain_type: '布帘',
        open_count: null, // 缺 ⇒ 页面必须显示「—」（不猜 0）
        cutting_mode: '定高买宽',
        fullness: 2,
        position_remark: '左窗',
        fabric_meters: 8.1,
        base: 2.7,
        cutting_height: 3.028,
        rounding: { mode: 'half_up', digits: 3 },
        hits: [
          { key: 'jiaxian', name: '加线', value: 0.0625, direction: 'add', height_join: false },
          { key: 'butie', name: '布贴', value: 0.015, direction: 'add', height_join: false },
          { key: 'jiagao', name: '加高拼接', value: 0.2, direction: 'add', height_join: true },
          { key: 'baobian', name: '包边', value: 0.05, direction: 'add', height_join: false },
        ],
        misses: [{ key: 'huaxian', name: '画线', reason: 'unresolved' }],
        missing: [],
        missing_reason: null,
      },
      {
        order_item_id: 'it-gauze',
        position_kind: '纱帘',
        position_name: '纱帘',
        scanned: false,
        brand: null,
        product_name: null,
        width: null,
        height: 2.4,
        craft: null,
        curtain_type: '纱帘',
        open_count: null,
        cutting_mode: null,
        fullness: null,
        position_remark: null,
        fabric_meters: null,
        base: 2.4,
        cutting_height: 2.48,
        rounding: { mode: 'half_up', digits: 3 },
        hits: [{ key: 'shazhe', name: '纱折', value: 0.08, direction: 'add', height_join: false }],
        misses: [],
        missing: [],
        missing_reason: null,
      },
    ],
  }
}

/** 报工回执（`ProductionScanCompleteService` 的冻结键）。 */
function receipt(overrides = {}) {
  return {
    operation_id: 'op-2',
    done_qty: 11,
    status: 'done',
    order_completed: false,
    replayed: false,
    set_no: '1',
    position: '布帘',
    set_progress: { total: 3, done: 2 },
    set_completed: false,
    next_operation: { operation_id: 'op-3', logical_name: '车位', position: '布帘' },
    ...overrides,
  }
}

/**
 * 造一个机台页：假 doc + 记录请求的假 fetch。
 *
 * @param {object} [opts]
 * @param {object} [opts.screenData] 裁高读面返回
 * @param {object|null} [opts.report] 报工结果：`receipt`（成功）或 `{status,code,message}`（失败）
 */
function machineApp({ screenData = screen(), report = null } = {}) {
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
    if (url.startsWith('/api/worker/production/scan/complete')) {
      if (report && report.fail) {
        return {
          status: report.status ?? 422,
          ok: false,
          json: async () => ({ success: false, error: { code: report.code ?? 'VALIDATION_ERROR', message: report.message } }),
        }
      }
      return { status: 200, ok: true, json: async () => ({ success: true, data: report?.receipt ?? receipt() }) }
    }
    return { status: 200, ok: true, json: async () => ({ success: true, data: screenData }) }
  }
  const api = createApi({ fetchImpl, storage, baseUrl: '' })
  const app = createMachineApp({ doc, api, location: 'https://7.app.migaozn.com/machine', storage })
  app.dispatch({ type: 'worker', worker: { workerName: '张三', workerId: 'worker-zhang' } })
  return { doc, app, calls, storage }
}

/** 扫一次 + 等一个微任务（走的是真实的全局 keydown ⇒ api 这条链）。 */
async function scan(app, doc, raw = 'https://7.app.migaozn.com/s/7K3M9QP2') {
  doc.type(raw)
  await once()
}

// ══════════════════════════════════════════════════════════════════════════════
// ① 扫一次码 ⇒ 同一屏：订单详情 + 裁高值大字 + 【完成】
// ══════════════════════════════════════════════════════════════════════════════

test('① 扫一次水洗唛（全局 keydown，不点任何输入框）⇒ 屏一 订单详情 + 裁高值大字 + 【完成】', async () => {
  const { doc, app, calls } = machineApp()

  await scan(app, doc)

  const html = doc.root.innerHTML
  assert.match(html, /订单详情/, '扫完必须直接给详情面（用户裁定：扫 ⇒ 直接展示订单详情）')
  assert.match(html, /米高/, '品牌')
  assert.match(html, /张女士/, '收货人')
  assert.match(html, /全遮光布窗帘/, '款式')
  assert.match(html, /套数<\/dt><dd>3套/, '套数（整数，不显示 3.000 套）')
  assert.match(html, /3\.500/, '宽（米，机器三位小数）')
  assert.match(html, /2\.700/, '高')
  assert.match(html, /定高买宽/, '加工类型')
  assert.match(html, /韩褶/, '安装工艺')
  assert.match(html, /8\.100/, '用料')
  assert.match(html, /左窗/, '部位备注')
  assert.match(html, /—/, '缺的键（开数）必须显式显示「—」，不猜')
  assert.match(html, /请在机器屏输入\s*<b>3\.028<\/b>\s*米/, '② 裁高值大字（与详情**同屏**）')
  assert.match(html, /data-machine-report/, '③ 【完成】按钮（同一屏）')
  // 一次扫码 = 一个 GET（码从 URL 里取出来，形态判定仍在服务端）
  assert.equal(calls.length, 1)
  assert.equal(calls[0].method, 'GET')
  assert.equal(calls[0].url, '/api/worker/production/cutting-height?token=7K3M9QP2')
  assert.equal(app.state.mode, 'detail')
})

test('①′ 屏二 裁高计算器：预勾命中项 + 大字（本次合计）', async () => {
  const { doc, app } = machineApp()
  await scan(app, doc)

  app.dispatch({ type: 'openCalc' })
  const html = doc.root.innerHTML
  assert.match(html, /裁高计算器/)
  assert.match(html, /加线/)
  assert.match(html, /包边/)
  assert.match(html, /请在机器屏输入\s*<b>3\.028<\/b>\s*米/)
  assert.match(html, /data-machine-report/, '屏二也要能报工（同一条链）')
  assert.equal(app.state.mode, 'calc')
})

test('①″ 部位切换：切到纱帘 ⇒ 用它自己的成品高与命中项（换部位重置手改）', async () => {
  const { doc, app } = machineApp()
  await scan(app, doc)

  app.dispatch({ type: 'openCalc' })
  app.dispatch({ type: 'toggleHit', key: 'jiaxian' })
  app.dispatch({ type: 'pick', index: 1 })

  assert.deepEqual(app.state.unchecked, [], '换部位必须把手改清掉（否则会把上一件帘的取舍算进来）')
  assert.match(doc.root.innerHTML, /请在机器屏输入\s*<b>2\.480<\/b>\s*米/)
})

// ══════════════════════════════════════════════════════════════════════════════
// ② 未配置取值：不计入 + 显式报出（不按 0 算）
// ══════════════════════════════════════════════════════════════════════════════

test('② 「画线」命中而未配置取值 ⇒ 标黄报出、**不计入**合计（绝不按 0 算）', async () => {
  const { doc, app } = machineApp()
  await scan(app, doc)
  app.dispatch({ type: 'openCalc' })

  const html = doc.root.innerHTML
  assert.match(html, /画线/)
  assert.match(html, /未配置取值/)
  assert.match(html, /wh5-machine__warn/, '必须标黄（结构性类名，不靠文案）')

  const cloth = screen().positions[0]
  assert.deepEqual(unresolvedRows(cloth).map((m) => m.key), ['huaxian'])
  assert.deepEqual(hitRows(cloth).map((h) => h.key), ['jiaxian', 'butie', 'jiagao', 'baobian'])
  assert.equal(machineTotal(cloth, []), 3.028)
  assert.ok(!hitRows(cloth).some((h) => h.name === '画线'), '未配置取值的项**不在**命中列表里（它只能在标黄区）')
})

// ══════════════════════════════════════════════════════════════════════════════
// ③ 取整三位小数
// ══════════════════════════════════════════════════════════════════════════════

test('③ 取整三位小数：3.0275 ⇒ 3.028（且显示三位）', () => {
  const cloth = screen().positions[0]
  assert.equal(machineTotal(cloth, []), 3.028, '手改合计必须与服务端规则值一致（同一取整位数）')
  assert.equal(machineTotal(cloth, []).toFixed(3), '3.028')
  assert.match(renderCalc({ data: screen(), unchecked: [], positionIndex: 0 }), /3\.028/)
  // 少一位就红：把 rounding.digits 改成 2 ⇒ 渲染成 3.03
  const twoDigits = { ...cloth, rounding: { mode: 'half_up', digits: 2 } }
  assert.match(renderCalc({ data: { positions: [twoDigits] }, unchecked: [], positionIndex: 0 }), /3\.03[^8]/)
})

test('③′ 手改只改本次显示：取消一项 ⇒ 合计变了、规则值仍在、标「手改」', () => {
  const state = reduceMachine({ data: screen(), positionIndex: 0, unchecked: [] }, { type: 'openCalc' })
  const edited = reduceMachine(state, { type: 'toggleHit', key: 'jiagao' })

  const html = renderCalc(edited)
  assert.match(html, /手改/)
  assert.match(html, /规则值/, '规则值（服务端）必须同时显示 —— 手改只是显示层的取舍')
  assert.match(html, /2\.828/, '3.028 − 0.2（加高拼接被取消）')
  assert.equal(machineTotal(screen().positions[0], ['jiagao']), 2.828)
  assert.match(html, /不落库、不留痕/)
})

// ══════════════════════════════════════════════════════════════════════════════
// ④ 🔴 不写机器
// ══════════════════════════════════════════════════════════════════════════════

test('④ 扫码 / 切部位 / 手改 ⇒ 全程**零写请求**（只有一个 GET，不写机器）', async () => {
  const { doc, app, calls } = machineApp()
  await scan(app, doc)
  app.dispatch({ type: 'openCalc' })
  app.dispatch({ type: 'toggleHit', key: 'jiaxian' })
  app.dispatch({ type: 'pick', index: 1 })

  assert.equal(calls.length, 1, '整个流程（扫码 + 切部位 + 手改）只该有一次读请求')
  assert.deepEqual(calls.map((c) => c.method), ['GET'])
  assert.ok(calls.every((c) => c.url.startsWith('/api/worker/production/cutting-height')), '只碰裁高读面')
})

test('④′ 组件源码里没有串口 / Modbus / 蓝牙写面（设计 §3 判据 8）', () => {
  // 剥注释：说明性注释里会**提到**这些词（写清「不做」本身就要点名），判据只该管**代码**
  const strip = (text) => text.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/\/\/[^\n]*/g, ' ')
  const sources = ['../src/machine.mjs', '../src/machine-app.mjs'].map((rel) =>
    strip(readFileSync(new URL(rel, import.meta.url), 'utf8')).toLowerCase())
  for (const token of ['serialport', 'jserialcomm', 'gnu.io', 'javax.comm', 'modbus', 'navigator.serial', 'bluetooth', 'writecharacteristic']) {
    for (const source of sources) {
      assert.ok(!source.includes(token), `出现 ${token} ⇒ 「不写机器」（用户裁定①）被破坏`)
    }
  }
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑤ 扫码输入不依赖 focus（keydown 直进）+ 输入法不吃字符
// ══════════════════════════════════════════════════════════════════════════════

test('⑤ 假 doc **没有 focus/activeElement**，扫码照样进（不依赖 focus）', async () => {
  const { doc, app, calls } = machineApp()
  assert.equal(doc.focus, undefined, '夹具刻意不给 focus：实现若依赖它，本用例当场炸')
  assert.equal(doc.activeElement, undefined)

  await scan(app, doc, '7K3M9QP2')

  assert.equal(calls.length, 1, '没有焦点也必须收到整串码')
  assert.equal(app.state.mode, 'detail')
})

test('⑤′ 码后缀 CR+LF / 双 Enter：空缓冲时的 Enter 被忽略（不会交出空码、也不会重复请求）', async () => {
  const codes = []
  const buffer = createScanBuffer({ onCode: (c) => codes.push(c), idleMs: 0 })
  const key = (k) => ({ key: k, prevented: 0, preventDefault() { this.prevented++ } })

  for (const ch of '7K3M9QP2') buffer.handleKeyDown(key(ch))
  const first = key('Enter')
  buffer.handleKeyDown(first)
  const second = key('Enter') // CR+LF 的第二下（缓冲已空）
  buffer.handleKeyDown(second)

  assert.deepEqual(codes, ['7K3M9QP2'], '一次扫码只交一次码')
  assert.equal(first.prevented, 1)
  assert.equal(second.prevented, 1, '空 Enter 也要吃掉默认行为（否则会「再点一次」当时聚焦的按钮）')
})

test('⑤″ 枪没配后缀时：静默 idleMs 也会交出（注入的定时器 ⇒ 判定与真实时钟无关）', () => {
  const codes = []
  const timers = []
  const buffer = createScanBuffer({
    onCode: (c) => codes.push(c),
    idleMs: 120,
    schedule: (fn) => { timers.push(fn); return timers.length },
    cancel: () => {},
  })
  for (const ch of '7K3M9QP2') buffer.handleKeyDown({ key: ch })
  assert.deepEqual(codes, [], '还没静默够 ⇒ 不交（免得把半截码当码）')
  timers.pop()()
  assert.deepEqual(codes, ['7K3M9QP2'])
})

test('⑤‴ 中文输入法：合成区间的按键**不进食**，合成文本不当码（机台页也没有文本输入元素）', () => {
  const codes = []
  const buffer = createScanBuffer({ onCode: (c) => codes.push(c), idleMs: 0 })
  buffer.handleCompositionStart()
  for (const ch of '画线') buffer.handleKeyDown({ key: ch })
  buffer.handleKeyDown({ key: 'Enter' })
  buffer.handleCompositionEnd()
  assert.deepEqual(codes, [], '输入法合成的内容绝不能被当成扫码结果')

  buffer.handleKeyDown({ key: '画', isComposing: true })
  buffer.handleKeyDown({ key: 'Enter', isComposing: true })
  assert.deepEqual(codes, [])

  // 渲染出的页面里没有任何**文本输入**元素 ⇒ IME 没有合成目标（第一道保险）
  const html = renderMachine({ data: screen(), positionIndex: 0, unchecked: [] })
  assert.ok(!/type="text"/.test(html))
  assert.ok(!/<textarea/.test(html))
  assert.ok(!/contenteditable/.test(html))
})

test('⑤⁗ 非扫码键不污染缓冲（Shift / Tab / 方向键 / 组合键）', () => {
  const codes = []
  const buffer = createScanBuffer({ onCode: (c) => codes.push(c), idleMs: 0 })
  for (const key of ['Shift', 'Tab', 'ArrowLeft', 'Control', 'F5']) buffer.handleKeyDown({ key })
  for (const ch of 'ABC') buffer.handleKeyDown({ key: ch })
  buffer.handleKeyDown({ key: 'Enter' })
  assert.deepEqual(codes, ['ABC'])
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑥ 报工（既有入口 scan/complete）：🔴 报工值不得被前端改写
// ══════════════════════════════════════════════════════════════════════════════

test('⑥ 点【完成】⇒ 恰好一次 POST scan/complete，**请求体只有 token**（数量/工序/身份都由服务端定）', async () => {
  const { doc, app, calls } = machineApp()
  await scan(app, doc)

  doc.click('[data-machine-report]')
  await once()

  const posts = calls.filter((c) => c.method === 'POST')
  assert.equal(posts.length, 1, '报工只有一个写入口（既有端点）')
  assert.equal(posts[0].url, '/api/worker/production/scan/complete')
  assert.deepEqual(Object.keys(posts[0].body), ['token'], '🔴 前端只发 token：数量 / 工序 / 身份一个都不许带')
  assert.equal(posts[0].body.token, '7K3M9QP2')
  assert.equal(posts[0].headers[SESSION_HEADER], 'sess-1', '身份载体 = 服务端解的 session 头')
  assert.ok(posts[0].headers[CLIENT_REQUEST_ID_HEADER], '幂等键走 X-Client-Request-Id 头')
  assert.equal(app.state.reporting, false)
})

test('⑥′ 🔴 手改裁高取舍**不进**报工请求（报工 ≠ 给机器输值）', async () => {
  const { doc, app, calls } = machineApp()
  await scan(app, doc)

  app.dispatch({ type: 'openCalc' })
  app.dispatch({ type: 'toggleHit', key: 'jiaxian' }) // 本次显示 2.9655 → 手改成少一项
  app.dispatch({ type: 'toggleHit', key: 'jiagao' })
  doc.click('[data-machine-report]')
  await once()

  const post = calls.find((c) => c.method === 'POST')
  assert.deepEqual(Object.keys(post.body), ['token'])
  assert.ok(!JSON.stringify(post.body).includes('2.8'), '屏上的数（含手改值）不得进请求体')
  assert.ok(!JSON.stringify(post.body).includes('jiaxian'))
})

test('⑥″ 成功 ⇒ 「已报工 · 下一道 = X」（下一道由服务端给），且按钮禁用防重复报工', async () => {
  const { doc, app } = machineApp()
  await scan(app, doc)

  doc.click('[data-machine-report]')
  await once()

  const html = doc.root.innerHTML
  assert.match(html, /已报工/)
  assert.match(html, /下一道 = 车位 · 布帘/, '下一道逐字取服务端回执（前端不猜工序）')
  assert.match(html, /disabled/, '报工成功后按钮必须禁用（防连点变成第二笔）')
  assert.equal(app.state.receipt.operationId, 'op-2')
})

test('⑥‴ 成功回执是服务端回放 ⇒ 明说「未重复计件」（不能假装是新记的一笔）', async () => {
  const { doc, app } = machineApp({ report: { receipt: receipt({ replayed: true }) } })
  await scan(app, doc)

  doc.click('[data-machine-report]')
  await once()

  assert.match(doc.root.innerHTML, /服务端回放，未重复计件/)
})

test('⑥⁗ 幂等键跨刷新复用：同码 + 同工人 ⇒ 复用**同一把**键（跨刷新也是）', async () => {
  const first = machineApp()
  await scan(first.app, first.doc)
  first.doc.click('[data-machine-report]')
  await once()
  const firstId = first.calls.find((c) => c.method === 'POST').headers[CLIENT_REQUEST_ID_HEADER]
  assert.equal(first.storage.getItem(PENDING_REQUEST_KEY), null, '服务端答复过 ⇒ 键必须清掉（下一笔换新键）')

  // 模拟「已发出、答复丢了」：页面重开，本地留着那次未确认的提交（就像 app.mjs 落盘的那一行）
  const again = machineApp()
  again.storage.setItem(PENDING_REQUEST_KEY,
    JSON.stringify({ token: '7K3M9QP2', workerId: 'worker-zhang', requestId: firstId }))
  await scan(again.app, again.doc)
  again.doc.click('[data-machine-report]')
  await once()

  const replayedId = again.calls.find((c) => c.method === 'POST').headers[CLIENT_REQUEST_ID_HEADER]
  assert.equal(replayedId, firstId, '同码 + 同工人 ⇒ 必须复用同一把键（否则服务端当成新的一次报工 = 多给钱）')

  // 换人 / 换码 ⇒ **绝不**复用（跨工人复用会把上一个人的报工回放给当前工人）
  const pending = { token: '7K3M9QP2', workerId: 'worker-li', requestId: firstId }
  assert.equal(resumePending(pending, { token: '7K3M9QP2', workerId: 'worker-zhang' }), null)
  assert.equal(resumePending({ ...pending, token: 'OTHER' }, { token: '7K3M9QP2', workerId: 'worker-li' }), null)
  assert.equal(resumePending(null, { token: '7K3M9QP2', workerId: 'worker-zhang' }), null)
  assert.equal(resumePending(pending, { token: '7K3M9QP2', workerId: 'worker-li' }), firstId)
})

test('⑥⁗′ 报工失败 ⇒ 屏上**大字报错**、不显示任何「已报工」（不假装成功）', async () => {
  const { doc, app, calls } = machineApp({ report: { fail: true, message: '该部位的工序未确定，无法报工' } })
  await scan(app, doc)

  doc.click('[data-machine-report]')
  await once()

  const html = doc.root.innerHTML
  assert.match(html, /报工失败/)
  assert.match(html, /该部位的工序未确定/)
  assert.ok(!/已报工 ·/.test(html), '失败时绝不能出现成功形态的字样')
  assert.equal(app.state.receipt, null)
  assert.equal(calls.filter((c) => c.method === 'POST').length, 1)
})

test('⑥⁗″ 报工传输层失败（断网）⇒ 键**保留**（重按是回放而不是第二笔）；服务端答复过 ⇒ 键清掉', async () => {
  const doc = fakeDoc()
  const storage = fakeStorage({ [STORAGE_KEY]: SESSION })
  const calls = []
  let offline = true
  const fetchImpl = async (url, opts) => {
    calls.push({ url, method: opts?.method ?? 'GET', headers: opts?.headers ?? {} })
    if (url.startsWith('/api/worker/production/scan/complete') && offline) {
      const err = new Error('Failed to fetch')
      throw err // 无 HTTP 响应 ⇒ 传输层失败
    }
    if (url.startsWith('/api/worker/production/scan/complete')) {
      return { status: 200, ok: true, json: async () => ({ success: true, data: receipt() }) }
    }
    return { status: 200, ok: true, json: async () => ({ success: true, data: screen() }) }
  }
  const api = createApi({ fetchImpl, storage, baseUrl: '' })
  const app = createMachineApp({ doc, api, storage })
  await scan(app, doc)

  doc.click('[data-machine-report]')
  await once()
  const firstId = calls.find((c) => c.method === 'POST').headers[CLIENT_REQUEST_ID_HEADER]
  assert.ok(storage.getItem(PENDING_REQUEST_KEY), '断网 ⇒ 未确认的那一笔必须留在本地')
  assert.match(doc.root.innerHTML, /报工失败/)

  // 人工重试（页面上就是再点一次【完成】）
  offline = false
  doc.click('[data-machine-report]')
  await once()
  const posts = calls.filter((c) => c.method === 'POST')
  assert.equal(posts[1].headers[CLIENT_REQUEST_ID_HEADER], firstId, '重试必须复用同一把键（服务端回放）')
  assert.equal(storage.getItem(PENDING_REQUEST_KEY), null, '拿到答复 ⇒ 清键')
  assert.match(doc.root.innerHTML, /已报工/)
})

test('⑥⁗‴ 未登录（401）⇒ 大字回落「登录已失效」，零写请求外观（只有那一次 GET）', async () => {
  const doc = fakeDoc()
  const storage = fakeStorage({ [STORAGE_KEY]: SESSION })
  const calls = []
  const unauthorized = async (url, opts) => {
    calls.push({ url, method: opts?.method ?? 'GET' })
    return { status: 401, ok: false, json: async () => ({ success: false, error: { code: 'UNAUTHORIZED' } }) }
  }
  const api = createApi({ fetchImpl: unauthorized, storage, baseUrl: '' })
  const app = createMachineApp({ doc, api, storage })

  await scan(app, doc, '7K3M9QP2')

  assert.equal(app.state.mode, 'error')
  assert.match(doc.root.innerHTML, /登录已失效/)
  assert.deepEqual(calls.map((c) => c.method), ['GET'])
})

// ══════════════════════════════════════════════════════════════════════════════
// 失败一律显式报缺（码无效 / 缺成品高）
// ══════════════════════════════════════════════════════════════════════════════

test('失败：码无效 ⇒ 大字报错 + 提示重扫（不静默、不猜 0）', async () => {
  const doc = fakeDoc()
  const storage = fakeStorage({ [STORAGE_KEY]: SESSION })
  const failing = async () => ({ status: 404, ok: false, json: async () => ({ success: false, error: { code: 'NOT_FOUND', message: '订单不存在' } }) })
  const api = createApi({ fetchImpl: failing, storage, baseUrl: '' })
  const app = createMachineApp({ doc, api, storage })

  doc.type('https://app.migaozn.com/s/NOPE')
  await once()

  assert.equal(app.state.mode, 'error')
  assert.match(doc.root.innerHTML, /订单不存在/)
  assert.match(doc.root.innerHTML, /请重新扫一次水洗唛/)
})

test('失败：缺成品高 ⇒ 指名报缺、**不算数**（页面不出现任何编造的裁高值，也不给「请输 X 米」）', async () => {
  const data = screen()
  data.positions[0] = {
    ...data.positions[0],
    height: null, base: null, cutting_height: null, hits: [], misses: [],
    missing: ['finished_height'], missing_reason: '缺少 finished_height，无法计算裁剪高度',
  }
  const { doc, app } = machineApp({ screenData: data })
  await scan(app, doc)

  assert.match(doc.root.innerHTML, /finished_height/, '缺项必须指名')
  assert.ok(!/请在机器屏输入/.test(doc.root.innerHTML), '屏一缺值 ⇒ 不给「输入 X 米」（那会诱导工人照一个假数输入）')

  app.dispatch({ type: 'openCalc' })
  const html = doc.root.innerHTML
  assert.match(html, /算不出裁剪高度/)
  assert.match(html, /本页不猜数/)
  assert.ok(!/请在机器屏输入/.test(html))
})
