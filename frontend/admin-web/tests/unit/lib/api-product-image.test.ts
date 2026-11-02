// case_ids: MC-136
/**
 * 商品图生成 API（issue #7731）：等待上限由 admin-api 下发的权威值派生，前端不写死。
 *
 * 判据：
 * 1. 浏览器等待上限 = 服务端权威上限 + 传输余量（改 ai-agent 的 `IMAGE_GEN_TIMEOUT` 一处，
 *    经 admin-api `/estimate` 下发后本层跟着走）；
 * 2. 上游未知（0 / null / undefined）⇒ 不设上限 —— 不擅自给一个比供应商更紧的数。
 *
 * 真实请求路径（`generate` 带 timeout）在 `ProductImageAI` 的组件链路里覆盖；本文件只钉纯函数派生，
 * 零网络。
 */
import { describe, it, expect } from 'vitest'
import { imageGenTimeoutMs } from '@/lib/api-product-image'

describe('imageGenTimeoutMs（issue #7731）', () => {
  it('浏览器等待上限 = 服务端权威上限 + 传输余量（改一处，本层跟着走）', () => {
    expect(imageGenTimeoutMs(240_000)).toBe(360_000)
    expect(imageGenTimeoutMs(300_000)).toBe(420_000)
  })

  it('上游未知 ⇒ 不设上限（不擅自给一个比供应商更紧的数）', () => {
    expect(imageGenTimeoutMs(0)).toBeUndefined()
    expect(imageGenTimeoutMs(null)).toBeUndefined()
    expect(imageGenTimeoutMs(undefined)).toBeUndefined()
  })
})
