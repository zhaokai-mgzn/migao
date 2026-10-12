/**
 * 工人**拍照发货**服务（issue #6761）—— 端点与字段面**照后端逐字同名**，零后端改动。
 *
 * ## 端点真值在后端（本文件不"照语义推测"）
 *
 * | 能力 | 端点（真值） |
 * |---|---|
 * | 拍照识别（target 硬编码 `shipment`；**不落库不提交**） | `POST /api/worker/shipment/recognize` |
 * | 发货（记实发 + 运单号 + 原子流转 `shipped`） | `POST /api/worker/shipment/orders/{orderId}/ship` |
 * | 实发读面（状态 + 发货单 + 套/件/卷汇总） | `GET /api/worker/shipment/orders/{orderId}` |
 *
 * 三个都来自 `backend/admin-api/src/main/java/com/migao/admin/controller/WorkerShipmentController.java`
 * 的 `@RequestMapping("/api/worker/shipment")` + 各 `@PostMapping` / `@GetMapping`
 * （**零后端改动**：本单只做端侧接线）。
 *
 * ## 三条纪律
 *
 * 1. 🔴 身份只由 `X-Worker-Session-Id` 解（`workerSessionHeaders()`）——
 *    `worker_id` / `worker_name` **一个字节都不进 body**（发货留痕是**责任凭证**，
 *    构造式白名单见 `src/utils/inbound/shipment.ts` 的 `buildShipBody`）；
 * 2. 🔴 幂等键 `X-Client-Request-Id`（**与后端 `ClientRequestIdService.HEADER` 逐字同名**）：
 *    随动作生成一把，超时重发**复用同一把** ⇒ 服务端不重复发货；
 * 3. 🔴 照片引用 + 识别留痕**随发货请求**原样提交（识别本身不落库，`recognize` 只读）。
 */
import { get, post } from '../utils/request'
import { API_BASE_URL } from '../utils/constants'
import { workerSessionHeaders } from '../utils/workerSession'
import type {
  ShipBody,
  ShipmentRecognition,
  ShipmentView,
} from '../utils/inbound/shipment'

export {
  SHIPMENT_FIELD_KEYS,
  buildShipBody,
  buildShipmentItem,
  formatShippedTotals,
  prefillFromRecognition,
} from '../utils/inbound/shipment'
export type {
  ShipBody,
  ShipBodyInput,
  ShipmentDraft,
  ShipmentField,
  ShipmentItemBody,
  ShipmentItemInput,
  ShipmentRecognition,
  ShipmentRow,
  ShipmentView,
  ShippedTotals,
  UncertainCell,
} from '../utils/inbound/shipment'

/**
 * 端点字面量（占位符沿用服务端 `@PathVariable` 的写法 `{orderId}`）。
 *
 * 抽成常量对象而不是散在函数里：端点漂移时**一处可见**，测试逐值比对它。
 */
export const SHIPMENT_ENDPOINTS = {
  recognize: '/api/worker/shipment/recognize',
  ship: '/api/worker/shipment/orders/{orderId}/ship',
  detail: '/api/worker/shipment/orders/{orderId}',
} as const

/**
 * 幂等键请求头 —— 逐字等于后端 `ClientRequestIdService.HEADER`。
 *
 * ⚠️ 与拍照入库那条链的 `Idempotency-Key`（`INBOUND_IDEMPOTENCY_HEADER`）**不是同一个头**：
 * 发货端点读的是 `X-Client-Request-Id`（`ProductionController.ship` / `WorkerShipmentController`
 * 都认它），写错 ⇒ 幂等**静默失效**（超时重发会真的发两次货，而两次都返回 200）。
 */
export const SHIPMENT_IDEMPOTENCY_HEADER = 'X-Client-Request-Id'

let requestSeq = 0

/** 生成一次发货动作的幂等键（重试沿用原键；前缀 `shipment-` 便于在服务端台账里一眼看出调用来源）。 */
export function newShipmentRequestId(): string {
  requestSeq += 1
  const nativeUuid = (globalThis as any)?.crypto?.randomUUID
  const suffix =
    typeof nativeUuid === 'function'
      ? nativeUuid.call((globalThis as any).crypto)
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
  return `shipment-${suffix}-${requestSeq}`
}

