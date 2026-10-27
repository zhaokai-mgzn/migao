// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5「我的计件」页（issue #6767；口径真值源 = docs/design/worker-home-menu.md §6.3）—— **纯逻辑**。
//
// 🔴 为什么这一页的判据必须钉在「渲染结果读的是**服务端**给的数」上：
//    涉钱面最危险的形态是**第二份求和**（端侧自己 Σ lines[].amount）—— 它与服务端「同一份聚合」
//    平时看着一样，一旦口径分叉（返工扣减 / 改价 / 未定价）就**不会变红**。
//    故本文件所有金额断言都用**刻意不自洽**的夹具（lines 之和 ≠ 服务端 amount_total）：
//    页面渲染服务端的 `amount_total` 才绿；改成 Σlines ⇒ 当场红。
//
// 三条纪律（与后端同一份口径，前端不是「另一套」）：
//   ① **只读**：本页没有任何写动作（无确认 / 无锁定 / 无结算入口）；
//   ② **未定价 ≠ 0 元**：`unpriced` 只出「N 道未定价（未计入合计）」+ 逐条工序 + 件数，
//      **绝不**印 ¥0.00、绝不计入合计；
//   ③ **身份与期间都在服务端**：本页不显示也不发送 worker_id / worker_name（身份由
//      `X-Worker-Session-Id` 解），月份切换的 `prev_period` / `can_prev` 由服务端给（前端不推算月份边界）。

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { createApi, SESSION_HEADER, STORAGE_KEY } from '../src/api.mjs'
import { formatYuan, PIECEWORK_UNREADABLE, pieceworkView, renderPiecework, UNPRICED_NOTICE } from '../src/piecework.mjs'
import { createPieceworkApp, monthFromLocation } from '../src/piecework-app.mjs'

/** 服务端读数夹具（刻意让 lines 之和 5.00 ≠ amount_total 7.20 —— 「端侧自己求和」当场红）。 */
const VIEW = {
  worker_name: '张三',
  period: '2026-10',
  amount_total: 7.2,
  qty_total: 30,
  lines: [
    { operation: '精裁-布', logical_name: '精裁', position: '布帘', qty: 10, amount: 1.2 },
    { operation: '精裁-纱', logical_name: '精裁', position: '纱帘', qty: 10, amount: 1.4 },
    { operation: '质检', logical_name: '质检', position: null, qty: 10, amount: 2.4 },
  ],
  unpriced: {
    qty: 5,
    operations: [{ operation: '车被-布', logical_name: '车被', qty: 5 }],
    hint: '请在「企业基础设置 → 工序与部位单价」里定价',
  },
  prev_period: '2026-09',
  next_period: null,
  can_prev: true,
  can_next: false,
}

test('🔴 合计金额**逐值渲染服务端读数**（端侧自己求和 ⇒ 红）', () => {
  const html = renderPiecework(VIEW)
  assert.match(html, /id="wh5-piecework-total"[^>]*>¥7\.20</, '合计必须是服务端的 amount_total（7.20）')
  // 红证：Σlines.amount = 5.00 —— 若页面改成自己求和，这里就会印 ¥5.00（与下面这条相反）
  assert.ok(!html.includes('¥5.00'), '页面自己 Σ lines[].amount（5.00）⇒ 第二份求和实现，红')
  assert.match(html, /id="wh5-piecework-qty"[^>]*>30</, '件数来自服务端 qty_total')
})

test('🔴 未定价**显式列出**且不进合计（绝不印 0 元）', () => {
  const html = renderPiecework(VIEW)
  assert.match(html, /id="wh5-piecework-unpriced"/, '未定价必须有独立可见块（静默折 0 元 ⇒ 红）')
  assert.ok(html.includes(UNPRICED_NOTICE(1, 5)), '未定价要说清「几道 / 多少件 / 未计入合计」')
  assert.match(html, /未计入合计/, '必须显式说明「未计入合计」')
  assert.ok(html.includes('车被'), '未定价的工序名要逐条列出（否则工人不知道哪道没算钱）')
  assert.ok(!/id="wh5-piecework-unpriced"[\s\S]*?¥0\.00/.test(html), '未定价**绝不**印 ¥0.00')
})

test('逐笔：工序（逻辑名 · 部位）+ 件数 + 金额来自服务端 lines', () => {
  const html = renderPiecework(VIEW)
  assert.match(html, /id="wh5-piecework-lines"/, '逐笔清单要有稳定 id')
  assert.ok(html.includes('精裁 · 布帘'), '逐笔要按「逻辑名 · 部位」渲染（服务端读时派生）')
  assert.ok(html.includes('质检'), '部位缺失的工序照样列出（不猜、不隐藏）')
  assert.equal((html.match(/class="wh5-piecework-line"/g) ?? []).length, 3, '每笔一行')
})

