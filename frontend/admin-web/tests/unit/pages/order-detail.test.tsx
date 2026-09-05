// case_ids: OR-001, OR-002, OR-003, UI-024
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { markErrorToastShown } from '@/lib/api-error'

// Mock API
const mockGetOrder = vi.fn()
const mockConfirmPayment = vi.fn()
const mockRefundOrder = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrder: (...args: any[]) => mockGetOrder(...args),
    closeOrder: vi.fn(),
    confirmPayment: (...args: any[]) => mockConfirmPayment(...args),
    updateOrderStatus: vi.fn(),
    updateLogistics: vi.fn(),
    refundOrder: (...args: any[]) => mockRefundOrder(...args),
  },
}))

// Mock useRouteId
vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'test-order-123',
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock sonner
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

import { toast } from 'sonner'

// Mock dayjs
vi.mock('dayjs', () => ({
  default: (date?: string) => ({
    format: () => date || '2026-04-25 10:00',
    diff: () => 3600,
  }),
}))

// Mock child components
vi.mock('@/components/orders', () => ({
  OrderProgressSteps: () => <div data-testid="order-progress">OrderProgressSteps</div>,
  CloseOrderModal: ({ open }: any) => open ? <div data-testid="close-modal">CloseModal</div> : null,
  LogisticsForm: ({ open }: any) => open ? <div data-testid="logistics-form">LogisticsForm</div> : null,
  RefundOrderModal: ({ open, onConfirm }: any) =>
    open ? (
      <div data-testid="refund-modal" role="dialog">
        <button data-testid="confirm-refund-detail" onClick={() => onConfirm({ refundAmount: 500, refundReason: '质量问题' })}>
          确认退款
        </button>
      </div>
    ) : null,
}))

import OrderDetailPage from '@/app/(dashboard)/orders/[id]/OrderDetail'

const mockOrder = {
  id: 'test-order-123',
  orderNo: 'MG202606001',
  status: 'pending_shipment',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '北京市朝阳区xx小区',
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
  processingItems: [],
}

