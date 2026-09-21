/**
 * 加工单生产报工服务（issue #3997，M4-G-3）
 *
 * 消费 M4-G-2 冻结契约（字段名不可改）：
 * - GET  /api/admin/production/orders/{orderId}/operations
 * - POST /api/admin/production/orders/{orderId}/operations/{operationId}/report
 *
 * 复用该小程序既有 request 封装（Token/重试/401 处理），不新造网络层。
 */

import { get, post } from '../utils/request'
import { API_BASE_URL } from '../utils/constants'
import { workerSessionHeaders } from '../utils/workerSession'

/** 工序实例（契约 1：positions[].operations[]） */
export interface ProductionOperation {
  id: string
  seq: number
  operation: string
  group: string
  unit: string
  qty: number
  unit_price: number
  // 计件系数（`factor`）**不再下发**（issue #4589）：计件工资 = 数量 × 计件单价，
  // 系数已从算法与读面退场（服务端不再返回该键 ⇒ 声明留着就是过期契约）。
  /**
   * 必完工序（缺这道工序不能打包）—— **读面契约键，保留**：后端读面照旧返回它
   * （`backend/admin-api/src/test/java/com/migao/admin/controller/ProductionControllerTest.java`
   * 断言 `positions[0].operations[*].is_must_finish`），且本仓 bmini 测试夹具仍在构造该键。
   * ⚠️ issue #4961 退场的是商家**写面与渲染点**（工人端从未渲染它），不是读面声明。
   */
  is_must_finish: boolean
  is_start_marker: boolean
  status: string
  done_qty: number
}

/**
 * 部位分组（布帘/纱帘/帘头…）+ **规格可见面**（issue #4347 §3.1）。
 *
 * <p>规格键**全部可选**：服务端在订单行取不到时**一个键都不加**（缺键就缺，不补默认值）——
 * 前端因此必须按「有没有这个键」渲染，不得给缺键编一个默认值显示出来（那就是冒充已知）。</p>
 */
export interface ProductionPosition {
  position_name: string
  /** 行标识（V69 / #4388）：区分**同名**部位 */
  order_item_id?: string | null
  position_kind?: string | null
  /** 宽 / 高（订单行 V63 列；下单页必填） */
  width?: number | string | null
  height?: number | string | null
  /** 工艺规格（逐字取订单行） */
  craft?: string | null
  curtainType?: string | null
  openCount?: number | string | null
  cuttingMode?: string | null
  isShaped?: boolean | null
  fullness?: number | string | null
  /** 用料（算料输出，单一真值 = ai-agent 引擎；Java 侧不重算） */
  fabric_meters?: number | string | null
  processingMeters?: number | string | null
  operations: ProductionOperation[]
}

/** 生产进度（契约 1：progress） */
export interface ProductionProgress {
  total: number
  done: number
  percent: number
}

/**
 * 操作记录一行（issue #4347 §3.2）：**服务端**报工流水。
 *
 * <p>与 `productionOffline.WorkLogEntry`（本机缓存）的区别：这是**全单**流水
 * （含别人报的工序），换设备也在；本机那份只在离线时兜底。</p>
 */
export interface WorkLogRow {
  operation_name: string
  worker_name: string
  qualified_qty: number | string
  work_type?: string | null
  /** 落库时刻（ISO 串）—— 不是业务日期（补报会改业务日期，落库时刻不会） */
  created_at?: string | null
}

/**
 * 发货结果（issue #4483 = 母单 #4347 §二.2，发货下放到工人扫码端）。
 * 后端原子入口：记物流（含发货人）+ 流转 shipped，**一个动作一个入口**。
 */
export interface ShipResult {
  order_id: string
  status: string
}

/** GET .../operations 的 data */
export interface OrderOperations {
  order_id: string
  qr_token?: string
  positions: ProductionPosition[]
  progress: ProductionProgress
  /** 操作记录（服务端报工流水，最近在前）；缺省 = 服务端未提供（按本机兜底渲染） */
  work_logs?: WorkLogRow[]
}

/**
 * 报工请求体（work_type: normal 正常 / rework 返工 / scrap 报废）。
 *
 * <p>🔴 <b>身份不在这里</b>（issue #4733）：`worker_id`/`worker_name` **已从契约移除** ——
 * 报工身份由服务端从工人 session（`X-Worker-Session-Id`）解出，前端传什么都不影响归属。
 * 旧版本传 `worker_id: user?.id`（商家账号 id）是**计件记错人**的根因：工人扫码端今天
 * 走的是商家会话，谁都能改。</p>
 */