test('期间切换只按服务端给的 can_prev / can_next（前端不推算月份边界）', () => {
  const html = renderPiecework(VIEW)
  assert.match(html, /id="wh5-piecework-prev"[^>]*data-month="2026-09"/, '上月按钮的月份值来自服务端')
  assert.ok(!html.includes('id="wh5-piecework-next"'), '服务端说 can_next=false ⇒ 不出「下月」按钮')
  const withNext = renderPiecework({ ...VIEW, period: '2026-09', next_period: '2026-10', can_next: true })
  assert.match(withNext, /id="wh5-piecework-next"[^>]*data-month="2026-10"/, 'can_next=true ⇒ 出「下月」按钮')
  assert.ok(!/2026-08/.test(html), '前端不得自己减一个月（prev_period 是服务端给的）')
})

test('🔴 只读：本页没有任何写动作 / 结算入口', () => {
  const html = renderPiecework(VIEW)
  assert.ok(!/<form|type="submit"/.test(html), '只读页不得有表单/提交')
  assert.ok(!/结算|锁定|确认计件/.test(html), '不做结算 / 锁定 / 确认（口径第 5 条）')
})

test('身份与空态：不显示 / 不发送 worker_id；无读数时如实说「本月暂无计件」而不是 0 元', () => {
  const empty = renderPiecework({ period: '2026-10', amount_total: 0, qty_total: 0, lines: [], unpriced: { qty: 0, operations: [] } })
  assert.ok(empty.includes('本月暂无计件'), '空月如实告知（不印 ¥0.00 充当读数）')
  assert.ok(!/\bworker_id\b/.test(renderPiecework(VIEW)), '页面不得回显 / 携带 worker_id（身份只由会话解）')
})

test('读数形状校验：不是对象 / 缺 amount_total ⇒ 抛错（由装配层显式上屏，不静默当 0）', () => {
  assert.throws(() => pieceworkView(null), new RegExp(PIECEWORK_UNREADABLE))
  assert.throws(() => pieceworkView({ qty_total: 3 }), new RegExp(PIECEWORK_UNREADABLE))
})

test('formatYuan：两位小数 + 千分位；null / 缺值 ⇒ —（不印 0）', () => {
  assert.equal(formatYuan(7.2), '¥7.20')
  assert.equal(formatYuan(1234.5), '¥1,234.50')
  assert.equal(formatYuan(null), '—')
  assert.equal(formatYuan(undefined), '—')
})

// ── API 客户端 + 装配层（issue #6767）────────────────────────────────────────────────────

/** 内存 localStorage 替身（与既有 worker-h5 测试同一写法）。 */
function memStorage(seed = {}) {
  const map = new Map(Object.entries(seed))
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
  }
}

const LOGGED_IN = { [STORAGE_KEY]: JSON.stringify({ sessionId: 'sess-1', workerName: '张三' }) }

test('🔴 API：`readPiecework` 只带 `month`，**绝不**带 worker_id / worker_name（作用域只认会话）', async () => {
  const calls = []
  const api = createApi({
    storage: memStorage(LOGGED_IN),
    fetchImpl: async (url, init = {}) => {
      calls.push({ url, init })
      return { ok: true, status: 200, json: async () => ({ success: true, data: VIEW }) }
    },
  })

  await api.readPiecework({})
  assert.equal(calls[0].url, '/api/worker/piecework', '缺省不带 month ⇒ 服务端按当前自然月')
  assert.equal(calls[0].init.headers[SESSION_HEADER], 'sess-1', '身份只在请求头上')

  await api.readPiecework({ month: '2026-09' })
  assert.equal(calls[1].url, '/api/worker/piecework?month=2026-09', '切月只传 month')
  for (const call of calls) {
    // 红证：一旦前端开始传 `worker_id`（想冒领 / 想指定看谁），本断言当场红
    assert.ok(!/worker_id|worker_name/.test(call.url), `请求里带上了身份参数（作用域必须只认会话）：${call.url}`)
  }
})

test('装配层：`?month=` 深链只认 YYYY-MM；非法值当缺省（不让 URL 决定服务端口径）', () => {
  assert.equal(monthFromLocation('https://x/w/piecework.html?month=2026-09'), '2026-09')
  assert.equal(monthFromLocation('https://x/w/piecework.html'), '')
  assert.equal(monthFromLocation('https://x/w/piecework.html?month=2026-9'), '')
  assert.equal(monthFromLocation('https://x/w/piecework.html?month=../etc'), '')
})

test('装配层：401 ⇒ 显式回落登录页（不静默重试、不按上一个人的身份读钱）', async () => {
  const root = { innerHTML: '' }
  const doc = {
    getElementById: (id) => (id === 'piecework-root' ? root : null),
    querySelector: () => null,
  }
  const api = {
    sessionId: () => 'sess-1',
    currentWorker: async () => ({ workerName: '张三' }),
    readPiecework: async () => {
      const err = new Error('登录已失效，请重新用工号 + PIN 登录')
      err.code = 'SESSION_EXPIRED'
      throw err
    },
  }
  const app = createPieceworkApp({ doc, api })
  await app.boot()
  assert.match(root.innerHTML, /id="wh5-piecework-login-required"/, '401 必须显式说清并给登录出口')
  assert.match(root.innerHTML, /href="\.\/"/, '登录出口是真链接')
})
