// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5 报工页 —— 装配层（DOM 绑定 + 会话续期检查）。
//
// 本文件**只做接线**：所有判据（能不能报工 / 旧码怎么降级 / 一屏长什么样）都在
// `render.mjs` 的纯函数里 —— 那样才能被 `node --test` 钉住（无需 DOM）。
//
// 共用 PAD 三条（设计 §3.1~§3.3）：
//   ① 页头常驻「当前工人」——取**服务端** `current-worker`（不是前端 state）；
//   ② 一步切换 —— 切完**不丢扫码上下文**（本文件只换 session，不清 `state.view`）；
//   ③ 闲置登出 —— 定时器 + `visibilitychange` 双保险（PAD 常被切到别的 App，只靠定时器会漏）。

import { createApi, PAGES_UNREAD, SESSION_EXPIRED } from './api.mjs'
import { deviceHomeFromLocation, enterpriseCodeFromLocation, parseScanInput } from './scan-input.mjs'
import {
  afterComplete,
  DEFAULT_WORKER_IDLE_MINUTES,
  doneNotice,
  initialState,
  legacySelection,
  MACHINE_ENTRY_HREF,
  reduce,
  renderPage,
} from './render.mjs'

/**
 * 「未确认提交」的本地持久化键（issue #4814）。
 *
 * 幂等键（`X-Client-Request-Id`）此前只活在内存里的 `state.view.__requestId` ⇒ **刷新/重开页面就没了**：
 * 断网（响应丢失）后重扫同一张码会带**新键**，服务端据此当成**新的一次报工**
 * （重扫时「待做工序」已推进到下一道 ⇒ 满额记在下一道上 = 多给钱）。
 * 故把**未收到服务端答复**的那一次提交落盘，跨刷新复用同一个键（服务端回放，不重复记账）。
 */
export const PENDING_REQUEST_KEY = 'migao:worker-h5:pending-report'

/**
 * **本机默认页**（设备级预设，issue #6635；用户 2026-10-10 裁定 = 设备级、零后端改动）。
 *
 * 机台那台屏（有线扫码枪 + 浏览器）只需要**一次**预设：打开
 * `https://app.migaozn.com/w/?page=cut_calc` ⇒ 本机记住，此后每次打开 `/w/` 都直接落到裁高页
 * （`/w/machine.html`）；`?page=report`（不带 `keep`）取消钉住。
 * 手机工人打开 `/w/`（不带参数、本机没钉过）⇒ 仍是报工页 —— 不需要任何后端字段/端点。
 *
 * 🔴 只在**已登录**时才把人换过去（`boot()` 与登录成功那处）：机台页**没有登录面**，
 * 未登录就把人换过去 = 把他关在门外（`/w/` 才是登录那一页）。
 */
export const DEVICE_HOME_KEY = 'migao:worker-h5:home'

/** 读本机默认页（storage 不可用 ⇒ 当没钉过；绝不因为存储而挡住报工）。 */
function readDeviceHome(storage) {
  try {
    return storage?.getItem(DEVICE_HOME_KEY) ?? null
  } catch {
    return null
  }
}

/** 写/清本机默认页；**返回是否写成**（写不成 ⇒ 不认这次预设，宁可留在报工页）。 */
function writeDeviceHome(storage, value) {
  try {
    if (value) storage?.setItem(DEVICE_HOME_KEY, value)
    else storage?.removeItem(DEVICE_HOME_KEY)
    return true
  } catch {
    return false
  }
}

/**
 * 把「本机默认页」应用到当前 URL（纯装配动作，可注入替身 ⇒ 被 `node --test` 钉住）。
 *
 * @param {object} deps
 * @param {Location|string} deps.location 当前 URL
 * @param {object} [deps.storage]
 * @param {Function} [deps.replace] 换页（`location.replace`）—— 只有真要换页时才被调用
 * @returns {'cut_calc'|'report'} 本机默认页（`cut_calc` ⇒ 调用方应换到 `/w/machine.html`）
 */
