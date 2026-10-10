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
// 工序显示名走**唯一**口径（issue #4963）：`src/shared/operation-display.mjs` 的
// `operationDisplayName` —— 本文件此前自拼 `${logical_name} · ${position ?? 部位}`，与
// admin-web 的 `frontend/admin-web/src/lib/operation-display.ts` 在「缺 logical_name」
// 「键值带空白」「全缺」三种输入下渲染不同（各拼一份必然漂移，而漂移的那一份不会变红）。
//
// 🔴 issue #6306：该模块原先住在**仓根** `frontend/shared/`（发布集之外）⇒ 线上这个相对
// 说明符解析成 `/shared/operation-display.mjs` —— 它**没随发布落地**，被 nginx 的 SPA 兜底
// 接成 `200 text/html` ⇒ 浏览器按 HTML 规范拒绝执行 module script ⇒ 工人端整页白屏
// （真浏览器读数 `bodyText=""` / `rootChildren=0`）。修法 = **树内迁移**（模块搬进
// `src/shared/`）：说明符落在发布集 `src/**` 内，发布与 `location /w/` 的 JS MIME 自动覆盖，
// 无需改 nginx、无需放宽发布腿红线。
import { operationDisplayName } from './shared/operation-display.mjs'

/** 初始态：未登录。 */
export function initialState() {
  return {
    mode: 'login',
    worker: null,
    view: null,
    selection: { setId: null, orderItemId: null },
    notice: null,
    error: null,
    // 报工 in-flight（issue #6667 第 4 条，**涉计件正确性**）：置真期间【开工】禁用 + 说「提交中」，
    // 且装配层的 handler 直接 return —— 车间戴手套连点两下不再变成两笔提交。
    reporting: false,
    // 租户口径（issue #6564）：企业编码 —— 初值来自 URL 的 `?tenant_code=`（短链 302 带上），
    // 仍是普通可编辑输入框（打印的码可能没带、也可能看错）
    enterpriseCode: '',
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
//   · `cut_calc` —— 裁高计算（一体机那台屏的页面，`/w/machine.html` 的入口链接）
//   · `shipment` —— 发货页（⚠️ 同上：`/w/` 暂无对应面 ⇒ 不造 UI；准入面
//                   `/api/worker/shipment/**` 已在后端，缺的只是入口）
// ════════════════════════════════════════════════════════════════════════════════

/** 页面键：报工主流程（本页）。 */
export const PAGE_REPORT = 'report'

/** 页面键：裁高计算（一体机那台屏，`/w/machine.html`）。 */
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

/** 裁高计算入口（同源静态页；`/w/` 与 `/w/machine.html` 同一静态根 ⇒ 相对路径、不写死域名）。
 *  文案 = 「裁高计算（一体机）」（2026-10-10 用户裁定：改前的「机台模式」只有内部人懂，issue #6635）。 */
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
 * 「本机菜单未开报工页」的**非阻断**提示（`report` ∉ `pages` 时）。
 *
 * 🔴 **2026-09-29 用户逐字改判（口径以 B 端 H5 为准）**：
 * 「参考现在 B 端 H5 页面的设计，即使关掉了依然能通过菜单进入页面」
 * —— B 端 H5 的页面开关语义 = **菜单 / 入口按开关显隐**，而**不是**「访问被挡」。
 * ⇒ 本页**照旧渲染、照旧可用**（扫水洗唛 / 报工都还能用），只多挂这一句**非阻断**的话。
 *
 * ⚠️ 改前的形态（已撤，**不要改回去**）：`report` ∉ `pages` ⇒ 渲染一个不渲染 `wh5-scan` /
 * `wh5-report` 的「本机未开报工页」视图 —— 那是**硬拦截**，与 B 端 H5 不一致，
 * 且把「菜单没开」变成「活干不了」（工人手上唯一常开的那一页被清空）。
 */
export const reportMenuClosedNotice = '本机菜单未开报工页（按管理员配置显隐）；本机报工仍可用 —— 如非预期，请找管理员在「工人端页面」里开，或换一台设备 / 换一个工人'

/**
 * 页头的**菜单/降级提示条**（两态共用一件，都是**非阻断**语义；都不挡任何入口）。
 *
 * 判据 = `tests/worker-h5-pages.test.mjs` 的 `::② …`（**双向**钉住「不拦截」）：
 * 去掉它 ⇒ 红；把页面挡掉（`wh5-scan` 不渲染）⇒ 也红。
 */
function pageNoticeBanner(state) {
  const { opened, unread } = effectivePages(state)
  if (unread) {
    return `<p class="wh5-perm-notice" id="wh5-perm-unread" role="status">${esc(permUnreadNotice)}</p>`
  }
  if (!opened.has(PAGE_REPORT)) {
    return `<p class="wh5-perm-notice" id="wh5-report-menu-closed" role="status">${esc(reportMenuClosedNotice)}</p>`
  }
  return ''
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
        // 🔴 `view: null` = **重扫**（`app.mjs` 的 `wh5-rescan` 出口）⇒ 回等扫码态。
        //    改前这里恒给 `'main'`：`renderPage` 靠 `!s.view` 兜住了屏面，但 `state.mode` 是**错的**
        //    （`main` 而不是 `scan`）⇒ 任何按 mode 判事的判据/调用方都读到假状态（issue #6667 第 3 条的红证）。
        mode: !view ? 'scan' : (needsSelection ? 'select' : 'main'),
        // 新一屏 = 新的一笔 ⇒ in-flight 闸归零（否则上一屏残留的「提交中」会把这一屏的按钮禁死）
        reporting: false,
      }
    }
    // 报工在飞（issue #6667 第 4 条）：置位在按钮点下的那一刻、清位在下面三处（换了屏 / 有了结论 / 登出）
    case 'reportStart':
      return { ...state, reporting: true, error: null, notice: null }
    case 'reportFailed':
      return { ...state, reporting: false }
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
        reporting: false, // 有了结论 ⇒ 闸放开（否则接着领下一道时按钮是禁的）
      }
    case 'notice':
      return { ...state, notice: action.notice ?? null }
    case 'error':
      return { ...state, error: action.error ?? null, reporting: false }
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
 *
 * 🔴 **in-flight 闸（issue #6667 第 4 条，涉计件正确性）**：提交在飞时按钮 `disabled` + 文案改
 * 「提交中…」—— 车间里戴手套、弱网下答复要等好几秒，**没有反馈就会被反复按**；
 * 与机台页 `machine.mjs::reportBlock` 同一把闸（同一份形态，两页两处）。
 */
