// case_ids: PG-018, BM-006, DF-017
//
// 工人端 H5 报工页 —— API 客户端（设计 #4716 §2.1 / §3.1~§3.3）。
//
// 四条纪律（每条都有对应断言，见 tests/worker-h5-api.test.mjs）：
//   ① 登录 = **工号 + PIN + 企业编码**（复用 #4733 的 `POST /api/worker/login`），**不依赖微信**（裁定③）；
//      🔴 租户**只由服务端解析**（issue #6564）：body 送 `enterpriseCode`，**不再**送 `tenantId`
//      （前端默认租户曾把租户 25 的工人登录判成租户 1 ⇒ 恒 401）；
//   ② 🔴 身份只由服务端解：报工 body **不含** `worker_id`/`worker_name`，
//      身份载体 = `X-Worker-Session-Id`（前端可被改，工资凭证不能信前端）；
//   ③ 🔴 401 ⇒ **回落未登录 + 清本地缓存**（闲置超时/被切换后**绝不**静默重试或按上一个人记账）；
//   ④ 🔴 **唯一写入口 = `POST /api/worker/production/scan/complete`**（#4792）：它按 `token` 定位部位、
//      由**服务端**推断工序。既有 `/orders/{orderId}/operations/{operationId}/report` 把
//      `orderId` + `operationId` 写进 **URL** ⇒「哪道工序」由**客户端**定、且**不携带码** ⇒
//      防呆④（非本部位码）/ 防呆⑤（工序必须确定）/ 一次事务 / `done_at` 在工人页**全都不生效**。
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

