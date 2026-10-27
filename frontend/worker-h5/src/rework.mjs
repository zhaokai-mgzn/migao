// case_ids: PG-098
//
// 工人端 H5「报返工的加工单」页的纯逻辑（issue #7860）—— 零 DOM、零网络、零依赖。
//
// 判据都在本文件（`node --test` 直接钉住，见 `tests/worker-h5-rework-page.test.mjs`）；
// 装配层 `rework-app.mjs` 只接线。四条纪律（每条都有对应断言）：
//   ① 🔴 **列表不在前端筛 / 排 / 算**：行 = `GET /api/worker/production/rework-orders` 的
//      `orders[]` **原样**（笔数 / 数量合计 / 最新时间 / 工序明细都是服务端聚合的口径，
//      在这里再算一遍 = 第二份口径，迟早与后端分叉）；
//   ② 🔴 **缺值不渲染占位**：订单号 / 返工笔数 / 最近返工 / 原因 / 涉及工序 —— 缺了就**整项不出现**
//      （不印 `—`、不印 `undefined` / `null` / `NaN`）。唯一的例外是**整行一个可显示值都没有**：
//      那时如实印一行 `—`（工人看到空行会以为页面坏了）。两种取向在本文件里**只有这一处**分叉。
//   ③ 🔴 **三种失败面各有各的话**（互不冒充）：
//      · 空态「还没有报返工的加工单」= 读了、真没有（**不是**错误态）；
//      · 读不到 = 人话文案 + 「重新读取」（技术原文只进日志面，见 {@link unreadableReason}）；
//      · 401 = 「登录已失效」+ `/w/` 登录页**真链接**（不静默重试）；
//      · 403 = 工人档案页面集里没有 `rework` 键（`WorkerPages.REWORK`，商家面名字「返工记录」）
//        ⇒ **可行动**提示（找管理员勾上），**不**冒充「读不到」也不冒充「没有返工」。
//   ④ 🔴 **一律转义**：单号 / 原因 / 工序名都可能是自由文本（`&` `<` `"` 不上屏成标记）。
//
// 样式类**复用** `src/styles.css` 里已定义的 `wh5-ready-*`（同款「单据卡片列表」版式）：
// 本包不改 `styles.css`（由主会话持有），新造一个 `wh5-rework-*` 类会直接触发
// `tests/worker-h5-style-coverage.test.mjs`（`src/**/*.mjs` 里静态出现的每个 `wh5-*` 都必须有样式）。
//
// 零依赖（同 `api.mjs` / `shipment.mjs`）：同一份 `.mjs` 直接给浏览器 `<script type="module">` 用，
// 也给 `node --test` 用。

/** 登录页（同源静态页；本页未登录时的出口）。 */
export const REWORK_LOGIN_HREF = './'

/** 缺值占位符（**只在整行一个可显示值都没有时**出现；与发货纸面 `—` 同口径）。 */
export const REWORK_MISSING = '—'

/** 空态文案（读了、真没有 —— **不是**错误态）。 */
export const REWORK_EMPTY = '还没有报返工的加工单'

/** 读面失败时的兜底文案（技术原文留在 `err.technical`，屏上只出现人话）。 */
export const REWORK_UNREADABLE = '返工的加工单读取失败：请检查网络后刷新'

/** 401 的显式文案（本页没有登录面 ⇒ 说清失效 + 给真链接）。 */
export const REWORK_LOGIN_REQUIRED = '登录已失效：请先用工号 + PIN 登录，再查看报返工的加工单'

/**
 * 403 的文案：工人档案的页面集里没有 `rework`（商家面名字「返工记录」）。
 *
 * 🔴 必须**可行动**（找谁、做什么、之后怎么办）：这句文案对应的现场是「这个人本来该有这页」。
 */
export const REWORK_FORBIDDEN = '本机未开「返工记录」页：请让管理员在工人档案的页面里勾选「返工记录」，回来刷新即可'

/** 极简 HTML 转义（与 `render.mjs` / `shipment.mjs` 同口径）。 */
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}

/** 值 → 展示文本：去空白后为空 ⇒ `''`（**缺值不编造**；调用方据此整项不渲染）。 */
function text(value) {
  return value == null ? '' : String(value).trim()
}

/**
 * 数字 → 展示文本（`2.00` ⇒ `2`，`2.5` ⇒ `2.5`）；非数字 / 缺值 ⇒ `''`（**不印 `NaN`**）。
 *
 * 只做「数字本身的写法」，**不**做任何聚合（聚合口径在服务端）。
 */
