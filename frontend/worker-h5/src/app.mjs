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
import { initialState, reduce, renderPage } from './render.mjs'

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
 * @returns {{state: object, dispatch: Function, destroy: Function}}
 */
export function createApp({ doc, api, location = globalThis.location }) {
  const href = typeof location === 'string' ? location : location?.href ?? ''
  const tenantId = tenantIdFromLocation(href)
  const root = doc.getElementById('worker-h5-root')
  let state = initialState()
  let idleTimer = null

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
        dispatch({ type: 'worker', worker: { workerName: s.workerName, workerNo: s.workerNo } })
        state = { ...state, worker: { ...state.worker, idleMinutes: s.idleMinutes } }
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
      try {
        const r = await api.report({
          orderId: v.order_id,
          operationId: v.operation.operation_id,
          qty: v.operation.qty,
          qualifiedQty: v.operation.qty,
          clientRequestId: newRequestId(),
        })
        dispatch({ type: 'notice', notice: r.orderCompleted ? '本单已完工 🎉' : '已报工' })
      } catch (e) {
        fail(e)
      }
    })

    for (const el of doc.querySelectorAll('[data-set-id]')) {
      el.addEventListener('click', () => dispatch({ type: 'pickSet', setId: el.dataset.setId, setNo: el.dataset.setNo }))
    }
    for (const el of doc.querySelectorAll('[data-order-item-id]')) {
      el.addEventListener('click', () => dispatch({ type: 'pickPosition', orderItemId: el.dataset.orderItemId }))
    }
    for (const el of doc.querySelectorAll('.wh5-alt[data-operation-id]')) {
      el.addEventListener('click', () => { void doScan(state.view?.__token ?? '', el.dataset.operationId) })
    }
  }

  async function doScan(raw, operationId) {
    const token = parseScanInput(raw, href)
    if (!token) {
      dispatch({ type: 'error', error: '没有识别到码：请扫一次，或手工输入短码 / 加工单号' })
      return
    }
    try {
      const view = await api.resolveScan({ token, operationId })
      state = { ...state, view: { ...view, __token: token } }
      dispatch({ type: 'resolved', view: state.view })
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
  const api = mk({ storage: globalThis.localStorage })
  const app = createApp({ doc: globalThis.document, api })
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
