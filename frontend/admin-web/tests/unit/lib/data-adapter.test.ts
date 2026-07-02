/**
 * 数据适配层测试 — 前后端数据转换的正确性
 *
 * 覆盖所有 api.ts 中的数据转换逻辑：
 * 1. 订单状态映射 (FrontendToBackendStatus / BackendToFrontendStatus)
 * 2. 商品创建/更新 payload 构建
 * 3. 物流信息 payload 构建
 * 4. 关单 payload 构建
 *
 * 这些转换如果出错，数据会静默损坏——后端收到错误值或前端展示错误状态。
 */
import { describe, it, expect } from 'vitest'
import {
  FrontendToBackendStatus,
  BackendToFrontendStatus,
} from '@/types'
import {
  buildProductPayload,
  buildLogisticsPayload,
  buildCloseOrderPayload,
} from '@/lib/data-adapter'
import type {
  ProductFormData,
  LogisticsFormData,
  CloseOrderParams,
  OrderStatus,
  BackendOrderStatus,
} from '@/types'

// ===================================================================
// 订单状态映射
// ===================================================================

describe('FrontendToBackendStatus', () => {
  it('maps all 6 frontend statuses to backend', () => {
    const expected: Record<OrderStatus, BackendOrderStatus> = {
      pending_payment: 'pending',
      pending_shipment: 'confirmed',
      shipped: 'shipped',
      completed: 'completed',
      closed: 'cancelled',
      refund: 'cancelled',
    }
    expect(FrontendToBackendStatus).toEqual(expected)
  })

  it('has no extra or missing keys', () => {
    const keys = Object.keys(FrontendToBackendStatus).sort()
    expect(keys).toEqual([
      'closed', 'completed', 'pending_payment',
      'pending_shipment', 'refund', 'shipped',
    ])
  })

  it('both "closed" and "refund" map to "cancelled"', () => {
    expect(FrontendToBackendStatus.closed).toBe('cancelled')
    expect(FrontendToBackendStatus.refund).toBe('cancelled')
  })
})

describe('BackendToFrontendStatus', () => {
  it('maps all 6 backend statuses to frontend', () => {
    const expected: Record<BackendOrderStatus, OrderStatus> = {
      pending: 'pending_payment',
      confirmed: 'pending_shipment',
      processing: 'pending_shipment',
      shipped: 'shipped',
      completed: 'completed',
      cancelled: 'closed',
    }
    expect(BackendToFrontendStatus).toEqual(expected)
  })

  it('has no extra or missing keys', () => {
    const keys = Object.keys(BackendToFrontendStatus).sort()
    expect(keys).toEqual([
      'cancelled', 'completed', 'confirmed',
      'pending', 'processing', 'shipped',
    ])
  })

  it('both "confirmed" and "processing" map to "pending_shipment" (display merge)', () => {
    expect(BackendToFrontendStatus.confirmed).toBe('pending_shipment')
    expect(BackendToFrontendStatus.processing).toBe('pending_shipment')
  })

  it('round-trip: front→back→front preserves display status (except refund→cancelled→closed)', () => {
    // All statuses except "refund" should round-trip
    const statuses: OrderStatus[] = [
      'pending_payment', 'pending_shipment', 'shipped', 'completed', 'closed',
    ]
    for (const frontend of statuses) {
      const backend = FrontendToBackendStatus[frontend]
      const roundTrip = BackendToFrontendStatus[backend]

      // pending_shipment maps to confirmed which maps back to pending_shipment ✅
      // BUT processing also maps back to pending_shipment, so it's a merge not 1:1
      if (frontend === 'pending_shipment') {
        // confirmed → pending_shipment, processing → pending_shipment
        expect(['pending_shipment']).toContain(roundTrip)
      } else {
        expect(roundTrip).toBe(frontend)
      }
    }
  })

  it('refund → cancelled → closed (intentional merge: backend has no refund status)', () => {
    const backend = FrontendToBackendStatus.refund
    expect(backend).toBe('cancelled')
    const display = BackendToFrontendStatus[backend]
    // refund loses its identity through the backend — displays as closed
    expect(display).toBe('closed')
  })
})

// ===================================================================
// 商品 Payload 构建
// ===================================================================

function makeProductForm(overrides?: Partial<ProductFormData>): ProductFormData {
  return {
    name: '测试商品',
    categoryId: 'cat-1',
    unit: '米',
    price: 99,
    images: ['https://cdn.example.com/img1.jpg', 'https://cdn.example.com/img2.jpg'],
    status: 'draft',
    skuCode: 'SKU001',
    ...overrides,
  }
}