export interface ReportPayload {
  qty: number
  qualified_qty: number
  work_type: 'normal' | 'rework' | 'scrap'
}

/** POST .../report 的 data（契约 2 + issue #4733 只加键） */
export interface ReportResult {
  operation_id: string
  done_qty: number
  status: string
  order_completed: boolean
  /** 本笔记到谁头上（**服务端解**，前端只展示） */
  worker_id?: string | null
  worker_name?: string | null
  /** server_session = 服务端解的身份；client_body = 无工人 session 的显式降级（商家侧） */
  identity_source?: 'server_session' | 'client_body'
  /** 服务端回放标记（issue #4116 §5-1）：true = 本次**没有**新落库（同幂等键重复到达） */
  replayed?: boolean
}

/**
 * 扫码解析结果（切片 ① 只读面 → 切片 ② 接线；设计 §2.3 / §2.6 / §3）。
 *
 * <p>与服务端 `ProductionScanService.resolve` 的响应**逐字同源**（商家端 `GET /api/admin/production/scan`
 * 与工人端 `GET /api/worker/production/scan` 是同一份实现 ⇒ 一个类型够用，不新造第二套形状）。</p>
 */
export interface ScanPositionView {
  order_item_id: string
  position_kind?: string | null
  position_name?: string | null
}

/** 一屏上的「这次报哪一道」（切片 ② 的 A 模式：系统推断 + 一键改）。 */
export interface ScanOperationView {
  operation_id: string
  logical_name?: string | null
  position?: string | null
  group_name?: string | null
  unit?: string | null
  /** 应做数量（**不是**剩余：剩余 = qty − 已报，由服务端在缺省时算） */
  qty: number
  /** null = **未定价**（≠ 0 元，issue #4696）：可照常完工，但不产生计件金额 */
  unit_price: number | null
  seq?: number | null
  status?: string | null
  /** inferred = 系统推断的下一道；picked = 工人一键改 */
  determined_by?: 'inferred' | 'picked' | null
  /** true = 本部位已做完，系统换到了**套级**工序（打卷/装袋/发货） */
  rerouted?: boolean
  /** 套级回落时的承载部位（工人知道去哪做） */
  carrier?: ScanPositionView | null
}

/** 一键改的候选（与默认项同一层级） */
export interface ScanAlternativeView {
  operation_id: string
  logical_name?: string | null
  position?: string | null
  seq?: number | null
  qty: number
  unit?: string | null
}

export interface ScanResolveResult {
  /** set_position = 新码（套 × 部位，部位由码给出）；order = 旧码降级（**必须**选套 + 选部位） */
  granularity: 'set_position' | 'order'
  order_id: string
  processing_order_no?: string | null
  set_no?: string | null
  set_index?: number | null
  position?: ScanPositionView | null
  /** 推断出的工序；null = 未确定（无待做 / 本套已完成）⇒ **服务端拒绝记账** */
  operation: ScanOperationView | null
  alternatives: ScanAlternativeView[]
  set_progress?: ProductionProgress | null
  /** null = **未知**（旧码降级判不出是哪一套），不是 false */
  completed?: boolean | null
  completed_at?: string | null
  /** 非空 = 旧码降级，必须由工人补齐（绝不默认取第 1 套） */
  needs_selection: string[]
}

/** POST /scan/complete 的 data：既有报工结果 + 一屏闭环（套号/部位/进度/下一道） */
export interface ScanCompleteResult extends ReportResult {
  set_no?: string | null
  position?: ScanPositionView | null
  rerouted?: boolean
  set_progress?: ProductionProgress | null
  set_completed?: boolean | null
  /** 下一道待做工序；null = 未知（尽力而为：缺它**不影响**本次报工已成功） */
  next_operation?: ScanOperationView | null
}

/**
 * 后端业务响应：success=false 时 message 为可展示文案
 * （兼容 {message} 与 {error:{message}} 两种后端错误形态）
 */
export interface ProductionResponse<T> {
  success: boolean
  data?: T
  message?: string
  error?: { code?: string; message?: string }
  /**
   * **传输层**失败标记（issue #4206）：true = 请求没拿到 HTTP 状态码（断网/超时/DNS）。
   * 调用方据此决定是否进离线补传队列 —— 有状态码的失败是服务端**已经答复**
   * （422 数量超上限 / 404 非本部位 / 409 同键在飞），重发不会变好，且服务端在失败路径上
   * 已释放幂等键（`ClientRequestIdService.discard`）⇒ 换个时机重发会**真的再执行一次**。
   */
  offline?: boolean
}

