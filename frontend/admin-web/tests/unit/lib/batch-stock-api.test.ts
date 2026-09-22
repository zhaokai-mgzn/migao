// case_ids: PR-057
import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * 批次账端点 / 生成加工单请求体（V116 / issue #5145 阶段 1，PR-054）。
 *
 * 本文件锚**请求层**（wire-level）：组件层的 `generate([orderId])` 单参调用只是代理，
 * 「不指派 ⇒ 请求体不带 `batches`」的真正落点是这里的 body 构造 —— 空数组也必须落成
 * **不带该键**（阶段 1 的定义特征就是「不指派 ⇒ 行为与今天逐字相同」）。
 */

const mockPost = vi.fn()
const mockGet = vi.fn()

vi.mock('@/lib/request', () => ({
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    patch: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}))

import { batchStockApi, processingOrderApi } from '@/lib/api'

describe('processingOrderApi.generate 请求体（PR-054）', () => {
  beforeEach(() => {
    mockPost.mockReset().mockResolvedValue({ data: { data: [] } })
    mockGet.mockReset().mockResolvedValue({ data: { data: null } })
  })

  it('不指派（不给 batches）⇒ 请求体只有 orderIds，**不含 batches 键**', async () => {
    await processingOrderApi.generate(['order-001'])

    expect(mockPost).toHaveBeenCalledWith('/api/admin/processing-orders/generate', { orderIds: ['order-001'] })
    const body = mockPost.mock.calls[0][1] as Record<string, unknown>
    expect(Object.keys(body)).toEqual(['orderIds'])
  })

  it('显式传空数组（= 不指派）⇒ 同样落成不带 batches 键', async () => {
    await processingOrderApi.generate(['order-001'], [])

    expect(mockPost).toHaveBeenCalledWith('/api/admin/processing-orders/generate', { orderIds: ['order-001'] })
    expect(Object.keys(mockPost.mock.calls[0][1] as Record<string, unknown>)).toEqual(['orderIds'])
  })

  it('指派 ⇒ 请求体带 batches（orderId/itemId/batchNo 逐字透传）', async () => {
    const batches = [{ orderId: 'order-001', itemId: 'item-a', batchNo: 'PC-20260901-0001' }]

    await processingOrderApi.generate(['order-001'], batches)

    expect(mockPost).toHaveBeenCalledWith('/api/admin/processing-orders/generate', {
      orderIds: ['order-001'],
      batches,
    })
  })
})

describe('batchStockApi 只读端点（PR-054）', () => {
  beforeEach(() => {
    mockGet.mockReset().mockResolvedValue({ data: { data: null } })
  })

  it('候选端点按（商品 + SKU + 行米数）取，路径与参数名与后端一致', async () => {
    await batchStockApi.candidates({ productId: 'prod-1', skuId: 11, meters: 2.7 })

    expect(mockGet).toHaveBeenCalledWith('/api/admin/batch-stock/candidates', {
      params: { productId: 'prod-1', skuId: 11, meters: 2.7 },
    })
  })

  it('余量 / 分布 / 对账三个读面各有端点（路径不与入库单批次查询混用）', async () => {
    await batchStockApi.batches({ productId: 'prod-1', onlyAvailable: true })
    await batchStockApi.distribution({ productId: 'prod-1' })
    await batchStockApi.reconcile({ productId: 'prod-1' })

    expect(mockGet.mock.calls.map((c) => c[0])).toEqual([
      '/api/admin/batch-stock/batches',
      '/api/admin/batch-stock/distribution',
      '/api/admin/batch-stock/reconcile',
    ])
  })
})
