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
    return { success: false, message: error?.data?.message || error?.message || '加载工序失败，请重试' }
  }
}

/**
 * 报工（一次扫码同时推进工序进度 + 记录个人计件）
 */
export async function reportOperation(
  orderId: string,
  operationId: string,
  payload: ReportPayload,
): Promise<ProductionResponse<ReportResult>> {
  try {
    const res = await post<ProductionResponse<ReportResult>>(
      `/api/admin/production/orders/${encodeURIComponent(orderId)}/operations/${encodeURIComponent(operationId)}/report`,
      payload,
      { baseURL: API_BASE_URL },
    )
    return toResponse(res, '报工失败，请重试')
  } catch (error: any) {
    return { success: false, message: error?.data?.message || error?.message || '报工失败，请重试' }
  }
}

export default { getOrderOperations, reportOperation }
