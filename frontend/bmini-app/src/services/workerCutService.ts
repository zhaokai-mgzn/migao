// case_ids: MC-226
/**
 * 工人端**裁高计算**只读服务（issue #7813 P2b）—— 端点与字段面照后端逐字同名，**零后端改动**。
 *
 * ## 端点真值（不按语义推测）
 *
 * `GET /api/worker/production/cutting-height?token=…`
 * —— `backend/admin-api/src/main/java/com/migao/admin/controller/WorkerProductionController.java`
 * 的 `@GetMapping("/cutting-height")`，实现 = `WorkerCuttingHeightService.read`
 * （计算**逐字复用**商家端 `CuttingHeightConfigService#preview` 的同一份口径）。
 *
 * 与 H5 机台屏 `/w/machine.html` **同一个端点**：本服务只搬读面，不另算。
 *
 * ## 三条纪律（与 `workerReworkService` 同款）
 *
 * 1. 🔴 **只读**：本文件没有任何 POST / 写动作。裁高值的终点是「请在机器屏输入 X.XXX 米」，
 *    下发由人在机器屏上完成（2026-09-29 用户裁定①：本面不写机器）。
 * 2. 🔴 **身份只由会话头解**（`workerSessionHeaders()`）：请求里不带 `worker_id` / `worker_name`。
 * 3. 🔴 **三态可分辨**：401（登录失效）/ 其它失败 / 离线 ⇒ 调用页各有各的出口，
 *    合成一句会让工人按错的下一步动作反复试。
 */
import { get } from '../utils/request'
import { API_BASE_URL } from '../utils/constants'
import { workerSessionHeaders } from '../utils/workerSession'
import type { CutHeightData } from '../utils/workerReadFaces'

/** 端点（与后端 `@RequestMapping("/api/worker/production")` + `@GetMapping("/cutting-height")` 逐字同名）。 */
export const CUT_HEIGHT_ENDPOINT = '/api/worker/production/cutting-height'

/** 统一响应（沿用 bmini 既有形状；`statusCode` / `offline` 必须透出）。 */
export interface CutHeightResponse {
  success: boolean
  data?: CutHeightData
  message: string
  offline?: boolean
  statusCode?: number
}

function toResponse(res: any, fallback: string): CutHeightResponse {
  return {
    success: !!res?.success && res?.data !== undefined,
    data: res?.data,
    message: res?.message || res?.error?.message || fallback,
  }
}

/**
 * 读一屏裁高（**只读**）。
 *
 * 空码**一个请求都不发**（fail-closed：拿空 token 打服务端只会得到一句与现场无关的报错）。
 *
 * @param token 码值（短码 / 裸 token / 整条印刷链接 —— 归一在服务端）
 */
export async function fetchCuttingHeight(token: string): Promise<CutHeightResponse> {
  const code = String(token ?? '').trim()
  if (code === '') {
    return { success: false, message: '请先扫一扫纸上的码，或输入单号' }
  }
  try {
    const res = await get<any>(
      `${CUT_HEIGHT_ENDPOINT}?token=${encodeURIComponent(code)}`,
      { baseURL: API_BASE_URL, headers: workerSessionHeaders() },
    )
    return toResponse(res, '读取裁高失败，请重试')
  } catch (error: any) {
    return {
      success: false,
      message:
        error?.data?.error?.message || error?.data?.message || error?.message || '读取裁高失败，请重试',
      offline: !error?.statusCode,
      statusCode: error?.statusCode,
    }
  }
}

export default { CUT_HEIGHT_ENDPOINT, fetchCuttingHeight }
