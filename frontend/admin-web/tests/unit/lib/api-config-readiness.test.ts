// case_ids: MC-189
/**
 * 配置就绪度端点的**接口面**守卫（issue #6579）。
 *
 * 为什么单开一个模块、也单开一条判据：`frontend/admin-web/src/lib/api.ts` 有**行数棘轮**
 * （只许缩短，上限已顶满）⇒ 新接口面只能落在 `lib/api-config-readiness.ts`。而「接口面单开」
 * 有个天然风险：**没有任何东西会盯着它到底打哪个地址** —— 地址写错时页面只会一直「读不到」，
 * 判据全绿（三态把 404 读成 `unknown` 是**正确行为**，所以它不会红）。
 *
 * 故这里钉三条**会红**的事实（都是「改一处就红」）：
 * 1. 打的是 `GET /api/admin/config-readiness`（**逐字**，换路径 ⇒ 红）；
 * 2. 不塞任何查询参数（聚合端点按调用方权限**自己**决定给不给跨码步骤；前端塞参数 =
 *    把「谁有权限」变成客户端可伪造的入参）；
 * 3. 响应壳**原样透传**（页面从 `data.data.steps` 取事实；这一层要是「好心」解包或改形，
 *    页面上的 `facts` 就全缺键 ⇒ 七步一起变「读不到」而没有任何断言会红）。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mockGet = vi.fn()

vi.mock('@/lib/request', () => ({
  default: { get: (...args: unknown[]) => mockGet(...args) },
}))

// eslint-disable-next-line import/first -- 必须在上面的 `vi.mock` 之后加载（模块求值即取 mock）
import { configReadinessApi } from '@/lib/api-config-readiness'

describe('判据 1：接口面打的是**那一个**聚合端点（不是别的 config 读面）', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockGet.mockResolvedValue({ data: { success: true, data: { steps: {} } } })
  })

  it('get() 打 `GET /api/admin/config-readiness`，且**不带**任何查询参数', async () => {
    await configReadinessApi.get()

    expect(mockGet).toHaveBeenCalledTimes(1)
    const call = mockGet.mock.calls[0]
    expect(call[0]).toBe('/api/admin/config-readiness')
    // 判别力：多塞一个参数（哪怕 `{}` 这种空壳）也算「客户端在决定读什么」⇒ 红
    expect(call).toHaveLength(1)
  })

  it('响应壳**原样**透传 —— 页面那一层拿到的就是 `{ data: { data: { steps } } }`', async () => {
    const payload = { data: { success: true, data: { steps: { calc: { facts: { source: 'stored' } } } } } }
    mockGet.mockResolvedValue(payload)

    const res = await configReadinessApi.get()

    expect(res).toBe(payload)
  })
})