/**
 * 幂等键（issue #4116 §5-1）：与服务端 `ClientRequestIdService.HEADER` 逐字同名。
 * 同键重复到达时服务端**不再执行**、直接回放首次结果 ⇒ 网络重试不会重复报工。
 */
export const CLIENT_REQUEST_ID_HEADER = 'X-Client-Request-Id'

/**
 * 生成本次报工动作的幂等键（一次**用户动作**一个键；重试沿用原键）。
 * 前缀 `report-` 便于在 `client_request_keys.endpoint` 旁一眼看出调用来源。
 */
export function newReportRequestId(): string {
  const nativeUuid = (globalThis as any)?.crypto?.randomUUID
  const suffix =
    typeof nativeUuid === 'function'
      ? nativeUuid.call((globalThis as any).crypto)
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
  return `report-${suffix}`
}

/**
 * 报工在飞锁（issue #4116 §5-1）——「同一时刻只允许一笔报工在飞」的**单一事实源**。
 *
 * 为什么需要它（以及为什么它是服务端幂等键**挡不住**的那一半）：工人手快连点两次
 * 「完成报工」会并发进入 `handleReport` 两次，各自生成一个**不同的**幂等键 ⇒ 服务端按
 * `(tenant_id, client_request_id)` 去重时两条都算「首执」⇒ 一次报工被记两遍
 * （`done_qty` 翻倍、计件虚高）。客户端必须在**动作层**只放一笔过去。
 *
 * 为什么抽成独立对象而不是页面里一个 `useState`：`<Button disabled>` 在时序上是**异步**的
 * （要等 React 重渲染），而真实连点在毫秒级；且 disabled 只是**可见面**，一旦它被改动
 * （换组件库 / 加 `loading` 态 / 事件重放）锁就静默消失。抽出来后锁可被单测**直接**证明
 * 「第二笔被拒」，不必依赖「disabled 恰好已生效」这种时序巧合 ——
 * 实测：靠 disabled 兜底时，把页面里的锁拔掉、连点断言**照样绿**（假绿）。
 */
export class ReportInFlightLock {
  private inFlight = false

  /** 尝试开始一笔报工：true = 允许（并置为在飞）；false = 已有一笔在飞，本次必须丢弃 */
  tryAcquire(): boolean {
    if (this.inFlight) return false
    this.inFlight = true
    return true
  }

  /** 结束（成功/失败/抛错都必须调，否则锁永久占死、工人再也报不了工） */
  release(): void {
    this.inFlight = false
  }

  isInFlight(): boolean {
    return this.inFlight
  }
}

/** 报工发送签名（在线报工与离线补传**共用同一份**实现 —— 两处各写一份必然漂移） */
export type ReportSender = (
  orderId: string,
  operationId: string,
  payload: ReportPayload,
  requestId?: string,
) => Promise<ProductionResponse<ReportResult>>

/** 报工在飞锁实例（页面级单例：报工页同时只服务一个加工单） */
export const reportInFlightLock = new ReportInFlightLock()

/**
 * 报工（一次扫码同时推进工序进度 + 记录个人计件）
 *
 * 幂等（issue #4116 §5-1）：每次调用生成一个幂等键随请求头发出 ⇒ 工具/网络层重试
 * 同一动作时服务端只真正报工一次（响应带 `replayed:true`，调用方据此不要重复刷新/播报）。
 * **连点**由调用方的 {@link reportInFlightLock} 拦（连点 = 两个不同幂等键，服务端去重挡不住）。
 *
 * @param requestId 本次动作的幂等键（issue #4206）：**调用方生成并在重发时复用同一个键**。
 *   不传则内部生成 —— 离线补传队列必须传（复用入队时的键，否则服务端记两遍）。
 */
