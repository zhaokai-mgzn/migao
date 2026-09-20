// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5 报工页 —— API 客户端（设计 #4716 §2.1 / §3.1~§3.3）。
//
// 三条纪律（每条都有对应断言，见 tests/worker-h5-api.test.mjs）：
//   ① 登录 = **工号 + PIN**（复用 #4733 的 `POST /api/worker/login`），**不依赖微信**（裁定③）；
//   ② 🔴 身份只由服务端解：报工 body **不含** `worker_id`/`worker_name`，
//      身份载体 = `X-Worker-Session-Id`（前端可被改，工资凭证不能信前端）；
//   ③ 🔴 401 ⇒ **回落未登录 + 清本地缓存**（闲置超时/被切换后**绝不**静默重试或按上一个人记账）。
//
// 零依赖（不用 axios / 不用 Taro）：同一份 `.mjs` 直接给浏览器 `<script type="module">` 用，
// 也给 `node --test` 用 ⇒ 无需构建步骤（最少代码阶梯：标准库 → 原生特性 → 已装依赖）。

/** 工人 session 的请求头（与后端 `WorkerSessionService.SESSION_HEADER` **逐字同名**）。 */
export const SESSION_HEADER = 'X-Worker-Session-Id'

/** 幂等键请求头（与后端 `ClientRequestIdService.HEADER` 逐字同名）。 */
export const CLIENT_REQUEST_ID_HEADER = 'X-Client-Request-Id'

/** 本地登录态键（设备记住登录；401 时整键清除）。 */
export const STORAGE_KEY = 'migao:worker-h5:session'

/** session 过期/失效的错误码（页面据此回落「未登录」）。 */
export const SESSION_EXPIRED = 'SESSION_EXPIRED'

/** 默认 baseUrl：同源（页面与 API 同在 app.migaozn.com ⇒ 无跨域）。 */
const SAME_ORIGIN = ''

function readStore(storage) {
  try {
    return JSON.parse(storage.getItem(STORAGE_KEY) ?? 'null')
  } catch {
    return null
  }
}

/**
 * 造一个工人端 API 客户端。
 *
 * @param {object} [opts]
 * @param {Function} [opts.fetchImpl] `fetch` 替身（测试注入）
 * @param {object}   [opts.storage]   `localStorage` 替身（测试注入）
 * @param {string}   [opts.baseUrl]   API 前缀（默认同源）
 * @param {string}   [opts.deviceLabel] 设备标签（PAD-车间-01 之类）
 */
