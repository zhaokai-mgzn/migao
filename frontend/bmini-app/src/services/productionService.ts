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

/** 工序实例（契约 1：positions[].operations[]） */
export interface ProductionOperation {
  id: string
  seq: number
  operation: string
  group: string
  unit: string
  qty: number
  unit_price: number
  factor?: number
  is_must_finish: boolean
  is_start_marker: boolean
  status: string
  done_qty: number
}

/** 部位分组（布帘/纱帘/帘头…） */
export interface ProductionPosition {
  position_name: string
  operations: ProductionOperation[]
}

/** 生产进度（契约 1：progress） */
export interface ProductionProgress {
  total: number
  done: number
  percent: number
}

/** GET .../operations 的 data */
export interface OrderOperations {
  order_id: string
  qr_token?: string
  positions: ProductionPosition[]
  progress: ProductionProgress
}

/** 报工请求体（契约 2；work_type: normal 正常 / rework 返工 / scrap 报废） */
export interface ReportPayload {
  worker_id: string
  worker_name: string
  qty: number
  qualified_qty: number
  work_type: 'normal' | 'rework' | 'scrap'
}

/** POST .../report 的 data（契约 2） */
export interface ReportResult {
  operation_id: string
  done_qty: number
  status: string
  order_completed: boolean
  /** 服务端回放标记（issue #4116 §5-1）：true = 本次**没有**新落库（同幂等键重复到达） */
  replayed?: boolean
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
      `/api/admin/production/orders/${encodeURIComponent(orderId)}/operations/${encodeURIComponent(operationId)}/report`,
      payload,
      {
        baseURL: API_BASE_URL,
        headers: { [CLIENT_REQUEST_ID_HEADER]: requestId || newReportRequestId() },
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
 * 拉取加工单工序列表 + 进度（扫码/手输单号后调用）
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

export default { getOrderOperations, getOrderPiecework, reportOperation }