describe('OrderDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetOrder.mockResolvedValue({
      data: { data: mockOrder },
    })
  })

  it('should show loading state initially', () => {
    render(<OrderDetailPage />)
    // Loading should show before data resolves
    expect(screen.getByText('加载订单详情...')).toBeInTheDocument()
  })

  it('should render page title after loading', async () => {
    render(<OrderDetailPage />)
    // 使用 findByText 内置 waitFor 避免竞态
    const heading = await screen.findAllByText('订单详情')
    expect(heading.length).toBeGreaterThanOrEqual(1)
  })

  it('should render breadcrumb navigation', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('首页')).toBeInTheDocument()
      expect(screen.getByText('订单列表')).toBeInTheDocument()
    })
  })

  it('should render basic info section', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('基础信息')).toBeInTheDocument()
      expect(screen.getByText('MG202606001')).toBeInTheDocument()
    })
  })

  it('should render customer info section', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('收货信息')).toBeInTheDocument()
      expect(screen.getByText('张三')).toBeInTheDocument()
    })
  })

  it('should render product info section', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('商品信息')).toBeInTheDocument()
    })
  })

  it('should show empty state when order not found', async () => {
    mockGetOrder.mockResolvedValue({ data: { data: null } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('订单不存在或已被删除')).toBeInTheDocument()
    })
  })

  it('should render amount summary with discount and actual amount', async () => {
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('实收款')).toBeInTheDocument()
      expect(screen.getByText('优惠金额')).toBeInTheDocument()
    })
  })

  // ===== 退款展示（目标契约：退款不再改变订单状态，refundAmount>0 表示已退款） =====

  it('renders 已退款 badge when refundAmount > 0 (not depending on refund status)', async () => {
    mockGetOrder.mockResolvedValue({
      data: {
        data: {
          ...mockOrder,
          status: 'completed',
          refundAmount: 150,
          refundAt: '2026-06-21T10:00:00Z',
        },
      },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('已退款 ¥150.00')).toBeInTheDocument()
    })
  })

  it('renders 退款时间 in badge when refundAt provided', async () => {
    mockGetOrder.mockResolvedValue({
      data: {
        data: {
          ...mockOrder,
          status: 'completed',
          refundAmount: 150,
          refundAt: '2026-06-21T10:00:00Z',
        },
      },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText(/退款时间：/)).toBeInTheDocument()
    })
  })

  it('amount summary shows 已退款 ¥X row when refundAmount > 0', async () => {
    mockGetOrder.mockResolvedValue({
      data: {
        data: { ...mockOrder, status: 'completed', refundAmount: 150, refundAt: '2026-06-21T10:00:00Z' },
      },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('已退款')).toBeInTheDocument()
      expect(screen.getByText('¥150.00')).toBeInTheDocument()
    })
  })

  it('does NOT render 已退款 when refundAmount is 0 or undefined', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, refundAmount: 0 } },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('商品信息')).toBeInTheDocument()
    })
    expect(screen.queryByText('已退款')).not.toBeInTheDocument()
    expect(screen.queryByText('已退款 ¥0.00')).not.toBeInTheDocument()
  })

  it('renders "-" for missing paidAt/shippedAt/receivedAt (defensive, no crash)', async () => {
    const noTimes = { ...mockOrder, paidAt: undefined, shippedAt: undefined, receivedAt: undefined }
    mockGetOrder.mockResolvedValue({ data: { data: noTimes } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('基础信息')).toBeInTheDocument()
    })
    // 支付时间 / 发货时间 / 确认收货时间 行均显示占位符 "-"
    for (const label of ['支付时间：', '发货时间：', '确认收货时间：']) {
      const row = screen.getByText(label).parentElement
      expect(row).toBeTruthy()
      expect(row!.textContent).toContain('-')
    }
  })

  // ===== 详情页操作区退款按钮（P1：confirmed/producing/shipped/completed 且未退款） =====

  it('待发货（confirmed）未退款订单操作区显示 退款 按钮', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'confirmed', refundAmount: 0 } },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '退款' })).toBeInTheDocument()
    })
  })

  it('已完成未退款订单操作区显示 退款 按钮', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'completed', refundAmount: 0 } },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '退款' })).toBeInTheDocument()
    })
  })

  it('已退款订单（refundAmount > 0）操作区不显示 退款 按钮', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'completed', refundAmount: 500 } },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('已退款 ¥500.00')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: '退款' })).not.toBeInTheDocument()
  })

  it('待付款订单操作区不显示 退款 按钮', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'pending', refundAmount: 0 } },
    })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('待买家付款')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: '退款' })).not.toBeInTheDocument()
  })

  it('点击 退款 弹出退款弹窗，提交调用 refundOrder 并重新加载订单', async () => {
    const user = userEvent.setup()
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'completed', refundAmount: 0 } },
    })
    mockRefundOrder.mockResolvedValue({ data: { success: true } })
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: '退款' })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: '退款' }))
    expect(screen.getByTestId('refund-modal')).toBeInTheDocument()

    await user.click(screen.getByTestId('confirm-refund-detail'))
    await waitFor(() => {
      expect(mockRefundOrder).toHaveBeenCalledWith('test-order-123', { refundAmount: 500, refundReason: '质量问题' })
    })
    // 成功后重新加载订单详情
    await waitFor(() => {
      expect(mockGetOrder.mock.calls.length).toBeGreaterThanOrEqual(2)
    })
  })

  // ===== 确认付款失败：错误提示去重（issue #2923，case UI-019） =====

  it('确认付款失败：拦截器已提示具体错误 → 页面不再重复弹通用提示、弹窗保持打开', async () => {
    const user = userEvent.setup()
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'pending', refundAmount: 0 } },
    })
    const stockError = new Error('商品「测试9999」库存不足')
    markErrorToastShown(stockError) // 模拟拦截器已 toast 具体错误并打标记
    mockConfirmPayment.mockRejectedValue(stockError)
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('待买家付款')).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: '确认付款' }))
    await user.click(screen.getByRole('button', { name: '确定' }))
    await waitFor(() => {
      expect(mockConfirmPayment).toHaveBeenCalledWith('test-order-123')
    })
    // 拦截器已提示 → 页面不叠加通用错误
    expect(toast.error).not.toHaveBeenCalledWith('确认付款失败')
    // 失败不关闭确认弹窗
    expect(screen.getByText(/确认已收到付款/)).toBeInTheDocument()
  })

  it('确认付款失败：未经拦截器的错误 → 仍显示通用 fallback 提示', async () => {
    const user = userEvent.setup()
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'pending', refundAmount: 0 } },
    })
    mockConfirmPayment.mockRejectedValue(new Error('client-side error'))
    render(<OrderDetailPage />)
    await waitFor(() => {
      expect(screen.getByText('待买家付款')).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: '确认付款' }))
    await user.click(screen.getByRole('button', { name: '确定' }))
    await waitFor(() => {
      expect(mockConfirmPayment).toHaveBeenCalled()
    })
    expect(toast.error).toHaveBeenCalledWith('确认付款失败')
  })
})