export async function reportOperation(
  orderId: string,
  operationId: string,
  payload: ReportPayload,
  requestId?: string,
): Promise<ProductionResponse<ReportResult>> {
  try {
    const res = await post<ProductionResponse<ReportResult>>(
      // 🔴 工人路径（issue #4733）：`/api/worker/**` —— 与 `/api/admin/**` 彻底分离，
      // 工人身份到不了管理后台。身份随 `X-Worker-Session-Id` 走，**不在 body 里**。
      `/api/worker/production/orders/${encodeURIComponent(orderId)}/operations/${encodeURIComponent(operationId)}/report`,
      payload,
      {
        baseURL: API_BASE_URL,
        headers: {
          [CLIENT_REQUEST_ID_HEADER]: requestId || newReportRequestId(),
          ...workerSessionHeaders(),
        },
      },
    )
    return toResponse(res, '报工失败，请重试')
  } catch (error: any) {
    return {
      success: false,
      message: error?.data?.message || error?.message || '报工失败，请重试',
      // 无 HTTP 状态码 = 传输层失败（断网/超时）；有状态码 = 服务端已答复（业务拒绝）
      offline: !error?.statusCode,
    }
  }
}

/**
 * 扫码解析 + 工序推断（**只读**，切片 ① 的实现；切片 ② 在工人端接线）。
 *
 * <p>🔴 新码优先：命中 {@code processing_set_part_tokens} ⇒ 返回（套，部位）+ 系统推断的下一道
 * 待做工序（部位由**码**给出，工人不选）；未命中只**回落**既有四形态（旧码 ⇒
 * {@code granularity="order"} + {@code needs_selection}，**绝不默认取第 1 套**）。</p>
 *
 * <p>工人路径：工人身份随 `X-Worker-Session-Id` 走（`/api/admin/**` 工人到不了）。</p>
 *
 * @param operationId 可选 = 工人「一键改」显式指定（必须属于本次扫码的部位/套，否则 422）
 */
export async function scanResolve(
  token: string,
  operationId?: string,
): Promise<ProductionResponse<ScanResolveResult>> {
  try {
    const query = operationId ? `&operation_id=${encodeURIComponent(operationId)}` : ''
    const res = await get<ProductionResponse<ScanResolveResult>>(
      `/api/worker/production/scan?token=${encodeURIComponent(token)}${query}`,
      { baseURL: API_BASE_URL, headers: workerSessionHeaders() },
    )
    return toResponse(res, '无法识别该二维码，请手动输入单号')
  } catch (error: any) {
    return {
      success: false,
      message: error?.data?.message || error?.message || '无法识别该二维码，请手动输入单号',
      offline: !error?.statusCode,
    }
  }
}

/**
 * 扫码**完成**（A 模式闭环的唯一写入口，切片 ② / 设计 §4 / §5）。
 *
 * <p>「做完扫一次 = 完工」：请求只带码 + 工序（系统推断或一键改），**不带数量**
 * —— 数量缺省由服务端取「剩余应做」（零额外交互）。要改数量请用既有工序列表里的
 * 「完成报工」（同一条记账核，见 `ProductionService.applyReport`）。</p>
 *
 * <p>服务端一次事务做四件事：防呆 → 工序确定性校验（**未确定 ⇒ 拒绝记账**）→ 写报工明细（数量 ×
 * 快照单价 + 价态）→ CAS 推进 `done_qty`/`status` + `done_at`（A 模式完工时刻）→ 必完全绿则加工单完工。
 * 身份由服务端从工人 session 解（body 里传 `worker_id` 无效）。</p>
 *
 * <p>幂等：每次调用生成一个幂等键随请求头发出（重试复用同一个键 ⇒ 服务端不重复计件）；
 * **连点**由调用方的 {@link reportInFlightLock} 拦。</p>
 */
export async function completeByScan(
  token: string,
  operationId: string,
  requestId?: string,
): Promise<ProductionResponse<ScanCompleteResult>> {
  try {
    const res = await post<ProductionResponse<ScanCompleteResult>>(
      '/api/worker/production/scan/complete',
      { token, operation_id: operationId },
      {
        baseURL: API_BASE_URL,
        headers: {
          [CLIENT_REQUEST_ID_HEADER]: requestId || newReportRequestId(),
          ...workerSessionHeaders(),
        },
      },
    )
    return toResponse(res, '报工失败，请重试')
  } catch (error: any) {
    return {
      success: false,
      message: error?.data?.message || error?.message || '报工失败，请重试',
      // 无 HTTP 状态码 = 传输层失败（断网/超时）；有状态码 = 服务端已答复（业务拒绝）
      offline: !error?.statusCode,
    }
  }
}

