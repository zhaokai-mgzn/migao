/**
 * 工人「返工记录」列表服务（issue #7921）—— 端点与字段面**照后端逐字同名**，零后端改动。
 *
 * ## 端点真值在后端（本文件不"照语义推测"）
 *
 * `GET /api/worker/production/rework-orders`
 * —— `backend/admin-api/src/main/java/com/migao/admin/controller/WorkerProductionController.java`
 * 的 `@GetMapping("/rework-orders")`，实现 = `ProductionReworkService.reworkOrders`
 * （与 H5 `/w/rework.html` 同一个端点、同一份服务端聚合，issue #7860）。
 *
 * 一行 = 一张加工单：加工单号 / 订单号 / 返工笔数 / 返工数量 / 最近返工时间 / 提示原因 / 涉及工序
 * ⇒ 端侧**只渲染**，不聚合、不排序、不补算（端侧再算一遍 = 第二份返工口径）。
 *
 * ## 准入（服务端，不是"界面藏起来"）
 *
 * 工人档案的页面集里必须有 `rework` 键（商家面名字「返工记录」）⇒ 未开 = **403**
 * （`WorkerProductionController.requireWorkerPage`）。调用页据此给**可行动**提示
 * （找管理员勾选），**不**把 403 渲染成「没有返工」。
 *
 * ## 三条纪律（与 `workerShipmentOrdersService` 同口径）
 *
 * 1. 🔴 **身份只由会话头解**（`workerSessionHeaders()`）：请求里不带 `worker_id` / `worker_name`；
 * 2. 🔴 **401 / 403 / 网络失败三态可分辨**：调用页各有各的出口（登录 / 找管理员 / 重试），
 *    合成一句就是让工人按错误的下一步动作反复试；
 * 3. 🔴 **缺值不编造**：服务端给 `null` 的字段原样留在类型里，由页面统一显示成 `—`。
 */
import { get } from '../utils/request'
import { API_BASE_URL } from '../utils/constants'
import { workerSessionHeaders } from '../utils/workerSession'

/** 端点字面量（与后端 `@RequestMapping("/api/worker/production")` + `@GetMapping("/rework-orders")` 逐字同名）。 */
export const REWORK_ORDERS_ENDPOINT = '/api/worker/production/rework-orders'

/** 涉及工序（服务端已按工序名合并、数量累加）。 */
export interface WorkerReworkOperation {
  operation_name?: string | null
  logical_name?: string | null
  qty?: number | string | null
  count?: number | null
}

/** 一行 = 一张有返工报工的加工单（全是**蛇形**键，与后端响应体一致）。 */
export interface WorkerReworkOrder {
  processing_order_id?: string | null
  processing_order_no?: string | null
  order_no?: string | null
  /** 加工单状态（内部值不上屏 ⇒ 页面不直接渲染它） */
  processing_status?: string | null
  /** 返工笔数（服务端聚合；缺值 ⇒ 页面不印「0 笔」） */
  rework_count?: number | null
  rework_qty?: number | string | null
  latest_rework_at?: string | null
  latest_reason?: string | null
  operations?: WorkerReworkOperation[] | null
}

/** 响应体：`{orders: [...]}`（与后端 `reworkOrders` 的返回逐字同名）。 */
export interface WorkerReworkOrdersPage {
  orders?: WorkerReworkOrder[]
}

/** 统一响应（沿用 bmini 既有形状；`statusCode` / `offline` 必须透出，见文件头第 2 条）。 */
export interface ReworkOrdersResponse<T> {
  success: boolean
  data?: T
  message: string
  offline?: boolean
  statusCode?: number
  code?: string
}

function toResponse<T>(res: any, fallback: string): ReworkOrdersResponse<T> {
  return {
    success: !!res?.success && res?.data !== undefined,
    data: res?.data,
    message: res?.message || res?.error?.message || fallback,
  }
}

function failure<T>(error: any, fallback: string): ReworkOrdersResponse<T> {
  return {
    success: false,
    message: error?.data?.error?.message || error?.data?.message || error?.message || fallback,
    offline: !error?.statusCode,
    statusCode: error?.statusCode,
    code: error?.data?.error?.code,
  }
}

/**
 * 读「有返工报工的加工单」列表（**只读**；本页没有写入口，报返工在报工页）。
 *
 * 服务端：无工人 session ⇒ 401；档案页面集没有 `rework` ⇒ 403。两者都由调用页分开呈现。
 */
export async function listWorkerReworkOrders(): Promise<
  ReworkOrdersResponse<WorkerReworkOrdersPage>
> {
  try {
    const res = await get<any>(REWORK_ORDERS_ENDPOINT, {
      baseURL: API_BASE_URL,
      headers: workerSessionHeaders(),
    })
    return toResponse<WorkerReworkOrdersPage>(res, '读取返工记录失败，请重试')
  } catch (error: any) {
    return failure<WorkerReworkOrdersPage>(error, '读取返工记录失败，请重试')
  }
}

export default {
  REWORK_ORDERS_ENDPOINT,
  listWorkerReworkOrders,
}
