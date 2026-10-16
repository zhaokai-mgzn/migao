// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5「我的计件」页（issue #6767）—— **纯逻辑**（渲染 + 读数形状校验，无 DOM 依赖）。
//
// 🔴 真值源 = 服务端 `GET /api/worker/piecework`（口径 = docs/design/worker-home-menu.md §6.3）：
//    · 金额聚合**只有一份**（服务端复用商家端计件读面的同一份实现）⇒ 本文件**只格式化**服务端给的
//      `amount_total` / `lines[].amount`，**不做任何求和**（端侧求和 = 第二份口径，见测试的红证）；
//    · 未定价 ≠ 0 元：`unpriced` 原样渲染成「N 道未定价（未计入合计）」，**绝不**印 ¥0.00；
//    · 期间切换的 `prev_period` / `can_prev` / `next_period` / `can_next` 全由服务端给
//      ⇒ 前端不推算月份边界（少一处会漂的真值）；
//    · 本页恒只读：没有任何写动词 / 结算 / 锁定入口。

/** 页面标题（工人话）。 */
export const PIECEWORK_TITLE = '我的计件'

/** 读数形状不对时的显式文案（**不静默当 0** —— 把「没读到」说成「没干活」是涉钱面上更坏的失败）。 */
export const PIECEWORK_UNREADABLE = '没能读到计件数据，请稍后重试或找管理员'

/** 空月文案（服务端回了读数、这一月确实没有计件 ⇒ 如实说，不印 ¥0.00 充当读数）。 */
export const PIECEWORK_EMPTY = '本月暂无计件'

/** 未定价那一条的显式说明（**绝不** ¥0.00）：几道 / 多少件 / 未计入合计。 */
export function unpricedNotice(count, qty) {
  return `${count} 道未定价（共 ${qty} 件，未计入合计）`
}

/** 与测试共用的同一份文案生成（避免判据里再抄一遍会漂的字符串）。 */
export const UNPRICED_NOTICE = unpricedNotice