/** 统一响应（沿用 bmini 既有形状：`success` + `data` + `message`，见 `workerInboundService`） */
export interface ShipmentResponse<T> {
  success: boolean
  data?: T
  message: string
  /** 传输层失败（断网/超时）—— 有 HTTP 状态码 = 服务端已答复 */
  offline?: boolean
  statusCode?: number
  code?: string
}

function toResponse<T>(res: any, fallback: string): ShipmentResponse<T> {
  return {
    success: !!res?.success && res?.data !== undefined,
    data: res?.data,
    message: res?.message || res?.error?.message || fallback,
    code: res?.error?.code,
  }
}

function failure<T>(error: any, fallback: string): ShipmentResponse<T> {
  return {
    success: false,
    message: error?.data?.error?.message || error?.data?.message || error?.message || fallback,
    offline: !error?.statusCode,
    statusCode: error?.statusCode,
    code: error?.data?.error?.code,
  }
}

/**
 * 拍照识别（**不落库、不提交**）：图 URL → 订单号 / 商品名 / 数量 / 宽 / 高 的候选。
 *
 * `target` 由**服务端**硬编码成 `shipment`（`OrderShipmentService.recognize`），
 * 端侧**没有** target 参数 —— 工人面开不出 `product` / `order` 的识别入口。
 */
export async function recognizeShipment(
  images: string[],
): Promise<ShipmentResponse<ShipmentRecognition>> {
  try {
    const res = await post<any>(
      SHIPMENT_ENDPOINTS.recognize,
      { images },
      { baseURL: API_BASE_URL, headers: workerSessionHeaders() },
    )
    return toResponse<ShipmentRecognition>(res, '识别失败，请重试或手工录入')
  } catch (error: any) {
    return failure<ShipmentRecognition>(error, '识别失败，请重试或手工录入')
  }
}

/**
 * **发货**：记实发明细 + 运单号 + 原子流转 `shipped`（一次事务，一个入口）。
 *
 * @param requestId 幂等键；调用方（页面）在**一次发货动作开始时**生成一把，
 *                  并在重试时**复用**它 —— 传空则本次调用内临时生成一把。
 */
export async function postWorkerShipment(
  orderId: string,
  body: ShipBody,
  requestId?: string,
): Promise<ShipmentResponse<Record<string, unknown>>> {
  try {
    const url = SHIPMENT_ENDPOINTS.ship.replace('{orderId}', encodeURIComponent(orderId))
    const res = await post<any>(url, body, {
      baseURL: API_BASE_URL,
      headers: {
        [SHIPMENT_IDEMPOTENCY_HEADER]: requestId || newShipmentRequestId(),
        ...workerSessionHeaders(),
      },
    })
    return toResponse<Record<string, unknown>>(res, '发货失败，请重试')
  } catch (error: any) {
    return failure<Record<string, unknown>>(error, '发货失败，请重试')
  }
}

/** 实发读面：状态 + 发货单（照片引用 / 识别留痕 / 撤销留痕）+ **实发套/件/卷**。 */
export async function readWorkerShipment(
  orderId: string,
): Promise<ShipmentResponse<ShipmentView>> {
  try {
    const url = SHIPMENT_ENDPOINTS.detail.replace('{orderId}', encodeURIComponent(orderId))
    const res = await get<any>(url, { baseURL: API_BASE_URL, headers: workerSessionHeaders() })
    return toResponse<ShipmentView>(res, '读实发明细失败，请重试')
  } catch (error: any) {
    return failure<ShipmentView>(error, '读实发明细失败，请重试')
  }
}

export default {
  SHIPMENT_ENDPOINTS,
  SHIPMENT_IDEMPOTENCY_HEADER,
  newShipmentRequestId,
  recognizeShipment,
  postWorkerShipment,
  readWorkerShipment,
}
