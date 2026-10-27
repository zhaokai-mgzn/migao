// case_ids: PG-098
//
// 工人端 H5「报返工的加工单」页 —— 纯函数判据（issue #7860），`node --test`，零 DOM。
//
// 判据对象 = `src/rework.mjs` 的**返回值**（不是「源码里有这行」）；每条用例都注明红证
// （怎么改会让它当场变红）。装配层 `rework-app.mjs` 只做接线：这里只钉「它接的是哪个读面」，
// 不测 DOM（仓库既有范式：纯函数全钉住，装配不造假 DOM）。
//
// 覆盖（与交付单逐条对应）：
//   ① 有行 —— 六个字段逐项上屏（加工单号 / 订单号 / 返工笔数 / 最近返工时间 / 最新原因 / 涉及工序）；
//   ② 空态 —— 「还没有报返工的加工单」，且**不是**错误态（出现 `wh5-rework-error` 即红）；
//   ③ 缺值 —— 缺项整项不渲染（不印 `—` / `undefined` / `null` / `NaN`）；整行无值 ⇒ 一行 `—`；
//   ④ 401 —— 显式「登录已失效」+ `/w/` 真链接（不静默重试）；
//   ⑤ 403 —— 「返工记录」页面键未开 ⇒ 可行动提示（与「读不到」「空」都分开）；
//   ⑥ 读不到 —— 人话文案 + 重新读取；技术原文（`err.technical`）永不上屏；
//   ⑦ 工序明细 —— 逐道 `工序名 ×数量`，缺数量只出工序名；
//   ⑧ 转义 —— 自由文本不进标记；
//   ⑨ 页头 —— 「当前工人」来自服务端对象；没有名字 ⇒ 整块不出现。

import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  buildReworkOperations,
  buildReworkRow,
  formatReworkAt,
  formatReworkCount,
  formatQty,
  renderPageHeader,
  renderReworkForbidden,
  renderReworkList,
  renderReworkLoginRequired,
  renderReworkRow,
  renderReworkUnreadable,
  REWORK_EMPTY,
  REWORK_FORBIDDEN,
  REWORK_LOGIN_HREF,
  REWORK_LOGIN_REQUIRED,
  REWORK_MISSING,
  REWORK_UNREADABLE,
  unreadableReason,
} from '../src/rework.mjs'

/** 服务端返回形状（`GET /api/worker/production/rework-orders`，下划线键）的**逐字样本**。 */
const SAMPLE = {
  orders: [
    {
      processing_order_id: 'po-1',
      processing_order_no: 'JG-20261026-0001',
      order_no: 'SO-20261026-0002',
      processing_status: 'in_processing',
      rework_count: 3,
      rework_qty: 6.0,
      latest_rework_at: '2026-10-26T17:00:00+08:00',
      latest_reason: '布面污渍',
      operations: [
        { operation_name: '车缝', qty: 2.0, count: 1 },
        { operation_name: '裁剪', qty: 4.5, count: 2 },
      ],
    },
    {
      processing_order_id: 'po-2',
      processing_order_no: 'JG-20261026-0007',
      order_no: null,
      processing_status: 'completed',
      rework_count: 1,
      rework_qty: null,
      latest_rework_at: null,
      latest_reason: null,
      operations: [{ operation_name: '质检', qty: 1.0, count: 1 }],
    },
  ],
}

const textOf = (html) => html.replace(/<[^>]*>/g, '')

// ══════════════════════════════════════════════════════════════════════════════
// ① 有行：六个字段逐项上屏
// ══════════════════════════════════════════════════════════════════════════════