/** 归一化后端业务响应（HTTP 200 但 success=false 的失败文案要能透出到页面） */
function toResponse<T>(res: ProductionResponse<T> | undefined, fallback: string): ProductionResponse<T> {
  const message = res?.message || res?.error?.message || fallback
  return {
    success: !!res?.success && !!res?.data,
    data: res?.data,
    message,
  }
}

/**
 * 拉取加工单工序列表 + 进度（**工人路径**，扫码/手输单号后调用）。
 *
 * <p>与 {@link getOrderOperations}（商家路径）读的是**同一份服务端读面**
 * （`ProductionService.getOperations`）⇒ 响应形状逐字同源，不新造第二套。</p>
 */
export async function getWorkerOrderOperations(
  orderId: string,
): Promise<ProductionResponse<OrderOperations>> {
  try {
    const res = await get<ProductionResponse<OrderOperations>>(
      `/api/worker/production/orders/${encodeURIComponent(orderId)}/operations`,
      { baseURL: API_BASE_URL, headers: workerSessionHeaders() },
    )
    return toResponse(res, '未找到该加工单，请确认单号')
  } catch (error: any) {
    return {
      success: false,
      message: error?.data?.message || error?.message || '加载工序失败，请重试',
      offline: !error?.statusCode,
    }
  }
}

/**
 * 拉取加工单工序列表 + 进度（**商家路径**；管理后台/既有调用方使用）
 */
export async function getOrderOperations(
  orderId: string,
): Promise<ProductionResponse<OrderOperations>> {
  try {
    const res = await get<ProductionResponse<OrderOperations>>(
      `/api/admin/production/orders/${encodeURIComponent(orderId)}/operations`,
      { baseURL: API_BASE_URL },
    )
    return toResponse(res, '未找到该加工单，请确认单号')
  } catch (error: any) {
    return {
      success: false,
      message: error?.data?.message || error?.message || '加载工序失败，请重试',
      offline: !error?.statusCode,
    }
  }
}

/**
 * 加工单计件汇总（契约 3：GET .../piecework）
 *
 * `{total, per_worker, per_operation}` —— Σ(合格数量 × 单价 × 系数)，**排除返工/报废**
 * （真值源 §4：内部计件与对外加工费两套账分离；计件按报工当时的单价快照）。
 * 页面据此展示「本单累计计件 + 该工序累计计件」（issue #4206 判据 3）。
 */
export interface PieceworkSummary {
  total: number
  per_worker: Record<string, number>
  per_operation: { operation: string; amount: number }[]
}

export async function getOrderPiecework(
  orderId: string,
): Promise<ProductionResponse<PieceworkSummary>> {
  try {
    const res = await get<ProductionResponse<PieceworkSummary>>(
      `/api/admin/production/orders/${encodeURIComponent(orderId)}/piecework`,
      { baseURL: API_BASE_URL },
    )
    return toResponse(res, '计件金额加载失败')
  } catch (error: any) {
    return { success: false, message: error?.data?.message || error?.message || '计件金额加载失败' }
  }
}

/**
 * **发货**（issue #4483 = #4347 §二.2）：录货运单号 ⇒ 订单 shipped（**原子**）。
 *
 * <p>为什么不是两个调用：后端 `PUT /logistics` 只记物流、`PUT /status` 只流转，
 * 分两次调用中间失败就是「有单号但没发货」或「发货了没单号」的静默不一致 ——
 * 故后端提供了原子入口 `POST /production/orders/{id}/ship`，这里只调它一次。</p>
 *
 * <p>承运商可不传：后端会取**既有物流记录**的承运商（工人端只填单号）；
 * 都没有时后端 422 显式报缺（不静默发一个没承运商的货）。</p>
 */
export async function shipOrder(
  orderId: string,
  trackingNo: string,
  logisticsCompany?: string,
): Promise<ProductionResponse<ShipResult>> {
  try {
    const res = await post<ProductionResponse<ShipResult>>(
      `/api/admin/production/orders/${encodeURIComponent(orderId)}/ship`,
      { trackingNo, logisticsCompany },
      { baseURL: API_BASE_URL },
    )
    return toResponse(res, '发货失败，请重试')
  } catch (error: any) {
    return {
      success: false,
      message: error?.data?.message || error?.message || '发货失败，请重试',
      offline: !error?.statusCode,
    }
  }
}

export default { getOrderOperations, getOrderPiecework, reportOperation, shipOrder, scanResolve, completeByScan }
