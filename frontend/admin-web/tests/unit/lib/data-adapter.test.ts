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
// case_ids: OR-003, OR-004, OR-005, UI-040, UI-047, PR-042, PR-043, PR-044, OR-046, OR-058, OR-059

import { readFileSync } from 'node:fs'
import { describe, it, expect } from 'vitest'
import {
  FrontendToBackendStatus,
  BackendToFrontendStatus,
} from '@/types'
import {
  buildProductPayload,
  buildLogisticsPayload,
  buildCloseOrderPayload,
  buildRefundPayload,
  shippingMethodForEdit,
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
      producing: 'pending_shipment',
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
      'pending', 'producing', 'shipped',
    ])
  })

  it('both "confirmed" and "producing" map to "pending_shipment" (display merge)', () => {
    expect(BackendToFrontendStatus.confirmed).toBe('pending_shipment')
    expect(BackendToFrontendStatus.producing).toBe('pending_shipment')
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
      brand: '米高',
    })
    const payload = buildProductPayload(form)
    expect(payload.name).toBe('遮光窗帘')
    expect(payload.skuCode).toBe('CUR-001')
    expect(payload.description).toBe('高品质遮光布料')
    expect(payload.categoryId).toBe('cat-5')
    expect(payload.unit).toBe('米')
    expect(payload.brand).toBe('米高')
  })

  it('handles colors and SKUs in payload', () => {
    const form = makeProductForm({
      colors: [{ id: '1', colorName: '红', sortOrder: 0 }],
      sellingMethods: ['bulk_cut'] as any,
      rollLengthM: 60,
      doorWidths: ['2.8米'],
      skus: [{ id: '-1', colorId: '1', colorName: '红', doorWidth: '2.8米', price: 99, stock: 10, status: 'active' }],
    })
    const payload = buildProductPayload(form)
    expect(payload.colors).toEqual(form.colors)
    expect(payload.skus).toEqual(form.skus)
    // 售卖方式 / 卷长是**商品级基础属性** ⇒ 走请求体**顶层**，不在 skus[] 里
    expect(payload.sellingMethods).toEqual(form.sellingMethods)
    expect(payload.rollLengthM).toBe(60)
    expect('sellingMethod' in (payload.skus![0] as object)).toBe(false)
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
      shippingMethod: 'logistics',
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
      shippingMethod: 'none',
    })
  })

  // issue #6239：用户做的这个选择此前**被丢掉**（后端从不读取 shippingMethod）⇒
  // 「无需物流」与「物流发货但没填单号」在库里不可区分。现在必须下发。
  it('下发 shippingMethod（issue #6239：物流发货 / 无需物流 开始被后端记录）', () => {
    const logistics = buildLogisticsPayload({
      company: '中通快递',
      trackingNo: 'ZTO9876543210',
      shippingMethod: 'logistics',
    })
    expect(logistics.shippingMethod).toBe('logistics')

    const none = buildLogisticsPayload({
      company: '',
      trackingNo: '',
      shippingMethod: 'none',
    })
    expect(none.shippingMethod).toBe('none')
  })

  // ── 未采集（NULL）不许被静默写成 logistics（issue #6254）────────────────────
  // 改前：`shippingMethod: data.shippingMethod || 'logistics'` ⇒ 「库里没采集过」与「采集到
  // logistics」在请求体里**不可区分**，后端据此把一个 NULL 记录**凭空写成** `logistics`（造数据）。
  // 改后：未采集 ⇒ **省略该键** ⇒ 后端按「不传 = 不改」保留原值（与 OR-058 判据 5② 同一条口径）。
  it('shippingMethod 未采集 ⇒ 不下发该键（不再兜底成 logistics，issue #6254）', () => {
    const payload = buildLogisticsPayload({
      company: '顺丰速运',
      trackingNo: 'SF1',
      shippingMethod: undefined,
    })
    expect(payload.shippingMethod).toBeUndefined()
    // 「不下发」的可核形态 = **序列化后的请求体里没有这个键**（undefined 不会被 JSON.stringify 写出）
    expect(JSON.stringify(payload)).not.toContain('shippingMethod')
  })

  // 反向对照：**真**采集到 logistics 的取值照旧下发（证明上面那条不是「一律不下发」）
  it('正对照：真 shippingMethod=logistics ⇒ 照旧下发 logistics', () => {
    const payload = buildLogisticsPayload({
      company: '顺丰速运',
      trackingNo: 'SF1',
      shippingMethod: 'logistics',
    })
    expect(payload.shippingMethod).toBe('logistics')
  })
})

