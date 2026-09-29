// case_ids: PG-018, BM-006, DF-017
//
// 一体机「机台模式」——装配层（DOM 绑定 + 常驻扫码枪 + 会话失效回落）。
//
// 判据都在 `machine.mjs` 的纯函数里（可被 `node --test` 直接钉住，无需 DOM）；
// 本文件只做接线，四条纪律：
//   ① **常驻扫码，不依赖 `focus()`**：`keydown` 监听挂在 `document` 上（车间里没人会先点输入框）；
//   ② 输入法兜底：`compositionstart/end` + `event.isComposing`（机台页**没有任何文本输入元素**，
//      IME 没有合成目标 —— 这是第一道，也是最强的一道）；
//   ③ 🔴 **不写机器**：与「给机器输值」这件事本文件一个字节都不碰（没有串口 / Modbus / 下发面）；
//   ④ 【完成】= 报工（`POST /api/worker/production/scan/complete`，**既有**入口）—— 前端只发
//      token + 幂等键，工序/数量/身份全由服务端定；失败大字显式，不假装成功；
//   ⑤ 401 ⇒ 大字回落「请先登录」（绝不静默重试、绝不按上一个人的身份读写）。

import { createApi, SESSION_EXPIRED } from './api.mjs'
import { parseScanInput } from './scan-input.mjs'
import { createScanBuffer, initialMachineState, reduceMachine, renderMachine, resumePending } from './machine.mjs'
// 未确认提交的幂等键**与手机报工页共用同一把**（同一个 storage 契约、同一份判据）⇒ 键名只有一处
import { PENDING_REQUEST_KEY } from './app.mjs'