export function formatQty(value) {
  if (value == null) return ''
  if (typeof value === 'string' && value.trim() === '') return ''
  const num = Number(value)
  return Number.isFinite(num) ? String(num) : ''
}

/** 返工笔数：`3` ⇒ `3 笔`；缺值 / 坏值 ⇒ `''`（整项不渲染，**不印 `0 笔` 冒充**）。 */
export function formatReworkCount(value) {
  const qty = formatQty(value)
  return qty === '' ? '' : `${qty} 笔`
}

/**
 * 最近返工时间：`2026-10-26T17:00:00+08:00` ⇒ `2026-10-26 17:00`。
 *
 * 🔴 **只切不改**：服务端已按业务时区给值（带偏移），这里再 `new Date()` 转一次就会在
 * 浏览器所在时区上漂（同 `ship-label` 的日期坑）。缺值 / 短到切不出分钟 ⇒ `''`（整项不渲染）。
 */
export function formatReworkAt(value) {
  const raw = text(value)
  return raw.length < 16 ? '' : raw.slice(0, 16).replace('T', ' ')
}

/**
 * 涉及工序：逐道 `工序名 ×数量`（至少一道）。
 *
 * 缺 `qty` ⇒ 只出工序名（**不印 `×NaN` / `×undefined`**）；缺 `operation_name` 的行丢掉
 * （没有名字的一行在屏上是噪声，工人认不出是哪道工序）。
 *
 * @param {Array<{operation_name?:string, qty?:number|string}>} operations
 * @returns {string[]} 已格式化的行（空数组 = 这一项不渲染）
 */
export function buildReworkOperations(operations) {
  return (Array.isArray(operations) ? operations : [])
    .map((op) => ({ name: text(op?.operation_name), qty: formatQty(op?.qty) }))
    .filter((op) => op.name !== '')
    .map((op) => (op.qty === '' ? op.name : `${op.name} ×${op.qty}`))
}

/**
 * 一行（一张加工单）的展示模型：**唯一**决定「哪些项出现」（渲染与测试都读它）。
 *
 * 顺序 = 工人核对返工的顺序：加工单号（标题）→ 订单号 → 返工笔数 → 最近返工 → 原因 → 涉及工序。
 *
 * @param {object} order `GET /api/worker/production/rework-orders` 的 `orders[]`（下划线键）
 * @returns {{key:string, heading:string, cells:Array<{key:string,label:string,text:string}>}}
 *          `heading` 空 ⇒ 不渲染标题行；`cells` 空且 `heading` 空 ⇒ 渲染一行 `—`
 */
export function buildReworkRow(order) {
  const cells = []
  const orderNo = text(order?.order_no)
  if (orderNo !== '') cells.push({ key: 'order_no', label: '订单号', text: orderNo })
  const count = formatReworkCount(order?.rework_count)
  if (count !== '') cells.push({ key: 'rework_count', label: '返工', text: count })
  const at = formatReworkAt(order?.latest_rework_at)
  if (at !== '') cells.push({ key: 'latest_rework_at', label: '最近返工', text: at })
  const reason = text(order?.latest_reason)
  if (reason !== '') cells.push({ key: 'latest_reason', label: '原因', text: reason })
  const operations = buildReworkOperations(order?.operations)
  if (operations.length > 0) {
    cells.push({ key: 'operations', label: '涉及工序', text: operations.join('、') })
  }
  return { key: text(order?.processing_order_id), heading: text(order?.processing_order_no), cells }
}

/** 一张加工单的卡片（`index` 只用来造稳定 id：判据按 id 取，不按文案）。 */
export function renderReworkRow(order, index) {
  const row = buildReworkRow(order)
  const heading = row.heading === ''
    ? ''
    : `<p class="wh5-ready-no" id="wh5-rework-no-${index}">${esc(row.heading)}</p>`
  const lines = row.cells.map((cell) => (
    `<p class="wh5-ready-sub" id="wh5-rework-${cell.key}-${index}">`
    + `${esc(cell.label)}：${esc(cell.text)}</p>`
  )).join('')
  // 整行一个可显示值都没有 ⇒ 如实印一行 `—`（空行会被当成「页面坏了」）
  const body = heading === '' && lines === ''
    ? `<p class="wh5-ready-no" id="wh5-rework-no-${index}">${esc(REWORK_MISSING)}</p>`
    : `${heading}${lines}`
  return `<li class="wh5-ready-row" id="wh5-rework-row-${index}">${body}</li>`
}

