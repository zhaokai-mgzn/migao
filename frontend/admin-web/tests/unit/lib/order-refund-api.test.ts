/**
 * orderApi.refundOrder 契约测试
 *
 * 后端端点：PUT /api/admin/orders/{id}/refund
 * body 支持 refund_reason（已存在），并将新增 refund_amount（目标契约）。
 */
// case_ids: OR-001, OR-002

import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockPut = vi.fn()

vi.mock('@/lib/request', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: (...args: unknown[]) => mockPut(...args),
    delete: vi.fn(),
  },
}))

import { orderApi } from '@/lib/api'

describe('orderApi.refundOrder', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockPut.mockResolvedValue({ data: { success: true } })
  })

  it('调用 PUT /api/admin/orders/{id}/refund 并发送 refund_reason + refund_amount', async () => {
    await orderApi.refundOrder('order-1', { refundAmount: 120.5, refundReason: '质量问题' })

    expect(mockPut).toHaveBeenCalledWith('/api/admin/orders/order-1/refund', {
      refund_reason: '质量问题',
      refund_amount: 120.5,
    })
  })

  it('未传 refundAmount 时 body 不包含 refund_amount（部分退款/仅原因）', async () => {
    await orderApi.refundOrder('order-2', { refundReason: '协商一致' })

    expect(mockPut).toHaveBeenCalledWith('/api/admin/orders/order-2/refund', {
      refund_reason: '协商一致',
    })
  })

  it('未传参数时仍可调用（body 为最小 payload）', async () => {
    await orderApi.refundOrder('order-3')

    expect(mockPut).toHaveBeenCalledWith('/api/admin/orders/order-3/refund', {
      refund_reason: '',
    })
  })
})