test('① 有行：加工单号 / 订单号 / 返工笔数 / 最近返工 / 原因 / 涉及工序都上屏（按服务端顺序）', () => {
  const html = renderReworkList(SAMPLE)
  assert.match(html, /id="wh5-rework-count"[^>]*>共 2 张加工单有返工报工</, '行数由服务端行的条数决定')
  // 第一张：字段逐项在，且**顺序**与核对顺序一致（改顺序 ⇒ 断言红）
  assert.match(html, /id="wh5-rework-no-0">JG-20261026-0001</, '加工单号是标题行')
  assert.match(html, /id="wh5-rework-order_no-0">订单号：SO-20261026-0002</, '订单号')
  assert.match(html, /id="wh5-rework-rework_count-0">返工：3 笔</, '返工笔数')
  assert.match(html, /id="wh5-rework-latest_rework_at-0">最近返工：2026-10-26 17:00</, '最近返工时间（slice+T 换空格）')
  assert.match(html, /id="wh5-rework-latest_reason-0">原因：布面污渍</, '最新原因')
  assert.match(html, /id="wh5-rework-operations-0">涉及工序：车缝 ×2、裁剪 ×4\.5</, '涉及工序逐道 `工序名 ×数量`')
  // 第二张：缺值的那几项**整项不出现**（不是空串、不是 —）
  assert.match(html, /id="wh5-rework-no-1">JG-20261026-0007</)
  assert.doesNotMatch(html, /id="wh5-rework-order_no-1"/, '订单号缺 ⇒ 该项不渲染（不写 `—` 占位）')
  assert.doesNotMatch(html, /id="wh5-rework-latest_rework_at-1"/, '时间缺 ⇒ 该项不渲染')
  assert.doesNotMatch(html, /id="wh5-rework-latest_reason-1"/, '原因缺 ⇒ 该项不渲染')
  // 红证：把 `if (orderNo !== '')` 那类守卫删掉（改成永远 push）⇒ 上面三条 doesNotMatch 当场红
})

test('①-b 行数 = 服务端给的条数（本页不筛、不排、不截断）', () => {
  const orders = Array.from({ length: 5 }, (_, i) => ({
    ...SAMPLE.orders[0], processing_order_id: `po-${i}`, processing_order_no: `JG-${i}`,
  }))
  const html = renderReworkList({ orders })
  for (let i = 0; i < 5; i += 1) assert.match(html, new RegExp(`id="wh5-rework-row-${i}"`))
  assert.doesNotMatch(html, /id="wh5-rework-row-5"/, '不许凭空多出一行')
  // 红证：在 `renderReworkList` 里加 `.slice(0, 3)` 或 `filter(...)` ⇒ 本用例红
})

// ══════════════════════════════════════════════════════════════════════════════
// ② 空态：读了、真没有（不是错误态）
// ══════════════════════════════════════════════════════════════════════════════

test('② 空态只说事实：「还没有报返工的加工单」，且不得长得像错误', () => {
  for (const payload of [{ orders: [] }, {}, null, undefined]) {
    const html = renderReworkList(payload)
    assert.match(html, /id="wh5-rework-empty">还没有报返工的加工单</, '空态文案逐字')
    assert.equal(textOf(html).includes('失败'), false, '空态里出现「失败」= 把空当成错误（工人会反复重试）')
    assert.doesNotMatch(html, /wh5-rework-error/, '空态不得渲染错误块')
    assert.doesNotMatch(html, /id="wh5-rework-row-0"/, '空态不得有行')
    assert.match(html, /id="wh5-rework-count"[^>]*>共 0 张加工单有返工报工</, '空态的计数仍是事实（0）')
  }
  // 红证：把空态改走 `renderReworkUnreadable()`（或文案改成「读取失败」）⇒ 本用例红
})

// ══════════════════════════════════════════════════════════════════════════════
// ③ 缺值：整项不渲染；整行无值 ⇒ 如实一行 `—`
// ══════════════════════════════════════════════════════════════════════════════

