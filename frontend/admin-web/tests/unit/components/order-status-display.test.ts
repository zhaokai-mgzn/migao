// @vitest-environment jsdom
// case_ids: UI-019, UI-030, MC-207
import { describe, it, expect } from 'vitest'
import { BackendToFrontendStatus, displayOrderStatus } from '@/types'

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

  // issue #8686：DB 有第 7 个值 packed（工人推进的打包态），展示层此前只准备 6 个 ⇒ 商家看到空白。
  it('packed（已打包）必须显示中文标签与颜色（显示专用，不授予动作）', () => {
    expect(displayOrderStatus('packed')).toEqual({ label: '已打包', color: 'info' })
  })

  it('未知状态必须有兜底标签，不得渲染成 undefined', () => {
    expect(displayOrderStatus('some_unknown_status')).toEqual({ label: '未知状态', color: 'default' })
  })

  it('显示放开不授予写路径：后端→前端映射仍只有 6 个、不含 packed', () => {
    const known = Object.keys(BackendToFrontendStatus)
    expect(known).toHaveLength(6)
    expect(known).not.toContain('packed')
  })
})
