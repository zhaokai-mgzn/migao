// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5 报工页 —— 状态机 + 一屏渲染（设计 #4716 §4.2 两断点 / §5.1 一屏 / §1.5 旧码降级）。
//
// 为什么把状态机与渲染分开：**报工按钮的出现条件**是本单最危险的一处
// （错了就把进度/钱记到错的套/错的人头上）。判据放在纯函数里 ⇒ 可被 `node --test` 直接钉住，
// 不需要 DOM、不需要浏览器（最少代码阶梯：原生特性优先，不引 jsdom/happy-dom）。
//
// 🔴 四条硬约束（每条都有对应断言）：
//   ① 旧码（`granularity:"order"`）⇒ **进 select 态，绝不默认取第 1 套**；
//   ② 工序未确定（`operation == null`）⇒ **不得出现报工按钮**（防呆⑤）；
//   ③ 未登录（`worker == null`）⇒ **不得出现报工按钮**（未登录不能报工）；
//   ④ 报工回执（`scan/complete`）⇒ 屏上只认回执给的「下一道 / 本套已完成」（#4792），
//      前端**不**自己猜下一道工序（猜错 = 把下一笔计件记到错的工序上）。

/** 初始态：未登录。 */
export function initialState() {
  return { mode: 'login', worker: null, view: null, selection: { setId: null, orderItemId: null }, notice: null, error: null }
}

/**
 * 状态转移（纯函数）。
 *
 * @param {object} state
 * @param {object} action
 */
export function reduce(state, action) {
  switch (action.type) {
    case 'worker': {
      const worker = action.worker ?? null
      return { ...state, worker, mode: worker ? (state.view ? state.mode : 'scan') : 'login' }
    }
    case 'logout':
      return { ...initialState() }
    case 'resolved': {
      const view = action.view
      // 🔴 旧码降级 ⇒ 强制选套/选部位（needs_selection 非空）
      const needsSelection = Array.isArray(view?.needs_selection) && view.needs_selection.length > 0
      return {
        ...state,
        view,
        selection: { setId: null, orderItemId: null },
        notice: needsSelection ? '这是一张旧码：请先选择套号与部位' : (action.notice ?? null),
        error: null,
        mode: needsSelection ? 'select' : 'main',
      }
    }
    case 'pickSet':
      return { ...state, selection: { setId: action.setId, orderItemId: null }, notice: `已选第 ${action.setNo} 套，请再选部位` }
    case 'pickPosition': {
      const set = findSet(state.view, state.selection.setId)
      const pos = findPosition(set, action.orderItemId)
      return {
        ...state,
        selection: { ...state.selection, orderItemId: action.orderItemId },
        notice: `已选：第 ${set?.set_no ?? '?'} 套 · ${pos?.position_name ?? ''}`,
      }
    }
    case 'completed':
      // 报工成功 ⇒ 屏上换成**回执**给的「下一道 / 本套已完成」（`__requestId` 已在 afterComplete 丢掉）
      return {
        ...state,
        view: action.view,
        selection: { setId: null, orderItemId: null },
        notice: action.notice ?? null,
        error: null,
        mode: 'main',
      }
    case 'notice':
      return { ...state, notice: action.notice ?? null }
    case 'error':
      return { ...state, error: action.error ?? null }
    default:
      return state
  }
}

function findSet(view, setId) {
  return (view?.selections ?? []).find((s) => s.set_id === setId) ?? null
}

function findPosition(set, orderItemId) {
  return (set?.positions ?? []).find((p) => p.order_item_id === orderItemId) ?? null
}

const esc = (v) =>
  String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

const fmtQty = (n) => (typeof n === 'number' ? n.toFixed(2) : String(n ?? ''))

/**
 * 报工按钮可否出现（**唯一判据**）。
 *
 * @param {object} state
 * @param {object} view
 * @returns {boolean}
 */
export function canReport(state, view) {
  if (!state.worker) return false                                   // ③ 未登录不能报工
  if (!view || view.completed === true) return false
  if (Array.isArray(view.needs_selection) && view.needs_selection.length > 0) return false // ① 旧码未选定
  if (!view.operation?.operation_id) return false                    // ② 工序未确定不得记账
  return true
}

/** 报工按钮（唯一的记账入口）。 */
function reportButton(state, view) {
  return canReport(state, view)
    ? `<button id="wh5-report" class="wh5-primary" type="button">完 成</button>`
    : ''
}

/**
 * 报工回执 ⇒ 下一屏（A 模式闭环的「接着做」那一半，设计 §4.1 ⑥）。
 *
 * 🔴 三条纪律：
 *   ① 屏上的工序**只**来自回执（`next_operation`）—— 前端不猜下一道；
 *   ② `__requestId` 必须**丢掉**：下一道是新的一笔 ⇒ 必须换新幂等键
 *      （复用旧键会被服务端回放成「已报过」⇒ 静默漏计件）；
 *   ③ `__token` 必须**保留**：同一个码接着做下一道，不必重扫（用户核心诉求「只扫一次」）。
 *
 * `set_completed` 为 `null`（服务端「下一道」推断失败，见 `enrichNextOperation` 的尽力而为）
 * ⇒ **不**敢说完工（不知道就说不知道），只把工序置空 ⇒ 报工按钮自然消失。
 */