/** 金额渲染（两位小数 + 千分位）；`null` / 非数 ⇒ `—`（**绝不**回落成 ¥0.00）。 */
export function formatYuan(value) {
  if (value === null || value === undefined || value === '' || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  const sign = n < 0 ? '-' : ''
  const [int, frac] = Math.abs(n).toFixed(2).split('.')
  return `${sign}¥${int.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${frac}`
}

/** 数量渲染（服务端给什么算什么；缺值 ⇒ `—`）。 */
export function formatQty(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  return Number.isInteger(n) ? String(n) : String(n)
}

/**
 * 读数形状校验 + 归一（**唯一**读取点）。
 *
 * 🔴 形状不对 ⇒ **抛错**（装配层显式上屏），不补默认值：涉钱面上「静默当 0」会让工人以为自己白干了。
 *
 * @param {object} data 服务端 `data`
 * @returns {{period:string, amountTotal:number, qtyTotal:number, lines:Array, unpriced:object, prev:object, next:object}}
 */
export function pieceworkView(data) {
  if (!data || typeof data !== 'object') {
    throw new Error(PIECEWORK_UNREADABLE)
  }
  if (data.amount_total === undefined || data.amount_total === null) {
    throw new Error(PIECEWORK_UNREADABLE)
  }
  const unpriced = data.unpriced && typeof data.unpriced === 'object' ? data.unpriced : { qty: 0, operations: [] }
  return {
    // 显示用的工人名来自服务端（只做回显；**不是**身份依据 —— 身份在 `X-Worker-Session-Id` 上）
    workerName: typeof data.worker_name === 'string' ? data.worker_name : '',
    period: typeof data.period === 'string' ? data.period : '',
    amountTotal: Number(data.amount_total),
    qtyTotal: Number(data.qty_total ?? 0),
    lines: Array.isArray(data.lines) ? data.lines : [],
    unpriced: {
      qty: Number(unpriced.qty ?? 0),
      operations: Array.isArray(unpriced.operations) ? unpriced.operations : [],
    },
    // 期间切换完全按服务端给的值（本页不写月份算术）
    prev: { can: data.can_prev === true, month: typeof data.prev_period === 'string' ? data.prev_period : '' },
    next: { can: data.can_next === true, month: typeof data.next_period === 'string' ? data.next_period : '' },
    empty: Number(data.amount_total) === 0 && (Array.isArray(data.lines) ? data.lines.length : 0) === 0,
  }
}

/** HTML 转义（与 render.mjs 同口径；本页独立成面，不反向依赖装配层）。 */
function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** 逐笔工序显示名：逻辑名 · 部位（服务端读时派生）；缺逻辑名 ⇒ 用快照名原文。 */
function operationLabel(line) {
  const logical = line?.logical_name || line?.operation || ''
  const position = line?.position
  return position ? `${logical} · ${position}` : String(logical)
}

/**
 * 渲染「我的计件」页（纯函数：入参 = 服务端读数，出参 = HTML 串）。
 *
 * @param {object} data 服务端 `data`（形状见 {@link pieceworkView}）
 */
export function renderPiecework(data) {
  const view = pieceworkView(data)
  const prev = view.prev.can
    ? `<button class="wh5-ghost" id="wh5-piecework-prev" type="button" data-month="${esc(view.prev.month)}">上月</button>`
    : ''
  const next = view.next.can
    ? `<button class="wh5-ghost" id="wh5-piecework-next" type="button" data-month="${esc(view.next.month)}">下月</button>`
    : ''

  const linesHtml = view.lines.length
    ? view.lines
        .map(
          (line) => `<li class="wh5-piecework-line">
        <span class="wh5-piecework-line-name">${esc(operationLabel(line))}</span>
        <span class="wh5-piecework-line-qty">${esc(formatQty(line?.qty))} 件</span>
        <span class="wh5-piecework-line-amount">${esc(formatYuan(line?.amount))}</span>
      </li>`,
        )
        .join('')
    : ''

  // 🔴 未定价：显式可见（几道 / 多少件 / **未计入合计**）+ 逐条工序名；**绝不** ¥0.00
  const unpricedHtml = view.unpriced.qty > 0
    ? `<section class="wh5-piecework-unpriced" id="wh5-piecework-unpriced">
      <p class="wh5-piecework-unpriced-title">${esc(unpricedNotice(view.unpriced.operations.length, view.unpriced.qty))}</p>
      <p class="wh5-piecework-unpriced-detail">这几道活还没定价，所以没有算进上面的合计（未计入合计）—— 请联系管理员定价。</p>
      <ul class="wh5-piecework-unpriced-list">
        ${view.unpriced.operations
          .map((op) => `<li>${esc(op?.logical_name || op?.operation || '未命名工序')} · ${esc(formatQty(op?.qty))} 件</li>`)
          .join('')}
      </ul>
    </section>`
    : ''

  const body = view.empty
    ? `<p class="wh5-piecework-empty" id="wh5-piecework-empty">${esc(PIECEWORK_EMPTY)}</p>`
    : `<dl class="wh5-piecework-summary">
      <dt>合计</dt><dd id="wh5-piecework-total">${esc(formatYuan(view.amountTotal))}</dd>
      <dt>件数</dt><dd id="wh5-piecework-qty">${esc(formatQty(view.qtyTotal))}</dd>
    </dl>
    <ul class="wh5-piecework-lines" id="wh5-piecework-lines">${linesHtml}</ul>
    ${unpricedHtml}`

  return `<section class="wh5-card">
    <h1 class="wh5-title" id="wh5-piecework-title">${esc(PIECEWORK_TITLE)}</h1>
    <p class="wh5-sub" id="wh5-piecework-period">${esc(view.period)}${view.workerName ? ` · ${esc(view.workerName)}` : ''}</p>
    ${body}
    <nav class="wh5-piecework-nav" id="wh5-piecework-nav" aria-label="切换月份">${prev}${next}</nav>
  </section>`
}
