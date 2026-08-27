/**
 * 订单退款字段类型契约测试 — 目标契约（后端并行新增 refundAmount/discountAmount/refundAt）
 *
 * - expectTypeOf 为运行时类型断言：字段缺失时测试在运行期失败（红）
 * - 对象字面量测试由 tsc --noEmit 兜底（tsc 阶段红）
 */
// case_ids: OR-001, OR-002

import { describe, it, expect, expectTypeOf } from 'vitest'
import type { Order } from '@/types'
import { BackendToFrontendStatus } from '@/types'

describe('Order 类型退款字段（目标契约）', () => {
  it('Order 接口包含 refundAmount/discountAmount/refundAt 可选字段', () => {
    expectTypeOf<Order>().toHaveProperty('refundAmount').toEqualTypeOf<number | undefined>()
    expectTypeOf<Order>().toHaveProperty('discountAmount').toEqualTypeOf<number | undefined>()
    expectTypeOf<Order>().toHaveProperty('refundAt').toEqualTypeOf<string | undefined>()
  })

  it('BackendToFrontendStatus 使用 producing（后端枚举），不是 processing', () => {
    expect(BackendToFrontendStatus).toHaveProperty('producing')
    expect(BackendToFrontendStatus).not.toHaveProperty('processing')
    expect(BackendToFrontendStatus.producing).toBe('pending_shipment')
  })

  it('可构造含退款字段的 Order 对象（目标契约示例，tsc 校验类型）', () => {
    const order: Order = {
      id: 'o1',
      orderNo: 'MG202600001',
      customerName: '张三',
      customerPhone: '13800000000',
      totalAmount: 1000,
      actualAmount: 900,
      discountAmount: 100,
      refundAmount: 900,
      refundAt: '2026-06-21T10:00:00Z',
      status: 'completed',
      hasProcessing: false,
    }
    expect(order.refundAmount).toBe(900)
    expect(order.refundAt).toBe('2026-06-21T10:00:00Z')
    expect(order.discountAmount).toBe(100)
  })
})
