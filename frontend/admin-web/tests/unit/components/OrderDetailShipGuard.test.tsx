// @vitest-environment jsdom
// case_ids: UI-019, UI-030, UI-115
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// issue #7276：订单详情页的**页面码 = order:detail**（判据见 tests/unit/pages/order-detail-permission-gate.test.tsx）
// ⇒ 本文件渲染的是「有权限的商家」形态，必须给登录态一份 `*` 权限；否则页面走拒绝态，
// 本文件的全部断言会凭空变红（那不是被测行为）。
const authMock = vi.hoisted(() => ({
  state: {
    user: { id: '1', username: 'tester', name: '测试账号', permissions: ['*'] as string[], roles: [] as string[] },
  },
}))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector?: (s: unknown) => unknown) =>
    typeof selector === 'function' ? selector(authMock.state) : authMock.state,
}))

/**
 * OrderDetail 发货入口守卫（issue #3889）：
 * 含加工项且加工单未完成 → 发货按钮区显示引导文案替代可点发货按钮（不再"先看到可发货、提交才被后端拦"）。
 * 加工单状态经 ProcessingOrderBlock.onStatusChange 上报（真实组件 + mock processingOrderApi.detail）。
 */

const mockGetOrder = vi.fn()
const mockPODetail = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrder: (...args: any[]) => mockGetOrder(...args),
    closeOrder: vi.fn(),
    confirmPayment: vi.fn(),
    updateOrderStatus: vi.fn(),
    updateLogistics: vi.fn(),
    refundOrder: vi.fn(),
  },
  processingOrderApi: {
    detail: (...args: any[]) => mockPODetail(...args),
  },
}))

vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'od-order-1',
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import OrderDetailPage from '@/app/(dashboard)/orders/[id]/OrderDetail'

const baseOrder = {
  id: 'od-order-1',
  orderNo: 'MG-OD-1',
  status: 'producing',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '北京市朝阳区',
  totalAmount: 1999,
  discountAmount: 0,
  actualAmount: 1999,
  createdAt: '2026-06-20T10:00:00Z',
  paidAt: '2026-06-20T10:30:00Z',
  items: [
    {
      id: 'item1',
      productId: 'prod1',
      productName: '测试窗帘布',
      sku: 'TEST-SKU-001',
      unitPrice: 99.5,
      quantity: 20,
      subtotal: 1990,
      processingInfo: null,
    },
  ],
  processingItems: [{ name: '打孔', quantity: 2 }],
  // issue #7079 第 5 包：发货入口判据 = 读面键 `work_order_kind`（后端 OrderShipGuard.needsWork 的同一份）
  work_order_kind: 'processing',
}

const po = (status: string) => ({
  id: 'po-1',
  orderId: 'od-order-1',
  orderNo: 'MG-OD-1',
  processingOrderNo: 'JG-OD-1',
  status,
  items: [],
})

describe('OrderDetail 发货入口守卫', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetOrder.mockResolvedValue({ data: { data: baseOrder } })
    mockPODetail.mockResolvedValue({ data: { data: po('issued') } })
  })

  it('生产中 + 加工单未完成 → 引导文案替代可点发货按钮，且展示「生产中」状态', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText(/先完成加工单的加工报工，再发货/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /^发货$/ })).not.toBeInTheDocument()
    // issue #3916：producing 订单向导第 2 步显示「生产中」，与 amber chip（#3889）同文案 → 至少 1 处
    expect(screen.getAllByText('生产中').length).toBeGreaterThanOrEqual(1)
  })

  it('含加工项但加工单已完成 → 发货按钮可点（与后端 countCompleted>0 放行口径一致）', async () => {
    mockPODetail.mockResolvedValue({ data: { data: po('completed') } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^发货$/ })).toBeInTheDocument()
    })
    expect(screen.queryByText(/先完成加工单的加工报工，再发货/)).not.toBeInTheDocument()
  })

  it('confirmed 含加工项且无加工单 → 同样引导（后端 countCompleted==0 也会拦）', async () => {
    mockPODetail.mockRejectedValue(new Error('404'))
    mockGetOrder.mockResolvedValue({ data: { data: { ...baseOrder, status: 'confirmed' } } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText(/先完成加工单的加工报工，再发货/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /^发货$/ })).not.toBeInTheDocument()
  })

  it('无加工项订单 → 发货按钮正常（不因加工单状态而阻断）', async () => {
    mockPODetail.mockRejectedValue(new Error('404'))
    mockGetOrder.mockResolvedValue({ data: { data: { ...baseOrder, processingItems: [], work_order_kind: null } } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^发货$/ })).toBeInTheDocument()
    })
    expect(screen.queryByText(/先完成加工单的加工报工，再发货/)).not.toBeInTheDocument()
  })
})

/**
 * issue #7079 第 5 包（UI-115）：订单详情的**发货入口**对卖布单也要有前置提示。
 *
 * 改前判据 = `order.processingItems.length > 0` ⇒ 卖布单直接渲染可点的「发货」按钮，
 * 用户点进去、填完表单、提交时才被后端拦（入口没有任何前置提示）。
 */
describe('OrderDetail 发货入口守卫：卖布单（issue #7079 第 5 包）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('UI-115 判据 5（红证）：卖布单 + 无作业单 ⇒ 引导句按型换成「卖布单 / 出库作业单」，发货按钮不可点', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...baseOrder, processingItems: [], work_order_kind: 'outbound' } },
    })
    mockPODetail.mockRejectedValue(new Error('404'))
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText(/该订单是卖布单：先完成出库作业单的裁剪与打包报工，再发货/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /^发货$/ })).not.toBeInTheDocument()
    expect(document.body.textContent ?? '').not.toContain('outbound')
  })

  it('UI-115 判据 6（红证）：卖布单 + 作业单已完成 ⇒ 发货按钮可点（与后端 countCompleted>0 放行一致）', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...baseOrder, processingItems: [], work_order_kind: 'outbound' } },
    })
    mockPODetail.mockResolvedValue({ data: { data: po('completed') } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^发货$/ })).toBeInTheDocument()
    })
  })

  it('UI-115 判据 7（反向护栏）：无作业的普通单（缺键）⇒ 不出现任何引导句，发货按钮照常', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...baseOrder, processingItems: [], work_order_kind: null } },
    })
    mockPODetail.mockRejectedValue(new Error('404'))
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^发货$/ })).toBeInTheDocument()
    })
    expect(screen.queryByText(/先完成加工单的加工报工/)).not.toBeInTheDocument()
    expect(screen.queryByText(/先完成出库作业单的裁剪与打包报工/)).not.toBeInTheDocument()
  })
})
