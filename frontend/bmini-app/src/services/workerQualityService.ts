// case_ids: MC-222
/**
 * 工人端**质检**只读服务（issue #7813 P2b）—— 端点与字段面照后端逐字同名，**零后端改动**。
 *
 * ## 端点真值（不按语义推测）
 *
 * `GET /api/worker/quality/latest?order_item_id=…[&set_no=…]`
 * —— `backend/admin-api/src/main/java/com/migao/admin/controller/WorkerQualityController.java`
 * 的 `@GetMapping("/latest")`（与 H5 `/w/` 报工页的「质检记录（做工）」块**同一个端点**）。
 *
 * 件 = 套号 × 部位（issue #7945 / #7973）：带上 `set_no` 时 `latest` 与 `records[0]` **同源**，
 * 多套同部位不串件。
 *
 * ## 三条纪律
 *
 * 1. 🔴 **只读**：本服务不录判定（`POST /api/worker/quality/inspections` 仍只在 `/w/`，
 *    P2b 的口径 =「一条入口 + 读面复用」）。录判定的写面是否搬进小程序 = P2c 之后另裁。
 * 2. 🔴 **准入在服务端**：工人档案的页面集里没有 `inspect` ⇒ **403**
 *    （`requireInspector`）。调用页据此给可行动提示，**不**把 403 渲染成「没有质检记录」。
 * 3. 🔴 **未登录不发请求**（401 是另一条出口，不能与「没记录」混成一句）。
 */
import { get } from '../utils/request'
import { API_BASE_URL } from '../utils/constants'
import { workerSessionHeaders } from '../utils/workerSession'
import type { QualityRecord } from '../utils/workerReadFaces'

/** 端点（与后端 `@RequestMapping("/api/worker/quality")` + `@GetMapping("/latest")` 逐字同名）。 */
export const QUALITY_LATEST_ENDPOINT = '/api/worker/quality/latest'

/** 读面返回（`latest` = null ⇒ 这一件**没有**判定记录，不是「合格」）。 */
export interface QualityLatestData {
  order_item_id?: string | null
  latest?: QualityRecord | null
  records?: QualityRecord[] | null
}

/** 统一响应（沿用 bmini 既有形状）。 */
export interface QualityResponse {
  success: boolean
  data?: QualityLatestData
  message: string
  offline?: boolean
  statusCode?: number
  code?: string
}

function toResponse(res: any, fallback: string): QualityResponse {
  return {
    success: !!res?.success && res?.data !== undefined,
    data: res?.data,
    message: res?.message || res?.error?.message || fallback,
  }
}

/**
 * 读这一件（套号 × 部位）的最新质检判定 + 记录列表（**只读**）。
 *
 * @param orderItemId 成品帘（水洗唛扫码结果里的 `position.order_item_id`）
 * @param setNo       套号（件键的一半；缺 ⇒ 服务端只能按部位行取，多套同部位会串）
 */
export async function fetchQualityLatest(
  orderItemId: string,
  setNo?: number | string | null,
): Promise<QualityResponse> {
  const itemId = String(orderItemId ?? '').trim()
  if (itemId === '') {
    return { success: false, message: '这次扫码没有指到具体的一件：请重新扫码' }
  }
  const query = [`order_item_id=${encodeURIComponent(itemId)}`]
  const set = setNo === null || setNo === undefined ? '' : String(setNo).trim()
  if (set !== '') query.push(`set_no=${encodeURIComponent(set)}`)
  try {
    const res = await get<any>(
      `${QUALITY_LATEST_ENDPOINT}?${query.join('&')}`,
      { baseURL: API_BASE_URL, headers: workerSessionHeaders() },
    )
    return toResponse(res, '读取质检记录失败，请重试')
  } catch (error: any) {
    return {
      success: false,
      message:
        error?.data?.error?.message || error?.data?.message || error?.message || '读取质检记录失败，请重试',
      offline: !error?.statusCode,
      statusCode: error?.statusCode,
      code: error?.data?.error?.code,
    }
  }
}

export default { QUALITY_LATEST_ENDPOINT, fetchQualityLatest }