/** 造一个「本机唯一」的幂等键（与 app.mjs 同口径：补传必须复用同一个键，绝不能重发时重新生成）。 */
function newRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `req-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

/**
 * 装配机台页。
 *
 * @param {object} deps
 * @param {Document} deps.doc
 * @param {object} deps.api
 * @param {Location|string} [deps.location]
 */
export function createMachineApp({ doc, api, location = globalThis.location, storage = null }) {
  const root = doc.getElementById('machine-root')
  let state = initialMachineState()

  // ── 未确认提交（幂等键跨刷新复用，issue #4814 的同一条纪律）：读/写/清都「尽力而为」——
  //    存不下就当没有，绝不因为存储不可用而挡住报工（那会把「钱记不上」变成「活报不上」）。
  const readPending = () => {
    try {
      return JSON.parse(storage?.getItem(PENDING_REQUEST_KEY) ?? 'null')
    } catch {
      return null
    }
  }
  const writePending = (pending) => {
    try {
      storage?.setItem(PENDING_REQUEST_KEY, JSON.stringify(pending))
    } catch {
      /* 存不下 ⇒ 退化为「跨刷新不做去重」 */
    }
  }
  const clearPending = () => {
    try {
      storage?.removeItem(PENDING_REQUEST_KEY)
    } catch {
      /* 同上 */
    }
  }

  const draw = () => {
    if (root) root.innerHTML = renderMachine(state)
    bind()
  }

  const dispatch = (action) => {
    state = reduceMachine(state, action)
    draw()
  }

  /** 扫一次码 ⇒ 一屏（计算全在服务端；前端只渲染）。 */
  async function readScanned(raw) {
    const token = parseScanInput(raw)
    if (!token) {
      dispatch({ type: 'failed', error: '没有识别到码：请扫一次水洗唛（或手工输入短码）' })
      return
    }
    try {
      const data = await api.readCuttingHeight(token)
      // token 一并进状态：报工（【完成】）要用**这次扫到的那张码**去定位（前端不重解析）
      dispatch({ type: 'scanned', data, token })
    } catch (e) {
      if (e?.code === SESSION_EXPIRED) {
        dispatch({ type: 'failed', error: '登录已失效：请先用工号 + PIN 登录本台设备，再扫码' })
        return
      }
      dispatch({ type: 'failed', error: e?.message ?? String(e) })
    }
  }

  // ① 常驻扫码枪（**不依赖 focus**）：全局 keydown 缓冲；③′ 输入法兜底两道
  const buffer = createScanBuffer({ onCode: (code) => { void readScanned(code) } })
  const onKeyDown = (event) => buffer.handleKeyDown(event)
  const onCompositionStart = () => buffer.handleCompositionStart()
  const onCompositionEnd = () => buffer.handleCompositionEnd()
  doc.addEventListener('keydown', onKeyDown)
  doc.addEventListener('compositionstart', onCompositionStart)
  doc.addEventListener('compositionend', onCompositionEnd)

  function bind() {
    for (const el of doc.querySelectorAll('[data-machine-pick]')) {
      el.addEventListener('click', () => dispatch({ type: 'pick', index: Number(el.dataset.machinePick) }))
    }
    for (const el of doc.querySelectorAll('[data-machine-hit]')) {
      el.addEventListener('change', () => dispatch({ type: 'toggleHit', key: el.dataset.machineHit }))
    }
    const openCalc = doc.querySelector('[data-machine-open-calc]')
    if (openCalc) openCalc.addEventListener('click', () => dispatch({ type: 'openCalc' }))
    const back = doc.querySelector('[data-machine-back]')
    if (back) back.addEventListener('click', () => dispatch({ type: 'back' }))
    const report = doc.querySelector('[data-machine-report]')
    if (report) report.addEventListener('click', () => { void reportWork() })
  }

  /**
   * 【完成】= **报工**（2026-09-29 追加裁定「一体机本期要做报工，且是一条链」）。
   *
   * 🔴 **前端只发 token + 幂等键**（`completeByScan` 内部就是白名单式构造）：
   *    工序由**服务端推断**（前端不许指定工序名）、数量由服务端取「剩余应做」、
   *    计件归属 = **服务端**从 `X-Worker-Session-Id` 解出的当前工人 ⇒ 屏上那个裁高值
   *    （以及手改的取舍）**不会**被写进报工请求。
   * 🔴 幂等：同一屏复用同一把键；「已发出、答复丢了」的那次提交**落盘**（跨刷新复用同一把键）
   *    ⇒ 重扫/重按都是服务端回放，不重复计件。
   * 🔴 失败**不假装成功**：传输层失败（无 HTTP 响应）保留键，服务端答复过就清键。
   */
  async function reportWork() {
    const token = state.token
    if (!token) {
      dispatch({ type: 'reportFailed', error: '没有扫码记录：请先扫一次水洗唛' })
      return
    }
    if (state.reporting) return // in-flight 锁：连点两下不会变成两笔报工
    const workerId = api.worker()?.workerId ?? null
    const clientRequestId = resumePending(readPending(), { token, workerId }) ?? newRequestId()
    dispatch({ type: 'reportStart' })
    // 发出**之前**落盘：否则「已发出、答复丢了」这段窗口在刷新后无据可查
    writePending({ token, workerId, requestId: clientRequestId })
    try {
      const receipt = await api.completeByScan({ token, clientRequestId })
      clearPending() // 服务端已答复（首次成功或回放）⇒ 这一笔有结论，下一笔必须换新键
      dispatch({ type: 'reported', receipt })
    } catch (e) {
      // 只有「服务端答复过」才算有结论（`err.status` 缺失 = 无 HTTP 响应：断网/超时）
      if (e?.status !== undefined) clearPending()
      if (e?.code === SESSION_EXPIRED) {
        dispatch({ type: 'failed', error: '登录已失效：请先用工号 + PIN 登录本台设备，再扫码报工' })
        return
      }
      dispatch({ type: 'reportFailed', error: e?.message ?? String(e) })
    }
  }

  return {
    get state() { return state },
    dispatch,
    /** 测试/嵌入用：把一次「扫到的码」直接喂进来（等价于扫码枪交付一次）。 */
    feed: (raw) => readScanned(raw),
    destroy() {
      doc.removeEventListener('keydown', onKeyDown)
      doc.removeEventListener('compositionstart', onCompositionStart)
      doc.removeEventListener('compositionend', onCompositionEnd)
    },
  }
}

/** 浏览器入口（`machine.html` 用 `<script type="module">` 直接加载，无构建步骤）。 */
export async function boot() {
  const storage = globalThis.localStorage
  const api = createApi({ storage, deviceLabel: 'MACHINE' })
  // storage 交给装配层：未确认提交的幂等键要跨刷新活着（与手机页同一把键，issue #4814）
  const app = createMachineApp({ doc: globalThis.document, api, storage })
  // 页头「当前工人」必须来自**服务端**（共用设备时前端 state 不可信）
  if (api.sessionId()) {
    try {
      const w = await api.currentWorker()
      app.dispatch({ type: 'worker', worker: { workerName: w.workerName, workerNo: w.workerNo } })
    } catch {
      app.dispatch({ type: 'failed', error: '登录已失效：请先用工号 + PIN 登录本台设备，再扫码' })
    }
  } else {
    app.dispatch({ type: 'failed', error: '本台设备还没登录：请先用工号 + PIN 登录，再扫码' })
  }
  return app
}

if (globalThis.document?.getElementById?.('machine-root')) {
  boot()
}