function reportButton(state, view) {
  if (!canReport(state, view)) return ''
  return state.reporting
    ? '<button id="wh5-report" class="wh5-primary" type="button" disabled>提交中…</button>'
    : '<button id="wh5-report" class="wh5-primary" type="button">开 工</button>'
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
 * 页头入口栏（2026-10-10 改版，issue #6635）。
 *
 * 🔴 **两条跨应用入口已移出本页**（用户 2026-10-10 逐字：「移除拍照入库和补打入库标签」）：
 * 它们是 bmini-app 的页面，动线由**工人工作台**承载
 * （frontend/bmini-app/src/pages/worker/home/index.tsx；入口台账 `PAGE_ENTRY_LEDGER` 的
 * `from` 就是它）⇒ 从 `/w/` 移出**不会**让那两页变成「走不到」。
 * 本页的反向钉住（页头再出现这两条 ⇒ 红）= frontend/worker-h5/tests/worker-h5-worker-entries.test.mjs。
 *
 * 入口栏**只**留 `cut_calc` 那一条，文案与商家端页面开关同源
 * （frontend/admin-web/src/components/settings/WorkerPageConfigPanel.tsx 的 `cut_calc` = 「裁高计算器」）：
 * 改前的「机台模式」只有内部人懂（用户 2026-10-10 逐字问「机台模式是什么含义」）。
 * `cut_calc` ∉ `pages` ⇒ **整条入口栏不渲染**（不留空 `<nav>`）—— 机台那台屏改用**本机预设**直达
 * （`?page=cut_calc`，见 frontend/worker-h5/src/scan-input.mjs 的 `deviceHomeFromLocation`）。
 *
 * ⚠️ 这是**菜单显隐**语义，不是「访问拦截」（2026-09-29 用户逐字改判，口径以 B 端 H5 为准）：
 * 链接消失 ≠ 页面不可达 —— `/w/machine.html` 直接敲 URL **仍可进入**（静态页，本包不给它加访问门禁）。
 * 同款语义的另一半 = 页头的 `pageNoticeBanner`（`report` 关掉时页面**照旧可用**，只多一句话）。
 */
function workerEntriesBar(state) {
  const { opened } = effectivePages(state)
  if (!opened.has(PAGE_CUT_CALC)) return ''
  return `<nav class="wh5-entries" id="wh5-worker-entries" aria-label="工人面入口">
    <a class="wh5-entry" id="wh5-machine-entry" href="${MACHINE_ENTRY_HREF}">裁高计算（一体机）</a>
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
  </header>${pageNoticeBanner(state)}${workerEntriesBar(state)}`
}

function loginView(state) {
  return `<section class="wh5-card">
    <h1 class="wh5-title">工人领活</h1>
    <p class="wh5-sub">工号 + PIN 登录（手机 / PAD 均可，无需微信）</p>
    ${state.error ? `<p class="wh5-error" id="wh5-error">${esc(state.error)}</p>` : ''}
    <label class="wh5-label">企业编码（向商家索取）<input id="wh5-enterprise-code" class="wh5-input" inputmode="text" autocomplete="organization" value="${esc(state.enterpriseCode ?? '')}" /></label>
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
    <button id="wh5-rescan" class="wh5-ghost" type="button">重扫</button>
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
  // 工序选择器（issue #6635，用户 2026-10-10 裁定 = 选项 A）：扫完码把**本套/本部位的全部待领工序**
  // 列出来（含系统推断的那道，默认选中）——「我这次做的是另一道」是**正常动作**，不是例外。
  // 点别的候选 ⇒ 走既有的**一键改**（`GET /scan?operation_id=…`，归属仍由服务端校验；防呆④ 一字不动）；
  // 点当前那道 ⇒ 不重发请求（装配层的绑定里 no-op，见 frontend/worker-h5/src/app.mjs）。
  //
  // 🔴 改前的形态（已撤，不要改回去）：候选只挂在「不是这道？」这行小字下 —— 而车间工序本来就
  // **不按固定顺序**做（用户 2026-10-10 逐字：「工人无法选取某个工序报工，因为工序不是固定顺序的」）。
  const candidates = [op, ...(v.alternatives ?? [])].filter((c) => c && c.operation_id)
  const picker = candidates.length > 1
    ? `<div class="wh5-pick" id="wh5-op-picker" role="group" aria-label="选工序">
        <span class="wh5-pick-label">选工序（点哪道就领哪道）</span>
        ${candidates.map((c) => {
          const on = c.operation_id === op.operation_id
          return `<button data-operation-id="${esc(c.operation_id)}" class="wh5-op-choice${on ? ' is-on' : ''}" aria-pressed="${on}" type="button">${esc(c.logical_name)}</button>`
        }).join('')}
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
    ${picker}
    ${reportButton(state, v)}
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
 * 闲置登出兜底分钟数 = 与服务端**同源**的全局默认（`WorkerSessionService.DEFAULT_IDLE_MINUTES`，43200 = 30 天）。
 *
 * 🔴 改前的兜底是 `15`（字面）：与服务端「全局默认 = 30 天」（2026-10-07 用户裁定「延长到 1 个月」；
 * 上一版一周）**不符** ⇒ 只在「拿不到 `idle_minutes`」时生效的一条路径上，前端会比服务端早
 * **43185 分钟**把工人踢出（页面上是"无缘无故要我重登"）。正常链路服务端**恒回** `idle_minutes`
 * （登录 / 续期 / `me` 三个响应都带），所以它只影响降级路径 —— 但降级路径的字面值**必须**与服务端同源，
 * 否则就是第二份会漂的默认值。
 */
export const DEFAULT_WORKER_IDLE_MINUTES = 43200

/**
 * 渲染整页（返回 HTML 串；调用方负责 `root.innerHTML = ...`）。
 *
 * @param {object} state 状态机当前态
 * @param {object} [view] 服务端解析结果（省略则用 `state.view`）
 */
export function renderPage(state, view = state.view) {
  const s = { ...state, view: view ?? state.view }
  if (!s.worker) return loginView(s)
  // 🔴 **不硬拦截**（2026-09-29 用户逐字改判，口径以 B 端 H5 为准）：
  // `report` ∉ `pages` **不再**挡页面 —— 页面照旧渲染、照旧可用（扫水洗唛 / 报工都能用），
  // 只在页头挂一条**非阻断**提示（`pageNoticeBanner`，两态共用）。页面开关的语义 =
  // **菜单 / 入口显隐**，不是「访问被挡」；真正的准入仍在服务端 `/api/worker/**`。
  if (!s.view) return scanView(s)
  if (s.mode === 'select' && (s.view.needs_selection ?? []).length > 0) return selectView(s)
  return mainView(s)
}