// ===================================================================
// 订单详情「编辑物流」弹窗的发货方式回填（issue #6254）
// ===================================================================

describe('shippingMethodForEdit', () => {
  it('未采集（undefined / null）⇒ undefined = 未记录（**不再读成 logistics**）', () => {
    expect(shippingMethodForEdit(undefined)).toBeUndefined()
    expect(shippingMethodForEdit(null)).toBeUndefined()
  })

  it('已采集的取值原样透传（正/反向对照：none 与 logistics 都不被改写）', () => {
    expect(shippingMethodForEdit('none')).toBe('none')
    expect(shippingMethodForEdit('logistics')).toBe('logistics')
  })

  // 🔴 接线判据（issue #6254）：口径本体被测到 ≠ **它接在真回填点上了**（同 `migao-dev-flow` §28.2）。
  // 订单详情必须**真的**用它、且不得再出现改前那条「NULL 兜底成 logistics」的表达式 ——
  // 谁哪天把兜底改回去，这一条当场红。
  it('接线：订单详情回填点真的走本函数，且不再有「NULL 当 logistics」的兜底表达式', () => {
    const src = readFileSync('src/app/(dashboard)/orders/[id]/OrderDetail.tsx', 'utf8')
    expect(src).toContain('shippingMethodForEdit(order.logistics?.shippingMethod)')
    expect(src).not.toContain("=== 'none' ? 'none' : 'logistics'")
  })

  // ---- 物流类型（issue #4419 / UI-047）----

  it('透传 logisticsType（express 快递 / logistics 物流专线）', () => {
    const payload = buildLogisticsPayload({
      company: '四季安物流',
      trackingNo: 'SJA001',
      shippingMethod: 'logistics',
      logisticsType: 'logistics',
    })
    expect(payload.logisticsType).toBe('logistics')
  })

  it('未选物流类型时不下发 logisticsType（由后端按列默认 express 兜底，不写假值）', () => {
    const payload = buildLogisticsPayload({
      company: '顺丰速运',
      trackingNo: 'SF1',
      shippingMethod: 'logistics',
    })
    expect(payload.logisticsType).toBeUndefined()
  })

  // ---- 发货人（发货单「经手人」，issue #3768 / UI-040）----

  it('透传 shipperName（并去掉首尾空格）', () => {
    const data: LogisticsFormData = {
      company: '顺丰速运',
      trackingNo: 'SF1234567890',
      shippingMethod: 'logistics',
      shipperName: '  王五  ',
    }
    const payload = buildLogisticsPayload(data)
    expect(payload.shipperName).toBe('王五')
  })

  it('shipperName 留空时不下发（由后端按当前登录用户兜底，避免前端塞空串覆盖）', () => {
    const blank = buildLogisticsPayload({
      company: '顺丰速运',
      trackingNo: 'SF1',
      shippingMethod: 'logistics',
      shipperName: '   ',
    })
    expect(blank.shipperName).toBeUndefined()

    const missing = buildLogisticsPayload({
      company: '顺丰速运',
      trackingNo: 'SF1',
      shippingMethod: 'logistics',
    })
    expect(missing.shipperName).toBeUndefined()
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

// ===================================================================
// 退款 Payload 构建（目标契约：body 支持 refund_reason，并将新增 refund_amount）
// ===================================================================

describe('buildRefundPayload', () => {
  it('maps refundAmount → refund_amount 且 refundReason → refund_reason', () => {
    const payload = buildRefundPayload({ refundAmount: 120.5, refundReason: '质量问题' })
    expect(payload).toEqual({
      refund_amount: 120.5,
      refund_reason: '质量问题',
    })
  })

  it('refundAmount 未传时省略 refund_amount（只退原因）', () => {
    const payload = buildRefundPayload({ refundReason: '协商一致' })
    expect(payload).toEqual({ refund_reason: '协商一致' })
    expect((payload as any).refund_amount).toBeUndefined()
  })

  it('refundReason 缺省时 refund_reason 为空字符串', () => {
    expect(buildRefundPayload()).toEqual({ refund_reason: '' })
  })

  it('trim 退款原因前后空白', () => {
    const payload = buildRefundPayload({ refundReason: '  客户退货  ' })
    expect(payload).toEqual({ refund_reason: '客户退货' })
  })
})
