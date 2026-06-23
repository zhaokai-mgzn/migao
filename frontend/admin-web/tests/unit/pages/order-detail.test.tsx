import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock API
const mockGetOrder = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrder: (...args: any[]) => mockGetOrder(...args),
    closeOrder: vi.fn(),
    confirmPayment: vi.fn(),
    updateOrderStatus: vi.fn(),
    updateLogistics: vi.fn(),
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
})
