// @vitest-environment jsdom
// case_ids: UI-019, UI-030
import { describe, it, expect } from 'vitest'
import { displayOrderStatus } from '@/types'

/**
 * displayOrderStatus（issue #3889）：backend producing 与 confirmed 的展示区分。
 * producing（生产中）不再归一为 pending_shipment（待发货）展示，避免用户以为可发货。
 * 仅影响展示；OrderStatus 联合类型与 FrontendToBackendStatus（过滤/请求语义）不变。
 */
describe('displayOrderStatus', () => {
  it('producing → 生产中（醒目色）', () => {
    expect(displayOrderStatus('producing')).toEqual({ label: '生产中', color: 'warning' })
  })

  it('confirmed → 待发货', () => {
    expect(displayOrderStatus('confirmed')).toEqual({ label: '待发货', color: 'info' })
  })

  it('其余后端状态沿用 OrderStatusLabels/Colors 归一化展示', () => {
    expect(displayOrderStatus('pending')).toEqual({ label: '待付款', color: 'warning' })
    expect(displayOrderStatus('shipped')).toEqual({ label: '已发货', color: 'indigo' })
    expect(displayOrderStatus('completed')).toEqual({ label: '已完成', color: 'success' })
    expect(displayOrderStatus('cancelled')).toEqual({ label: '已关闭', color: 'default' })
  })

  it('前端枚举值直接透传展示', () => {
    expect(displayOrderStatus('pending_shipment')).toEqual({ label: '待发货', color: 'info' })
  })

  it('空值回退为待付款展示', () => {
    expect(displayOrderStatus(undefined)).toEqual({ label: '待付款', color: 'warning' })
    expect(displayOrderStatus(null)).toEqual({ label: '待付款', color: 'warning' })
  })
})
