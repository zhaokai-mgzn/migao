/**
 * 工人**待发货单**列表服务（issue #7806 P1a）—— 端点与字段面**照后端逐字同名**，零后端改动。
 *
 * ## 端点真值在后端（本文件不"照语义推测"）
 *
 * `GET /api/worker/shipment/orders`
 * —— `backend/admin-api/src/main/java/com/migao/admin/controller/WorkerShipmentController.java` 的
 * `@GetMapping("/orders")`（随 #7764 上线），实现 = `WorkerShipmentReadyService.listReadyOrders`。
 *
 * 它只回「**多套全部完工** + 可发货状态（`confirmed/producing/packed`）+ 作业单已完成」的订单，
 * 行内带收货信息与物流方式 / 公司 ⇒ 端侧**只渲染**，不筛、不排序、不补算套数
 * （端侧再算一遍 = 第二份完工口径，与 H5 `/w/` 的那一份迟早分叉）。
 *
 * ## 三条纪律
 *
 * 1. 🔴 **身份只由会话头解**（`workerSessionHeaders()`）：请求里不带任何 `worker_id` /
 *    `worker_name`（工人面读面同理 —— 身份是责任凭证，不由客户端自称）；
 * 2. 🔴 **401 单独可分辨**：本服务把 `statusCode` 原样透出，调用页据此回落「去登录工人身份」，
 *    **不**把 401 渲染成空态 / 失败态（那是三种不同的事实，见页面注释）；
 * 3. 🔴 **缺值不编造**：服务端给 `null` 的字段原样留在类型里（`?: ... | null`），
 *    由页面统一显示成 `—` —— 本文件**不**补默认值（补 0 / 补「快递」都是编数据）。
 */
import { get } from '../utils/request'
import { API_BASE_URL } from '../utils/constants'
import { workerSessionHeaders } from '../utils/workerSession'

/** 端点字面量（与后端 `@RequestMapping("/api/worker/shipment")` + `@GetMapping("/orders")` 逐字同名）。 */
export const SHIPMENT_ORDERS_ENDPOINT = '/api/worker/shipment/orders'

/**
 * 一行 = 一张全完工待发货单（字段面与 `WorkerShipmentReadyService.rowView` 逐字同名）。
 *
 * ⚠️ 全是**蛇形**键（与后端响应体一致）：本仓其它工人服务也是这个口径，端侧不另起一层
 * 驼峰映射（多一层转换就多一处会漂的地方）。
 */
export interface ReadyShipmentOrder {
  order_id: string
  order_no?: string | null
  status?: string | null
  status_label?: string | null
  created_at?: string | null
  /** 收货信息（建单时采集；缺值 = null，页面显示 `—`） */
  customer_name?: string | null
  customer_phone?: string | null
  customer_address?: string | null
  /** 物流类型：`express` / `logistics`（**内部值不上屏**，页面只用 `logistics_type_label`） */
  logistics_type?: string | null
  /** 物流类型的中文展示名（`快递` / `物流专线`；未采集 ⇒ null，**不猜**） */
  logistics_type_label?: string | null
  logistics_company?: string | null
  /** 套数：服务端给的读数（`completed_sets === total_sets` 才是「全完工」） */
  total_sets?: number | null
  completed_sets?: number | null
  processing_order_no?: string | null
  remark?: string | null
  /** 随货标识（issue #7856，服务端已下发）：帘种，按部位序去重、`/` 连接；缺值 = 发货联该行不印 */
  curtain_types?: string | null
  /** 安装小区（可选附注；缺值 = 该行不印） */
  install_community?: string | null
  /** 安装位置（可选附注；可多行，缺值 = 该行不印） */
  install_rooms?: string | null
}

/** 本次扫描的边界（截断不静默：`truncated=true` 时页面要说明「还有更多单未列出」）。 */
export interface ReadyShipmentOrdersScan {
  limit?: number
  truncated?: boolean
}

/** 列表响应体（`{total, items, scan}`，与后端 `listReadyOrders` 的返回逐字同名）。 */
export interface ReadyShipmentOrdersPage {
  total?: number
  items?: ReadyShipmentOrder[]
  scan?: ReadyShipmentOrdersScan
}

/**
 * 统一响应（沿用 bmini 既有形状：`success` + `data` + `message`，见 `workerShipmentService`）。
 *
 * `statusCode` / `code` / `offline` 三件**必须**透出：调用页要能分开
 * 「未登录（401）」「读不到（网络 / 5xx）」「读到了但没有单（空态）」三种事实。
 */
export interface ShipmentOrdersResponse<T> {
  success: boolean
  data?: T
  message: string
  /** 传输层失败（断网 / 超时）—— 有 HTTP 状态码 = 服务端已答复 */
  offline?: boolean
  statusCode?: number
  code?: string
}

function toResponse<T>(res: any, fallback: string): ShipmentOrdersResponse<T> {
  return {
    success: !!res?.success && res?.data !== undefined,
    data: res?.data,
    message: res?.message || res?.error?.message || fallback,
  }
}

function failure<T>(error: any, fallback: string): ShipmentOrdersResponse<T> {
  return {
    success: false,
    message: error?.data?.error?.message || error?.data?.message || error?.message || fallback,
    offline: !error?.statusCode,
    statusCode: error?.statusCode,
    code: error?.data?.error?.code,
  }
}

/**
 * 读「全完工待发货单」列表（**只读**；没有写入口 —— 本页不发货，发货联打印只读本列表的行字段）。
 *
 * 服务端无工人 session ⇒ 401；调用页据此引导去工人登录页（而不是显示「没有单」）。
 */
export async function listReadyShipmentOrders(): Promise<
  ShipmentOrdersResponse<ReadyShipmentOrdersPage>
> {
  try {
    const res = await get<any>(SHIPMENT_ORDERS_ENDPOINT, {
      baseURL: API_BASE_URL,
      headers: workerSessionHeaders(),
    })
    return toResponse<ReadyShipmentOrdersPage>(res, '读取待发货单失败，请重试')
  } catch (error: any) {
    return failure<ReadyShipmentOrdersPage>(error, '读取待发货单失败，请重试')
  }
}

export default {
  SHIPMENT_ORDERS_ENDPOINT,
  listReadyShipmentOrders,
}