export function applyDeviceHome({ location, storage = null, replace } = {}) {
  const href = typeof location === 'string' ? location : location?.href ?? ''
  const { page, once } = deviceHomeFromLocation(href)
  let pinned
  if (page === 'cut_calc') {
    pinned = writeDeviceHome(storage, 'cut_calc') // 刚钉上：**存得下**才算钉住
  } else if (page === 'report') {
    if (!once) writeDeviceHome(storage, null) // 明确取消钉住（`keep=1` = 只本次 ⇒ 不动预设）
    pinned = false
  } else {
    pinned = readDeviceHome(storage) === 'cut_calc' // 没带参数 ⇒ 按本机记忆
  }
  if (pinned) {
    replace?.(MACHINE_ENTRY_HREF)
    return 'cut_calc'
  }
  return 'report'
}

/** 造一个「本机唯一」的幂等键（补传必须复用同一个键 ⇒ 绝不能在重发时重新生成）。 */
function newRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `req-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

/**
 * 装配页面。
 *
 * @param {object} deps
 * @param {Document} deps.doc
 * @param {object} deps.api
 * @param {Location|string} [deps.location]
 * @param {object} [deps.storage] `localStorage`（**刷新后仍活着的那份**）—— 未确认提交的幂等键落它；
 *        缺省 null ⇒ 不做跨刷新复用（与改前同级；测试注入用）
 * @returns {{state: object, dispatch: Function, destroy: Function}}
 */
export function createApp({ doc, api, location = globalThis.location, storage = null }) {
  const href = typeof location === 'string' ? location : location?.href ?? ''
  // 企业编码（issue #6564）：短链 302 的 `?tenant_code=` 只是**初值**（预填进输入框，可编辑）
  const urlEnterpriseCode = enterpriseCodeFromLocation(href)
  const root = doc.getElementById('worker-h5-root')
  let state = { ...initialState(), enterpriseCode: urlEnterpriseCode ?? '' }
  let idleTimer = null

  // ── 未确认提交（issue #4814）：读/写/清都是「尽力而为」——存不下就当没有，
  //    绝不因为存储不可用而挡住报工（那会把「钱记不上」变成「活报不上」）。
  const readPending = () => {
    try {
      return JSON.parse(storage?.getItem(PENDING_REQUEST_KEY) ?? 'null')
    } catch {
      return null
    }
  }
  const writePending = (p) => {
    try {
      storage?.setItem(PENDING_REQUEST_KEY, JSON.stringify(p))
    } catch {
      /* 存不下 ⇒ 退化为改前行为（跨刷新不做去重） */
    }
  }
  const clearPending = () => {
    try {
      storage?.removeItem(PENDING_REQUEST_KEY)
    } catch {
      /* 同上 */
    }
  }

  /**
   * 本次提交可复用的键 = 上次**未确认**提交的那把（服务端会回放，不再记账）。
   *
   * 🔴 必须同时满足「同一张码」+「同一工人」：跨码复用会把另一笔活回放掉，
   * 跨工人复用会把**上一个人的报工**回放给当前工人 ⇒ 两人的计件都错。
   * 任一条件不成立（含 workerId 取不到）⇒ null（fail-closed，退回新键）。
   */
  const resumedRequestId = (token) => {
    const me = api.worker()?.workerId ?? null
    const p = readPending()
    return me && p && p.token === token && p.workerId === me ? p.requestId : null
  }

  /**
   * 本机被钉在裁高页（issue #6635）⇒ 换过去。
   *
   * 🔴 只在**已登录**后调用：机台页没有登录面，未登录换过去 = 把人关在门外。
   */
  const gotoPinnedHome = () =>
    applyDeviceHome({
      location: href,
      storage,
      replace: (url) => {
        if (typeof location !== 'string') location?.replace?.(url)
      },
    })

  /** 上次提交没收到答复 ⇒ 明说「重扫是安全的」（工人据此才敢再点一次）。 */
  const resumedNotice = (token) =>
    resumedRequestId(token)
      ? '上次提交没收到结果：点【完成】会按同一次提交处理（服务端回放，不会重复计件）'
      : null

  const draw = () => {
    root.innerHTML = renderPage(state, state.view)
    bind()
  }

  const dispatch = (action) => {
    state = reduce(state, action)
    if (action.type === 'resolved') armIdle(state.view?.idle_minutes)
    draw()
  }

  /** 报错统一出口：session 过期 ⇒ 回落未登录（清本地已由 api 完成）。 */
  const fail = (e) => {
    if (e?.code === SESSION_EXPIRED) {
      dispatch({ type: 'logout' })
      dispatch({ type: 'notice', notice: null })
      state = { ...state, error: e.message }
      draw()
    } else {
      dispatch({ type: 'error', error: e?.message ?? String(e) })
    }
  }

  /**
   * 闲置登出：定时器（服务端 `idle_minutes`）+ 可见性变化双保险。
   *
   * 🔴 兜底必须与服务端**同源**（母单 #5161 顺手修的不一致）：改前这里是字面 `15`，
   * 而服务端全局默认 = **30 天**（`WorkerSessionService.DEFAULT_IDLE_MINUTES = 43200`，
   * 2026-10-07 用户裁定「延长到 1 个月」；上一版一周 10080）。正常链路服务端**恒回** `idle_minutes`
   * （登录响应就带 ⇒ 进 state），故兜底只在拿不到时生效；但字面 `15` 会让降级路径比服务端早 43185 分钟踢人。
   */
  function armIdle() {
    if (idleTimer) clearTimeout(idleTimer)
    const minutes = state.worker?.idleMinutes ?? DEFAULT_WORKER_IDLE_MINUTES
    idleTimer = setTimeout(() => { void checkAlive() }, Math.max(1, minutes) * 60_000)
  }

  /**
   * 拉一次自助读面（`GET /api/worker/me`）把**页面集**放进 state 并重渲染。
   *
   * 🔴 调用点 = 「会话就绪」的每一处：首屏（`boot`）/ 登录成功 / 与服务器对账（`checkAlive`）
   * —— 缺了登录那处，**换人会沿用上一个人的页面集**（切换工人后页面开关不生效）。
   *
   * 🔴 fail-open（本单硬约束，**故意**与 `completeByScan` 的 fail-closed 不同口径）：
   * 读不到页面权限 ⇒ **按全开运行**并让页面显式提示 —— 把「开关没读到」变成「活干不了」
   * 是更坏的失败（挡的是计件工资，而这里本来就只是可见性）。
   * 唯一例外 = 401：那是身份面的事，交给 `fail()` 回落未登录（绝不静默按上一个人继续）。
   *
   * @returns {Promise<boolean>} 是否拿到了页面集（false = 降级态，页面已显式提示）
   */
  async function refreshPages() {
    try {
      const me = await api.readMe()
      // `pages` 缺失 / 非数组 ⇒ 原样传 null ⇒ `effectivePages` 按全开跑 + 打提示（不在这里编一份默认值）
      dispatch({ type: 'pages', pages: me.pages })
      return Array.isArray(me.pages) && me.pages.length > 0
    } catch (e) {
      if (e?.code === PAGES_UNREAD) {
        dispatch({ type: 'pages', pages: null, pagesUnread: true })
        return false
      }
      fail(e) // 401 / 会话过期：回落未登录（清本地已由 api 完成）
      return false
    }
  }

  /** 与**服务端**对一次账：401 ⇒ 回落未登录（绝不静默按上一个人记账）。 */
  async function checkAlive() {
    if (!api.sessionId()) return
    try {
      const w = await api.currentWorker()
      dispatch({ type: 'worker', worker: { workerName: w.workerName, workerNo: w.workerNo } })
      await refreshPages() // 页面开关可能被商家在中途改过 ⇒ 每次对账顺带刷新（换人换权限）
      armIdle()
    } catch (e) {
      fail(e)
    }
  }

  function bind() {
    const on = (id, fn) => {
      const el = doc.getElementById(id)
      if (el) el.addEventListener('click', fn)
    }

    on('wh5-login', async () => {
      const workerNo = doc.getElementById('wh5-worker-no')?.value?.trim()
      const pin = doc.getElementById('wh5-pin')?.value ?? ''
      // 企业编码：以输入框为准（URL 值已在首屏预填进去，可编辑）—— 租户只由服务端解析
      const enterpriseCode = doc.getElementById('wh5-enterprise-code')?.value?.trim()
      try {
        const s = await api.login({ workerNo, pin, enterpriseCode })
        // idleMinutes 一并进 state：前端定时器与服务端 `idle_expires_at` 用**同一个**数值
        // （不是前端自己拍一个 15 分钟 —— 服务端可配 5~60，两处不一致就会出现
        //  「前端还显示着工人、服务端已经 401」的错位）
        dispatch({
          type: 'worker',
          worker: { workerName: s.workerName, workerNo: s.workerNo, idleMinutes: s.idleMinutes },
        })
        armIdle()
        // 🔴 登录成功也要拉页面集（本单）：换人换权限 —— 上一个人的页面开关不得沿用给当前这位工人
        await refreshPages()
        // 🔴 本机被钉在裁高页（机台那台屏，issue #6635）⇒ 登录成功直接换过去（不必再点）
        if (gotoPinnedHome() === 'cut_calc') return
        // 扫码落地：URL 里带码 ⇒ 登录后直接解析（一次扫码 = 1 步）
        const code = parseScanInput(href, href)
        if (code) await doScan(code)
      } catch (e) {
        fail(e)
      }
    })

    on('wh5-logout', async () => {
      await api.logout()
      dispatch({ type: 'logout' })
    })

    on('wh5-switch', async () => {
      // 一步切换：**保留** state.view（不丢扫码上下文）—— 只把身份换掉
      await api.logout()
      state = { ...state, worker: null, mode: 'login', notice: '请登录要切换到的工人（扫码结果已保留）' }
      draw()
    })

    on('wh5-scan', async () => {
      const raw = doc.getElementById('wh5-code')?.value ?? ''
      await doScan(raw)
    })

    on('wh5-rescan', () => {
      dispatch({ type: 'resolved', view: null })
      draw()
    })

    on('wh5-report', async () => {
      const v = state.view
      if (!v?.operation?.operation_id) return
      // 🔴 幂等键**同一屏复用**（重试 = 服务端回放首次结果，绝不重复计件）；成功换屏 ⇒ 换新键。
      // 刻意**不**每次点击都新造一个：那样「第一次其实成功了、响应丢了，工人再点一次」= 第二笔报工。
      // 🔴 跨刷新（#4814）：屏上的键随刷新消失 ⇒ 补第二条通道 —— 上次**没收到服务端答复**的那一次
      //    提交已落盘，同一工人 + 同一张码 ⇒ 复用同一个键（服务端回放，不会二次记账）。
      const clientRequestId = v.__requestId ?? resumedRequestId(v.__token) ?? newRequestId()
      state = { ...state, view: { ...v, __requestId: clientRequestId } }
      // 发出**之前**落盘：否则「已发出、答复丢了」这段窗口在刷新后无据可查
      writePending({ token: v.__token, workerId: api.worker()?.workerId ?? null, requestId: clientRequestId })
      try {
        const r = await api.completeByScan({
          token: v.__token,
          // 只有「一键改」（工人显式指定）才带 operation_id：归属由**服务端**校验（防呆④）。
          // 默认路径**只带 token** ⇒ 哪道工序由**系统**定（防呆⑤），数量由服务端取「剩余应做」。
          operationId: v.operation.determined_by === 'picked' ? v.operation.operation_id : undefined,
          // 旧码收口（#4794）：只有旧码路径的视图才有 `__selection`（新码恒 undefined ⇒ body 只带 token）
          selection: v.__selection,
          clientRequestId,
        })
        // 服务端已答复（首次成功或回放）⇒ 这一笔有结论：下一笔必须换新键
        clearPending()
        // 回执驱动下一屏：接着做下一道 / 本套完工（`afterComplete` 丢掉 __requestId ⇒ 下一笔换新键）
        dispatch({ type: 'completed', view: afterComplete(state.view, r), notice: doneNotice(r) })
      } catch (e) {
        // 只有「服务端答复过」才算有结论（`err.status` 缺失 = 无 HTTP 响应：断网/超时）
        // ⇒ 传输层失败时**保留**这把键，刷新后重扫仍然回放同一次提交
        if (e?.status !== undefined) clearPending()
        fail(e)
      }
    })

    for (const el of doc.querySelectorAll('[data-set-id]')) {
      el.addEventListener('click', () => dispatch({ type: 'pickSet', setId: el.dataset.setId, setNo: el.dataset.setNo }))
    }
    for (const el of doc.querySelectorAll('[data-order-item-id]')) {
      el.addEventListener('click', () => { void pickPosition(el.dataset.orderItemId) })
    }
    // 工序选择器（issue #6635）：点**别的**候选 = 反复解析一次（服务端校验归属）；
    // 点**当前已选中**那道 ⇒ no-op（它不是"再查一次"的开关，也绝不因此多发一次请求）。
    for (const el of doc.querySelectorAll('.wh5-op-choice[data-operation-id]')) {
      el.addEventListener('click', () => {
        if (el.classList.contains('is-on')) return
        void doScan(state.view?.__token ?? '', el.dataset.operationId, state.view?.__selection)
      })
    }
  }

  /**
   * 旧码收口（issue #4794）：选完套 + 部位 ⇒ **服务端**按 (码, 套, 部位) 重新解析出部位级视图。
   *
   * 🔴 为什么必须再请求一次（而不是前端自己挑工序）：工序由**服务端**推断（防呆⑤）——
   * 前端自己挑 = 把「哪道工序」交给客户端，正是 #4792 要治的病。选择经 `legacySelection()`
   * 判定（新码恒 null）；选中项随视图带下去（`__selection`），报工时原样回传 ⇒ 服务端重解析同一部位。
   */
  async function pickPosition(orderItemId) {
    const setId = state.selection.setId
    const token = state.view?.__token
    dispatch({ type: 'pickPosition', orderItemId })
    const selection = legacySelection(state.view, { setId, orderItemId })
    if (!token || !selection) return
    try {
      const view = await api.resolveScan({ token, selection })
      state = { ...state, view: { ...view, __token: token, __selection: selection } }
      // 重扫同一张码且上次提交没收到答复 ⇒ 明说「这一下是回放、不会重复计件」
      dispatch({ type: 'resolved', view: state.view, notice: resumedNotice(token) })
    } catch (e) {
      fail(e)
    }
  }

  async function doScan(raw, operationId, selection) {
    const token = parseScanInput(raw, href)
    if (!token) {
      dispatch({ type: 'error', error: '没有识别到码：请扫一次，或手工输入短码 / 加工单号' })
      return
    }
    try {
      const view = await api.resolveScan({ token, operationId, selection })
      state = {
        ...state,
        view: { ...view, __token: token, ...(selection ? { __selection: selection } : {}) },
      }
      dispatch({ type: 'resolved', view: state.view, notice: resumedNotice(token) })
    } catch (e) {
      fail(e)
    }
  }

  const onVisible = () => { if (doc.visibilityState === 'visible') void checkAlive() }
  doc.addEventListener('visibilitychange', onVisible)

  return {
    get state() { return state },
    dispatch,
    /** 手工刷新页面集（`GET /api/worker/me`）：供装配层/测试在会话就绪后显式调用一次。 */
    refreshPages,
    destroy() {
      if (idleTimer) clearTimeout(idleTimer)
      doc.removeEventListener('visibilitychange', onVisible)
    },
  }
}

/** 浏览器入口（`index.html` 用 `<script type="module">` 直接加载，无构建步骤）。 */
export async function boot() {
  const { createApi: mk } = await import('./api.mjs')
  const storage = globalThis.localStorage
  const api = mk({ storage })
  // storage 交给装配层：未确认提交的幂等键要跨刷新活着（#4814）
  const app = createApp({ doc: globalThis.document, api, storage })
  // 🔴 设备级预设（issue #6635）：本机被钉在裁高页 **且已登录** ⇒ 换页走人（前置：机台页无登录面）
  if (applyDeviceHome({ location: globalThis.location, storage }) === 'cut_calc' && api.sessionId()) return app
  // 首屏：本地有登录态 ⇒ 与**服务端**对一次账再显示（页头必须服务端来源）
  if (api.sessionId()) {
    try {
      const w = await api.currentWorker()
      app.dispatch({ type: 'worker', worker: { workerName: w.workerName, workerNo: w.workerNo } })
      // 页面集随会话就绪一起拉（本单）：读不到 ⇒ 页面按全开跑 + 显式提示（fail-open）
      await app.refreshPages()
    } catch {
      app.dispatch({ type: 'logout' })
    }
  } else {
    app.dispatch({ type: 'worker', worker: null })
  }
  return app
}

if (globalThis.document?.getElementById?.('worker-h5-root')) {
  boot()
}
