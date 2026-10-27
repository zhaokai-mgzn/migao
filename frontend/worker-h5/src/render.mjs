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
// 本部位生产信息（母单 #6901）的标签 / 单位 / 格式化走**唯一一份**（`position-spec.mjs`）——
// 与机台屏（`machine.mjs`）共用；本文件**不**再写第二份标签表（那正是本单要治的形态）。
import { specRows } from './position-spec.mjs'

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
    // 质检（issue #7162）：最新判定 / 读取中 / 读失败；qualityForm = 展开中的录入表单
    quality: null,
    qualityForm: null,
    // 裁剪报工确认批次（issue #7647）：`null` = 工人还没动过输入框（⇒ 用服务端预填的派工批次）；
    // 字符串 = 工人当前输入的原样值。只对 `batch_required` 为真的屏有意义（其余屏一个字节都不看）。
    batchNo: null,
    // 成品入库块（issue #7845）：服务端给的 `finished_inbound`（入库单号 / 仓位 / 标签 / 质检结论）；
    // `null` = 这张码还没入库 / 不是打包工序 ⇒ 整块卡片不渲染（不摆空壳）。
    finishedInbound: null,
    // 报返工（issue #7860）：`rework` = 最近一次的返工回执（返工单号 / 工序）；`reworkForm` = 展开中的表单。
    // 与质检（`quality`）**两套**：返工改的是报工三态（计件归零），质检落的是成品帘判定。
    rework: null,
    reworkForm: null,
  }
}

// ════════════════════════════════════════════════════════════════════════════════
// 工人端页面开关（V141，母单 #5161）—— `GET /api/worker/me` 的 `pages` 的**唯一**消费处。
//
// 它回答「本机这个工人能走到哪几页」。**默认不是权限**（准入仍在服务端 `/api/worker/**`）——
// 🔴 唯一例外：`inspect`（质检）同时是服务端写准入（`/api/worker/quality/**` 会校验它，issue #7162）。
// 与后端 `com.migao.admin.worker.WorkerPages` 的闭词表**逐字同名**（改一边 ⇒ 判据红）：
//   · `report`    —— 报工主流程（本页，`/w/`）
//   · `piecework` —— 我的计件（**含金额**；`/w/piecework.html`，issue #6767）
//   · `order`     —— 订单页（⚠️ `/w/` **暂无对应面**：`render.mjs` 里没有订单 UI 入口
//                    ⇒ 本包**不为它造 UI**，只登记「键存在、`/w/` 暂无对应面」；
//                    将来 `/w/` 长出订单面时，在这里按 `effectivePages().has(PAGE_ORDER)` 门控）
//   · `cut_calc`  —— 裁高计算（一体机那台屏的页面，`/w/machine.html` 的入口链接）
//   · `shipment`  —— 发货页（⚠️ 同上：`/w/` 暂无对应面 ⇒ 不造 UI；准入面
//                    `/api/worker/shipment/**` 已在后端，缺的只是入口）
//   · `inspect`   —— 质检（issue #7162）：扫水洗唛后在本页出现质检区块，可录判定、生成质检单。
//                    🔴 与其它页**语义不同**：它同时是服务端**写准入**（`/api/worker/quality/**`
//                    会校验工人档案的页面集里有它），且**不在** `DEFAULT_PAGES` 里（逐人开）。
// ════════════════════════════════════════════════════════════════════════════════

/** 页面键：报工主流程（本页）。 */
export const PAGE_REPORT = 'report'

/** 页面键：我的计件（`/w/piecework.html`；含金额，issue #6767）。 */
export const PAGE_PIECEWORK = 'piecework'

/** 页面键：裁高计算（一体机那台屏，`/w/machine.html`）。 */
export const PAGE_CUT_CALC = 'cut_calc'

/** 页面键：订单页 —— **`/w/` 暂无对应面**（登记，不造 UI）。 */
export const PAGE_ORDER = 'order'

/**
 * 页面键：**待发货单**（`/w/shipment.html`，issue #7761 / #7814）。
 *
 * <p>与 {@link PAGE_SHIPMENT}（发货 = 拍照发货，写面）是**两个能力**：本键管「车间今天能发哪些单、
 * 贴哪张标签」（读面）。商家后台「设置工人端菜单」按这个键勾选（issue #7814）。</p>
 *
 * <p>2026-10-25 之前这里写着「`/w/` 暂无对应面（登记，不造 UI）」—— 那个缺口已经补上：
 * 后端 `/api/worker/shipment/**` 早在 #5648 就齐了，缺的一直只是入口与页面。</p>
 */
export const PAGE_SHIPMENT = 'shipment'

/** 页面键：待发货单（名单 + 发货标签；与 {@link PAGE_SHIPMENT} 写面分开，issue #7814）。 */
export const PAGE_TO_SHIP = 'to_ship'

/**
 * 页面键：质检（issue #7162）—— 扫水洗唛后录判定、生成质检单。
 *
 * 🔴 **不在** `DEFAULT_PAGES` 里（逐人开）；且后端把它当 `/api/worker/quality/**` 的写准入。
 */
export const PAGE_INSPECT = 'inspect'

/**
 * 页面键：**返工记录**（issue #7860）—— `/w/rework.html`：有返工报工的加工单列表。
 *
 * 🔴 与 `inspect` 的差别：它只是**读面可见性**（用户 2026-10-26 裁定「在工人档案中设置过可见权限的
 * 工人」）；**报返工的写准入 = 有效工人 session**（任一工序工人都能报，不看这个键）。
 * 后端同名键 = `WorkerPages.REWORK`（`ALL` 含它、`defaultPages()` 不含）。
 */
export const PAGE_REWORK = 'rework'

/**
 * 默认页面集合 = 后端 `WorkerPages.defaultPages()` 的**逐字镜像**（缺行 ⇒ 默认全开）。
 *
 * ⚠️ 这是**第二份**默认值（真值在后端；前端不可能 import Java）⇒ 唯一防线是判据：
 * `tests/worker-h5-pages.test.mjs` 逐值比对**全部**键 + 顺序，改一边不改另一边 ⇒ 红。
 */
export const DEFAULT_PAGES = [PAGE_REPORT, PAGE_PIECEWORK, PAGE_ORDER, PAGE_CUT_CALC, PAGE_SHIPMENT, PAGE_TO_SHIP]

/** 裁高计算入口（同源静态页；`/w/` 与 `/w/machine.html` 同一静态根 ⇒ 相对路径、不写死域名）。
 *  文案 = 「裁高计算（一体机）」（2026-10-10 用户裁定：改前的「机台模式」只有内部人懂，issue #6635）。 */
export const MACHINE_ENTRY_HREF = './machine.html'

// 🔴 这里原本还有两条入口常量（`./piecework.html` / `./shipment.html`）——**已删**（issue #7934，
// 2026-10-27 用户逐字「我的计件和发货…为什么做到报工详情页面？应该都作为工人菜单页面上的菜单，
// 工人页面有拍照发货了，可以把报工详情页面的发货功能移除掉」）。两条入口改由**工人菜单页**承载：
// 「我的计件」= bmini `pages/worker/piecework/index`；「发货」= bmini `pages/worker/shipment/index`
// （工人菜单页本来就有「拍照发货」行卡 ⇒ 本页那条是重复入口）。
// 两张静态页本身**保留可直连**（`/b/report/piecework.html` / `shipment.html`，菜单显隐 ≠ 访问拦截）。