/** `GET /api/worker/me` 读不到（非 401）⇒ 页面按「全开」运行并**显式**提示（见 `readMe`）。 */
export const PAGES_UNREAD = 'PAGES_UNREAD'

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
     * 工号 + PIN + 企业编码登录（腿 A：**主路径**，任何浏览器可用，不依赖微信）。
     *
     * @param {{workerNo: string, pin: string, enterpriseCode?: string}} input 企业编码 = 租户的**唯一**来源（issue #6564）
     */
    async login({ workerNo, pin, enterpriseCode }) {
      const data = await request('/api/worker/login', {
        method: 'POST',
        body: { workerNo, pin, deviceLabel, enterpriseCode },
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
     * 🔴 旧码收口（#4794）：`selection` 是**可选**入参，只在旧码（`granularity:"order"`）
     * 「选完套 + 部位」后带上 ⇒ 服务端据此重新解析出部位级视图（工序仍由**服务端**推断）。
     * 不带 ⇒ 与改前逐字一致（旧码仍是降级形态，新码一个字节都不变）。
     *
     * @returns 一屏数据；旧码 ⇒ `granularity:"order"` + `needs_selection`（**页面必须强制选**）
     */
    async resolveScan({ token, operationId, selection }) {
      const qs = new URLSearchParams({ token })
      if (operationId) qs.set('operation_id', operationId)
      // 🔴 只有「套 + 部位」**两个都选**才带（半截选择不带：服务端仍要求完整选择）
      if (selection?.setId && selection?.orderItemId) {
        qs.set('set_id', selection.setId)
        qs.set('order_item_id', selection.orderItemId)
      }
      return request(`/api/worker/production/scan?${qs.toString()}`)
    },

    /** 页头「当前工人」——**服务端**来源（PAD 共用时前端 state 不可信）。 */
    async currentWorker() {
      const d = await request('/api/worker/production/current-worker')
      return { workerId: d.worker_id, workerNo: d.worker_no, workerName: d.worker_name }
    },

    /**
     * 自助读面（V141，母单 #5161）：`GET /api/worker/me` ⇒ 我是谁 + **本租户给我开了哪几个工人端页面**。
     *
     * 🔴 `pages` 只决定「页面上看不看得见」，**不是**权限码（后端 `WorkerProfileController` 的类注释
     * 有完整理由）：真正的准入仍在服务端（`/api/worker/**`）—— 前端拿不到、也不该拿它当授权。
     *
     * 🔴 读取失败**必须可分辨**（调用方据此 fail-open + 在页面上显式说出来）：这里把所有非 401 失败
     * （5xx / 断网 / 响应形状不对）**统一**抛成 `code = PAGES_UNREAD`，由 `app.mjs::refreshPages()`
     * 转成「按全开运行」+ 显式提示。
     * <p>刻意**不**在这里 fail-open：把「读不到」伪装成「读到了全开」，页面就没法把「这是降级态」
     * 说出来（后端只对**成功**的读面回非空数组 ⇒ 两种情况在此可分）。</p>
     */
    async readMe() {
      try {
        const d = await request('/api/worker/me')
        return {
          workerId: d.worker_id,
          workerName: d.worker_name,
          // `pages` 缺失 / 不是数组 ⇒ **原样**回 `null`（由调用方按 fail-open 处置），这里不补默认值
          pages: Array.isArray(d.pages) ? d.pages : null,
        }
      } catch (e) {
        if (e?.code === SESSION_EXPIRED) throw e // 会话过期是身份面的事，原样上抛（调用方据此回落未登录）
        const err = new Error(e?.message ?? '未能读取页面权限')
        err.code = PAGES_UNREAD
        err.status = e?.status
        throw err
      }
    },

    /**
     * 一体机**裁高读面**（母单 #5161）：扫一次水洗唛 ⇒ 一屏（订单详情 + 逐部位裁剪高度）。
     *
     * 🔴 **只读**：`GET /api/worker/production/cutting-height?token=…` —— 本包**不写机器**
     * （不开串口、不发 Modbus、不写下发；用户 2026-09-29 裁定①）。页面终点 = 大字给出
     * 「请在机器屏输入 X.XXX 米」，由人在机器屏上输入。
     *
     * 计算全在**服务端**（复用 `CuttingHeightConfigService.preview` ⇒ 与商家端配置页预演同一份口径）：
     * 前端只渲染 `base` / `cutting_height` / `rounding` / `hits[]` / `misses[]` / `missing[]`，
     * **不自己算**命中、不猜缺值（缺 ⇒ `null`，页面显示「—」）。
     *
     * @param {string} token 码值（短码 / 裸 token / 整条印刷 URL —— 归一在服务端）
     */
    async readCuttingHeight(token) {
      const qs = new URLSearchParams({ token })
      return request(`/api/worker/production/cutting-height?${qs.toString()}`)
    },

    /**
     * 扫码完成 —— **工人页唯一的写入口**（切片② 的 `POST /api/worker/production/scan/complete`）。
     *
     * 一次事务（明细 + CAS 推进 + `done_at` + 完工判定）+ 未确定工序拒绝记账（422，零写入）
     * + 幂等（同键 ⇒ 回放首次结果，不重复计件）**都在服务端**：前端不做推断、不猜工序、不定数量。
     *
     * 🔴 无 session ⇒ **抛错且一个请求都不发**（fail-closed；未登录不能报工）。
     *
     * @param {object} p
     * @param {string} p.token 码值（新码 ⇒ 套 × 部位由码给出）
     * @param {string} [p.operationId] 一键改：工人显式指定的工序（服务端校验**归属本次扫码部位**，
     *        不属于 ⇒ 422 —— 防呆④ 在服务端，不在前端）
     * @param {object} [p.selection] 旧码收口（#4794）：工人从降级清单里选的 `{setId, orderItemId}`。
     *        **只在旧码路径**由 `render.mjs` 的 `legacySelection()` 给出（新码恒 null ⇒ body 只带
     *        token）。它**不**决定工序：工序仍由服务端推断（防呆⑤）。
     * @param {number} [p.qty] 省略 = 服务端取「剩余应做」（A 模式：做完扫一次 = 完工）
     * @param {string} [p.clientRequestId] 幂等键（**同一次提交必须复用同一个**）
     */
    async completeByScan({ token, operationId, qty, qualifiedQty, workType, selection, clientRequestId } = {}) {
      // 🔴 白名单式构造（**不是**把入参展开）：默认**只带 token** —— 调用方硬塞
      // `unit_price` / `factor` / `worker_id` / 顶层 `setId`/`orderItemId` 也进不去请求体。
      // 历史计件单价在**报工那一刻**由服务端固化（§3.6 W6 红线），前端永远不参与定价。
      if (!session?.sessionId) {
        const err = new Error('尚未登录工人身份，请先用工号 + PIN 登录')
        err.code = SESSION_EXPIRED
        throw err
      }
      const body = { token }
      if (operationId) body.operation_id = operationId
      // 🔴 旧码收口（#4794）：只从**具名的** `selection` 通道取（顶层 setId/orderItemId 仍被忽略）
      if (selection?.setId && selection?.orderItemId) {
        body.set_id = selection.setId
        body.order_item_id = selection.orderItemId
      }
      if (qty !== undefined && qty !== null) body.qty = qty
      if (qualifiedQty !== undefined && qualifiedQty !== null) body.qualified_qty = qualifiedQty
      if (workType) body.work_type = workType
      const data = await request('/api/worker/production/scan/complete', {
        method: 'POST',
        // 刻意**不含** worker_id / worker_name：身份由 X-Worker-Session-Id 解（设计 §3.1）
        body,
        extraHeaders: clientRequestId ? { [CLIENT_REQUEST_ID_HEADER]: clientRequestId } : {},
      })
      return {
        operationId: data.operation_id,
        doneQty: data.done_qty,
        status: data.status,
        orderCompleted: data.order_completed,
        replayed: data.replayed === true,
        // 切片② 追加的「一屏闭环回执」（`ProductionScanCompleteService.enrichNextOperation`）
        setNo: data.set_no,
        position: data.position,
        setProgress: data.set_progress,
        setCompleted: data.set_completed,
        nextOperation: data.next_operation,
      }
    },

    // ════════════════════════════════════════════════════════════════════════════════
    // 发货面（issue #5648）：拍照识别 → 打包 / 发货 / 撤销 → 读实发
    //
    // 🔴 与报工**同一份**客户端、同一套纪律：身份只由 `X-Worker-Session-Id` 解，
    //    body 里**没有** worker_id / worker_name（发货留痕是责任凭证，不能由前端自称）。
    // 🔴 也**没有**商家权限码：这四个端点在 `/api/worker/shipment/**` 上，
    //    准入判据 = 有效工人 session（后端 `WorkerShipmentController` 的类注释有完整理由）。
    // ════════════════════════════════════════════════════════════════════════════════

    /**
     * 拍照识别：图 → 订单行 / 商品标签上的**文字**候选（**不落库、不提交**）。
     *
     * 识别不确定 ⇒ 服务端**不预填**（那一格 `value` 为 null + 给 reason）⇒
     * 页面用 `prefillFromRecognition()` 把它显示成**空框 + 「请手工填写」**，绝不猜。
     *
     * @param {string[]} images 已上传图片的 URL 列表
     */
    async recognizeShipment(images) {
      return request('/api/worker/shipment/recognize', {
        method: 'POST',
        body: { images: [...(images ?? [])] },
      })
    },

    /** 打包：`confirmed|producing → packed`（用户裁定：打包与发货都是工人的动作）。 */
    async packOrder(orderId, clientRequestId) {
      return request(`/api/worker/shipment/orders/${encodeURIComponent(orderId)}/pack`, {
        method: 'POST',
        extraHeaders: clientRequestId ? { [CLIENT_REQUEST_ID_HEADER]: clientRequestId } : {},
      })
    },

    /**
     * 发货：记**实发**明细 + 物流 + 原子流转 `shipped`（一次事务，一个入口）。
     *
     * 🔴 无 session ⇒ **抛错且一个请求都不发**（fail-closed，与报工同口径）。
     * 🔴 body 由 `shipment.mjs` 的 `buildShipBody()` **白名单**构造后传入 ——
     *    本方法不再展开入参（避免调用方硬塞 `worker_id` 之类）。
     */
    async shipOrder(orderId, body, clientRequestId) {
      if (!session?.sessionId) {
        const err = new Error('尚未登录工人身份，请先用工号 + PIN 登录')
        err.code = SESSION_EXPIRED
        throw err
      }
      return request(`/api/worker/shipment/orders/${encodeURIComponent(orderId)}/ship`, {
        method: 'POST',
        body,
        extraHeaders: clientRequestId ? { [CLIENT_REQUEST_ID_HEADER]: clientRequestId } : {},
      })
    },

    /** 撤销打包：`packed → producing`（**必带理由** —— 已打包是涉责任状态，不留痕不给撤）。 */
    async unpackOrder(orderId, reason, clientRequestId) {
      return request(`/api/worker/shipment/orders/${encodeURIComponent(orderId)}/unpack`, {
        method: 'POST',
        body: { reason },
        extraHeaders: clientRequestId ? { [CLIENT_REQUEST_ID_HEADER]: clientRequestId } : {},
      })
    },

    /** 发货读面：状态 + 发货单（照片引用 / 识别留痕 / 撤销留痕）+ **实发套/件/卷**。 */
    async readShipment(orderId) {
      return request(`/api/worker/shipment/orders/${encodeURIComponent(orderId)}`)
    },
  }
}
