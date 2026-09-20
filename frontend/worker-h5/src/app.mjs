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

import { createApi, SESSION_EXPIRED } from './api.mjs'
import { parseScanInput, tenantIdFromLocation } from './scan-input.mjs'
import { afterComplete, doneNotice, initialState, legacySelection, reduce, renderPage } from './render.mjs'

/**
 * 「未确认提交」的本地持久化键（issue #4814）。
 *
 * 幂等键（`X-Client-Request-Id`）此前只活在内存里的 `state.view.__requestId` ⇒ **刷新/重开页面就没了**：
 * 断网（响应丢失）后重扫同一张码会带**新键**，服务端据此当成**新的一次报工**
 * （重扫时「待做工序」已推进到下一道 ⇒ 满额记在下一道上 = 多给钱）。
 * 故把**未收到服务端答复**的那一次提交落盘，跨刷新复用同一个键（服务端回放，不重复记账）。
 */
export const PENDING_REQUEST_KEY = 'migao:worker-h5:pending-report'

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
  const tenantId = tenantIdFromLocation(href)
  const root = doc.getElementById('worker-h5-root')
  let state = initialState()
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

  /** 闲置登出：定时器（服务端 `idle_minutes`）+ 可见性变化双保险。 */
  function armIdle() {
    if (idleTimer) clearTimeout(idleTimer)
    const minutes = state.worker?.idleMinutes ?? 15
    idleTimer = setTimeout(() => { void checkAlive() }, Math.max(1, minutes) * 60_000)
  }

  /** 与**服务端**对一次账：401 ⇒ 回落未登录（绝不静默按上一个人记账）。 */
  async function checkAlive() {
    if (!api.sessionId()) return
    try {
      const w = await api.currentWorker()
      dispatch({ type: 'worker', worker: { workerName: w.workerName, workerNo: w.workerNo } })
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
      try {
        const s = await api.login({ workerNo, pin, tenantId })
        // idleMinutes 一并进 state：前端定时器与服务端 `idle_expires_at` 用**同一个**数值
        // （不是前端自己拍一个 15 分钟 —— 服务端可配 5~60，两处不一致就会出现
        //  「前端还显示着工人、服务端已经 401」的错位）
        dispatch({
          type: 'worker',
          worker: { workerName: s.workerName, workerNo: s.workerNo, idleMinutes: s.idleMinutes },
        })
        armIdle()
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
    for (const el of doc.querySelectorAll('.wh5-alt[data-operation-id]')) {
      el.addEventListener('click', () => {
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
  // 首屏：本地有登录态 ⇒ 与**服务端**对一次账再显示（页头必须服务端来源）
  if (api.sessionId()) {
    try {
      const w = await api.currentWorker()
      app.dispatch({ type: 'worker', worker: { workerName: w.workerName, workerNo: w.workerNo } })
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