/** 返工记录入口（同源静态页；issue #7860 —— 有返工报工的加工单列表）。 */
export const REWORK_ENTRY_HREF = './rework.html'

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
      // 🔴 **成功迁移必须清错误位**（issue #6749）：登录成功（worker 非空）⇒ 屏上那句
      //    「上一次失败」的结论必须消失，否则工人第二次输对了 PIN、页头都换成「当前工人」了，
      //    红字还留着 ⇒ 「明明登进去了却还说我不对」。
      //    同族口径：`resolved` / `reportStart` / `completed` 都写 `error: null`、`logout` 回初值
      //    —— 改前这一处是**漏网的一处**（不是有意口径）。
      //    ⚠️ 只清**成功**那一路（`worker` 非空）；`worker = null`（回落未登录）留着错误位，
      //    好让"为什么被踢回来"的原因仍然可见。
      return {
        ...state,
        worker,
        mode: worker ? (state.view ? state.mode : 'scan') : 'login',
        ...(worker ? { error: null } : {}),
      }
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
        // 🔴 `view: null` ⇒ 回等扫码态（issue #7845 起 UI 不再有「重扫」按钮；这条分支留给
        //    「还没解析出任何一屏」与装配层/测试的显式复位）。
        //    改前这里恒给 `'main'`：`renderPage` 靠 `!s.view` 兜住了屏面，但 `state.mode` 是**错的**
        //    （`main` 而不是 `scan`）⇒ 任何按 mode 判事的判据/调用方都读到假状态（issue #6667 第 3 条的红证）。
        mode: !view ? 'scan' : (needsSelection ? 'select' : 'main'),
        // 新一屏 = 新的一笔 ⇒ in-flight 闸归零（否则上一屏残留的「提交中」会把这一屏的按钮禁死）
        reporting: false,
        // 新一屏 = 新的一张码 ⇒ 工人上一屏手输的批次**不带走**（预填值重新来自服务端）
        batchNo: null,
        // 🔴 换成**这一张码**的成品入库块（issue #7845）：服务端随扫码视图下发已入库的那一件；
        //    没入库 ⇒ null（**不沿用**上一件——那会把 A 的仓位/入库单画到 B 的码上）。
        finishedInbound: action.finishedInbound ?? view?.finished_inbound ?? null,
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
        // 这一笔的批次已记账 ⇒ 下一笔的输入框回到「没动过」（预填只来自服务端，绝不带上一笔的值）
        batchNo: null,
        // 打包工序的成品入库块（issue #7845）：回执带 `finished_inbound` ⇒ 换成它；
        // 没带（非打包 / 入库失败 / 已在库未回传）⇒ 保留屏上既有的那一块（同一张码，不清空）。
        finishedInbound: action.finishedInbound ?? state.finishedInbound ?? null,
      }
    // 报工三态选择（issue #5652 第二刀）：**只记在 view 上**（不进 `state.selection` ——
    // 那个键是**旧码的套 / 部位**选择，语义不同，混用会让"半截选择"判据失真）。
    // 放 view 上的好处：`resolved` / `completed` 天然把它换掉 / 丢掉 ⇒ 不必额外写"复位"分支，
    // 「不把报废悄悄留给下一笔」是状态机自己保证的，不靠人记得清。
    case 'workType':
      return { ...state, view: { ...(state.view ?? {}), work_type: normalizeWorkType(action.workType) } }
    // 裁剪批次输入（issue #7647）：**纯状态**动作（不发请求）+ 由装配层**就地**同步按钮禁用态 ——
    // 刻意**不**走整页重渲染：那会重建输入框 ⇒ 焦点丢失、光标跳走（现场表现为「批次打不进字」）。
    // `null` = 回到「没动过输入框」（预填重新取服务端的派工批次）。
    case 'batch':
      return { ...state, batchNo: action.batchNo === null ? null : String(action.batchNo ?? '') }
    // ── 质检（issue #7162）：读最新判定 / 录判定（生成质检单） ──
    // 🔴 「未检 ≠ 合格」：无记录 ⇒ latest=null，界面写「未检」，不折成「合格」。
    case 'qualityLoading':
      return { ...state, quality: { loading: true, latest: state.quality?.latest ?? null, error: null } }
    case 'qualityLoaded':
      return { ...state, quality: { loading: false, latest: action.latest ?? null, error: null } }
    case 'qualityFailed':
      return { ...state, quality: { loading: false, latest: null, error: action.error ?? '质检状态读不到' } }
    case 'qualityFormOpen':
      // 唯一可录的判定 = 返工（issue #7749；合格是默认态，屏上不给这个按钮）
      return { ...state, qualityForm: { result: 'rework', submitting: false, error: null } }
    case 'qualityFormClose':
      return { ...state, qualityForm: null }
    case 'qualitySubmitting':
      return { ...state, qualityForm: { ...(state.qualityForm ?? {}), submitting: true, error: null } }
    case 'qualityFormError':
      return { ...state, qualityForm: { ...(state.qualityForm ?? {}), submitting: false, error: action.error ?? null } }
    case 'qualitySubmitted':
      return {
        ...state,
        quality: { loading: false, latest: action.latest ?? null, error: null },
        qualityForm: null,
        notice: '质检单已生成',
        error: null,
      }
    // ── 报返工（issue #7860）：任一工序工人都能报；这一笔被服务端改记为返工（不计件）并生成返工单 ──
    case 'reworkFormOpen':
      return { ...state, reworkForm: { submitting: false, error: null } }
    case 'reworkFormClose':
      return { ...state, reworkForm: null }
    case 'reworkSubmitting':
      return { ...state, reworkForm: { ...(state.reworkForm ?? {}), submitting: true, error: null } }
    case 'reworkFormError':
      return { ...state, reworkForm: { ...(state.reworkForm ?? {}), submitting: false, error: action.error ?? null } }
    case 'reworkSubmitted':
      // 服务端已改记 ⇒ 表单收起、屏上留一张回执；`view` 由装配层用同一张码重解析后带进来
      // （进度被退回 ⇒ 这一屏要回到真实值，不能停在被改记前的旧读数上）。
      return {
        ...state,
        view: action.view ?? state.view,
        rework: action.rework ?? null,
        reworkForm: null,
        notice: action.notice ?? null,
        error: null,
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

// ════════════════════════════════════════════════════════════════════════════════
// 报工三态（issue #5652 第二刀，2026-10-16）
//
// 🔴 用户裁定：服务端**已支持** `production_work_logs.work_type ∈ {normal, rework, scrap}`
//    （计件聚合也已排除 rework/scrap）⇒ 端侧只做**接线**，不改后端、**不新开端点**。
//
// 🔴 数量语义（**必须诚实**）：服务端 `ProductionScanCompleteService` 解析 `qualified_qty` 的
//    缺省 = `qty`（「rawQualified == null ? qty : …」）⇒ 只送 `work_type` 而**不**送
//    `qualified_qty` 时，报废那一笔会被记成**满额合格**。故非「正常」一律由装配层显式带
//    `qualified_qty: 0`（见 `frontend/worker-h5/src/app.mjs` 的 `wh5-report`）。
//
// 闭词表与后端 `ProductionService.WORK_TYPES` **逐字同名**（「work_type 仅支持 normal/rework/scrap」）。

/** 报工三态（**唯一一份**词表；`reduce` 与装配层共用同一把判据）。 */
export const WORK_TYPES = ['normal', 'rework', 'scrap']

/** 默认 = 正常（缺省 / 非法值都归到它 ⇒ 老行为一字不变：body 里**没有** `work_type` 键）。 */
export const DEFAULT_WORK_TYPE = 'normal'

const WORK_TYPE_LABELS = { normal: '正常', rework: '返工', scrap: '报废' }

/**
 * 质检**只有一个**录入动作 = 返工（issue #7749，用户 2026-10-25 逐字：
 * 「质检不要显示合格，默认都合格，只有出现问题时允许直接选择返工，只提供一个返工选项，
 * 加一些备注说明即可」）。
 *
 * 🔴 为什么不再有「合格 / 报废」两个选项：
 * ① 没问题就是**默认**（不点任何东西）⇒ 摆一个「合格」选项只会让工人多点一次；
 * ② 报废不在工人这一屏处置（真报废走商家侧质量处置）⇒ 工人端只负责「把问题记下来」。
 * 服务端 `QualityCheckService.RESULTS` 仍保留三态（观星台商家面零回归）—— 端侧只是**不提供**另外两个。
 */
export const QUALITY_RESULTS = [
  { value: 'rework', label: '返工', hint: '写明问题，提交后生成质检单（同一件返工后再检）' },
]

/**
 * 质检状态的显示词。
 *
 * 🔴 **不出现「合格」**（用户 2026-10-25 逐字「质检不要显示合格」）：
 * 合格是默认态、没有「合格」这个动作 ⇒ 屏上只在**有返工记录**时说话；其余一律「正常」。
 */
const QUALITY_LABELS = { pass: '正常', rework: '已记做工返工', scrap: '已记报废' }

/**
 * 本屏这道工序是不是「质检」（issue #7186）。
 *
 * 🔴 与后端 `DocumentOperationLinkage.QUALITY_OPERATION_NAME`（= `质检`）**逐字同名**。
 * 真闸在服务端（报工 / 扫码完成两条写入口对质检工序 422，唯一实现
 * `DocumentOperationLinkage#rejectManualReport`）；这里只决定「出不出报工按钮」——
 * 客户端藏按钮不构成授权，服务端拦不住才是 bug。
 *
 * 为什么判「逻辑名」而不是「工序 id 白名单」：路由里的质检工序按**名称**匹配（同 #7165），
 * 租户自建的质检工序（如 `质检-帘身`）经 `logicalOperationName` 归一后同样是「质检」。
 */
export function isQualityOperation(op) {
  const name = String(op?.logical_name ?? op?.operation_name ?? op?.operation ?? '').trim()
  return name === '质检'
}

/** 任意输入 ⇒ 闭词表内的值（缺省 / 非法 ⇒ 正常）。 */
export function normalizeWorkType(v) {
  return WORK_TYPES.includes(v) ? v : DEFAULT_WORK_TYPE
}

// ════════════════════════════════════════════════════════════════════════════════
// 裁剪报工：确认批次（issue #7647，用户 2026-10-24 逐字）
//   「裁剪报工的时候需要工人裁剪的哪个批次，如果通过智能派单的就默认展示指定批次，允许工人改，
//     如果没指定批次就需要工人手输才能完成报工，并且实时更新库存」
//
// 🔴 适用面**只由服务端**给（`batch_required`）：裁剪是当前唯一的适用工序，但「哪一行要不要批次」
//    是本单的业务判定（未指派 / 无批次入库的 SKU 会有例外，见 issue 的「边界」）——前端**不按工序名猜**，
//    也不自己写第二份「裁剪」字面。缺键 / 非 true ⇒ **一个字节都不变**（老后端 / 非裁剪工序零回归）。
// ════════════════════════════════════════════════════════════════════════════════

/**
 * 本屏这次报工是否必须确认批次（**唯一判据** = 服务端 `batch_required === true`）。
 *
 * @param {object} view 扫码解析结果
 * @returns {boolean}
 */
export function isBatchRequired(view) {
  return view?.batch_required === true
}

/** 派工指定批次（输入框预填值）：缺键 / 非字符串 / 空串 ⇒ `''`（绝不把 `undefined` 印上屏）。 */
export function assignedBatchNo(view) {
  const raw = view?.batch_no
  return typeof raw === 'string' ? raw.trim() : ''
}

/**
 * 工人当前**实际**的批次值（渲染预填 / 门禁 / 提交取值共用这**一份**判据）。
 *
 * `state.batchNo === null` = 还没动过输入框 ⇒ 用服务端预填的派工批次；否则用工人输入的原样值（`trim`）。
 * **不**在这里校验批次号格式：那是服务端的硬闸（`BATCH_NOT_FOUND` / `BATCH_SKU_MISMATCH` 422），
 * 前端凭一份会漂的正则提前拒绝，只会把「批次能改」变成「改不了」。
 */
export function currentBatchNo(state, view) {
  if (!isBatchRequired(view)) return ''
  if (typeof state?.batchNo === 'string') return state.batchNo.trim()
  return assignedBatchNo(view)
}

/**
 * 报工门禁：要批次却（trim 后）没填。
 *
 * 🔴 门禁只**禁用**按钮（与既有 in-flight 禁用态同一套样式），不把按钮藏起来 ——
 * 藏起来工人会以为「这一屏不能报工」，而他要的动作恰恰是**先填批次**。
 */
export function batchBlocked(state, view) {
  return isBatchRequired(view) && currentBatchNo(state, view) === ''
}

/** 候选批次（快捷项）：脏项（非字符串 / 空串）逐个丢掉；非裁剪工序 ⇒ 空数组（整块候选区不渲染）。 */
export function batchCandidates(view) {
  if (!isBatchRequired(view)) return []
  return (Array.isArray(view?.batch_candidates) ? view.batch_candidates : []).filter(
    (c) => typeof c?.batch_no === 'string' && c.batch_no.trim() !== '',
  )
}

/** 门禁提示（可行动，不责备；`render` 与装配层**共用同一句**，两处不会漂）。 */
export const BATCH_GATE_HINT = '请先填批次号再报工（这次从哪一批裁，就填哪一批）。'

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
  // ④ 质检工序**没有报工动作**（issue #7186）：判定即报工 ⇒ 这一屏只出质检区块，
  //    不出报工按钮 / 报工三态（服务端同款判据见 isQualityOperation 的注释）。
  if (isQualityOperation(view.operation)) return false
  return true
}

