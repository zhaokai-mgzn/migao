// case_ids: UI-073
/**
 * 看板卡 → 订单列表的**下钻口径**（issue #5792 口径②）。
 *
 * ## 治的形态
 *
 * 前端类型里那句映射注释一直写着「`pending_shipment: 'confirmed'` // **confirmed 和 producing 都算待发货**」，
 * 而实际下发只发 `confirmed` 一个值 ⇒ 列表比**计数**少一截
 * （看板「待发货」卡 = `confirmed + producing` 两状态之和）⇒ **计数与下钻不一致**。
 * 列表页自己选「待发货」也是同一个错，所以修在**映射层**（`toBackendStatusParam`）而不是看板卡上。
 *
 * ## 为什么单独一个文件
 *
 * `tests/unit/pages/orders.test.tsx` 把 `@/types` **整体 mock** 成了「后端状态键」的简化版
 * （`OrderStatusLabels: { pending: '待确认', … }`），在那份 mock 下 `?status=待发货` 根本解析不出来
 * ⇒ 本判据在该文件里不可测。这里**不 mock `@/types`**，用真映射，端到端钉住「URL → 请求参数」。
 */
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const mockGetOrders = vi.fn()

// 只 mock「外部世界」（网络/路由），不 mock 纯映射模块 —— 判据要跑真映射
const h = vi.hoisted(() => ({ params: new URLSearchParams() }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => h.params,
  usePathname: () => '/orders',
}))
vi.mock('next/link', () => ({
  default: ({ children, ...props }: any) => <a {...props}>{children}</a>,
}))
vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrders: (...args: any[]) => mockGetOrders(...args),
    updateOrderStatus: vi.fn(),
    exportOrders: vi.fn(),
  },
  dashboardApi: {},
  afterSalesApi: {},
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

import OrdersPage from '@/app/(dashboard)/orders/page'
import { toBackendStatusParam } from '@/types'

beforeEach(() => {
  vi.clearAllMocks()
  h.params = new URLSearchParams()
  mockGetOrders.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
})

describe('订单列表下钻口径（issue #5792）', () => {
  it('🔴 纯映射：`pending_shipment`（待发货）⇒ **两个**后端状态；其余仍单值', () => {
    // 这两条是「注释与行为不符」的最小锁：注释说两个都算，行为就必须发两个
    expect(toBackendStatusParam('pending_shipment')).toBe('confirmed,producing')
    expect(toBackendStatusParam('pending_payment')).toBe('pending')
    expect(toBackendStatusParam('shipped')).toBe('shipped')
    expect(toBackendStatusParam('completed')).toBe('completed')
    expect(toBackendStatusParam('closed')).toBe('cancelled')
    // 不得把「单值」也放宽成多值（那会悄悄改掉其他筛选的语义）
    for (const s of ['pending_payment', 'shipped', 'completed', 'closed', 'refund'] as const) {
      expect(toBackendStatusParam(s)).not.toContain(',')
    }
  })

  it('🔴 端到端：看板卡跳 `?status=待发货` ⇒ 请求带 `confirmed,producing`（列表不再比计数少）', async () => {
    h.params = new URLSearchParams('status=待发货')
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())
    const params = mockGetOrders.mock.calls.at(-1)?.[0] as Record<string, unknown>
    expect(params.status).toBe('confirmed,producing')
  })

  it('🔴 端到端：`?status=已完成` ⇒ 仍发单值 `completed`（兼容多值不放大口径）', async () => {
    h.params = new URLSearchParams('status=已完成')
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())
    const params = mockGetOrders.mock.calls.at(-1)?.[0] as Record<string, unknown>
    expect(params.status).toBe('completed')
  })

  it('反空跑：无 `status` 参数 ⇒ 不传 status（默认「全部」）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())
    const params = mockGetOrders.mock.calls.at(-1)?.[0] as Record<string, unknown>
    expect(params.status).toBeUndefined()
    // 页面确实渲染了（否则上面的「没传」可能只是因为根本没跑起来）
    expect(screen.getAllByText('全部').length).toBeGreaterThanOrEqual(1)
  })
})
