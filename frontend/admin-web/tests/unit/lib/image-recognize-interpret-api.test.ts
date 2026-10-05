// case_ids: PR-008
/**
 * `imageRecognizeApi.interpret` 的**请求形状**（issue #6367 包 P3，冻结契约）。
 *
 * 为什么不写在组件测试里：组件测试整模块 mock 了 `@/lib/api` ⇒ 端点路径与请求体
 * 不在其覆盖内（同 `production-api.test.ts` 的口径）。这里直连真 `api.ts`，
 * 只把最底层 `@/lib/request` 换成 spy。
 *
 * 判据（会红）：
 * 1. 端点 = `POST /api/admin/image-recognition/interpret`，与 `recognize` 是**两个**端点；
 * 2. `targetType` + `images` 逐字进请求体；
 * 3. `hint` 非空 ⇒ 逐字带上；**空串 / 缺省 ⇒ 该键不出现**（空要求 ≠ 空字符串要求）。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const { mockPost } = vi.hoisted(() => ({ mockPost: vi.fn() }))

vi.mock('@/lib/request', () => ({
  default: { post: (...args: unknown[]) => mockPost(...args) },
}))

import { imageRecognizeApi } from '@/lib/api'

const URL_ONE = 'https://oss.example.com/a.jpg'

/** 请求体（第 2 个实参） */
function bodyOf(callIndex: number): Record<string, unknown> {
  return mockPost.mock.calls[callIndex][1] as Record<string, unknown>
}

describe('imageRecognizeApi.interpret（issue #6367 包 P3 契约）', () => {
  beforeEach(() => {
    mockPost.mockReset().mockResolvedValue({
      data: {
        success: true,
        data: { component: 'page_fill', target_type: 'product', fields: [] },
      },
    })
  })

  it('判据 1：打 POST /api/admin/image-recognition/interpret（不是 recognize 的端点）', async () => {
    await imageRecognizeApi.interpret('product', [URL_ONE])
    expect(mockPost.mock.calls[0][0]).toBe('/api/admin/image-recognition/interpret')

    await imageRecognizeApi.recognize('product', [URL_ONE])
    expect(mockPost.mock.calls[1][0]).toBe('/api/admin/image-recognition')
  })

  it('判据 2：targetType + images 逐字进请求体', async () => {
    await imageRecognizeApi.interpret('product', [URL_ONE, 'https://oss.example.com/b.jpg'])
    expect(bodyOf(0)).toEqual({
      targetType: 'product',
      images: [URL_ONE, 'https://oss.example.com/b.jpg'],
    })
  })

  it('判据 3：空串 / 缺省 hint ⇒ 请求体**没有** hint 键', async () => {
    await imageRecognizeApi.interpret('product', [URL_ONE])
    await imageRecognizeApi.interpret('product', [URL_ONE], '')
    await imageRecognizeApi.interpret('product', [URL_ONE], undefined)

    for (const index of [0, 1, 2]) {
      expect(Object.keys(bodyOf(index))).toEqual(['targetType', 'images'])
      expect('hint' in bodyOf(index)).toBe(false)
    }
  })

  it('判据 3b：非空 hint ⇒ 逐字带上（含前后空格，不改写）', async () => {
    const hint = '客厅雪尼尔，韩褶，遮光'
    await imageRecognizeApi.interpret('product', [URL_ONE], hint)
    expect(bodyOf(0)).toEqual({ targetType: 'product', images: [URL_ONE], hint })

    const padded = ' 客厅用 '
    await imageRecognizeApi.interpret('product', [URL_ONE], padded)
    expect(bodyOf(1).hint).toBe(padded)
  })

  it('响应形状 = ApiResponse<PageFillPlan>（component / target_type / fields 原样透传）', async () => {
    const res = await imageRecognizeApi.interpret('product', [URL_ONE])
    expect(res.data.data.component).toBe('page_fill')
    expect(res.data.data.target_type).toBe('product')
    expect(res.data.data.fields).toEqual([])
  })
})