export function createApi(opts = {}) {
  const fetchImpl = opts.fetchImpl ?? ((...a) => globalThis.fetch(...a))
  const storage = opts.storage ?? globalThis.localStorage
  const baseUrl = opts.baseUrl ?? SAME_ORIGIN
  const deviceLabel = opts.deviceLabel ?? 'H5'

  let session = readStore(storage)

  const persist = (s) => {
    session = s
    if (s) storage.setItem(STORAGE_KEY, JSON.stringify(s))
    else storage.removeItem(STORAGE_KEY)
  }

  const clear = () => persist(null)

  const headers = (extra = {}) => {
    const h = { 'Content-Type': 'application/json', ...extra }
    if (session?.sessionId) h[SESSION_HEADER] = session.sessionId
    return h
  }

  /**
   * 统一请求 + 统一错误面。
   *
   * 🔴 401 ⇒ 抛 `SESSION_EXPIRED` 并**清本地**（不静默续期、不重试）。
   * 其余失败 ⇒ 带服务端 `error.message` 的普通 Error（页面直接显示给工人）。
   */
  async function request(path, { method = 'GET', body, extraHeaders } = {}) {
    const res = await fetchImpl(`${baseUrl}${path}`, {
      method,
      headers: headers(extraHeaders),
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    let payload = null
    try {
      payload = await res.json()
    } catch {
      payload = null
    }
    if (res.status === 401) {
      clear()
      const err = new Error(payload?.error?.message ?? '登录已失效，请重新用工号 + PIN 登录')
      err.code = SESSION_EXPIRED
      err.status = 401
      throw err
    }
    if (!res.ok || payload?.success === false) {
      const err = new Error(payload?.error?.message ?? `请求失败（HTTP ${res.status}）`)
      err.code = payload?.error?.code ?? 'REQUEST_FAILED'
      err.status = res.status
      throw err
    }
    return payload?.data ?? {}
  }

  return {
    /** 当前本地登录态（未登录 ⇒ null）。 */
    sessionId: () => session?.sessionId ?? null,
    /** 当前工人（**页头必须改用 `currentWorker()` 的服务端结果**，这里只作首屏占位）。 */
    worker: () => session ?? null,

    /**
     * 工号 + PIN 登录（腿 A：**主路径**，任何浏览器可用，不依赖微信）。
     */
    async login({ workerNo, pin, tenantId }) {
      const data = await request('/api/worker/login', {
        method: 'POST',
        body: { workerNo, pin, deviceLabel, tenantId: tenantId ?? undefined },
      })
      const s = {
        sessionId: data.session_id,
        workerId: data.worker_id,
        workerNo: data.worker_no,
        workerName: data.worker_name,
        idleMinutes: data.idle_minutes,
        idleExpiresAt: data.idle_expires_at,
      }
      persist(s)
      return s
    },

    /** 主动登出（幂等；无论服务端结果如何都清本地）。 */
    async logout() {
      const id = session?.sessionId
      try {
        if (id) await request('/api/worker/session/logout', { method: 'POST' })
      } catch {
        // 登出是「清理本地」优先：服务端失败也必须把设备上的登录态清掉
      } finally {
        clear()
      }
    },

    /**
     * 扫码解析 + 工序推断（消费切片① 的 `ProductionScanService`，**不在前端兜底**）。
     *
     * @returns 一屏数据；旧码 ⇒ `granularity:"order"` + `needs_selection`（**页面必须强制选**）
     */
    async resolveScan({ token, operationId }) {
      const qs = new URLSearchParams({ token })
      if (operationId) qs.set('operation_id', operationId)
      return request(`/api/worker/production/scan?${qs.toString()}`)
    },

    /** 页头「当前工人」——**服务端**来源（PAD 共用时前端 state 不可信）。 */
    async currentWorker() {
      const d = await request('/api/worker/production/current-worker')
      return { workerId: d.worker_id, workerNo: d.worker_no, workerName: d.worker_name }
    },

    /**
     * 报工（**身份只来自 session**）。
     *
     * 🔴 无 session ⇒ **抛错且一个请求都不发**（fail-closed；未登录不能报工）。
     */
    async report({ orderId, operationId, qty, qualifiedQty, workType = 'normal', clientRequestId }) {
      // 🔴 白名单式构造（**不是**把入参展开）：body 只认这三个键 ——
      // 调用方硬塞 `unit_price` / `factor` / `worker_id` 也进不去请求体。
      // 历史计件单价在**报工那一刻**由服务端固化（§3.6 W6 红线），前端永远不参与定价。
      if (!session?.sessionId) {
        const err = new Error('尚未登录工人身份，请先用工号 + PIN 登录')
        err.code = SESSION_EXPIRED
        throw err
      }
      const data = await request(
        `/api/worker/production/orders/${encodeURIComponent(orderId)}/operations/${encodeURIComponent(operationId)}/report`,
        {
          method: 'POST',
          // 刻意**不含** worker_id / worker_name：身份由 X-Worker-Session-Id 解（设计 §3.1）
          body: { qty, qualified_qty: qualifiedQty, work_type: workType },
          extraHeaders: clientRequestId ? { [CLIENT_REQUEST_ID_HEADER]: clientRequestId } : {},
        },
      )
      return { operationId: data.operation_id, doneQty: data.done_qty, orderCompleted: data.order_completed }
    },
  }
}