/**
 * 「报返工的加工单列表」（`GET /api/worker/production/rework-orders` 的返回体）。
 *
 * 三种状态互斥、各有稳定 id（判据按 id 取，不按文案）：列表 / 空态。
 * 空态只说**事实**（读了、真没有），不催促、不责备（`migao-dev-flow` §31 P4）。
 */
export function renderReworkList(payload) {
  const orders = Array.isArray(payload?.orders) ? payload.orders : []
  const countLine = `<p class="wh5-ready-count" id="wh5-rework-count">共 ${orders.length} 张加工单有返工报工</p>`
  if (orders.length === 0) {
    return `<section class="wh5-ready" id="wh5-rework-orders">
    ${countLine}
    <p class="wh5-ready-empty" id="wh5-rework-empty">${esc(REWORK_EMPTY)}</p>
  </section>`
  }
  return `<section class="wh5-ready" id="wh5-rework-orders">
    ${countLine}
    <ul class="wh5-ready-list">${orders.map(renderReworkRow).join('')}</ul>
  </section>`
}

/**
 * 页头「当前工人」（**服务端**来源；共用 PAD 时屏上必须看得出是「谁」，与发货页同口径）。
 *
 * @param {{workerName?:string, workerNo?:string, worker_name?:string, worker_no?:string}|null} worker
 * @returns {string} 读不到工人 ⇒ `''`（页头整块不出现；列表仍然可用）
 */
export function renderPageHeader(worker) {
  const name = text(worker?.workerName ?? worker?.worker_name)
  if (name === '') return ''
  const no = text(worker?.workerNo ?? worker?.worker_no)
  return `<header class="wh5-header">
    <span class="wh5-worker" id="wh5-current-worker">当前工人：${esc(name)}${no === '' ? '' : `（工号 ${esc(no)}）`}</span>
    <a class="wh5-ghost" id="wh5-rework-back" href="${REWORK_LOGIN_HREF}">返回报工</a>
  </header>`
}

/** 「登录已失效」的显式视图（401；本页没有登录面 ⇒ 给 `/w/` 真链接，不静默重试）。 */
export function renderReworkLoginRequired() {
  return `<section class="wh5-card">
    <h1 class="wh5-title">报返工的加工单</h1>
    <p class="wh5-error" id="wh5-rework-login-required">${esc(REWORK_LOGIN_REQUIRED)}</p>
    <a class="wh5-entry" id="wh5-rework-login" href="${REWORK_LOGIN_HREF}">去登录</a>
  </section>`
}

/**
 * 403 视图：工人档案页面集里没有 `rework` 键（可行动，不当成故障）。
 *
 * 🔴 与 {@link renderReworkUnreadable} **分开**：一个是「找管理员开户」，一个是「网络/服务抖一下，重试」——
 * 两种现场该做的事完全不同，合成一句就是让工人反复点重试。
 */
export function renderReworkForbidden() {
  return `<section class="wh5-card">
    <h1 class="wh5-title">报返工的加工单</h1>
    <p class="wh5-error" id="wh5-rework-forbidden">${esc(REWORK_FORBIDDEN)}</p>
    <a class="wh5-ghost" id="wh5-rework-forbidden-back" href="${REWORK_LOGIN_HREF}">返回报工</a>
  </section>`
}

/**
 * 读面失败的**上屏文案**：只取人话（`err.message`），技术原文（`err.technical`）**永不上屏**。
 *
 * @param {unknown} err `api.mjs` 抛出的错误（`message` 已是人话；`technical` 是 `HTTP 500` / 原始异常串）
 * @returns {string} 非空人话（兜底 {@link REWORK_UNREADABLE}）
 */
export function unreadableReason(err) {
  const message = typeof err?.message === 'string' ? err.message.trim() : ''
  return message === '' ? REWORK_UNREADABLE : message
}

/** 「读不到」的视图（人话 + 重新读取；技术原文不上屏）。 */
export function renderReworkUnreadable(err) {
  return `<section class="wh5-card">
    <h1 class="wh5-title">报返工的加工单</h1>
    <p class="wh5-error" id="wh5-rework-error">${esc(unreadableReason(err))}</p>
    <button type="button" class="wh5-entry" id="wh5-rework-retry">重新读取</button>
  </section>`
}
