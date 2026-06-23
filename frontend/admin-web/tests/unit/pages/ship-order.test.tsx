import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock API
const mockGetOrder = vi.fn()
const mockUpdateLogistics = vi.fn()
const mockUpdateOrderStatus = vi.fn()

vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrder: (...args: any[]) => mockGetOrder(...args),
    updateLogistics: (...args: any[]) => mockUpdateLogistics(...args),
    updateOrderStatus: (...args: any[]) => mockUpdateOrderStatus(...args),
  },
}))

// Mock useRouteId
vi.mock('@/lib/use-route-id', () => ({
  useRouteId: () => 'test-order-456',
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock sonner
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

const mockOrder = {
  id: 'test-order-456',
  orderNo: 'MG202606002',
  status: 'pending_shipment',
  customerName: '李四',
  customerPhone: '13900139000',
  customerAddress: '上海市浦东新区',
  actualAmount: 3500,
  items: [
    {
      id: 'item2',
      productId: 'prod2',
      productName: '遮光窗帘',
      productCode: 'SKU-002',
      unitPrice: 175,
      quantity: 20,
      amount: 3500,
    },
  ],
  processingItems: [],
}

import ShipOrder from '@/app/(dashboard)/orders/[id]/ship/ShipOrder'

describe('ShipOrder', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetOrder.mockResolvedValue({
      data: { data: mockOrder },
    })
  })

  it('should show loading state initially', () => {
    render(<ShipOrder />)
    expect(screen.getByText('加载订单详情...')).toBeInTheDocument()
  })

  it('should render page title after loading', async () => {
    render(<ShipOrder />)
    // 页面标题 "商品发货" 在 h1 和面包屑中都会出现
    const headings = await screen.findAllByText('商品发货')
    expect(headings.length).toBeGreaterThanOrEqual(1)
  })

  it('should render breadcrumb navigation', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('首页')).toBeInTheDocument()
      expect(screen.getByText('订单管理')).toBeInTheDocument()
    })
  })

  it('should render confirm goods section', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('确认商品信息')).toBeInTheDocument()
      expect(screen.getByText('商品信息')).toBeInTheDocument()
    })
  })

  it('should render confirm shipping info section', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('确认收货信息')).toBeInTheDocument()
      expect(screen.getByText('收货信息')).toBeInTheDocument()
      expect(screen.getByText('李四')).toBeInTheDocument()
    })
  })

  it('should render logistics section', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('确认物流')).toBeInTheDocument()
    })
  })

  it('should render shipping method options', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('物流发货')).toBeInTheDocument()
      expect(screen.getByText('无需物流')).toBeInTheDocument()
    })
  })

  it('should render confirm and cancel buttons', async () => {
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('确认发货')).toBeInTheDocument()
      expect(screen.getByText('取消发货')).toBeInTheDocument()
    })
  })

  it('should show not-allowed state for non-shippable order', async () => {
    mockGetOrder.mockResolvedValue({
      data: { data: { ...mockOrder, status: 'completed' } },
    })
    render(<ShipOrder />)
    await waitFor(() => {
      expect(screen.getByText('当前订单状态不允许发货')).toBeInTheDocument()
    })
  })
})
