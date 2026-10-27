/**
 * 工人「我的计件」读面服务（issue #7934）—— 端点与字段面**照后端逐字同名**，零后端改动。
 *
 * ## 端点真值在后端（本文件不"照语义推测"）
 *
 * `GET /api/worker/piecework?month=YYYY-MM`
 * —— `backend/admin-api/src/main/java/com/migao/admin/controller/WorkerPieceworkController.java`，
 * 实现 = `ProductionService.workerPieceworkLedger`（issue #6767 上线；与 H5 `/w/piecework.html`
 * **同一个端点**）。
 *
 * 🔴 **金额没有第二份聚合**：服务端的 `workerPieceworkLedger` 只是
 * `ProductionService.aggregate`（per-order 汇总 / 期间报表 / agent 工人计件共用的**唯一**算法）之上
 * 一层「按当前工人 + 期间」的过滤投影（口径 = docs/design/worker-home-menu.md §6.3）⇒ 端侧**只格式化**，
 * 不求和、不补算、不推算月份边界（`prev_period` / `can_prev` / `next_period` / `can_next` 全由服务端给）。
 *
 * ## 三条纪律（与 `workerReworkService` / `workerShipmentOrdersService` 同口径）
 *
 * 1. 🔴 **身份只由会话头解**（`workerSessionHeaders()`）：请求里**只**有可选 `month`，
 *    **绝不**带 `worker_id` / `worker_name`（涉钱面：工资归属不能由前端自称）；
 * 2. 🔴 **401 / 网络失败可分辨**：调用页据此分开呈现（登录 / 重试），合成一句会让人按错的下一步反复试；
 * 3. 🔴 **缺值不编造**：服务端给 `null` 的字段原样留在类型里，由页面统一显示成 `—`（**绝不**当 0 元）。
 */
import { get } from '../utils/request'
import { API_BASE_URL } from '../utils/constants'
import { workerSessionHeaders } from '../utils/workerSession'

/** 端点字面量（与后端 `@RequestMapping("/api/worker/piecework")` 逐字同名）。 */
export const PIECEWORK_ENDPOINT = '/api/worker/piecework'

/** 逐笔一行 = 「按工序」聚合行（服务端读时派生：逻辑名 + 部位 + 数量 + 金额）。 */
export interface WorkerPieceworkLine {
  logical_name?: string | null
  operation?: string | null
  position?: string | null
  qty?: number | string | null
  amount?: number | string | null
}

/** 未定价的工序（`unit_price IS NULL` 的行 —— **不计入合计**，但必须显式列出）。 */
export interface WorkerPieceworkUnpricedOperation {
  logical_name?: string | null
  operation?: string | null
  qty?: number | string | null
}

/** 服务端 `data`（全是**蛇形**键，与后端响应体一致）。 */
export interface WorkerPieceworkLedger {
  /** 当前工人姓名（只做回显；**不是**身份依据 —— 身份在 `X-Worker-Session-Id` 上） */
  worker_name?: string | null
  /** 期间 `YYYY-MM`（服务端按业务时区算出来的，端侧不做月份算术） */
  period?: string | null
  /** 合计金额（服务端同一份聚合；`null` ⇒ 页面显示 `—`，**绝不**印 0 元） */
  amount_total?: number | string | null
  /** 合格件数合计 */
  qty_total?: number | string | null
  lines?: WorkerPieceworkLine[] | null
  unpriced?: {
    qty?: number | string | null
    operations?: WorkerPieceworkUnpricedOperation[] | null
  } | null
  prev_period?: string | null
  next_period?: string | null
  can_prev?: boolean | null
  can_next?: boolean | null
}

/** 统一响应（沿用 bmini 既有形状；`statusCode` / `offline` 必须透出，见文件头第 2 条）。 */
export interface PieceworkResponse<T> {
  success: boolean
  data?: T
  message: string
  offline?: boolean
  statusCode?: number
  code?: string
}

/** `YYYY-MM` 形态校验（月边界只有服务端会算；这里只挡非月份串，不让 URL / 入参决定口径）。 */
const MONTH_PATTERN = /^\d{4}-\d{2}$/

/** 拼读取路径：只有合法 `YYYY-MM` 才进查询串（缺省 = 服务端按业务当前自然月）。 */
export function pieceworkPath(month?: string): string {
  return month && MONTH_PATTERN.test(month)
    ? `${PIECEWORK_ENDPOINT}?month=${month}`
    : PIECEWORK_ENDPOINT
}

function toResponse<T>(res: any, fallback: string): PieceworkResponse<T> {
  return {
    success: !!res?.success && res?.data !== undefined,
    data: res?.data,
    message: res?.message || res?.error?.message || fallback,
  }
}

function failure<T>(error: any, fallback: string): PieceworkResponse<T> {
  return {
    success: false,
    message: error?.data?.error?.message || error?.data?.message || error?.message || fallback,
    offline: !error?.statusCode,
    statusCode: error?.statusCode,
    code: error?.data?.error?.code,
  }
}

/**
 * 读「我的计件」台账（**只读**；本页没有写入口）。
 *
 * @param month `YYYY-MM`；省略 = 服务端按业务当前自然月
 *
 * 服务端：无工人 session ⇒ 401（页面引导登录）；非法 / 未来月份 ⇒ 422（页面按「读不到」呈现）。
 */
export async function readWorkerPiecework(
  month?: string,
): Promise<PieceworkResponse<WorkerPieceworkLedger>> {
  try {
    const res = await get<any>(pieceworkPath(month), {
      baseURL: API_BASE_URL,
      headers: workerSessionHeaders(),
    })
    return toResponse<WorkerPieceworkLedger>(res, '读取计件失败，请重试')
  } catch (error: any) {
    return failure<WorkerPieceworkLedger>(error, '读取计件失败，请重试')
  }
}

export default {
  PIECEWORK_ENDPOINT,
  pieceworkPath,
  readWorkerPiecework,
}
