// case_ids: PG-019
// PG-019（issue #4240 前端半边）：撤销二维码端点的**前端调用面** —— 本单要治的是
// 「后端就绪（#4237/#4202）但零发射点」，页面测试整模块 mock 了 '@/lib/api'，
// 端点的 URL/动词不在其覆盖内 ⇒ 这里单独钉住，防「按钮接了别的方法 / 路径写错」的静默失效。
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockPost = vi.fn()
const mockGet = vi.fn()
vi.mock('@/lib/request', () => ({
  default: {
    post: (...args: unknown[]) => mockPost(...args),
    get: (...args: unknown[]) => mockGet(...args),
  },
}))

import { productionApi } from '@/lib/api'

describe('productionApi 端点路径（issue #4240）', () => {
  beforeEach(() => {
    mockPost.mockReset().mockResolvedValue({ data: { success: true, data: { revoked: true, qr_token: null } } })
    mockGet.mockReset().mockResolvedValue({ data: { success: true, data: {} } })
  })

  it('revokeQrToken 打 POST /api/admin/production/orders/{orderId}/qr-token/revoke', async () => {
    const res = await productionApi.revokeQrToken('order-uuid-1')

    expect(mockPost).toHaveBeenCalledTimes(1)
    // 路径段就是 orderId（生产端点统一按订单 id，不是加工单号）
    expect(mockPost).toHaveBeenCalledWith('/api/admin/production/orders/order-uuid-1/qr-token/revoke')
    // 响应透传：撤销语义 = qr_token 置空 + revoked=true（PG-019 data_checks）
    expect(res.data.data).toEqual({ revoked: true, qr_token: null })
  })

  it('既有同族端点路径不回归（生产端点统一按订单 id）', async () => {
    await productionApi.getOrderOperations('order-uuid-1')
    await productionApi.recordPrint('order-uuid-1')
    await productionApi.instantiate('order-uuid-1')

    expect(mockGet.mock.calls.map((c) => c[0])).toEqual([
      '/api/admin/production/orders/order-uuid-1/operations',
    ])
    expect(mockPost.mock.calls.map((c) => c[0])).toEqual([
      '/api/admin/production/orders/order-uuid-1/print',
      '/api/admin/production/orders/order-uuid-1/instantiate',
    ])
  })
})