describe('buildProductPayload', () => {
  it('maps price → basePrice for create/update', () => {
    const payload = buildProductPayload(makeProductForm({ price: 128 }))
    expect(payload.basePrice).toBe(128)
    // price field should NOT be in payload (it was destructured out)
    expect((payload as any).price).toBeUndefined()
  })

  it('maps images[0] → mainImage', () => {
    const payload = buildProductPayload(
      makeProductForm({ images: ['https://cdn.example.com/a.jpg', 'https://cdn.example.com/b.jpg'] }),
    )
    expect(payload.mainImage).toBe('https://cdn.example.com/a.jpg')
    // images array still present (backend needs all images)
    expect(payload.images).toEqual(['https://cdn.example.com/a.jpg', 'https://cdn.example.com/b.jpg'])
  })

  it('sets mainImage to null when images is empty', () => {
    const payload = buildProductPayload(makeProductForm({ images: [] }))
    expect(payload.mainImage).toBeNull()
  })

  it('sets mainImage to null when images is undefined', () => {
    const form = makeProductForm()
    delete (form as any).images
    const payload = buildProductPayload(form)
    expect(payload.mainImage).toBeNull()
  })

  it('passes through all other fields unchanged', () => {
    const form = makeProductForm({
      name: '遮光窗帘',
      skuCode: 'CUR-001',
      description: '高品质遮光布料',
      categoryId: 'cat-5',
      unit: '米',
      supportsProcessing: true,
    })
    const payload = buildProductPayload(form)
    expect(payload.name).toBe('遮光窗帘')
    expect(payload.skuCode).toBe('CUR-001')
    expect(payload.description).toBe('高品质遮光布料')
    expect(payload.categoryId).toBe('cat-5')
    expect(payload.unit).toBe('米')
    expect(payload.supportsProcessing).toBe(true)
  })

  it('handles colors and SKUs in payload', () => {
    const form = makeProductForm({
      colors: [{ id: 1, colorName: '红', sortOrder: 0 }],
      sellingMethods: ['bulk_cut'] as any,
      doorWidths: ['2.8米'],
      skus: [{ id: -1, colorId: 1, colorName: '红', sellingMethod: 'bulk_cut', doorWidth: '2.8米', price: 99, stock: 10, status: 'active' }],
    })
    const payload = buildProductPayload(form)
    expect(payload.colors).toEqual(form.colors)
    expect(payload.skus).toEqual(form.skus)
    expect(payload.sellingMethods).toEqual(form.sellingMethods)
    expect(payload.doorWidths).toEqual(form.doorWidths)
  })

  it('strips price from spread but keeps basePrice', () => {
    const payload = buildProductPayload(makeProductForm({ price: 200 }))
    expect(payload.basePrice).toBe(200)
    // price is destructured out — it should not leak into payload
    expect(Object.keys(payload)).not.toContain('price')
  })
})

// ===================================================================
// 物流 Payload 构建
// ===================================================================

describe('buildLogisticsPayload', () => {
  it('maps company → logisticsCompany', () => {
    const data: LogisticsFormData = {
      company: '顺丰速运',
      trackingNo: 'SF1234567890',
      shippingMethod: 'logistics',
    }
    const payload = buildLogisticsPayload(data)
    expect(payload).toEqual({
      logisticsCompany: '顺丰速运',
      trackingNo: 'SF1234567890',
    })
  })

  it('handles "none" shipping method (no logistics)', () => {
    const data: LogisticsFormData = {
      company: '',
      trackingNo: '',
      shippingMethod: 'none',
    }
    const payload = buildLogisticsPayload(data)
    expect(payload).toEqual({
      logisticsCompany: '',
      trackingNo: '',
    })
  })

  it('does NOT include shippingMethod in payload (not sent to backend)', () => {
    const data: LogisticsFormData = {
      company: '中通快递',
      trackingNo: 'ZTO9876543210',
      shippingMethod: 'logistics',
    }
    const payload = buildLogisticsPayload(data)
    expect((payload as any).shippingMethod).toBeUndefined()
  })
})

// ===================================================================
// 关单 Payload 构建
// ===================================================================

describe('buildCloseOrderPayload', () => {
  it('maps reason → closeReason', () => {
    const data: CloseOrderParams = { reason: '客户取消订单' }
    const payload = buildCloseOrderPayload(data)
    expect(payload).toEqual({ closeReason: '客户取消订单' })
  })

  it('defaults closeReason to empty string when data is undefined', () => {
    const payload = buildCloseOrderPayload(undefined)
    expect(payload).toEqual({ closeReason: '' })
  })

  it('defaults closeReason to empty string when reason is empty', () => {
    const payload = buildCloseOrderPayload({ reason: '' })
    expect(payload).toEqual({ closeReason: '' })
  })

  it('ignores extra fields like remark', () => {
    const payload = buildCloseOrderPayload({ reason: '其他原因', remark: '详细说明' })
    expect(payload).toEqual({ closeReason: '其他原因' })
    // remark should not leak into close order payload
    expect((payload as any).remark).toBeUndefined()
  })
})
