// case_ids: PG-018, BM-006, DF-017, BM-025
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
//
// 工序显示名走**唯一**口径（issue #4963）：`frontend/shared/operation-display.mjs` 的
// `operationDisplayName` —— 本文件此前自拼 `${logical_name} · ${position ?? 部位}`，与
// admin-web 的 `frontend/admin-web/src/lib/operation-display.ts` 在「缺 logical_name」
// 「键值带空白」「全缺」三种输入下渲染不同（各拼一份必然漂移，而漂移的那一份不会变红）。
import { operationDisplayName } from '../../shared/operation-display.mjs'

/** 初始态：未登录。 */
export function initialState() {
  return {
    mode: 'login',
    worker: null,
    view: null,
    selection: { setId: null, orderItemId: null },
    notice: null,
    error: null,
    // 工人端页面权限（V141 母单 #5161）：`null` = **还没读到**（fail-open 的初值，见 `effectivePages`）
    pages: null,
    pagesUnread: false,
  }
}

// ════════════════════════════════════════════════════════════════════════════════
// 工人端页面开关（V141，母单 #5161）—— `GET /api/worker/me` 的 `pages` 的**唯一**消费处。
//
// 它回答「本机这个工人能走到哪几页」，**不是**权限（准入仍在服务端 `/api/worker/**`）。
// 与后端 `com.migao.admin.worker.WorkerPages` 的闭词表**逐字同名**（改一边 ⇒ 判据红）：
//   · `report`   —— 报工主流程（本页，`/w/`）
//   · `order`    —— 订单页（⚠️ `/w/` **暂无对应面**：`render.mjs` 里没有订单 UI 入口
//                   ⇒ 本包**不为它造 UI**，只登记「键存在、`/w/` 暂无对应面」；
//                   将来 `/w/` 长出订单面时，在这里按 `effectivePages().has(PAGE_ORDER)` 门控）
//   · `cut_calc` —— 机台模式（`/w/machine.html` 的入口链接）
//   · `shipment` —— 发货页（⚠️ 同上：`/w/` 暂无对应面 ⇒ 不造 UI；准入面
//                   `/api/worker/shipment/**` 已在后端，缺的只是入口）
// ════════════════════════════════════════════════════════════════════════════════

/** 页面键：报工主流程（本页）。 */
export const PAGE_REPORT = 'report'

/** 页面键：机台模式（一体机，`/w/machine.html`）。 */
export const PAGE_CUT_CALC = 'cut_calc'

/** 页面键：订单页 —— **`/w/` 暂无对应面**（登记，不造 UI）。 */
export const PAGE_ORDER = 'order'

/** 页面键：发货页 —— **`/w/` 暂无对应面**（登记，不造 UI）。 */
export const PAGE_SHIPMENT = 'shipment'

/**
 * 默认页面集合 = 后端 `WorkerPages.defaultPages()` 的**逐字镜像**（缺行 ⇒ 默认四页全开）。
 *
 * ⚠️ 这是**第二份**默认值（真值在后端；前端不可能 import Java）⇒ 唯一防线是判据：
 * `tests/worker-h5-pages.test.mjs` 逐值比对四个键 + 顺序，改一边不改另一边 ⇒ 红。
 */
export const DEFAULT_PAGES = [PAGE_REPORT, PAGE_ORDER, PAGE_CUT_CALC, PAGE_SHIPMENT]

/** 机台模式入口（同源静态页；`/w/` 与 `/w/machine.html` 同一静态根 ⇒ 相对路径、不写死域名）。 */
export const MACHINE_ENTRY_HREF = '/w/machine.html'

/**
 * 本机实际可走的页面集合（**唯一判据**）—— 三态各不相同，绝不合并：
 *   ① `pagesUnread` ⇒ **fail-open**：读不到权限 ⇒ 按**全开**运行（把「开关没读到」变成
 *      「活干不了」是更坏的失败），同时由页面**显式**提示这是降级态（见 `permUnreadNotice`）；
 *   ② `pages == null`（还没读过）/ 空数组 ⇒ 同上按默认全开（后端对**成功**的读面恒回非空数组，
 *      故空数组只可能来自旧版服务端 / 异常数据 ⇒ 与"读不到"同口径）；
 *   ③ 非空数组 ⇒ **就是它**（未知键自动被忽略：前端不认识的面不因为多一个字符串就冒出来）。
 *
 * @param {object} state
 * @returns {{opened: Set<string>, unread: boolean}} 生效页面集 + 是否处于「没读到权限」的降级态
 */
