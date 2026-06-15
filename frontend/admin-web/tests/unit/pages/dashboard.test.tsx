import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock request (for /api/admin/orders/statistics)
const mockRequestGet = vi.fn()
vi.mock('@/lib/request', () => ({
  default: { get: (...args: any[]) => mockRequestGet(...args) },
}))

// Mock useAuthStore
const mockUseAuthStore = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: (...args: any[]) => mockUseAuthStore(...args),
}))

// Mock dashboard API
const mockGetStats = vi.fn()
const mockGetOrderTrend = vi.fn()
const mockGetRecentOrders = vi.fn()
const mockGetProductRanking = vi.fn()

vi.mock('@/lib/api', () => ({
  dashboardApi: {
    getStats: (...args: any[]) => mockGetStats(...args),
    getOrderTrend: (...args: any[]) => mockGetOrderTrend(...args),
    getRecentOrders: (...args: any[]) => mockGetRecentOrders(...args),
    getProductRanking: (...args: any[]) => mockGetProductRanking(...args),
  },
}))

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

import DashboardPage from '@/app/(dashboard)/dashboard/page'

function mockApiSuccess() {
  mockGetStats.mockResolvedValue({
    data: {
      data: {
        todayOrders: 10,
        todayOrdersChange: 25.5,
        todaySales: 39800,
        todaySalesChange: -12.3,
        monthRevenue: 5000000,
        monthRevenueChange: 15.8,
      },
    },
  })
  mockGetOrderTrend.mockResolvedValue({
    data: { data: [{ date: '2026-06-11', orders: 5, amount: 200 }, { date: '2026-06-10', orders: 3, amount: 100 }] },
  })
  mockGetRecentOrders.mockResolvedValue({
    data: {
      data: [
        { id: '1', orderNo: 'ORD-001', customerName: '张三', totalAmount: 398, status: 'confirmed', createdAt: '2026-06-11T08:00:00Z' },
        { id: '2', orderNo: 'ORD-002', customerName: '李四', totalAmount: 650, status: 'shipped', createdAt: '2026-06-10T10:00:00Z' },
      ],
    },
  })
  mockGetProductRanking.mockResolvedValue({
    data: {
      data: [
        { rank: 1, productId: 'p1', productName: '2699色卡', salesQty: 30, qtyDisplay: '30', salesAmount: 12000, amountDisplay: '1.2w', dailyChange: 15.5 },
        { rank: 2, productId: 'p2', productName: '窗帘轨道', salesQty: 20, qtyDisplay: '20', salesAmount: 8000, amountDisplay: '8000', dailyChange: -5.2 },
      ],
    },
  })
  mockRequestGet.mockResolvedValue({
    data: { data: { confirmedCount: 8, producingCount: 3 } },
  })
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseAuthStore.mockReturnValue({})
    mockApiSuccess()
  })

  // ── 基础渲染 ──

  it('should render page heading', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('数据看板')).toBeInTheDocument()
    })
  })

  it('should render data update time', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      const elements = screen.getAllByText(/数据更新时间：/)
      expect(elements.length).toBeGreaterThanOrEqual(1)
    })
  })

  // ── 经营数据 ──

  it('should render business stats section', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('经营数据')).toBeInTheDocument()
      expect(screen.getByText('今日订单数')).toBeInTheDocument()
      expect(screen.getByText('今日销售额')).toBeInTheDocument()
      expect(screen.getByText('本月销售额')).toBeInTheDocument()
    })
  })

  it('should display stats values after loading', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      const orderElements = screen.getAllByText('今日订单数')
      expect(orderElements.length).toBeGreaterThanOrEqual(1)
      const currencyElements = screen.getAllByText(/¥[\d.]+万/)
      expect(currencyElements.length).toBeGreaterThanOrEqual(1)
    })
  })

  // ── 待处理 ──

  it('should render pending section', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('待处理')).toBeInTheDocument()
      expect(screen.getByText('待发货订单')).toBeInTheDocument()
      expect(screen.getByText('含加工待发货订单')).toBeInTheDocument()
      expect(screen.getByText('待补库存商品')).toBeInTheDocument()
    })
  })

  it('should fetch order statistics for pending counts', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(mockRequestGet).toHaveBeenCalledWith('/api/admin/orders/statistics')
    })
  })

  it('should display pending shipment counts', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      // 待发货 = confirmedCount(8) + producingCount(3) = 11
      expect(screen.getByText('11')).toBeInTheDocument()
      // 含加工待发货 = producingCount(3) = 3
      expect(screen.getByText('3')).toBeInTheDocument()
    })
  })

  // ── 趋势图 ──

  it('should render order trend section', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('订单趋势')).toBeInTheDocument()
      expect(screen.getByText('销售额数据')).toBeInTheDocument()
    })
  })

  it('should render trend period toggle buttons', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('近7天')).toBeInTheDocument()
      expect(screen.getByText('近30天')).toBeInTheDocument()
    })
  })

  // ── 近期订单 ──

  it('should render recent orders table', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('近期订单')).toBeInTheDocument()
      expect(screen.getByText('张三')).toBeInTheDocument()
      expect(screen.getByText('李四')).toBeInTheDocument()
    })
  })

  it('should render "查看全部" link', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      const link = screen.getByText('查看全部')
      expect(link.closest('a')).toHaveAttribute('href', '/orders')
    })
  })

  // ── 商品排行 ──

  it('should render product ranking section', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('商品销量排行')).toBeInTheDocument()
    })
  })

  it('should render ranking items', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('2699色卡')).toBeInTheDocument()
      expect(screen.getByText('窗帘轨道')).toBeInTheDocument()
    })
  })

  it('should show empty state when ranking is empty', async () => {
    mockGetProductRanking.mockResolvedValue({ data: { data: [] } })
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('暂无数据')).toBeInTheDocument()
    })
  })

  // ── 加载/错误处理 ──

  it('should show loading skeleton initially', () => {
    render(<DashboardPage />)
    const skeletons = document.querySelectorAll('.animate-pulse')
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it('should handle API errors gracefully', async () => {
    mockGetStats.mockRejectedValue(new Error('Network error'))
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('数据看板')).toBeInTheDocument()
    })
  })

  it('should handle empty trend data', async () => {
    mockGetOrderTrend.mockResolvedValue({ data: { data: [] } })
    render(<DashboardPage />)
    await waitFor(() => {
      const emptyNodes = screen.getAllByText('暂无数据')
      expect(emptyNodes.length).toBeGreaterThanOrEqual(2)
    })
  })

  it('should have refresh button', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      const refreshIcon = screen.getByTestId('icon-refresh-cw')
      expect(refreshIcon).toBeInTheDocument()
    })
  })
})
