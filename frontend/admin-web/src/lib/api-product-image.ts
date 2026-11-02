import request from './request'
import type { ApiResponse } from '@/types'

/**
 * 商品图生成 API（issue #7335；等待上限单一来源 = issue #7731）—— 建品页「AI 生成商品图」。
 *
 * 从 `api.ts` 拆出的原因：`api.ts` 是 loc ratchet 的冻结文件（只许缩短），
 * 本能力的端点与等待上限派生统一住在这里（不再散回冻结文件）。
 *
 * 请求 = 已上传的**样图 URL** + 商品名 + 用途；响应 = 一张**已转存 OSS** 的永久 URL。
 * 🔴 **不落库**：生成结果只进表单预览，提交仍走既有建品保存链路。
 * 🔴 **等待上限不在这里写死**（issue #7731）：真值在 ai-agent 的 `IMAGE_GEN_TIMEOUT`
 * （唯一真正等供应商的一层），经 admin-api 的 `/estimate` 下发；本层只加浏览器侧余量。
 */

/** AI 生成的商品图（`url` = 已转存 OSS 的永久地址；`model` = 实际模型，排障用）。 */
export interface AiProductImageResult {
  url: string
  model: string
}

/** 生成用途（与 admin-api `ProductImageGenerationService.KINDS` 同源）。 */
export type AiProductImageKind = 'main' | 'white' | 'texture' | 'craft' | 'scene'

/** 生图等待上限（毫秒；0 = 暂时取不到）：真值在 ai-agent 的 `IMAGE_GEN_TIMEOUT`（issue #7731）。 */
export interface AiProductImageEstimate {
  estimated_deadline_ms: number
}

/** 浏览器侧余量：在服务端上限之上再等这么多（转存 OSS + 网络抖动）。**不是**生图 deadline。 */
const IMAGE_GEN_CLIENT_MARGIN_MS = 120_000

/** 本页会话只取一次（admin-api 侧另有缓存）；取不到 ⇒ 不设超时（不擅自给一个更紧的数）。 */
let imageGenDeadlineMs: number | null = null

async function ensureImageGenDeadlineMs(): Promise<number | null> {
  if (imageGenDeadlineMs !== null) return imageGenDeadlineMs
  try {
    const res = await request.get<ApiResponse<AiProductImageEstimate>>(
      '/api/admin/products/ai-images/estimate'
    )
    imageGenDeadlineMs = res.data.data?.estimated_deadline_ms ?? 0
  } catch {
    imageGenDeadlineMs = 0
  }
  return imageGenDeadlineMs
}

/** 浏览器等待上限 = 服务端权威上限 + 传输余量；未知 ⇒ undefined（axios 默认 = 不设上限）。 */
export function imageGenTimeoutMs(deadlineMs: number | null | undefined): number | undefined {
  return deadlineMs && deadlineMs > 0 ? deadlineMs + IMAGE_GEN_CLIENT_MARGIN_MS : undefined
}

export const aiProductImageApi = {
  generate: (payload: {
    imageUrl: string
    productName?: string
    kind: AiProductImageKind
    /** 主图构图变体（issue #7782）：0 正面棚拍 / 1 半垂坠 / 2 悬挂近景；其它用途忽略 */
    variant?: number
  }) =>
    ensureImageGenDeadlineMs().then((deadlineMs) =>
      request.post<ApiResponse<AiProductImageResult>>(
        '/api/admin/products/ai-images',
        payload,
        { timeout: imageGenTimeoutMs(deadlineMs) }
      )
    ),
  /** 生图等待上限（毫秒；0 = 未知）—— 面板据此显示「最长约 N 分钟」（issue #7731）。 */
  estimate: async (): Promise<number> => (await ensureImageGenDeadlineMs()) ?? 0,
}
