// case_ids: PP-011
// PP-011（issue #4000，M4-H 按需单据渲染）：useRouteId 支持「动态段 + 已知后缀」路由
// /processing-orders/{id}/production —— 后缀 production 必须被跳过取到加工单 id，
// 否则生产明细页会拿 'production' 当加工单号发请求（页面白屏/查无此单）。
import { describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useRouteId } from '@/lib/use-route-id'

describe('useRouteId — 嵌套动态段后缀（issue #4000）', () => {
  it('跳过已知后缀 production，取到加工单 id', () => {
    window.history.pushState({}, '', '/processing-orders/JG-20260917-0001/production')

    const { result } = renderHook(() => useRouteId('id'))

    expect(result.current).toBe('JG-20260917-0001')
  })

  it('既有后缀 ship 行为不变（/orders/{id}/ship 不回归）', () => {
    window.history.pushState({}, '', '/orders/order-uuid-1/ship')

    const { result } = renderHook(() => useRouteId('id'))

    expect(result.current).toBe('order-uuid-1')
  })

  it('末尾即 id 时直接取该段', () => {
    window.history.pushState({}, '', '/customers/customer-uuid-1')

    const { result } = renderHook(() => useRouteId('id'))

    expect(result.current).toBe('customer-uuid-1')
  })
})
