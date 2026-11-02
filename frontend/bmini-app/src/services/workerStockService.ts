/**
 * 工人端**库存修正**服务（issue #8104）—— 端点与字段面照后端逐字同名，零后端改动。
 *
 * ## 端点真值在后端
 *
 * - `GET  /api/worker/batch-stock/batches`   —— 按批次找（批次号 / 货号 / 缸号 / 入库单号任一段）
 * - `POST /api/worker/batch-stock/correction` —— 提交一次修正（实盘为准）
 *
 * 实现 = `backend/admin-api/src/main/java/com/migao/admin/controller/WorkerBatchStockController.java`
 * （读面回 `WorkerBatchStockViews.BatchPage`，写面回 `WorkerBatchStockViews.Correction`；
 * 两者都是 **snake_case**，端侧不另起一层驼峰映射 —— 多一层转换就多一处会漂的地方）。
 *
 * ## 三条纪律
 *
 * 1. 🔴 **身份只由会话头解**（`workerSessionHeaders()`）：请求体里不带 `worker_id` /
 *    `worker_name` / `tenant_id`（构造式白名单在 `utils/workerStock.ts` 的 `buildCorrectionBody`）；
 * 2. 🔴 **401 单独可分辨**：把 `statusCode` 原样透出，调用页据此引导「去登录工人身份」，
 *    **不**把 401 渲染成「读不到」或「没有批次」（三种事实各有各的出口）；
 * 3. 🔴 **缺值不编造**：服务端给 `null` 的字段原样留在类型里（`?: ... | null`），页面统一显示 `—`。
 */
import { get, post } from '../utils/request'
import { API_BASE_URL } from '../utils/constants'
import { workerSessionHeaders } from '../utils/workerSession'
import type {
  CorrectionBody,
  CorrectionReason,
  CorrectionReceipt,
  StockBatchRow,
} from '../utils/workerStock'
import type { RecognizedFieldCell } from '../utils/workerStockRecognize'

/** 端点字面量（与后端 `@RequestMapping("/api/worker/batch-stock")` 逐字同名）。 */
export const BATCHES_ENDPOINT = '/api/worker/batch-stock/batches'
export const CORRECTION_ENDPOINT = '/api/worker/batch-stock/correction'
/** 拍照识别批次号（issue #8210；返回 ai-agent 的字段表**原样**）。 */
export const RECOGNIZE_ENDPOINT = '/api/worker/batch-stock/recognize'

/** 识别回执（ai-agent 的出口形状原样搬运：端侧只读 `fields[].key/value`）。 */
export interface BatchRecognizeResult {
  targetType?: string
  fields?: RecognizedFieldCell[]
  degraded?: boolean
}

/** 读面回执（行 + 原因闭词表 + 分页）。 */
export interface StockBatchPage {
  items?: StockBatchRow[]
  total?: number
  page?: number
  size?: number
  reasons?: CorrectionReason[]
}

/**
 * 统一响应（沿用 bmini 既有形状：`success` + `data` + `message`）。
 *
 * `statusCode` 必须透出：调用页要能分开「未登录（401）」「读不到（网络 / 5xx）」
 * 与「读到了但没有批次（空态）」三种事实。
 */
export interface WorkerStockResponse<T> {
  success: boolean
  data?: T
  message: string
  offline?: boolean
  statusCode?: number
  code?: string
}

function toResponse<T>(res: any, fallback: string): WorkerStockResponse<T> {
  return {
    success: !!res?.success && res?.data !== undefined,
    data: res?.data,
    message: res?.message || res?.error?.message || fallback,
  }
}

function failure<T>(error: any, fallback: string): WorkerStockResponse<T> {
  return {
    success: false,
    message: error?.data?.error?.message || error?.data?.message || error?.message || fallback,
    offline: !error?.statusCode,
    statusCode: error?.statusCode,
    code: error?.data?.error?.code,
  }
}

/**
 * 按关键词搜批次（空关键词 = 最近入库的批次，工人可直接浏览）。
 *
 * 服务端无工人 session ⇒ 401；调用页据此引导去工人登录页（而不是显示「没有批次」）。
 */
export async function searchStockBatches(keyword: string): Promise<WorkerStockResponse<StockBatchPage>> {
  try {
    const res = await get<any>(BATCHES_ENDPOINT, {
      baseURL: API_BASE_URL,
      headers: workerSessionHeaders(),
      params: { keyword: keyword.trim() },
    })
    return toResponse<StockBatchPage>(res, '搜索批次失败，请重试')
  } catch (error: any) {
    return failure<StockBatchPage>(error, '搜索批次失败，请重试')
  }
}

/**
 * 提交一次修正。
 *
 * 🔴 同一次提交的重发必须复用同一个 `client_request_id`（页面层持有）；换新值 = 新的一次修正。
 */
export async function submitBatchCorrection(
  body: CorrectionBody,
): Promise<WorkerStockResponse<CorrectionReceipt>> {
  try {
    const res = await post<any>(CORRECTION_ENDPOINT, body, {
      baseURL: API_BASE_URL,
      headers: workerSessionHeaders(),
    })
    return toResponse<CorrectionReceipt>(res, '提交修正失败，请重试')
  } catch (error: any) {
    return failure<CorrectionReceipt>(error, '提交修正失败，请重试')
  }
}

/**
 * **拍照识别批次号**（issue #8210）。
 *
 * 上游 = `ImageRecognitionClient` → ai-agent vision（target `batch`）⇒ 回执是**字段表原样**
 * （Java 侧不重建表、不做二次消歧）。端侧按键 `batch_no` 取值，取到后**仍要工人核对**。
 *
 * 🔴 识别不落库、不提交：它是预填，提交永远是人的动作。
 * 🔴 401 单独透出（`statusCode`）：会话失效 ⇒ 页面引导登录，**不**渲染成「没认出来」。
 */
export async function recognizeBatchNo(
  images: string[],
): Promise<WorkerStockResponse<BatchRecognizeResult>> {
  try {
    const res = await post<any>(RECOGNIZE_ENDPOINT, { images }, {
      baseURL: API_BASE_URL,
      headers: workerSessionHeaders(),
    })
    return toResponse<BatchRecognizeResult>(res, '识别批次号失败，请重试')
  } catch (error: any) {
    return failure<BatchRecognizeResult>(error, '识别批次号失败，请重试')
  }
}

export default {
  BATCHES_ENDPOINT,
  CORRECTION_ENDPOINT,
  RECOGNIZE_ENDPOINT,
  searchStockBatches,
  submitBatchCorrection,
  recognizeBatchNo,
}