export function afterComplete(view, receipt) {
  const { __requestId, ...rest } = view ?? {}
  return {
    ...rest,
    set_no: receipt.setNo ?? view?.set_no ?? null,
    position: receipt.position ?? view?.position ?? null,
    set_progress: receipt.setProgress ?? view?.set_progress ?? null,
    operation: receipt.nextOperation ?? null,
    alternatives: [],
    needs_selection: [],
    completed: receipt.setCompleted === true,
  }
}

/**
 * 旧码收口（issue #4794）：报工要回传的「套 + 部位」。
 *
 * 🔴 两条判据都在这里（纯函数 ⇒ 可被 `node --test` 钉住）：
 *   ① **只有旧码**（`granularity === "order"`）才有这两个键 —— 新码主路径恒 `null`
 *      ⇒ 报工 body **只带 token**（#4792 的防呆⑤ 断言一条不放宽）；
 *   ② **两个都选了**才回传（半截选择不带：服务端仍要求完整选择 ⇒ 否则它会回落到降级形态）。
 *
 * 它**不**决定工序：工序仍由服务端推断（防呆⑤）；跨部位的 `operation_id` 仍由服务端 422（防呆④）。
 */
export function legacySelection(view, selection) {
  if (view?.granularity !== 'order') return null
  if (!selection?.setId || !selection?.orderItemId) return null
  return { setId: selection.setId, orderItemId: selection.orderItemId }
}

/** 报工回执 ⇒ 给工人的一句话（`replayed` 必须显式说清「没有新增计件」，不谎报一笔新报工）。 */export function doneNotice(receipt) {
  if (receipt.replayed) return '这次没有新增计件：重复提交已回放（同一次扫码只算一次）'
  if (receipt.orderCompleted) return '已报工 · 本单已完工 🎉'
  if (receipt.setCompleted === true) return '已报工 · 本套已完工 🎉'
  if (receipt.nextOperation?.logical_name) return `已报工 · 下一道：${receipt.nextOperation.logical_name}`
  return '已报工'
}

/** 页头：**服务端**带来的「当前工人」+ 一步切换 + 登出（共用 PAD 三条，设计 §3.1~§3.3）。 */
function header(state) {
  if (!state.worker) return ''
  const name = esc(state.worker.workerName ?? state.worker.worker_name ?? '')
  const no = esc(state.worker.workerNo ?? state.worker.worker_no ?? '')
  return `<header class="wh5-header">
    <span class="wh5-worker" id="wh5-current-worker">当前工人：${name}${no ? `（工号 ${no}）` : ''}</span>
    <button id="wh5-switch" class="wh5-ghost" type="button">切换</button>
    <button id="wh5-logout" class="wh5-ghost" type="button">登出</button>
  </header>`
}

function loginView(state) {
  return `<section class="wh5-card">
    <h1 class="wh5-title">工人报工</h1>
    <p class="wh5-sub">工号 + PIN 登录（手机 / PAD 均可，无需微信）</p>
    ${state.error ? `<p class="wh5-error" id="wh5-error">${esc(state.error)}</p>` : ''}
    <label class="wh5-label">工号<input id="wh5-worker-no" class="wh5-input" inputmode="text" autocomplete="username" /></label>
    <label class="wh5-label">PIN<input id="wh5-pin" class="wh5-input" type="password" inputmode="numeric" autocomplete="current-password" /></label>
    <button id="wh5-login" class="wh5-primary" type="button">登 录</button>
  </section>`
}

function scanView(state) {
  return `${header(state)}
  <section class="wh5-card">
    ${state.notice ? `<p class="wh5-notice" id="wh5-notice">${esc(state.notice)}</p>` : ''}
    ${state.error ? `<p class="wh5-error" id="wh5-error">${esc(state.error)}</p>` : ''}
    <h1 class="wh5-title">扫码报工</h1>
    <p class="wh5-sub">用任意扫一扫工具扫码即可；扫不了就输码</p>
    <label class="wh5-label">输码（短码 / 加工单号 / 订单号）
      <input id="wh5-code" class="wh5-input" inputmode="text" autocapitalize="characters" /></label>
    <button id="wh5-scan" class="wh5-primary" type="button">确 定</button>
  </section>`
}

