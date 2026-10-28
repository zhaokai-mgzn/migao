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
import { deviceHomeFromLocation, enterpriseCodeFromLocation, normalizeEnterpriseCode, parseScanInput } from './scan-input.mjs'
import {
  afterComplete,
  autoReportable,
  batchBlocked,
  BATCH_GATE_HINT,
  currentBatchNo,
  DEFAULT_WORKER_IDLE_MINUTES,
  DEFAULT_WORK_TYPE,
  doneNotice,
  effectivePages,
  initialState,
  legacySelection,
  MACHINE_ENTRY_HREF,
  normalizeWorkType,
  PAGE_INSPECT,
  reduce,
  renderPage,
  washLabelPrintHtml,
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
 * @param {Function} [deps.replace] 换页动作；缺省 = `location.replace`（传字符串 URL 的测试里天然是 no-op）
 * @param {boolean} [deps.navigate] **现在能不能跳** —— 由调用方把门（见下），`false` ⇒ 一个字节都不跳
 * @returns {'cut_calc'|'report'} 本机默认页（`cut_calc` = 该落在裁高页）
 *
 * 🔴 **为什么换页要由调用方把门**（真浏览器验收实测两次踩过）：机台页 `/w/machine.html` **没有登录面**
 * ⇒ 未登录就换过去 = 把工人关在门外（他连登录那一页都回不去）。所以：`boot()` 只在
 * **已有工人 session** 时 `navigate`；登录成功那处（`gotoPinnedHome`）才 `navigate: true`。
 * 返回值**照旧**是 `cut_calc`（调用方据此在登录后补跳）—— 把「该落哪页」与「现在跳不跳」拆成两件事。
 */
export function applyDeviceHome({ location, storage = null, replace, navigate = false } = {}) {
  const href = typeof location === 'string' ? location : location?.href ?? ''
  // 🔴 缺省换页动作 = 传进来的 `location.replace` 本身（真浏览器里 `globalThis.location` 就是它）
  // —— 缺了这一步，`boot()` 那处只拿到 `'cut_calc'` 却**什么也没跳**（真浏览器验收实测：重开 `/w/`
  // 停在报工页，而单测因为自己注入了 `replace` 察觉不到）。判据 = worker-h5-pages.test.mjs 的 ⑥。
  const go = replace ?? ((url) => {
    if (typeof location !== 'string') location?.replace?.(url)
  })
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
  if (pinned && navigate) go(MACHINE_ENTRY_HREF)
  return pinned ? 'cut_calc' : 'report'
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
/**
 * `checkAlive()`（后台对账）的两条护栏 —— issue #6642，2026-10-10 线上日志实测。
 *
 * **实测现场**（SWAS `migao-deploy-nginx-1`，2026/10/10 08:12:10）：同一条工人 session
 * 在 ~4 秒里打出 **92 个请求**（15–23 req/s），被 nginx `worker_sess`（rate=2r/s burst=60）拒了 4 条 ——
 * 被拒的只有 `GET /api/worker/me` 与 `GET /api/worker/production/current-worker` 两个**读面**
 * （写面 `/scan`、`/scan/complete` 一次都没被拒），而 `current-worker` 的失败走了 `fail()`
 * ⇒ 报工卡上出现了用户截图那行红字「请求失败（HTTP 429）」。
 *
 * ⇒ ① 请求**有界**（单飞 + 最小间隔）；② 失败**不进报工卡**（身份面 401 除外）。
 */
const ALIVE_MIN_INTERVAL_MS = 5000

/** 后台对账失败（**非**身份面）时的屏上措辞：说事实 + 说清**不影响报工**（§31：不摆内部标识、不吓人）。 */
const ALIVE_UNREACHABLE_NOTICE = '与服务器核对没成功（网络不稳）：不影响报工，回到本页会自动再核对'

/**
 * `setTimeout` 能接受的最大延时 = 2^31-1 ms（issue #7251）。
 *
 * 超过它，浏览器 / Node 会把延时**钳成 ~1ms 立即触发**（Node 实测：
 * `TimeoutOverflowWarning ... Timeout duration was set to 1` + `fired after 3 ms`；
 * MDN：`delay > 2147483647ms` 按 1ms 处理）。30 天 = **2,592,000,000 ms** 正落在这一侧。
 */
export const MAX_TIMER_DELAY_MS = 2147483647

/**
 * 把闲置登出延时切成每片 ≤ `MAX_TIMER_DELAY_MS` 的片（issue #7251；纯函数，单测覆盖服务端全区间）。
 *
 * 🔴 **口径不变**：各片之和 = `Math.max(1, minutes) * 60_000`（30 天就是 30 天）。
 * 变的只是**怎么排** —— 旧实现把整个延时一次性塞进 `setTimeout`：
 * 超上限 ⇒ 被平台钳成 ~1ms ⇒ ① 「闲置 30 天登出」从未按 30 天排期（节流分支不重排 ⇒ 之后不再有闲置登出）；
 * ② 每次 `armIdle()` 立刻多打一轮 `current-worker` + `/me`。
 * 新实现按片上链：前 N-1 片到期**只续排**，**最后一片**到期才真的做一次后台对账。
 *
 * @param {number} minutes 服务端下发的 `idle_minutes`（`worker.session.idle-minutes`，可配区间 5~43200）
 * @returns {number[]} 依次入队的分片（毫秒）；每片 ≤ `MAX_TIMER_DELAY_MS`，和 = 总延时
 */
export function idleSlices(minutes) {
  let left = Math.max(1, minutes) * 60_000
  const slices = []
  while (left > 0) {
    const slice = Math.min(left, MAX_TIMER_DELAY_MS)
    slices.push(slice)
    left -= slice
  }
  return slices
}

export function createApp({ doc, api, location = globalThis.location, storage = null }) {
  const href = typeof location === 'string' ? location : location?.href ?? ''
  // 企业编码（issue #6564）：短链 302 的 `?tenant_code=` 只是**初值**（预填进输入框，可编辑）
  const urlEnterpriseCode = enterpriseCodeFromLocation(href)
  const root = doc.getElementById('worker-h5-root')
  // 打印窗口的宿主（`createApp` 只拿到 doc；`defaultView` 是同一份 window，jsdom 也有）
  const win = doc.defaultView ?? globalThis
  let state = { ...initialState(), enterpriseCode: urlEnterpriseCode ?? '' }
  let idleTimer = null
  let aliveInFlight = false // 单飞：同一时刻最多一个对账在飞
  let lastAliveAt = 0 // 节流：两次对账的最小间隔（毫秒）

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
  const gotoPinnedHome = () => applyDeviceHome({ location, storage, navigate: true })

  /** 上次提交没收到答复 ⇒ 明说「重扫是安全的」（工人据此才敢再点一次）。 */
  const resumedNotice = (token) =>
    resumedRequestId(token)
      ? '上次提交没收到结果：点【完成】会按同一次提交处理（系统不会重复计件）'
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

  /**
   * 页头入口在屏顶、表单在「问题记录」卡里（issue #7973 版式：本次动作 → 记录 → 报工动作）⇒
   * 点开后把表单带进视野：否则工人点了【质检】/【报返工】只看到页面重画一下，表单其实在折叠线下方。
   * 替身 doc（node --test）没有 `scrollIntoView` ⇒ 可选调用 + try/catch，一律静默跳过。
   */
  const revealForm = (id) => {
    try { doc.getElementById(id)?.scrollIntoView?.({ block: 'center' }) } catch { /* 忽略 */ }
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

  // ══════════════════════════════════════════════════════════════════════════════
  // 质检（issue #7162）：扫水洗唛后读这一件的最新判定 / 录判定（生成质检单）。
  //
  // 🔴 只在 `inspect` ∈ 页面集时读 —— 但**真正**的准入在服务端 `/api/worker/quality/**`
  //    （工人档案里没开这一页 ⇒ 403）。这里少渲染一块，不等于挡住了接口。
  // ══════════════════════════════════════════════════════════════════════════════
  const qualityItemId = () => state.view?.position?.order_item_id ?? null
  /** 件键（issue #7973）：套号 × 部位 —— 读面返回时必须仍是**这一件**，否则丢弃（多套同部位会串）。 */
  const qualityPieceKey = () => `${qualityItemId() ?? ''}|${state.view?.set_no ?? ''}`

  async function loadQuality() {
    const itemId = qualityItemId()
    if (!itemId) return
    if (!effectivePages(state).opened.has(PAGE_INSPECT)) return
    const pieceKey = qualityPieceKey()
    dispatch({ type: 'qualityLoading' })
    try {
      // 件键随读面带上（issue #7945 / #7973）：只按部位行取最新会把 A 樘的判定画到 B 樘上
      const d = await api.qualityLatest(itemId, state.view?.set_no ?? null)
      // 读回来时屏已经换了一件 / 一套 ⇒ 丢弃（避免把上一件的判定画到这一件上）
      if (qualityItemId() !== itemId || qualityPieceKey() !== pieceKey) return
      dispatch({ type: 'qualityLoaded', latest: d.latest, records: d.records })
    } catch (e) {
      dispatch({ type: 'qualityFailed', error: e?.message ?? String(e) })
    }
  }

  async function submitQuality() {
    const form = state.qualityForm
    const itemId = qualityItemId()
    if (!form || !itemId) return
    // 原因由**提交那一刻**从 DOM 读（不在 input 事件里重绘，否则每敲一个字就丢焦点）
    const reason = (doc.getElementById('wh5-quality-reason')?.value ?? '').trim()
    // 🔴 工人端只有一个判定 = 返工（issue #7749：合格是默认态，屏上不给这个动作）
    //    ⇒ 说明必填；这里先拦一次只为不白跑网络，服务端 422 才是真判据。
    if (!reason) {
      dispatch({ type: 'qualityFormError', error: '记返工要写明问题（例如：布面污渍 / 尺寸偏差 / 缝线开裂）。' })
      return
    }
    dispatch({ type: 'qualitySubmitting' })
    try {
      const latest = await api.createQuality({
        orderItemId: itemId,
        result: 'rework',
        reason,
        // 件键（issue #7945）：套号 × 部位；本屏扫码已定位到这一件，套号随判定一起提交
        setNo: state.view?.set_no ?? null,
        // 复检回路（issue #7973）：从「待复检」点的【复检仍有问题】= 新的一轮判定（服务端放行）
        recheck: form.recheck === true,
      })
      dispatch({ type: 'qualitySubmitted', latest, notice: '质检已登记' })
      // 追加成功 ⇒ 重新读一次记录（列表是服务端口径，不在前端拼接第二条真值）
      void loadQuality()
    } catch (e) {
      // 服务端下发的业务文案原样显示（不把 HTTP 状态码当工人文案）
      dispatch({ type: 'qualityFormError', error: e?.message ?? String(e) })
    }
  }

  /**
   * 复检通过（issue #7973）：`pass` 是一次新判定（关闭「待复检」）—— 沿用同一个写端点，不新开端点。
   *
   * 用户 2026-10-25 的「默认合格、不摆合格按钮」**不变**：这个动作只在**已有做工返工记录**时出现，
   * 不是每件都要点一次「合格」（ISO 9001 §8.7.1.4：返工后放行前必须再检验）。
   */
  async function recheckQualityPass() {
    const itemId = qualityItemId()
    if (!itemId || state.quality?.rechecking) return
    dispatch({ type: 'qualityRecheckStart' })
    try {
      const latest = await api.createQuality({
        orderItemId: itemId,
        result: 'pass',
        setNo: state.view?.set_no ?? null,
      })
      dispatch({ type: 'qualitySubmitted', latest, notice: '复检通过：本件回到「正常」' })
      void loadQuality()
    } catch (e) {
      dispatch({ type: 'qualityRecheckFailed', error: e?.message ?? String(e) })
    }
  }

  // ══════════════════════════════════════════════════════════════════════════════
  // 报返工（issue #7860）：任一工序工人都能报 —— 身份只由 `X-Worker-Session-Id` 解。
  //
  // 服务端把「这件的这道活、本人最近一笔 normal 报工」改记为 rework（回退 done_qty / done_at /
  // 加工单完成态，计件归零）并生成返工单；本函数只负责读说明、发一次请求、把回执画上屏。
  // ══════════════════════════════════════════════════════════════════════════════
  async function submitRework() {
    const form = state.reworkForm
    const token = state.view?.__token
    if (!form || !token) return
    // 说明在**提交那一刻**从 DOM 读（不在 input 事件里重绘，否则每敲一个字就丢焦点）
    const reason = (doc.getElementById('wh5-rework-reason')?.value ?? '').trim()
    if (!reason) {
      dispatch({ type: 'reworkFormError', error: '报返工要写明问题（例如：布面污渍 / 尺寸偏差 / 缝线开裂）。' })
      return
    }
    dispatch({ type: 'reworkSubmitting' })
    try {
      await api.reportRework({ token, reason })
      // 进度被服务端退回了 ⇒ 用同一张码重解析一次，屏上回到真实读数（**记录也随之刷新**）。
      // 读失败**不影响**返工已成立（写面已返回成功）—— 保持原屏，只少一次刷新。
      let view = state.view
      try {
        const fresh = await api.resolveScan({ token })
        view = { ...fresh, __token: token }
      } catch {
        view = state.view
      }
      // 单号不再由 notice 重复念（记录卡里已有；§31 P2）
      dispatch({ type: 'reworkSubmitted', view, notice: '返工已登记' })
    } catch (e) {
      // 服务端下发的业务文案原样显示（不把 HTTP 状态码当工人文案）
      dispatch({ type: 'reworkFormError', error: e?.message ?? String(e) })
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
  function armIdle(minutesArg) {
    if (idleTimer) clearTimeout(idleTimer)
    const minutes = minutesArg ?? state.worker?.idleMinutes ?? DEFAULT_WORKER_IDLE_MINUTES
    // 🔴 分片排队（issue #7251）：旧实现是**单次** `setTimeout(30 天)`，而 2,592,000,000 ms
    //    超过 2^31-1 ⇒ 平台把延时钳成 ~1ms **立即触发** ⇒ 30 天排期从未生效、且每次装配多打一轮对账。
    //    现在只有**最后一片**到期才 `checkAlive()`；前几片只续排（首片到期 ≠ 闲置到期）。
    const slices = idleSlices(minutes)
    const schedule = (i) => {
      idleTimer = setTimeout(() => {
        if (i + 1 < slices.length) schedule(i + 1)
        else void checkAlive()
      }, slices[i])
    }
    schedule(0)
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

  /**
   * 与**服务端**对一次账（`current-worker` + `/me`）。挂在 `visibilitychange` 与闲置定时器上。
   *
   * 🔴 ① **有界**（issue #6642 线上实测）：一次可见性事件风暴会把「一事件一轮」放大成
   * 15–23 req/s（同一条 session 4 秒 92 个请求）⇒ 单飞 + `ALIVE_MIN_INTERVAL_MS` 节流，
   * 把风暴塌缩成有界请求。**不依赖"先查清事件从哪来"**才能止血。
   *
   * 🔴 ② **失败不进报工卡**：对账是**后台**动作（工人没点任何东西）⇒ 它的失败（429 / 5xx / 断网）
   * 不得占用报工卡的错误位，只给一句"不影响报工"的提示。唯一例外 = **401 / 会话过期**：
   * 那是身份面的事，仍走 `fail()` 回落未登录（绝不静默按上一个人继续记账）。
   */
  async function checkAlive() {
    if (!api.sessionId()) return
    if (aliveInFlight) return
    const now = Date.now()
    if (now - lastAliveAt < ALIVE_MIN_INTERVAL_MS) return
    aliveInFlight = true
    lastAliveAt = now
    try {
      const w = await api.currentWorker()
      dispatch({ type: 'worker', worker: { workerName: w.workerName, workerNo: w.workerNo } })
      await refreshPages() // 页面开关可能被商家在中途改过 ⇒ 每次对账顺带刷新（换人换权限）
      armIdle()
      // 上一轮失败留下的提示：这一轮通了 ⇒ 撤掉（不留常驻噪音）
      if (state.notice === ALIVE_UNREACHABLE_NOTICE) dispatch({ type: 'notice', notice: null })
    } catch (e) {
      if (e?.code === SESSION_EXPIRED) {
        fail(e)
        return
      }
      dispatch({ type: 'notice', notice: ALIVE_UNREACHABLE_NOTICE })
    } finally {
      aliveInFlight = false
    }
  }

  function bind() {
    const on = (id, fn) => {
      const el = doc.getElementById(id)
      if (el) el.addEventListener('click', fn)
    }

    // 入库标签打印（issue #7845）：数据 = 服务端回执里的 `finished_inbound.label`
    on('wh5-fi-print', printWashLabel)

    on('wh5-login', async () => {
      const workerNo = doc.getElementById('wh5-worker-no')?.value?.trim()
      const pin = doc.getElementById('wh5-pin')?.value ?? ''
      // 企业编码：以输入框为准（URL 值已在首屏预填进去，可编辑）—— 租户只由服务端解析
      // 🔴 提交前**归一为小写**（issue #6738 要求 1）：用户照屏把编码抄成大写是常见手误；
      //    只归一（小写 + 去空白），**不**重定义格式（字符集仍由服务端裁定）。
      const enterpriseCode = normalizeEnterpriseCode(doc.getElementById('wh5-enterprise-code')?.value)
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
      // 换人 ⇒ 上一班手输的批次**不带走**（批次归属涉钱：绝不能把 A 的批次留给 B 报工）
      state = { ...state, worker: null, mode: 'login', batchNo: null, notice: '请登录要切换到的工人（扫码结果已保留）' }
      draw()
    })

    // 🔴 issue #7845：`wh5-scan`（手输短码 + 确定）与 `wh5-rescan`（底部重扫）已撤 ——
    //    用户 2026-10-26 逐字「底部的重扫按钮先移除，当前点击跳转后是手输短码，这个功能不需要，没什么用」。
    //    入口只剩「扫纸上的二维码」：扫一次 = 一次新的页面落地（`?t=`），页内不再需要重扫按钮。

    // 质检（issue #7162 / #7749）：展开返工表单 / 取消 / 提交（说明在提交时从 DOM 读）。
    // 🔴 已无「判定单选」：工人端唯一的判定就是返工（合格是默认态，不点即合格）。
    // 报返工（issue #7860）：展开表单 / 取消 / 提交
    on('wh5-rework-action', () => { dispatch({ type: 'reworkFormOpen' }); revealForm('wh5-rework-form') })
    on('wh5-rework-cancel', () => dispatch({ type: 'reworkFormClose' }))
    on('wh5-rework-submit', () => { void submitRework() })

    // 顶部菜单「质检」= 判定入口（2026-10-27 改判 issue #7945）：点开当前扫码件的做工判定面板；
    // 首次点开时补读一次最新判定（不靠「进页面就全量拉」）。
    on('wh5-quality-entry', () => {
      dispatch({ type: 'qualityFormOpen' })
      revealForm('wh5-quality-form')
      if (!state.quality?.latest) void loadQuality()
    })
    // 待复检（issue #7973）：通过 = 关闭；仍有问题 = 新的一轮判定（表单带 recheck）
    on('wh5-quality-recheck-pass', () => { void recheckQualityPass() })
    on('wh5-quality-recheck-open', () => { dispatch({ type: 'qualityFormOpen', recheck: true }); revealForm('wh5-quality-form') })
    on('wh5-quality-cancel', () => dispatch({ type: 'qualityFormClose' }))
    on('wh5-quality-submit', () => { void submitQuality() })

    // 报工三态（issue #5652 第二刀）：选择只落在 `state.view.work_type`（纯状态动作、**不发请求**）。
    // 🔴 放在 in-flight 闸**之前**：正在提交时也能改选 —— 那一笔的 `workType` 在点【报工】那一刻
    //    就已取值（下面的条件）⇒ 改选只影响**下一笔**，不会把这一笔改掉。
    const dispatchWorkType = (raw) => {
      if (normalizeWorkType(raw) === normalizeWorkType(state.view?.work_type)) return // 已选中 ⇒ no-op（不无谓重绘）
      dispatch({ type: 'workType', workType: raw })
    }

    // 返回 Promise（不是 void）⇒ 测试/调用方 `await fire(...)` 能等到这一次提交**有结论**；
    // 浏览器里事件的返回值没有副作用（既有行为不变）。
    on('wh5-report', () => submitReport(false))

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
    // 报工三态选择器（issue #5652 第二刀）：点一下就换选（纯状态、不发任何请求）。
    // 形态与上面的工序选择器同一把（`data-*` 委派 + `is-on` 标记当前选中）。
    for (const el of doc.querySelectorAll('[data-work-type]')) {
      el.addEventListener('click', () => dispatchWorkType(el.dataset.workType))
    }

    // ── 裁剪报工：确认批次（issue #7647）──
    // 🔴 **不整页重渲染**：每敲一个字就 `draw()` 会重建输入框 ⇒ 焦点丢失、光标跳走
    //    （现场表现为「批次号打不进字」）。⇒ `input` 事件只做两件事：把值记进状态 + **就地**同步
    //    报工按钮的禁用态与门禁提示（元素句柄不变，输入框保持可用）。
    const syncBatchGate = () => {
      const blocked = batchBlocked(state, state.view)
      const report = doc.getElementById('wh5-report')
      if (report && report.disabled !== blocked) report.disabled = blocked
      const hint = doc.getElementById('wh5-batch-hint')
      if (hint) hint.textContent = blocked ? BATCH_GATE_HINT : ''
    }
    const batchInput = doc.getElementById('wh5-batch-input')
    if (batchInput) {
      batchInput.addEventListener('input', () => {
        state = reduce(state, { type: 'batch', batchNo: String(batchInput.value ?? '') })
        syncBatchGate()
      })
    }
    // 候选批次（服务端下发的本次可用批次 + 本批余量）：点一下就填入，同样不重绘。
    for (const el of doc.querySelectorAll('[data-batch-no]')) {
      el.addEventListener('click', () => {
        const no = el.dataset.batchNo ?? ''
        state = reduce(state, { type: 'batch', batchNo: no })
        const input = doc.getElementById('wh5-batch-input')
        if (input) input.value = no
        syncBatchGate()
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
      void loadQuality()
    } catch (e) {
      fail(e)
    }
  }

  /**
   * 报工（唯一的记账动作）—— 手动点【报工】与**扫码自动报工**（issue #7845）走同一段。
   *
   * <p>用户 2026-10-26 逐字：「现在还是不能扫码直接报工」。自动报的**准入**不在本函数里：
   * 判据 = {@link autoReportable}（纯函数，`render.mjs`），只在「这道活由工人档案唯一确定、
   * 批次已可用、不是质检工序」时为真 ⇒ 本函数只负责把这一次提交做完。</p>
   *
   * @param {boolean} auto true = 扫到码后自动提交（屏上不出按钮，结论写「已自动报工」）
   */
  async function submitReport(auto = false) {
    const v = state.view
    if (!v?.operation?.operation_id) return
    // 🔴 报工三态（issue #5652 第二刀）**在这一点取值**：闭词表归一（缺省/非法 = 正常）。
    //    取值早于 await / 重绘 ⇒ 这一笔送出的就是工人**按下时**看到的那个选择。
    const workType = normalizeWorkType(v.work_type)
    // 🔴 in-flight 闸（issue #6667 第 4 条，**涉计件正确性**）：车间里戴手套、弱网下答复要等几秒
    //    ⇒ 没有闸就会被连点。抄机台页那一把（machine-app.mjs::reportWork 的 `if (state.reporting) return`）。
    //    叠在既有幂等键之上：键保证「服务端只算一次」，闸保证「客户端只发一次」——两道都要。
    if (state.reporting) return
    // 🔴 裁剪批次门禁（issue #7647）：要批次却没填 ⇒ **一个请求都不发**（服务端也有硬闸，但先拦一次
    //    免得工人干等一个注定 422 的答复）。非裁剪工序 `batchBlocked` 恒 false ⇒ 这段是 no-op。
    if (batchBlocked(state, state.view)) {
      dispatch({ type: 'error', error: BATCH_GATE_HINT })
      return
    }
    // 这一笔的批次在**按下那一刻**取值（早于 await / 重绘 ⇒ 送出的就是工人看到的那个值）。
    // 非裁剪工序 ⇒ `''` ⇒ api 侧不写 `batch_no` 键（请求体与改前逐字节相同）。
    const batchNo = currentBatchNo(state, state.view)
    // 🔴 幂等键**同一屏复用**（重试 = 服务端回放首次结果，绝不重复计件）；成功换屏 ⇒ 换新键。
    // 刻意**不**每次点击都新造一个：那样「第一次其实成功了、响应丢了，工人再点一次」= 第二笔报工。
    // 🔴 跨刷新（#4814）：屏上的键随刷新消失 ⇒ 补第二条通道 —— 上次**没收到服务端答复**的那一次
    //    提交已落盘，同一工人 + 同一张码 ⇒ 复用同一个键（服务端回放，不会二次记账）。
    const clientRequestId = v.__requestId ?? resumedRequestId(v.__token) ?? newRequestId()
    state = { ...state, view: { ...v, __requestId: clientRequestId } }
    dispatch({ type: 'reportStart' }) // 置 in-flight 闸 + 重绘（按钮变 `disabled` + 「提交中…」）
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
        // 报工三态（issue #5652 第二刀）：**正常 = 一个字节都不送**（`undefined` ⇒ api 侧不写
        // `work_type` 键 ⇒ 与改前的请求体**逐字节相同**，既有 7 条硬约束一条不放宽）。
        // 非正常 ⇒ 送闭词表里的值。
        workType: workType === DEFAULT_WORK_TYPE ? undefined : workType,
        // 🔴 数量诚实（本单要点）：服务端 `qualified_qty` 缺省 = `qty` ⇒ 只送 `work_type`
        // 会把**报废**那笔记成**满额合格**。非「正常」一律显式 `qualified_qty: 0`
        // （不猜数量：`qty` 仍缺省 ⇒ 服务端照旧按「剩余应做」推进进度，"这次做了多少"不由前端编）。
        qualifiedQty: workType === DEFAULT_WORK_TYPE ? undefined : 0,
        batchNo,
        clientRequestId,
      })
      // 服务端已答复（首次成功或回放）⇒ 这一笔有结论：下一笔必须换新键
      clearPending()
      // 回执驱动下一屏：接着做下一道 / 本套完工（`afterComplete` 丢掉 __requestId ⇒ 下一笔换新键）
      dispatch({
        type: 'completed',
        view: afterComplete(state.view, r),
        notice: doneNotice(r, { auto }),
        // 打包工序的成品入库块（issue #7845）：服务端随回执下发 ⇒ 这一屏立刻有「入库单/仓位/标签」
        finishedInbound: r.finishedInbound ?? state.finishedInbound ?? null,
      })
    } catch (e) {
      // 只有「服务端答复过」才算有结论（`err.status` 缺失 = 无 HTTP 响应：断网/超时）
      // ⇒ 传输层失败时**保留**这把键，刷新后重扫仍然回放同一次提交
      if (e?.status !== undefined) clearPending()
      fail(e)
    }
  }

  async function doScan(raw, operationId, selection) {
    const token = parseScanInput(raw, href)
    if (!token) {
      dispatch({ type: 'error', error: '没有识别到码：请用水洗唛上的二维码扫一次' })
      return
    }
    try {
      const view = await api.resolveScan({ token, operationId, selection })
      state = {
        ...state,
        view: { ...view, __token: token, ...(selection ? { __selection: selection } : {}) },
        // issue #7845：这一件**已入库** ⇒ 服务端随视图下发 `finished_inbound`（入库单/仓位/标签/质检）
        // —— 刷新、回退、重复扫同一张码都不丢卡片；没入库 ⇒ null（不沿用上一件）。
        finishedInbound: view.finished_inbound ?? null,
      }
      dispatch({ type: 'resolved', view: state.view, notice: resumedNotice(token) })
      void loadQuality()
      // 🔴 扫码即报工（issue #7845）：准入判据是纯函数（未绑定工序 / 质检工序 / 批次没填 / 旧码 ⇒ 不自动），
      //    这里只负责在准入通过时**提交一次**。`operationId` 非空 = 工人刚手动「一键改」了工序，
      //    那一下不是在扫码领活 ⇒ 不自动提交（让他确认后自己点【报工】）。
      if (!operationId && autoReportable(state, state.view)) void submitReport(true)
    } catch (e) {
      fail(e)
    }
  }

  /** 打印**入库**标签（issue #7845）：新窗口只放标签（`@page 50mm 70mm`），不把报工页印上纸。 */
  function printWashLabel() {
    const w = state.finishedInbound
    if (!w) return
    const popup = win.open('', '_blank', 'width=460,height=620')
    if (!popup) {
      dispatch({ type: 'error', error: '浏览器拦下了打印窗口：允许弹窗后再点一次「打印入库标签」' })
      return
    }
    popup.document.write(washLabelPrintHtml(w))
    popup.document.close()
    popup.focus()
    popup.print()
  }

  const onVisible = () => { if (doc.visibilityState === 'visible') void checkAlive() }
  doc.addEventListener('visibilitychange', onVisible)

  return {
    get state() { return state },
    dispatch,
    /** 手工刷新页面集（`GET /api/worker/me`）：供装配层/测试在会话就绪后显式调用一次。 */
    refreshPages,
    /**
     * **扫一次码（程序化入口）**（issue #7845）：页面里已没有手输框 ⇒ 这里是唯一的扫码动作；
     * URL 落地（{@link scanFromUrl}）与单测都走它 —— 同一条 `doScan`，不是第二份实现。
     */
    scan: (raw) => doScan(raw),
    /**
     * **扫码落地**（issue #6866）：把当前 URL 里带的码解析一次。
     *
     * @returns {Promise<boolean>} 是否解析了（URL 里没有码 ⇒ false，调用方据此什么都不做）
     */
    scanFromUrl: async () => {
      const code = parseScanInput(href, href)
      if (!code) return false
      await doScan(code)
      return true
    },
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
  // 🔴 设备级预设（issue #6635）：本机被钉在裁高页 **且已登录** ⇒ 换页走人
  //    （机台页**没有登录面** ⇒ 未登录就换过去 = 把工人关在门外；`navigate` 这道门就是为此设的）
  const hasSession = Boolean(api.sessionId())
  if (applyDeviceHome({ location: globalThis.location, storage, navigate: hasSession }) === 'cut_calc' && hasSession) return app
  // 首屏：本地有登录态 ⇒ 与**服务端**对一次账再显示（页头必须服务端来源）
  if (api.sessionId()) {
    try {
      const w = await api.currentWorker()
      app.dispatch({ type: 'worker', worker: { workerName: w.workerName, workerNo: w.workerNo } })
      // 页面集随会话就绪一起拉（本单）：读不到 ⇒ 页面按全开跑 + 显式提示（fail-open）
      await app.refreshPages()
      // 🔴 扫码落地（issue #6866）：工人**已登录**（闲置默认 30 天 ⇒ 常态）时扫部位码，
      //    服务端 302 把码放在 `?t=`，而此前只有「登录成功」那一支读它 ⇒ 已登录的工人落在输码空态
      //    （现场读作「扫了还要再输一遍单号」）。
      // 🔴 **只在装载时解析这一次**：不挂 `visibilitychange` / 定时器 —— 那条路是 `checkAlive`
      //    的后台对账面，把解析叠上去就是 #6642 的请求风暴形态（线上实测 15–23 req/s）。
      // 🔴 **只读**：`doScan` → `api.resolveScan`（`GET /production/scan`）；写路（`scan/complete`）
      //    仍只在工人点【完成】时发生（`wh5-report`）。
      // 失败已由 `doScan` 落到既有错误面（服务端点名的原因逐字上屏）⇒ 无需在此另加一层。
      await app.scanFromUrl()
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