test('③ 缺值不渲染占位：不出现 `undefined` / `null` / `NaN`，也不出现 `—` 占位', () => {
  const html = renderReworkList({ orders: SAMPLE.orders })
  for (const bad of ['undefined', 'null', 'NaN']) {
    assert.equal(html.includes(bad), false, `屏上出现 ${bad} = 拿原始值直接拼了（工人看不懂）`)
  }
  // 第二张（除标题外全缺）没有 `—`：标题可显示 ⇒ 不是「整行无值」
  const row1 = html.slice(html.indexOf('id="wh5-rework-row-1"'))
  assert.equal(row1.includes(REWORK_MISSING), false, '有加工单号就不许再补 `—`（缺项一律不渲染）')
  // 红证：把 `formatReworkCount` 的 `''` 兜底换成 `String(value)` ⇒ 「NaN/null」断言红
})

test('③-b 整行一个可显示值都没有 ⇒ 如实印一行 `—`（不渲染空卡片）', () => {
  const html = renderReworkRow({ processing_order_id: 'po-x' }, 0)
  assert.equal(textOf(html).trim(), REWORK_MISSING, '整行无值时必须有一个看得见的占位，否则是空白卡片')
  assert.match(html, /id="wh5-rework-no-0">—</)
  // 反向：只要有一个可显示值，就**不再**出现占位（两者择一，保持一致）
  const one = renderReworkRow({ processing_order_no: 'JG-1' }, 0)
  assert.equal(textOf(one).includes(REWORK_MISSING), false)
  // 红证：删掉 `heading === '' && lines === ''` 这一支 ⇒ 第一条断言红（渲染成空 `<li>`）
})

// ══════════════════════════════════════════════════════════════════════════════
// ④ 401：显式「登录已失效」+ 登录页真链接
// ══════════════════════════════════════════════════════════════════════════════