export function effectivePages(state) {
  const pages = Array.isArray(state?.pages) ? state.pages.filter((p) => typeof p === 'string') : null
  const unread = state?.pagesUnread === true || pages === null || pages.length === 0
  return { opened: new Set(unread ? DEFAULT_PAGES : pages), unread }
}

/** 读不到页面权限时给工人的**显式**一句话（不许静默降级：工人得知道"这不是本机被关了页"）。 */
export const permUnreadNotice = '未能读取页面权限，本机按全开运行（可继续报工；若与本机应开的页面不符，请找管理员）'

/**
 * 「本机未开报工页」视图（`pages` 不含 `report` 时的**显式**终点）。
 *
 * 🔴 为什么必须显式：静默留着一个扫不动码的页面 = 工人以为"扫码枪坏了 / 码脏了"，
 * 反复重扫、找错人修 —— 而真因是这台设备/这个工人没开报工页。⇒ 说清三件事：
 * ① 本机未开此页（不是码的问题）；② 出口 = 找管理员在「工人端页面」里开；
 * ③ 出口 = 换设备 / 换工人（页面开关是**租户级**的，换人换机可能就开了）。
 *
 * ⚠️ 这里**只**管可见性：真正的准入仍在服务端（`/api/worker/**`）—— 本视图不代替鉴权。
 */