/**
 * **扫码即自动报工**的唯一判据（issue #7845）。
 *
 * <p>用户 2026-10-26 逐字：「现在还是不能扫码直接报工…」「扫码后除了自动报工，还需要生成成品入库单」。
 * 本函数与 {@link canReport} 的关系是**加严**：能报工 ≠ 能自动报。额外两条：</p>
 * <ol>
 *   <li><b>工序必须由工人档案唯一确定</b>（{@code determined_by === 'worker'}，issue #7749）——
 *       未绑定时服务端按顺序推断出的那一道未必是本次真正做的活，自动提交会把下一道记成这一道（计件错）；</li>
 *   <li><b>裁剪批次必须已经可用</b>（派工预填的就是它）—— 要批次却空着 ⇒ 服务端必 422，
 *       自动提交只会让工人盯着一句报错；这时停在屏上，等他填完手点【报工】。</li>
 * </ol>
 *
 * <p>放纯函数里（不发 DOM / 不发请求）⇒ `node --test` 可逐条钉住；装配层只在它为真时自动提交一次。</p>
 */
export function autoReportable(state, view) {
  if (!canReport(state, view)) return false
  if (view.operation.determined_by !== 'worker') return false
  if (isBatchRequired(view) && batchBlocked(state, view)) return false
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
 * 🔴 **2026-10-14 文案口径统一（issue #6868，用户逐字裁定②「工人屏全部统一到『报』」）**：
 * 按钮文案**再由【开工】改为【报工】**（只换词；上面那条 #4967 记录保留为沿革，不要按它改回去）。
 * 记账时点**不变**（仍是点这一下推进进度 + 记计件），所以文案说「领活」而不承诺「完工」。
 *
 * 🔴 **in-flight 闸（issue #6667 第 4 条，涉计件正确性）**：提交在飞时按钮 `disabled` + 文案改
 * 「提交中…」—— 车间里戴手套、弱网下答复要等好几秒，**没有反馈就会被反复按**；
 * 与机台页 `machine.mjs::reportBlock` 同一把闸（同一份形态，两页两处）。
 */
/**
 * 报工三态选择器（issue #5652 第二刀）—— 正常 / 返工 / 报废。
 *
 * 🔴 **只报数量，不报判定**：这是**工人**对自己这道活的数量归属（正常做出来的 / 返工的 / 报废的）。
 *    「质检结论」（这块布合不合格）由**另一个角色**在**另一个面**（商家侧质量检验）记录 ——
 *    工人屏**不得**出现任何质检判定控件（用户裁定：本单不是检验帘的那个面）。
 *
 * 🔴 出现条件与报工按钮**同一把**判据（`canReport`）⇒ 两者同生同灭，不会有
 *    「按钮没有、选择器还在」这种半截形态（那道判据在 `canReport` 一处，不复制第二份）。
 *
 * 形态抄既有约定（issue #6635 的工序选择器）：实线可点按钮 + `data-*` 委派 + 选中项
 * `is-on` + `aria-pressed`（选中态**看得见**，不是"记在内存里"）。
 */
function workTypePicker(state, view) {
  if (!canReport(state, view)) return ''
  const current = normalizeWorkType(view?.work_type)
  const choices = WORK_TYPES.map((t) => {
    const on = t === current
    return `<button data-work-type="${t}" class="wh5-choice${on ? ' is-on' : ''}" aria-pressed="${on}" type="button">${WORK_TYPE_LABELS[t]}</button>`
  }).join('')
  return `<div class="wh5-group" id="wh5-work-type" role="group" aria-label="报工类型">
      <span class="wh5-group-label">报工类型</span>${choices}
    </div>`
}

function reportButton(state, view) {
  if (!canReport(state, view)) return ''
  if (state.reporting) return '<button id="wh5-report" class="wh5-primary" type="button" disabled>提交中…</button>'
  // 裁剪批次门禁（issue #7647）：要批次却没填 ⇒ 与 in-flight **同一套**禁用态（`.wh5-primary[disabled]`）。
  // 非裁剪工序 / 已填 ⇒ 与改前**逐字节相同**。
  if (batchBlocked(state, view)) return '<button id="wh5-report" class="wh5-primary" type="button" disabled>报 工</button>'
  return '<button id="wh5-report" class="wh5-primary" type="button">报 工</button>'
}

/**
 * 「批次」区块（issue #7647）：输入框（预填派工批次、可改）+ 候选快捷项 + 一句说明 + 门禁提示。
 *
 * <p>🔴 只在 `batch_required === true` 时渲染；候选为空 ⇒ **整块候选区不渲染**（不摆空壳）。
 * 输入事件**不**整页重渲染（由 `app.mjs` 就地同步），所以这里的 `value` 就是工人当前的值。</p>
 *
 * <p>为什么候选做成「点一下就填入」而不是下拉：车间戴手套 + 弱光，下拉要两次精确点击；
 * 而且候选带**本批余量**——工人据此直接看出这一批够不够裁。</p>
 */
function batchBlock(state, view) {
  if (!isBatchRequired(view)) return ''
  const value = currentBatchNo(state, view)
  const cands = batchCandidates(view)
  // 说明只承诺**屏上真有**的动作（没有候选就不提候选 —— 让工人去找一个不存在的按钮是坏出口）
  const note = assignedBatchNo(view)
    ? '派工指定了这一批：按实际裁的批次改一下（这次从哪一批裁，就填哪一批）。'
    : cands.length > 0
      ? '本单没有指派批次：这次从哪一批裁，就填哪一批（点下面的候选可直接填入）。'
      : '本单没有指派批次：这次从哪一批裁，就填哪一批（必填，不填不能报工）。'
  const candHtml = cands.length === 0
    ? ''
    : `<div class="wh5-batch-cands" id="wh5-batch-candidates" role="group" aria-label="候选批次">${cands
        .map((c) => {
          const no = esc(c.batch_no.trim())
          // 余量 / 够不够都由服务端给（`remaining_meters` / `enough`）；缺键 ⇒ 这一句不渲染
          const rem = typeof c.remaining_meters === 'number' && Number.isFinite(c.remaining_meters)
            ? ` · 余 ${esc(fmtQty(c.remaining_meters))} 米`
            : ''
          const short = c.enough === false ? ' · 余量不足' : ''
          return `<button type="button" class="wh5-choice" data-batch-no="${no}">${no}${rem}${short}</button>`
        })
        .join('')}</div>`
  return `<div class="wh5-batch" id="wh5-batch">
      <label class="wh5-label">批次（这次从哪一批裁）
        <input id="wh5-batch-input" class="wh5-input" inputmode="text" autocomplete="off" placeholder="例如：PC-20261020-0007" value="${esc(value)}" />
      </label>
      <p class="wh5-sub" id="wh5-batch-note">${esc(note)}</p>
      ${candHtml}
      <p class="wh5-batch-hint" id="wh5-batch-hint">${batchBlocked(state, view) ? esc(BATCH_GATE_HINT) : ''}</p>
    </div>`
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
  // `work_type` 与 `__requestId` 同族：**丢掉** ⇒ 下一屏回到默认「正常」
  // （否则「报废」会悄悄留在屏上，下一笔正常做出来的活被记成报废）。
  // 批次（issue #7647）：下一屏的判据**只认服务端那一次重解析**（`next_batch_*`），既不沿用上一屏
  // （会让「打包」屏多出一个不该有的输入框、按钮还被禁死），也不一律清空
  // （报废不推进进度 ⇒ 下一道仍是「裁剪」，清空了工人就填不了批次、报不上去）。
  // 这一笔的 `batch_no` / `batch_candidates`（余量是记账**前**的读数）照旧丢弃。
  const { __requestId, work_type: _workType, batch_no: _batchNo, batch_candidates: _batchCandidates, ...rest } = view ?? {}
  return {
    ...rest,
    batch_required: receipt?.nextBatchRequired === true,
    batch_no: typeof receipt?.nextBatchNo === 'string' ? receipt.nextBatchNo : null,
    batch_candidates: Array.isArray(receipt?.nextBatchCandidates) ? receipt.nextBatchCandidates : [],
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
export function doneNotice(receipt, { auto = false } = {}) {
  return `${doneNoticeBase(receipt, auto)}${batchReceiptTail(receipt)}`
}

/**
 * 回执里的**批次尾部**（issue #7647）：本次批次 + 该批次记账后余量，余量不足时补一句缺口。
 *
 * <p>🔴 「缺键就缺」（本仓工人端纪律）：三键任一缺失 / 形状不对 ⇒ 对应那一句**整句不出现**，
 * 绝不渲染 `undefined` / `null` / `NaN`。非裁剪工序 ⇒ 三键都缺 ⇒ 返回 `''`（文案与改前逐字节相同）。</p>
 *
 * <p>余量不足照实说、不责备、不惊叹号（`migao-dev-flow` §31 P4）：不挡工人记工钱，
 * 只让他知道这一批已经透支了多少米。</p>
 */
function batchReceiptTail(receipt) {
  const no = typeof receipt?.batchNo === 'string' ? receipt.batchNo.trim() : ''
  const remaining = typeof receipt?.batchRemaining === 'number' && Number.isFinite(receipt.batchRemaining)
    ? receipt.batchRemaining
    : null
  const shortage = typeof receipt?.batchShortageMeters === 'number' && Number.isFinite(receipt.batchShortageMeters)
    && receipt.batchShortageMeters > 0
    ? receipt.batchShortageMeters
    : null
  const parts = []
  if (no) parts.push(remaining === null ? `批次 ${no}` : `批次 ${no} · 余量 ${fmtQty(remaining)} 米`)
  if (shortage !== null) parts.push(`本批余量不足，缺口 ${fmtQty(shortage)} 米已如实记账`)
  return parts.length === 0 ? '' : ` · ${parts.join(' · ')}`
}

function doneNoticeBase(receipt, auto) {
  if (receipt.replayed) return '这次没有新增计件：重复提交已回放（同一次扫码只算一次）'
  // 🔴 issue #7845：扫码即自动记账 ⇒ 文案必须**说清这一下已经记了账**（工人没点任何按钮，
  // 不能让他以为"还要再点一下"）。手动那条「已报工」四段**逐字冻结**（跨面文案守卫
  // `frontend/bmini-app/tests/worker-scan-report-copy-same-source.test.ts` 逐字钉住）⇒
  // 这里保留字面量、不拼 `head`（拼了就只剩后缀，守卫会判「回执缺『已报工 · 下一道：』」）。
  if (receipt.orderCompleted) {
    return auto ? '已自动报工 · 本单工序都报完了 🎉' : '已报工 · 本单工序都报完了 🎉'
  }
  if (receipt.setCompleted === true) {
    return auto ? '已自动报工 · 本套工序都报完了 🎉' : '已报工 · 本套工序都报完了 🎉'
  }
  // 🔴 「下一道」必须**带部位**（issue #4963）：改前只拼 `nextOperation.logical_name`
  // ⇒ 跨部位时屏上少一半信息（`打卷 · 布帘` 显示成 `打卷`）。回执的 `next_operation`
  // 本来就带 `position`（逐字照 `ProductionScanCompleteService.enrichNextOperation`）。
  // 文案语义（`已报工` = 扫码开工/领活这一下，issue #4967 用户逐字裁定 +#6868 统一口径）
  // **一字不动**，只补部位。
  const next = operationDisplayName(receipt.nextOperation)
  if (next) return auto ? `已自动报工 · 下一道：${next}` : `已报工 · 下一道：${next}`
  return auto ? '已自动报工' : '已报工'
}

/**
 * 页头入口栏（2026-10-10 改版 issue #6635；2026-10-27 再收窄 issue #7934）。
 *
 * 🔴 **四条跨应用入口已移出本页**，只剩两条：
 *  · 拍照入库 / 补打入库标签（用户 2026-10-10 逐字「移除拍照入库和补打入库标签」）——
 *    动线由**工人工作台**承载（frontend/bmini-app/src/pages/worker/home/index.tsx）；
 *  · 我的计件 / 发货（issue #7934，用户 2026-10-27 逐字「我的计件和发货…为什么做到报工详情页面？
 *    应该都作为工人菜单页面上的菜单，工人页面有拍照发货了，可以把报工详情页面的发货功能移除掉」）——
 *    同样由**工人工作台**承载（「我的计件」「拍照发货」两条行卡；入口台账 `PAGE_ENTRY_LEDGER` 的
 *    `from` 就是它）⇒ 从报工页移出**不会**让那两页变成「走不到」。
 * 反向钉住（页头再出现这四条 ⇒ 红）= frontend/worker-h5/tests/worker-h5-worker-entries.test.mjs
 * + frontend/worker-h5/tests/worker-h5-pages.test.mjs。
 *
 * 入口栏 = `pages` 里**本页有对应面、且没有别处入口**的那几条（`cut_calc` / `rework`），文案与商家端
 * 页面开关同源（页面键与商家面人话名的唯一真值 =
 * backend/admin-api/src/main/java/com/migao/admin/worker/WorkerPages.java）：
 * 改前的「机台模式」只有内部人懂（用户 2026-10-10 逐字问「机台模式是什么含义」）。
 * 一条都没开 ⇒ **整条入口栏不渲染**（不留空 `<nav>`）—— 机台那台屏改用**本机预设**直达
 * （`?page=cut_calc`，见 frontend/worker-h5/src/scan-input.mjs 的 `deviceHomeFromLocation`）。
 *
 * 🔴 **裁高计算这条有意暂留本页**（issue #7934 的边界）：端内（bmini）还没有裁高页，撤掉会让手机端
 * 工人彻底没有裁高入口；一体机那台屏自己用本机预设直达，不受影响。端内裁高页另单（并入 #7813）。
 *
 * ⚠️ 这是**菜单显隐**语义，不是「访问拦截」（2026-09-29 用户逐字改判，口径以 B 端 H5 为准）：
 * 链接消失 ≠ 页面不可达 —— `/b/report/{machine,piecework,shipment}.html` 直接敲 URL **仍可进入**
 * （静态页，本包不给它加访问门禁）。同款语义的另一半 = 页头的 `pageNoticeBanner`
 * （`report` 关掉时页面**照旧可用**，只多一句话）。
 */
function workerEntriesBar(state) {
  const { opened } = effectivePages(state)
  const machine = opened.has(PAGE_CUT_CALC)
    ? `<a class="wh5-entry" id="wh5-machine-entry" href="${MACHINE_ENTRY_HREF}">裁高计算（一体机）</a>` : ''
  // 返工记录（issue #7860）：`rework` ∈ 页面集才出入口（用户裁定「在工人档案中设置过可见权限的工人」）；
  // 文案与后端 `WorkerPages.labels()` 同源（商家在工人档案里勾的就是「返工记录」）。
  const rework = opened.has(PAGE_REWORK)
    ? `<a class="wh5-entry" id="wh5-rework-entry" href="${REWORK_ENTRY_HREF}">返工记录</a>` : ''
  // 质检（2026-10-27 改判 issue #7945）：入口只在 `inspect` ∈ 页面集**且已扫到一件**时出现
  // （没扫码时点了也无对象可判 ⇒ 不给死按钮）；点开 = 当前件的「做工判定」面板。
  const inspect = opened.has(PAGE_INSPECT) && state.view?.position?.order_item_id
    ? `<button class="wh5-entry" id="wh5-quality-entry" type="button">质检</button>` : ''
  // 报返工（2026-10-27 上移）：任一工序工人、已扫到一件就能报（布料问题，不看页面键）；
  // 与「质检」（做工问题）并列在页头，工人不用再滑到页面底部找按钮。
  const reworkAction = state.view?.position?.order_item_id
    ? `<button class="wh5-entry" id="wh5-rework-action" type="button">报返工</button>` : ''
  if (!machine && !rework && !inspect && !reworkAction) return ''
  return `<nav class="wh5-entries" id="wh5-worker-entries" aria-label="工人面入口">
    ${machine}${rework}${inspect}${reworkAction}
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
    <h1 class="wh5-title">工人报工</h1>
    <p class="wh5-sub">工号 + PIN 登录（手机 / PAD 均可，无需微信）</p>
    ${state.error ? `<p class="wh5-error" id="wh5-error">${esc(state.error)}</p>` : ''}
    <label class="wh5-label">企业编码（向商家索取）<input id="wh5-enterprise-code" class="wh5-input" inputmode="text" autocomplete="organization" value="${esc(state.enterpriseCode ?? '')}" /></label>
    <label class="wh5-label">工号<input id="wh5-worker-no" class="wh5-input" inputmode="text" autocomplete="username" /></label>
    <label class="wh5-label">PIN<input id="wh5-pin" class="wh5-input" type="password" inputmode="numeric" autocomplete="current-password" /></label>
    <button id="wh5-login" class="wh5-primary" type="button">登 录</button>
  </section>`
}

/**
 * 待扫码态（issue #7845：**手输短码已撤**）。
 *
 * <p>用户 2026-10-26 逐字：「当前点击跳转后是手输短码，这个功能不需要，没什么用」⇒ 本屏只剩一句
 * 指路：用水洗唛上的二维码扫一次（微信扫一扫 / 手机相机）。没有码就没有可做的事 —— 不摆一个
 * 没人用的输入框（它会被误读成"系统要我抄码"）。</p>
 */
function scanView(state) {
  return `${header(state)}
  <section class="wh5-card" id="wh5-scan-hint">
    ${state.notice ? `<p class="wh5-notice" id="wh5-notice">${esc(state.notice)}</p>` : ''}
    ${state.error ? `<p class="wh5-error" id="wh5-error">${esc(state.error)}</p>` : ''}
    <h1 class="wh5-title">扫码报工</h1>
    <p class="wh5-sub">用水洗唛上的二维码扫一次（微信扫一扫 / 手机相机）—— 扫到就自动报工，不用再点按钮。</p>
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

/**
 * 当前扫码部位的**生产信息**（母单 #6901）：从 `set_overview.positions[]` 里取**本部位**那一行
 * （键与工序明细**同一份**取数 ⇒ 不再多一个读面）。取不到（旧码降级 / 服务端未下发规格）⇒ 空串
 * ⇒ `positionSpecBlock` 自然不渲染（不是空块）。
 *
 * <p>它在 `mainView` 顶上印、并由 `overviewView` **排除**同一个 `order_item_id` ⇒
 * 同一件事实在同一屏恰好出现**一次**（`migao-dev-flow` §31 P2 信息不重复）。</p>
 */
function currentSpecBlock(v) {
  const itemId = v?.position?.order_item_id
  if (itemId === null || itemId === undefined) return ''
  const positions = v?.set_overview?.positions
  if (!Array.isArray(positions)) return ''
  const me = positions.find((p) => p?.order_item_id === itemId)
  return me ? positionSpecBlock(me) : ''
}

/**
 * 帘种那一行（issue #7739）—— 用户 2026-10-25 逐字「工人报工详情页面也缺失帘种这一关键信息，
 * 需要告诉工人是布帘还是纱帘」。
 *
 * <p>取数顺序 = **同一件事实的可靠度序**：扫码解析给的 `position.position_kind`（服务端直接算）→
 * 本部位行的 `position_kind`（工序实例）→ 订单行快照的 `curtain_type`。任一在场即上屏。</p>
 *
 * <p>🔴 它**不在规格块里**（`SCAN_BLOCK_EXCLUDED_KEYS`）：规格块的规则是「缺值整行不出现」，
 * 而这一项是识别信息 —— 两处都缺时屏上**不编**（不显示「帘种 —」）；有值就必须看得见。</p>
 */
function ternLine(v) {
  const me = (Array.isArray(v?.set_overview?.positions) ? v.set_overview.positions : [])
    .find((p) => p && p.order_item_id === v?.position?.order_item_id)
  const kind = v?.position?.position_kind ?? me?.position_kind ?? me?.curtain_type ?? null
  const text = typeof kind === 'string' ? kind.trim() : ''
  return text ? `<p class="wh5-sub" id="wh5-tern">帘种 ${esc(text)}</p>` : ''
}

/**
 * 质检工序的「这一屏只有一个动作」说明（issue #7186）。
 *
 * <p>用户 2026-10-18 逐字：「质检员不需要报工这个动作，只需要有一个质检动作，完成判定后自动报工，
 * 然后自动生成质检流水」⇒ 本屏对「质检」工序**不出**报工按钮（{@link canReport} 判 false）。
 * 不给一句话就是**死页面**（工人看到应做数量、却没有可点的动作）。</p>
 *
 * <p>两句不同是因为**授权**不同（`inspect` 逐人开）：没开这一页的人不该以为「点一下就能报」——
 * 说清「要谁来录」，而不是把按钮藏起来不说理由。</p>
 */
function qualityOnlyNote(state, view) {
  if (!isQualityOperation(view?.operation)) return ''
  return effectivePages(state).opened.has(PAGE_INSPECT)
    ? '<p class="wh5-sub" id="wh5-quality-only">本道是质检工序：默认没问题，完成生产即算做完；有问题在下面记返工即可（不用报工）。</p>'
    : '<p class="wh5-sub" id="wh5-quality-only">本道是质检工序：默认没问题；要记返工需开通「质检」页（当前账号未开通）。</p>'
}

/**
 * 「你的工序」一行（issue #7749）：工人档案上绑定的那道工序 —— 扫完码直接告诉他
 * 「这次系统替你选的是哪道」，不用他去比对工序名（绑定时就已经定下来了）。
 *
 * <p>未绑定（`worker_operation` 为 null / 缺键）⇒ 整行**一个字节都不出现**（保持改前的屏）。</p>
 */
function workerOperationLine(v) {
  const name = typeof v?.worker_operation === 'string' ? v.worker_operation.trim() : ''
  return name ? `<p class="wh5-sub" id="wh5-worker-operation">你的工序：${esc(name)}</p>` : ''
}

/**
 * 质检区块（issue #7162）：工人扫水洗唛后，在这一屏录判定、生成「质检单」。
 *
 * <p>口径（用户 2026-10-17 逐字）：「工人不能进入观星台……只需要在小程序端扫码进入报工页后
 * 有入口进行质检即可」「质检等同发货工序一样，打包发货完成后生成发货单，质检完成后生成质检单」。</p>
 *
 * 🔴 三条硬约束：
 * ① 只在 `inspect` ∈ 页面集时渲染（逐人开；服务端 `/api/worker/quality/**` 同时做写准入，
 *    藏起 UI **不是**授权）；
 * ② **默认没问题**（issue #7749）：没有记录 ⇒ 显示「正常」，屏上**不出现「合格」**这个选项/状态；
 * ③ 只有一个动作 =【返工】+ 问题说明（必填；前端先拦一次不白跑网络，服务端 422 才是真判据）。
 *
 * <p>成品帘 = `view.position.order_item_id`（水洗唛是部位码 ⇒ 扫码已指到这一件），
 * 不逐工序、不重算报工数量。</p>
 */
function qualityBlock(state, view) {
  const { opened } = effectivePages(state)
  if (!opened.has(PAGE_INSPECT)) return ''
  const itemId = view?.position?.order_item_id
  if (itemId === null || itemId === undefined || itemId === '') return ''

  const q = state.quality ?? { loading: true, latest: null, error: null }
  const latest = q.latest ?? null
  const result = latest?.result ?? null
  // 没有记录 = **默认没问题**（「正常」，不写「合格」）；有记录才显示记了什么
  const stateText = QUALITY_LABELS[result] ?? '正常'
  const stateClass = result && QUALITY_LABELS[result] ? `is-${result}` : 'is-pending'
  const moment = typeof latest?.inspected_at === 'string'
    ? latest.inspected_at.slice(0, 16).replace('T', ' ')
    : ''
  const meta = latest
    ? `<div class="wh5-q-meta" id="wh5-quality-meta">检验人 ${esc(latest.inspector_name || '—')}${moment ? ` · ${esc(moment)}` : ''}</div>`
    : ''
  const reason = latest?.reason
    ? `<div class="wh5-q-reason" id="wh5-quality-reason-latest">原因：${esc(latest.reason)}</div>`
    : ''
  const loadingText = q.loading ? '<p class="wh5-sub" id="wh5-quality-loading">质检状态读取中…</p>' : ''
  const errorText = q.error ? `<p class="wh5-error" id="wh5-quality-error">${esc(q.error)}</p>` : ''
  const form = state.qualityForm ? qualityFormView(state) : ''

  return `<section class="wh5-card wh5-quality" id="wh5-quality">
    <div class="wh5-q-head">
      <span class="wh5-q-title">质检（做工）</span>
      <span class="wh5-q-state ${stateClass}" id="wh5-quality-state">${stateText}</span>
    </div>
    ${meta}
    ${reason}
    ${loadingText}
    ${errorText}
    <p class="wh5-sub">做工有问题才在这里记（例如缝线开裂 / 走线歪）；布料/来料问题走下面的「返工」，两者不是一回事。${state.qualityForm ? '' : '要记就点上方菜单「质检」。'}</p>
    ${form}
  </section>`
}

/**
 * 质检录入表单（issue #7749：**只有一个动作** —— 做工返工 + 问题说明）。
 *
 * <p>用户逐字「只提供一个返工选项，加一些备注说明即可」⇒ 不再有判定单选组（合格 / 报废都退场）；
 * 说明在提交时由装配层从 DOM 读值（不在 input 事件里重绘 ⇒ 每敲一个字不会丢焦点）。</p>
 */
function qualityFormView(state) {
  const f = state.qualityForm
  return `<div class="wh5-q-form" id="wh5-quality-form">
      <p class="wh5-sub" id="wh5-quality-hint">这次记为「做工返工」：写明问题，提交后生成质检单。</p>
      <label class="wh5-label">问题说明（必填）
        <textarea id="wh5-quality-reason" class="wh5-input" rows="2"
          placeholder="例如：缝线开裂 / 走线歪 / 拼缝不齐"></textarea>
      </label>
      ${f.error ? `<p class="wh5-error" id="wh5-quality-form-error">${esc(f.error)}</p>` : ''}
      <div class="wh5-q-actions">
        <button id="wh5-quality-submit" class="wh5-primary" type="button"${f.submitting ? ' disabled' : ''}>${f.submitting ? '提交中…' : '提交质检'}</button>
        <button id="wh5-quality-cancel" class="wh5-ghost" type="button"${f.submitting ? ' disabled' : ''}>取消</button>
      </div>
    </div>`
}


/**
 * 「成品入库」卡片（issue #7845）：**打包工序**扫码报工成功后出现在报工页顶部。
 *
 * <p>用户 2026-10-26 逐字：「只有打包工序绑定了成品帘入库，如果是打包工人，那扫码后除了自动报工，
 * 还需要生成成品入库单」「打包扫码报工时就需要确认质检结果和成品入库&打入库标签」。</p>
 *
 * <p>🔴 内容全部来自服务端（回执 {@code finished_inbound} / 再次扫码时的同名块）：
 * 质检结论 / 入库单号 / 仓位 / 标签逐行（`label.rows`），前端**不拼业务字段**。
 * 出库**不在本页**（用户同日裁定：打包 = 入库；出库留给发货 / 商家侧）—— 改前那个「出库」按钮
 * （#7762）已被本单撤下，`disabled` 兜底随之退场（连按钮都不渲染，服务端写面仍保留）。</p>
 */
function finishedInboundCard(state) {
  const w = state.finishedInbound
  if (!w) return ''
  const label = w.label ?? {}
  const rows = (Array.isArray(label.rows) ? label.rows : []).map((row) => (
    `<div class="wh5-fl-row" data-label-key="${esc(row.label)}">`
    + `<span class="wh5-fl-k">${esc(row.label)}</span>`
    + `<span class="wh5-fl-v">${esc(row.value)}</span></div>`
  )).join('')
  // 质检：无记录 = 正常（与质检块的默认口径同一份：合格是默认态，不写「未检」吓人）
  const q = w.quality ?? null
  const quality = q ? `${QUALITY_LABELS[q.result] ?? '已检'}${q.reason ? `（原因：${q.reason}）` : ''}` : '正常'
  return `<section class="wh5-card wh5-finished-label" id="wh5-finished-inbound" aria-label="成品入库">
    <div class="wh5-set" id="wh5-fi-bin">成品入库 · 仓位 ${esc(w.bin_code ?? '未分配')}</div>
    <p class="wh5-sub" id="wh5-fi-quality">质检：${esc(quality)}</p>
    ${w.inbound_no ? `<p class="wh5-sub" id="wh5-fi-no">入库单 ${esc(w.inbound_no)}</p>` : ''}
    <div class="wh5-fl-rows" id="wh5-fl-rows">${rows}</div>
    ${label.short_code ? `<p class="wh5-fl-code" id="wh5-fl-code">${esc(label.short_code)}</p>` : ''}
    <div class="wh5-fl-actions">
      <button id="wh5-fi-print" class="wh5-ghost" type="button">打印入库标签</button>
    </div>
  </section>`
}

/**
 * 返工区块（issue #7860）—— **任一工序工人**扫水洗唛后都能报，不看打包工序、不看 `inspect` 页。
 *
 * <p>用户 2026-10-26 逐字：「质检不能绑定死打包工序，需要允许任一工序工人报返工」
 * 「报返工的那个工序不能计件的，只报返工，生成返工单」；追问「刚自动记的那一笔怎么处理」时
 * 选「把刚自动记的那一笔改记为返工（回退进度与计件）」。</p>
 *
 * 🔴 三条硬约束：
 * ① **不按页面键门控**（与质检区块相反）：报返工是「这件没做好」的事实上报，任何一个工位都可能第一时间发现；
 * ② 只有一个动作 =【报返工】+ 问题说明（必填）；提交后服务端改记报工三态并生成返工单；
 * ③ 只在这一屏**能定位到一件**时渲染（`position.order_item_id`）—— 没有件就没有可改记的账。</p>
 */
function reworkBlock(state, view) {
  const itemId = view?.position?.order_item_id
  if (itemId === null || itemId === undefined || itemId === '') return ''
  const r = state.rework ?? null
  const receipt = r
    ? `<p class="wh5-sub" id="wh5-rework-done">返工单 ${esc(r.reworkNo ?? '')} 已生成${r.operationName ? ` · 工序 ${esc(r.operationName)}` : ''}（这一笔已改记为返工，不计件）</p>`
    : ''
  return `<section class="wh5-card wh5-rework" id="wh5-rework">
    <div class="wh5-q-head"><span class="wh5-q-title">返工（布料）</span></div>
    ${receipt}
    <p class="wh5-sub">布料/来料有问题就报返工：这一笔记为返工（不计件），同时生成一张返工单给车间跟进；做工问题请走「质检」。要报就点页头「报返工」。</p>
    ${state.reworkForm ? reworkFormView(state) : ''}
  </section>`
}

/** 返工录入表单（issue #7860）：只有一个动作 —— 返工 + 问题说明（必填）。 */
function reworkFormView(state) {
  const f = state.reworkForm ?? {}
  return `<div class="wh5-q-form" id="wh5-rework-form">
      <label class="wh5-label">问题说明（必填）
        <textarea id="wh5-rework-reason" class="wh5-input" rows="2"
          placeholder="例如：布面污渍 / 布料破洞 / 色差"></textarea>
      </label>
      ${f.error ? `<p class="wh5-error" id="wh5-rework-form-error">${esc(f.error)}</p>` : ''}
      <div class="wh5-q-actions">
        <button id="wh5-rework-submit" class="wh5-primary" type="button"${f.submitting ? ' disabled' : ''}>${f.submitting ? '提交中…' : '提交返工'}</button>
        <button id="wh5-rework-cancel" class="wh5-ghost" type="button"${f.submitting ? ' disabled' : ''}>取消</button>
      </div>
    </div>`
}

function mainView(state) {
  const v = state.view
  const op = v.operation
  // 🔴 工序未确定（本套工序都已被领走 / 服务端推断不出待领工序）⇒ **只给结论，不给开工按钮**。
  // 改前这里直接读 `op.unit_price` ⇒ TypeError（页面白屏）；而「回执驱动的一屏」正好会走到这个形态
  // （`set_completed:true` / `next_operation:null`）⇒ 必须显式分支（防呆⑤ 的记账侧那一半）。
  if (!op) {
    return `${header(state)}
    ${finishedInboundCard(state)}
  <section class="wh5-card">
    <div class="wh5-set" id="wh5-set">第 ${esc(v.set_no)} 套 · ${esc(v.position?.position_name ?? '')}</div>
    ${ternLine(v)}
    ${qualityBlock(state, v)}
    ${reworkBlock(state, v)}
    ${v.completed === true
      ? '<p class="wh5-done" id="wh5-completed">本套工序都已报工 🎉</p>'
      : v.worker_operation
        ? `<p class="wh5-sub" id="wh5-no-operation">你的工序是「${esc(v.worker_operation)}」：本件${v.worker_operation_state === 'done' ? '的这道已经做完' : '没有这道工序'}，不用报工。</p>`
        : '<p class="wh5-sub" id="wh5-no-operation">本部位推断不出待报工序（工序未确定 ⇒ 不得记账）</p>'}
    ${overviewView(v)}
    ${cutPlanView(v)}
    ${state.notice ? `<p class="wh5-notice" id="wh5-notice">${esc(state.notice)}</p>` : ''}
    ${state.error ? `<p class="wh5-error" id="wh5-error">${esc(state.error)}</p>` : ''}
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
  //
  // 🔴 issue #7749：工人**绑定了工序**时服务端已自动选中 ⇒ 不出选择器（alternatives 也恒为空）。
  //    显式判 `!v.worker_operation` 是刻意的双保险：绑定工人不该看到「改报别的工序」的入口。
  const candidates = [op, ...(v.alternatives ?? [])].filter((c) => c && c.operation_id)
  const picker = !v.worker_operation && candidates.length > 1
    ? `<div class="wh5-pick" id="wh5-op-picker" role="group" aria-label="选工序">
        <span class="wh5-pick-label">选工序（点哪道就领哪道）</span>
        ${candidates.map((c) => {
          const on = c.operation_id === op.operation_id
          return `<button data-operation-id="${esc(c.operation_id)}" class="wh5-op-choice${on ? ' is-on' : ''}" aria-pressed="${on}" type="button">${esc(c.logical_name)}</button>`
        }).join('')}
      </div>`
    : ''
  return `${header(state)}
  ${finishedInboundCard(state)}
  <section class="wh5-card">
    <div class="wh5-set" id="wh5-set">第 ${esc(v.set_no)} 套 · ${esc(v.position?.position_name ?? '')}</div>
    ${ternLine(v)}
    ${qualityBlock(state, v)}
    ${reworkBlock(state, v)}
    ${workerOperationLine(v)}
    <div class="wh5-op" id="wh5-operation">${esc(operationDisplayName(op))}</div>
    <div class="wh5-qty" id="wh5-qty">应做 ${fmtQty(op.qty)} ${esc(op.unit ?? '')}</div>
    <div class="wh5-price-row">${price}</div>
    ${currentSpecBlock(v)}
    ${v.completed === true ? '<p class="wh5-done" id="wh5-completed">本套工序都已报工</p>' : ''}
    ${state.notice ? `<p class="wh5-notice" id="wh5-notice">${esc(state.notice)}</p>` : ''}
    ${state.error ? `<p class="wh5-error" id="wh5-error">${esc(state.error)}</p>` : ''}
    ${picker}
    ${qualityOnlyNote(state, v)}
    ${workTypePicker(state, v)}
    ${batchBlock(state, v)}
    ${reportButton(state, v)}
    ${overviewView(v, v.position?.order_item_id ?? null)}
    ${cutPlanView(v)}
  </section>`
}

/**
 * 「本部位生产信息」（母单 #6901，用户诉求：「工人需要这些信息 + 商品信息来决定如何生产」）。
 *
 * <p>数据**只**来自服务端下发的部位对象（`set_overview.positions[]`，键 = `ProductionService
 * #orderSpecByItemId` 的单一取数）—— 页面不另取一份、不算第二份。标签 / 单位 / 数值格式化走
 * **共享** `position-spec.mjs`（与机台屏同一份；本文件零标签表）。</p>
 *
 * <p>🔴 <b>缺值不渲染该行</b>（工人端不摆「批号 —」这种空占位，与精裁清单的 `component` /
 * `batch_no` 同款）；行数恒等于「该部位真有值的规格数」⇒ 一张老单（空快照）不会多出一片空网格。
 * 绝不出现 `undefined` / `null` / `NaN`（三者都由 `formatSpecValue` 归到 `EMPTY` ⇒ 整行跳过）。</p>
 *
 * <p>两态都挂（`mainView` 与 `overviewView`）⇒ 扫后一屏与「本套工序」里每个部位都能看到自己的规格。
 * 服务端到达之前（报工回执等**不带**规格的响应）⇒ 没有任何行 ⇒ 整块（含标题）**一个字节都不出现**。</p>
 */
function positionSpecBlock(p) {
  const rows = specRows(p)
  if (rows.length === 0) return ''
  const items = rows
    .map((row) => `<div class="wh5-spec-row"><dt>${esc(row.label)}</dt><dd>${esc(row.text)}</dd></div>`)
    .join('')
  return `<dl class="wh5-spec" id="wh5-position-spec"><div class="wh5-spec-title">本部位生产信息</div>${items}</dl>`
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
function overviewView(v, excludeOrderItemId = null) {
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
          // 状态与已报数量让工人区分「还没报 / 已报过」——两者都要看得见
          const claimed = o.status === 'done'
          return `<li class="wh5-ov-op${claimed ? ' is-done' : ''}">
          <span class="wh5-ov-name">${esc(o.logical_name ?? '')}</span>
          <span class="wh5-ov-qty">应做 ${fmtQty(o.qty)} ${esc(o.unit ?? '')}</span>
          <span class="wh5-ov-price">${price}</span>
          <span class="wh5-ov-status">${claimed ? '已报工' : '待报工'}</span>
          <span class="wh5-ov-done">已报 ${fmtQty(o.done_qty)} ${esc(o.unit ?? '')}</span>
        </li>`
        })
        .join('')
      return `<div class="wh5-ov-pos">
        <div class="wh5-ov-pos-name">${esc(p.position_name ?? p.position_kind ?? '')}</div>
        ${p.order_item_id === excludeOrderItemId ? '' : positionSpecBlock(p)}
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
 *
 * <p><b>派工指定批次（issue #6754）</b>：`batch_no` = 这一行「**从哪一批裁**」（真值源 = 批次消耗台账，
 * 与商家端精裁清单、工人端部位规格面**同一份**取数）—— 裁床据此去拿料。**未指派（`null`）
 * ⇒ 这一格不渲染**（与上面的 `component` 同款：工人端只摆「照着干活要用」的信息，不摆空占位；
 * 服务端也只在真指派过时才给值）。</p>
 *
 * <p><b>从该批裁多少布（issue #7722）</b>：`batch_meters` 与 `batch_no` **同一份取数**（台账净额）
 * ⇒ 这一格显示「批次 PC-… · 裁 12.30 米」，工人一眼知道**裁哪一批、这一批裁多少**。
 * 两者任一缺失 ⇒ 该子项不渲染（不造 0 米、不摆空占位）。</p>
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
      // 派工指定批次（issue #6754）+ 从该批裁多少布（issue #7722）：未指派 / 作废后净额归零
      // ⇒ `null` ⇒ 这一格不出现（与 `component` 同款；工人端不摆「批次 —」这种空占位）
      const batch = typeof r.batch_no === 'string' && r.batch_no.trim() ? esc(r.batch_no.trim()) : ''
      const batchMeters =
        r.batch_meters === null || r.batch_meters === undefined ? '' : ` · 裁 ${fmtQty(r.batch_meters)} 米`
      return `<li class="wh5-cut-row">
        <span class="wh5-cut-size">裁 ${size}</span>
        <span class="wh5-cut-name">${esc(name)}${component}</span>
        <span class="wh5-cut-meters">用料 ${meters}</span>
        ${batch ? `<span class="wh5-cut-batch">批次 ${batch}${batchMeters}</span>` : ''}
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
/**
 * 成品标签的**打印纸张文档**（50mm × 70mm，V197 / issue #7762）。
 *
 * <p>为什么是一份独立文档（而不是给报工页加打印样式）：`@page` 是**文档级**声明 —— 放进报工页
 * 会把整页（登录/报工/工序选择器）都按 50×70 印出来。#7761 的发货标签用「打印态隔离」解，
 * 这里同样只让标签上纸：新窗口 = 干净文档，`@page` 只作用于它。</p>
 *
 * <p>返回纯字符串 ⇒ 可零浏览器单测（判据：行序 = 服务端下发顺序、缺值行不出现、短码在纸面上）。</p>
 */
export function washLabelPrintHtml(w) {
  const label = w?.label ?? {}
  const rows = (Array.isArray(label.rows) ? label.rows : []).map((row) => (
    `<div class="row"><span class="k">${esc(row.label)}</span><span class="v">${esc(row.value)}</span></div>`
  )).join('')
  const code = label.short_code ? `<div class="code">${esc(label.short_code)}</div>` : ''
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8" />
<title>成品标签 ${esc(label.bin_code ?? w?.bin_code ?? '')}</title>
<style>
  @page { size: 50mm 70mm; margin: 0; }
  * { box-sizing: border-box; }
  body { margin: 0; width: 50mm; height: 70mm; padding: 1.5mm; font-family: "PingFang SC", "Microsoft YaHei", sans-serif; color: #000; }
  .row { display: flex; gap: 1mm; font-size: 2.6mm; line-height: 1.35; }
  .k { flex: 0 0 11mm; color: #333; }
  .v { flex: 1 1 auto; font-weight: 600; word-break: break-all; }
  .code { margin-top: 1mm; font-size: 3mm; letter-spacing: .3mm; font-weight: 700; text-align: center; }
</style></head><body>
${rows}
${code}
</body></html>`
}

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
