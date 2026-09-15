// @vitest-environment jsdom
// case_ids: UI-019, UI-030
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

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
  processingItems: [{ name: '打孔', unitPrice: 1, quantity: 2, amount: 2 }],
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
      expect(screen.getByText(/先完成加工单再发货/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /^发货$/ })).not.toBeInTheDocument()
    expect(screen.getByText('生产中')).toBeInTheDocument()
  })

  it('含加工项但加工单已完成 → 发货按钮可点（与后端 countCompleted>0 放行口径一致）', async () => {
    mockPODetail.mockResolvedValue({ data: { data: po('completed') } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^发货$/ })).toBeInTheDocument()
    })
    expect(screen.queryByText(/先完成加工单再发货/)).not.toBeInTheDocument()
  })

  it('confirmed 含加工项且无加工单 → 同样引导（后端 countCompleted==0 也会拦）', async () => {
    mockPODetail.mockRejectedValue(new Error('404'))
    mockGetOrder.mockResolvedValue({ data: { data: { ...baseOrder, status: 'confirmed' } } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText(/先完成加工单再发货/)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /^发货$/ })).not.toBeInTheDocument()
  })

  it('无加工项订单 → 发货按钮正常（不因加工单状态而阻断）', async () => {
    mockPODetail.mockRejectedValue(new Error('404'))
    mockGetOrder.mockResolvedValue({ data: { data: { ...baseOrder, processingItems: [] } } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^发货$/ })).toBeInTheDocument()
    })
    expect(screen.queryByText(/先完成加工单再发货/)).not.toBeInTheDocument()
  })
})