test('④ 401：显式「登录已失效」+ `/w/` 真链接（不静默重试）', () => {
  const html = renderReworkLoginRequired()
  assert.match(html, /id="wh5-rework-login-required">登录已失效：/, '必须明说登录已失效（不能只说「请登录」）')
  assert.equal(textOf(html).includes(REWORK_LOGIN_REQUIRED), true)
  assert.match(html, new RegExp(`<a[^>]*id="wh5-rework-login"[^>]*href="${REWORK_LOGIN_HREF}"`), '登录出口必须是真链接')
  assert.equal(REWORK_LOGIN_HREF, './', '登录页 = 工人端首页（改路径 ⇒ 红）')
  assert.doesNotMatch(html, /wh5-rework-retry/, '401 不许给「重新读取」（会话没了，重试不会成功）')
  assert.doesNotMatch(html, /失败/, '401 的文案是「登录已失效」，不是泛化的「失败」')
  // 红证：把 `<a href>` 换成 `<button>`（或删掉 href）⇒ 第二条断言红
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑤ 403：页面键未开 ⇒ 可行动提示（与「读不到」「空」都分开）
// ══════════════════════════════════════════════════════════════════════════════

test('⑤ 403：说清「返工记录」页没开 + 找管理员勾上（不冒充读不到/空）', () => {
  const html = renderReworkForbidden()
  assert.equal(textOf(html).includes(REWORK_FORBIDDEN), true)
  assert.match(html, /id="wh5-rework-forbidden">/, '403 有自己的稳定 id（判据按 id 取）')
  assert.match(textOf(html), /返工记录/, '文案必须用商家面的名字「返工记录」（工人拿这句话去找管理员）')
  assert.match(textOf(html), /管理员/, '必须说清该找谁')
  assert.doesNotMatch(html, /wh5-rework-retry/, '403 给「重新读取」= 让工人反复点一个不会成功的东西')
  assert.equal(textOf(html).includes('登录已失效'), false, '403 不是会话问题，不能说登录已失效')
  assert.doesNotMatch(html, /wh5-rework-empty/, '403 不是「没有返工」')
  assert.match(html, new RegExp(`href="${REWORK_LOGIN_HREF}"`), '403 也要有出路（返回报工）')
  // 红证：把 403 与「读不到」合成同一句（或删掉「管理员」）⇒ 本用例红
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑥ 读不到：人话文案 + 重新读取；技术原文永不上屏
// ══════════════════════════════════════════════════════════════════════════════

test('⑥ 读不到：人话兜底 + 重新读取；技术原文（technical）永不上屏', () => {
  const bare = renderReworkUnreadable()
  assert.equal(textOf(bare).includes(REWORK_UNREADABLE), true, '无 message 时用兜底人话')
  assert.match(bare, /id="wh5-rework-retry"[^>]*>重新读取</, '读不到必须有重试出口')
  assert.doesNotMatch(bare, /wh5-rework-empty/, '读不到不许冒充空态')

  // 技术原文只进日志面：`message` 是人话、`technical` 是原始串 ⇒ 只有前者上屏
  const reason = unreadableReason({ message: '网络不稳，请稍后重试', technical: 'TypeError: Failed to fetch' })
  assert.equal(reason, '网络不稳，请稍后重试')
  const html = renderReworkUnreadable({ message: '网络不稳，请稍后重试', technical: 'TypeError: Failed to fetch' })
  assert.equal(textOf(html).includes('TypeError'), false, '技术原文上屏 = 工人看不懂，且暴露内部细节')
  // 只有 technical、没有 message ⇒ 落到兜底人话（technical 不得被顶上屏）
  assert.equal(unreadableReason({ technical: 'HTTP 502' }), REWORK_UNREADABLE)
  assert.equal(unreadableReason({ message: '   ' }), REWORK_UNREADABLE, '空白 message 不算人话')
  // 红证：把 `unreadableReason` 改成 `err?.technical ?? err?.message` ⇒ 后两条断言红
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑦ 工序明细：逐道 `工序名 ×数量`
// ══════════════════════════════════════════════════════════════════════════════

test('⑦ 工序明细：逐道 `工序名 ×数量`；缺数量只出工序名；空/坏形状 ⇒ 整项不渲染', () => {
  assert.deepEqual(
    buildReworkOperations([{ operation_name: '车缝', qty: 2 }, { operation_name: '裁剪', qty: 4.5 }]),
    ['车缝 ×2', '裁剪 ×4.5'],
  )
  assert.deepEqual(buildReworkOperations([{ operation_name: '车缝' }]), ['车缝'], '缺数量不印 `×undefined`')
  assert.deepEqual(buildReworkOperations([{ operation_name: '车缝', qty: null }]), ['车缝'])
  assert.deepEqual(buildReworkOperations([{ operation_name: '车缝', qty: 'NaN' }]), ['车缝'], '坏数字不印 `×NaN`')
  assert.deepEqual(buildReworkOperations([{ qty: 2 }]), [], '没有工序名的一行是噪声（认不出哪道工序）')
  assert.deepEqual(buildReworkOperations([]), [])
  assert.deepEqual(buildReworkOperations(null), [], '缺 operations ⇒ 空数组（不是抛错）')
  assert.deepEqual(buildReworkOperations('车缝'), [], '坏形状（字符串）也不许抛错')
  // 至少一道：两道都上屏（不是只取第一条）
  const row = buildReworkRow({ operations: [{ operation_name: '车缝', qty: 1 }, { operation_name: '包装', qty: 3 }] })
  assert.equal(row.cells.find((c) => c.key === 'operations')?.text, '车缝 ×1、包装 ×3')
  // 红证：把 `operations.map` 改成 `operations.slice(0, 1)` ⇒ 最后一条断言红
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑧ 转义：自由文本不进标记
// ══════════════════════════════════════════════════════════════════════════════

test('⑧ 一律转义：单号 / 原因 / 工序名里的标记字符原样成文本', () => {
  const html = renderReworkList({
    orders: [{
      processing_order_no: 'JG<1>',
      order_no: 'SO&2',
      rework_count: 1,
      latest_reason: '<b>污渍</b>',
      operations: [{ operation_name: '车"缝', qty: 1 }],
    }],
  })
  assert.equal(html.includes('<b>污渍</b>'), false, '原因当标记渲染 = XSS 面')
  assert.match(html, /&lt;b&gt;污渍&lt;\/b&gt;/)
  assert.match(html, /JG&lt;1&gt;/, '单号里的 `<` 必须转义')
  assert.match(html, /SO&amp;2/, '`&` 必须转义')
  assert.match(html, /车&quot;缝/, '`"` 必须转义')
  // 红证：把 `esc()` 换成恒等函数（或只转 `&`）⇒ 前三条断言各自红
})

test('⑧-b 时间与数量格式：只切不改时区、只改写法不补零', () => {
  assert.equal(formatReworkAt('2026-10-26T17:00:00+08:00'), '2026-10-26 17:00')
  assert.equal(formatReworkAt('2026-10-26T23:59'), '2026-10-26 23:59')
  assert.equal(formatReworkAt('2026-10-26'), '', '切不出分钟 ⇒ 该项不渲染')
  assert.equal(formatReworkAt(null), '')
  assert.equal(formatReworkAt('  '), '')
  assert.equal(formatQty(2.0), '2')
  assert.equal(formatQty(2.5), '2.5')
  assert.equal(formatQty(0), '0', '0 是真的读数，不许当缺值')
  assert.equal(formatQty(''), '')
  assert.equal(formatQty(null), '')
  assert.equal(formatQty(undefined), '')
  assert.equal(formatReworkCount(3), '3 笔')
  assert.equal(formatReworkCount(null), '')
  // 红证：把 `formatReworkAt` 改成 `new Date(raw).toLocaleString()` ⇒ 第一条断言红（时区/写法都漂）
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑨ 页头「当前工人」（服务端来源）
// ══════════════════════════════════════════════════════════════════════════════

test('⑨ 页头：有名字才出现「当前工人」，且带回 `/w/` 的返回链接', () => {
  const html = renderPageHeader({ workerName: '张师傅', workerNo: 'W-001' })
  assert.match(html, /id="wh5-current-worker">当前工人：张师傅（工号 W-001）/, '当前工人必须常驻页头')
  assert.match(html, new RegExp(`<a[^>]*id="wh5-rework-back"[^>]*href="${REWORK_LOGIN_HREF}"`))
  assert.match(renderPageHeader({ worker_name: '李师傅' }), /当前工人：李师傅</, '兼容下划线键')
  assert.equal(renderPageHeader(null), '', '读不到工人 ⇒ 整块不出现（不印「当前工人：」空壳）')
  assert.equal(renderPageHeader({}), '')
  // 红证：把 `if (name === '') return ''` 删掉 ⇒ 最后两条断言红
})

// ══════════════════════════════════════════════════════════════════════════════
// ⑩ 装配层只接线（不造假 DOM）：读的是哪个端点、401/403 各自去哪
// ══════════════════════════════════════════════════════════════════════════════

test('⑩ 装配层：读面 = `api.listReworkOrders()`，401 判 `SESSION_EXPIRED`，403 单独一支', () => {
  const app = readFileSync(new URL('../src/rework-app.mjs', import.meta.url), 'utf8')
  assert.match(app, /await api\.listReworkOrders\(\)/, '列表只来自这一个读面（别处再拼一份 = 第二份口径）')
  assert.match(app, /e\?\.code === SESSION_EXPIRED/, '401 必须判 SESSION_EXPIRED（否则会被当成普通错误）')
  assert.match(app, /HTTP_FORBIDDEN/, '403 必须单独一支（页面键未开 ≠ 读不到）')
  assert.match(app, /api\.currentWorker\(\)/, '页头「当前工人」取服务端（PAD 共用时前端 state 不可信）')
  assert.equal(app.includes('fetch('), false, '装配层不许自己发请求（统一走 api.mjs）')
  assert.equal(app.includes('worker_id'), false, '不许在请求里自称工人（身份只由会话解）')
  // 红证：把 `await api.listReworkOrders()` 换成 `await api.listReadyShipments()` ⇒ 第一条断言红
})