function reportPageClosedView(state) {
  return `${header(state)}
  <section class="wh5-card" id="wh5-report-closed">
    <h1 class="wh5-title">本机未开报工页</h1>
    <p class="wh5-sub">本机（本租户）的「工人端页面」里**没有**开报工页 ⇒ 这个页面上的扫码 / 报工入口已停用，不是码的问题。</p>
    <ul class="wh5-closed-exits">
      <li>找管理员在「设置 · 工人端页面」里把<b>报工</b>打开</li>
      <li>或换一台已开报工页的设备 / 换一个已开报工页的工人（页面开关按租户下发）</li>
    </ul>
    <button id="wh5-logout" class="wh5-ghost" type="button">登出 / 换工人</button>
  </section>`
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
    // 页面权限读到（或**读不到**）：`action.pages` = 数组 ⇒ 用它；null/缺省 ⇒ fail-open 并按全开跑
    // 🔴 换人换权限：登录成功 / 切换工人后必须**重拉**（app.mjs），`logout` 会把这两个键一并清回初值
    case 'pages':
      return {
        ...state,
        pages: Array.isArray(action.pages) ? [...action.pages] : null,
        pagesUnread: action.pagesUnread === true,
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

/**
 * 开工按钮（唯一的记账入口）。
 *
 * 🔴 **2026-09-21 语义改判（issue #4967，用户逐字裁定①）**：扫码 = **开工 / 领活**，
 * 不是「做完扫一次」—— 真实车间是「先扫码领活 → 再生产；完工不扫」（用户逐字：
 * 「工人都是先扫码报工后再真实进行生产，不是先生产再扫码报工」）。
 * 按钮文案随之由【完成】改为【开工】；**id 与动作一字未改**（`wh5-report` + `scan/complete`）
 * —— 端点名是冻结契约，改了会把已发版的客户端打回 404。
 * 记账时点**不变**（仍是点这一下推进进度 + 记计件），所以文案说「领活」而不承诺「完工」。
 */
function reportButton(state, view) {
  return canReport(state, view)
    ? `<button id="wh5-report" class="wh5-primary" type="button">开 工</button>`
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

/** 报工回执 ⇒ 给工人的一句话（`replayed` 必须显式说清「没有新增计件」，不谎报一笔新报工）。 */
export function doneNotice(receipt) {
  if (receipt.replayed) return '这次没有新增计件：重复提交已回放（同一次扫码只算一次）'
  if (receipt.orderCompleted) return '已领活 · 本单工序都领完了 🎉'
  if (receipt.setCompleted === true) return '已领活 · 本套工序都领完了 🎉'
  // 🔴 「下一道」必须**带部位**（issue #4963）：改前只拼 `nextOperation.logical_name`
  // ⇒ 跨部位时屏上少一半信息（`打卷 · 布帘` 显示成 `打卷`）。回执的 `next_operation`
  // 本来就带 `position`（逐字照 `ProductionScanCompleteService.enrichNextOperation`）。
  // 文案语义（「已领活」= 扫码开工/领活，issue #4967 用户逐字裁定）**一字不动**，只补部位。
  const next = operationDisplayName(receipt.nextOperation)
  if (next) return `已领活 · 下一道：${next}`
  return '已领活'
}

/**
 * 工人面两页的入口（issue #5052 实现 PR；设计 §5.4 路线 (a)）。
 *
 * 治的形态：两个功能（拍照入库 / 拍照补打标签）**页面都做完了、都合并了**，而工人
 * **一步也走不到** —— 没有入口的功能按验收口径（交付物可达性三问之②）**不算交付**。
 *
 * 🔴 为什么入口在这里：`/w/` 是工人在车间**手里唯一常开的那一页**（他一天扫几十次
 * 洗水码报工）；把入口挂在他眼前的那一页，才叫动线。（另一条候选「入库另配短码入口」
 * 需要新造服务端短链面 + 再印一张纸，本单边界明令不新造后端端点 ⇒ 选 (a)。）
 *
 * 🔴 跨应用**静态链接**（不是框架路由）：`/w/` 与 `/b/` 同源（同一台 nginx、同一个静态根）
 * ⇒ 用相对路径、**不写死域名**。目标是 bmini-app 的页面路由，Taro h5 默认 hash 路由 ⇒ `/b/#<路由>`。
 * 本文件保持**零依赖**（裁定 13「不重写 worker-h5」）：一行 `<a href>` + 一条 CSS，不引任何包。
 *
 * ⚠️ 登录态**不跨应用**：`/w/` 的工人 session 在 `localStorage['migao:worker-h5:session']`，
 * bmini 侧在 `worker_session_id` —— 两个键、两条链路（各自服务端 `worker_sessions` 行）。
 * 因此工人到 `/b/` 通常**还没有** bmini 侧的工人 session ⇒ 页面显式给「去登录工人身份」
 * （工号 + PIN），登录后回来继续。**刻意不打通**：让一个页面替另一个页面写身份键 =
 * 把两条链路的真值源合成一个，而两侧的闲置登出 / 切换工人语义并不相同。
 *
 * 判据 = `frontend/bmini-app/tests/page-entry-reachability.test.ts`（把这里的路由段与
 * bmini 的路由常量**逐值比对**：改一边不改另一边 ⇒ 红）。
 */
function workerEntriesBar(state) {
  const { opened } = effectivePages(state)
  // 🔴 入口栏按页面集过滤（本单）：机台模式（`cut_calc`）在**集合里才有链接**。
  // 两条跨应用静态入口**不受** `pages` 影响（`/b/#/pages/worker/*` 不属于这四个键
  // ⇒ 没有对应开关就不该由它决定去留：误删会让 #5052 那两页重新变成「走不到」）。
  const machine = opened.has(PAGE_CUT_CALC)
    ? `<a class="wh5-entry" id="wh5-machine-entry" href="${MACHINE_ENTRY_HREF}">机台模式</a>`
    : ''
  return `<nav class="wh5-entries" id="wh5-worker-entries" aria-label="工人面入口">
    <a class="wh5-entry" href="/b/#/pages/worker/inbound/index">拍照入库</a>
    <a class="wh5-entry" href="/b/#/pages/worker/reprint/index">补打入库标签</a>${machine}
  </nav>`
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
  </header>${permUnreadBanner(state)}${workerEntriesBar(state)}`
}

/**
 * 「页面权限没读到」的常驻提示（fail-open 的**可观察面**）。
 *
 * 🔴 为什么必须有这一句：降级跑 ≠ 正常跑 —— 不写出来，商家改过的开关被静默忽略，
 * 而页面上一切正常（最坏的形态：**没人发现开关失效**）。
 */
function permUnreadBanner(state) {
  return effectivePages(state).unread
    ? `<p class="wh5-perm-unread" id="wh5-perm-unread" role="status">${esc(permUnreadNotice)}</p>`
    : ''
}

function loginView(state) {
  return `<section class="wh5-card">
    <h1 class="wh5-title">工人领活</h1>
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
    <h1 class="wh5-title">扫码领活</h1>
    <p class="wh5-sub">扫一次码 = 把这道活领走（先领活再生产，做完不用再扫）；扫不了就输码</p>
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
    <p class="wh5-sub" id="wh5-legacy-hint">选完套 + 部位即可报工 —— 该做哪道工序由系统推断（不用你找）。</p>
  </section>`
}

function mainView(state) {
  const v = state.view
  const op = v.operation
  // 🔴 工序未确定（本套工序都已被领走 / 服务端推断不出待领工序）⇒ **只给结论，不给开工按钮**。
  // 改前这里直接读 `op.unit_price` ⇒ TypeError（页面白屏）；而「回执驱动的一屏」正好会走到这个形态
  // （`set_completed:true` / `next_operation:null`）⇒ 必须显式分支（防呆⑤ 的记账侧那一半）。
  if (!op) {
    return `${header(state)}
  <section class="wh5-card">
    <div class="wh5-set" id="wh5-set">第 ${esc(v.set_no)} 套 · ${esc(v.position?.position_name ?? '')}</div>
    ${v.completed === true
      ? '<p class="wh5-done" id="wh5-completed">本套工序都已被领走 🎉</p>'
      : '<p class="wh5-sub" id="wh5-no-operation">本部位推断不出待领工序（工序未确定 ⇒ 不得记账）</p>'}
    ${overviewView(v)}
    ${cutPlanView(v)}
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
    <div class="wh5-op" id="wh5-operation">${esc(operationDisplayName(op))}</div>
    <div class="wh5-qty" id="wh5-qty">应做 ${fmtQty(op.qty)} ${esc(op.unit ?? '')}</div>
    <div class="wh5-price-row">${price}</div>
    ${v.completed === true ? '<p class="wh5-done" id="wh5-completed">本套工序都已被领走</p>' : ''}
    ${state.notice ? `<p class="wh5-notice" id="wh5-notice">${esc(state.notice)}</p>` : ''}
    ${state.error ? `<p class="wh5-error" id="wh5-error">${esc(state.error)}</p>` : ''}
    ${reportButton(state, v)}
    ${alts}
    ${overviewView(v)}
    ${cutPlanView(v)}
    <button id="wh5-rescan" class="wh5-ghost" type="button">重扫</button>
  </section>`
}

/**
 * 部位级备注（issue #5685）：商家在**订单行**（`processingInfo.remark`）上写的「这个数字怎么来的」，
 * 由服务端随 `set_overview.positions[].remark` 下发 —— 工人扫一次就在**该部位**标题下看见。
 *
 * <p>🔴 <b>缺值不渲染</b>：`null` / 缺键 / 空串 / 纯空白 ⇒ 返回空串 ⇒ 整行**一个字节都不出现**
 * （绝不渲染「部位备注：undefined / null」这种假数据，也不留空行）。</p>
 * <p>文本是商家自由文本 ⇒ 一律 `esc()` 转义；换行/溢出由 `.wh5-ov-remark` 负责（窄屏可读）。</p>
 */
function positionRemark(p) {
  const text = typeof p?.remark === 'string' ? p.remark.trim() : ''
  return text ? `<p class="wh5-ov-remark">部位备注：${esc(text)}</p>` : ''
}

/**
 * 本套工序明细（issue #4967 交付物 2）：**本套 → 部位 → 工序**，工人一眼看到「这一套还有哪几道没做」。
 *
 * <p>数据**只**来自服务端解析响应的 `set_overview`（`ProductionScanService#setOverview`）——
 * 页面**不**自己聚合、也不另拉一份工序列表再按套重排（那就是第二份口径，两处迟早不同）。
 * 与「这次领哪一道」同一次请求 ⇒ 工人扫一次就看全。</p>
 *
 * <p>🔴 <b>缺值不渲染</b>：`set_overview` 缺失 / `positions` 为空 / 某道工序缺 `operation_id`
 * ⇒ 整块（或该行）**不出现**，绝不渲染「undefined 米 / ¥NaN」这种假数据。
 * `unit_price` 为 `null` = <b>未定价</b>（≠ 0 元，V90 / #4696）⇒ 显式写「未定价」。</p>
 */
function overviewView(v) {
  const positions = v?.set_overview?.positions
  if (!Array.isArray(positions) || positions.length === 0) return ''
  const groups = positions
    .map((p) => {
      const ops = (p?.operations ?? []).filter((o) => o?.operation_id)
      if (ops.length === 0) return ''
      const rows = ops
        .map((o) => {
          const price = o.unit_price === null || o.unit_price === undefined
            ? '未定价'
            : `${fmtQty(o.unit_price)} 元/${esc(o.unit ?? '')}`
          // 状态与已报数量让工人区分「还没领 / 已被领走」——两者都要看得见
          const claimed = o.status === 'done'
          return `<li class="wh5-ov-op${claimed ? ' is-done' : ''}">
          <span class="wh5-ov-name">${esc(o.logical_name ?? '')}</span>
          <span class="wh5-ov-qty">应做 ${fmtQty(o.qty)} ${esc(o.unit ?? '')}</span>
          <span class="wh5-ov-price">${price}</span>
          <span class="wh5-ov-status">${claimed ? '已领' : '待领'}</span>
          <span class="wh5-ov-done">已报 ${fmtQty(o.done_qty)} ${esc(o.unit ?? '')}</span>
        </li>`
        })
        .join('')
      return `<div class="wh5-ov-pos">
        <div class="wh5-ov-pos-name">${esc(p.position_name ?? p.position_kind ?? '')}</div>
        ${positionRemark(p)}
        <ul class="wh5-ov-ops">${rows}</ul>
      </div>`
    })
    .join('')
  if (!groups) return ''
  return `<section class="wh5-overview" id="wh5-set-overview">
    <div class="wh5-ov-title">第 ${esc(v.set_no)} 套 · 本套工序</div>
    ${groups}
  </section>`
}

/**
 * 精裁输出清单（issue #5693）—— 给裁床的「**裁多长（米）× 几片**」。
 *
 * <p>数据**只**来自服务端解析响应的 `set_overview.cut_plan`（后端唯一实现
 * `ProcessingSetReadService`），与商家端加工单详情**同一份** —— 页面不算法、不算第二份、
 * 不做单位换算（`meters / panels` 由服务端按 `CuttingPlanCalculator` 的同一份分解给出）。</p>
 *
 * <p>🔴 <b>缺值不渲染假数据</b>：`panel_count` / `panel_length_m` 任一为 `null`
 * （算料没给用料米数或幅数）⇒ 该项显示 `—`，**不**显示 0 / 1；`fabric_meters` 为 `null`
 * 同理。`missing_reason` 只在真缺时渲染一行小字（「缺什么」要看得见）。
 * `cut_plan` 缺失 / 非数组 / 为空 ⇒ 整块**一个字节都不出现**。</p>
 */
function cutPlanView(v) {
  const rows = Array.isArray(v?.set_overview?.cut_plan)
    ? v.set_overview.cut_plan.filter((r) => r && r.order_item_id)
    : []
  if (rows.length === 0) return ''
  const items = rows
    .map((r) => {
      const name = r.position_name ?? r.position_kind ?? ''
      const component = typeof r.component === 'string' && r.component.trim() ? ` · ${esc(r.component)}` : ''
      const size =
        r.panel_length_m === null || r.panel_length_m === undefined || r.panel_count === null || r.panel_count === undefined
          ? '—'
          : `${fmtQty(r.panel_length_m)} 米 × ${esc(String(r.panel_count))} 片`
      const meters =
        r.fabric_meters === null || r.fabric_meters === undefined ? '—' : `${fmtQty(r.fabric_meters)} 米`
      const reason =
        typeof r.missing_reason === 'string' && r.missing_reason.trim()
          ? `<p class="wh5-cut-reason">${esc(r.missing_reason)}</p>`
          : ''
      return `<li class="wh5-cut-row">
        <span class="wh5-cut-size">裁 ${size}</span>
        <span class="wh5-cut-name">${esc(name)}${component}</span>
        <span class="wh5-cut-meters">用料 ${meters}</span>
        ${reason}
      </li>`
    })
    .join('')
  return `<section class="wh5-cutplan" id="wh5-cut-plan">
    <div class="wh5-cut-title">精裁输出（裁多长 × 几片）</div>
    <ul class="wh5-cut-rows">${items}</ul>
  </section>`
}

/**
 * 闲置登出兜底分钟数 = 与服务端**同源**的全局默认（`WorkerSessionService.DEFAULT_IDLE_MINUTES`，10080）。
 *
 * 🔴 改前的兜底是 `15`（字面）：与服务端「全局默认 = 一周」（2026-09-29 用户裁定）**不符**
 * ⇒ 只在「拿不到 `idle_minutes`」时生效的一条路径上，前端会比服务端早 **10065 分钟**把工人踢出
 * （页面上是"无缘无故要我重登"）。正常链路服务端**恒回** `idle_minutes`（登录 / 续期 / `me` 三个响应都带），
 * 所以它只影响降级路径 —— 但降级路径的字面值**必须**与服务端同源，否则就是第二份会漂的默认值。
 */
export const DEFAULT_WORKER_IDLE_MINUTES = 10080

/**
 * 渲染整页（返回 HTML 串；调用方负责 `root.innerHTML = ...`）。
 *
 * @param {object} state 状态机当前态
 * @param {object} [view] 服务端解析结果（省略则用 `state.view`）
 */
export function renderPage(state, view = state.view) {
  const s = { ...state, view: view ?? state.view }
  if (!s.worker) return loginView(s)
  // 🔴 报工页门控（本单）：`report` 不在集合里 ⇒ **显式**给「本机未开报工页」终点，
  // 绝不静默留一个"扫不动码"的页面（旧码选套 / 主屏 / 开工按钮一并不可达 —— 唯一入口在这里）。
  if (!effectivePages(s).opened.has(PAGE_REPORT)) return reportPageClosedView(s)
  if (!s.view) return scanView(s)
  if (s.mode === 'select' && (s.view.needs_selection ?? []).length > 0) return selectView(s)
  return mainView(s)
}