function selectView(state) {
  const sets = state.view?.selections ?? []
  const set = findSet(state.view, state.selection.setId)
  const setsHtml = sets
    .map((s) => `<button class="wh5-choice${state.selection.setId === s.set_id ? ' is-on' : ''}"
        data-set-id="${esc(s.set_id)}" data-set-no="${esc(s.set_no)}" type="button">第 ${esc(s.set_no)} 套</button>`)
    .join('')
  const posHtml = set
    ? (set.positions ?? [])
        .map((p) => `<button class="wh5-choice${state.selection.orderItemId === p.order_item_id ? ' is-on' : ''}"
            data-order-item-id="${esc(p.order_item_id)}" type="button">${esc(p.position_name)}</button>`)
        .join('')
    : ''
  return `${header(state)}
  <section class="wh5-card">
    <h1 class="wh5-title">旧码：请选择套号与部位</h1>
    ${state.notice ? `<p class="wh5-notice" id="wh5-notice">${esc(state.notice)}</p>` : ''}
    <p class="wh5-sub">这张码只到加工单级（旧码），系统判不出是哪一套、哪个部位 —— 请手工选一次。</p>
    <div class="wh5-group"><span class="wh5-group-label">选套</span>${setsHtml}</div>
    ${set ? `<div class="wh5-group"><span class="wh5-group-label">选部位</span>${posHtml}</div>` : ''}
    <p class="wh5-sub" id="wh5-legacy-pending">本单：${esc(state.view?.processing_order_no ?? '')}</p>
    <p class="wh5-sub" id="wh5-legacy-hint">选完套 + 部位即可报工 —— 该做哪道工序由**系统**推断（不用你找）。</p>
  </section>`
}

function mainView(state) {
  const v = state.view
  const op = v.operation
  // 🔴 工序未确定（本套已完工 / 服务端推断不出待做工序）⇒ **只给结论，不给报工按钮**。
  // 改前这里直接读 `op.unit_price` ⇒ TypeError（页面白屏）；而「回执驱动的一屏」正好会走到这个形态
  // （`set_completed:true` / `next_operation:null`）⇒ 必须显式分支（防呆⑤ 的记账侧那一半）。
  if (!op) {
    return `${header(state)}
  <section class="wh5-card">
    <div class="wh5-set" id="wh5-set">第 ${esc(v.set_no)} 套 · ${esc(v.position?.position_name ?? '')}</div>
    ${v.completed === true
      ? '<p class="wh5-done" id="wh5-completed">本套已完成 🎉</p>'
      : '<p class="wh5-sub" id="wh5-no-operation">本部位推断不出待做工序（工序未确定 ⇒ 不得记账）</p>'}
    ${state.notice ? `<p class="wh5-notice" id="wh5-notice">${esc(state.notice)}</p>` : ''}
    ${state.error ? `<p class="wh5-error" id="wh5-error">${esc(state.error)}</p>` : ''}
    <button id="wh5-rescan" class="wh5-ghost" type="button">重扫</button>
  </section>`
  }
  const price = op.unit_price === null || op.unit_price === undefined
    ? '<span class="wh5-unpriced">未定价</span>'
    : `<span class="wh5-price">${fmtQty(op.unit_price)} 元/${esc(op.unit ?? '')}</span>`
  const alts = (v.alternatives ?? []).length
    ? `<div class="wh5-alts">不是这道？
        ${(v.alternatives ?? []).map((a) => `<button class="wh5-alt" data-operation-id="${esc(a.operation_id)}" type="button">${esc(a.logical_name)}</button>`).join('')}
      </div>`
    : ''
  return `${header(state)}
  <section class="wh5-card">
    <div class="wh5-set" id="wh5-set">第 ${esc(v.set_no)} 套 · ${esc(v.position?.position_name ?? '')}</div>
    <div class="wh5-op" id="wh5-operation">${esc(op.logical_name)} · ${esc(op.position ?? v.position?.position_name ?? '')}</div>
    <div class="wh5-qty" id="wh5-qty">应做 ${fmtQty(op.qty)} ${esc(op.unit ?? '')}</div>
    <div class="wh5-price-row">${price}</div>
    ${v.completed === true ? '<p class="wh5-done" id="wh5-completed">本套已完成</p>' : ''}
    ${state.notice ? `<p class="wh5-notice" id="wh5-notice">${esc(state.notice)}</p>` : ''}
    ${state.error ? `<p class="wh5-error" id="wh5-error">${esc(state.error)}</p>` : ''}
    ${reportButton(state, v)}
    ${alts}
    <button id="wh5-rescan" class="wh5-ghost" type="button">重扫</button>
  </section>`
}

/**
 * 渲染整页（返回 HTML 串；调用方负责 `root.innerHTML = ...`）。
 *
 * @param {object} state 状态机当前态
 * @param {object} [view] 服务端解析结果（省略则用 `state.view`）
 */
export function renderPage(state, view = state.view) {
  const s = { ...state, view: view ?? state.view }
  if (!s.worker) return loginView(s)
  if (!s.view) return scanView(s)
  if (s.mode === 'select' && (s.view.needs_selection ?? []).length > 0) return selectView(s)
  return mainView(s)
}
