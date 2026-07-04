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
  // dashboard 拆 3 端点：待发货 / 含加工待发货 / 低库存 SKU
  // 按 URL 分发返回
  mockRequestGet.mockImplementation((url: string) => {
    if (url === '/api/admin/dashboard/pending-shipment-count') {
      return Promise.resolve({ data: { data: 8 } })
    }
    if (url === '/api/admin/dashboard/processing-shipment-count') {
      return Promise.resolve({ data: { data: 3 } })
    }
    if (url.startsWith('/api/admin/products/low-stock-by-color')) {
      return Promise.resolve({
        data: {
          data: [
            { skuId: 's1', productName: '2699色卡', color: '米白', stock: 50 },
            { skuId: 's2', productName: '窗帘轨道', color: '咖啡', stock: 30 },
          ],
        },
      })
    }
    return Promise.resolve({ data: { data: 0 } })
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

  it('should fetch dashboard pending counts via 3 separate endpoints', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(mockRequestGet).toHaveBeenCalledWith('/api/admin/dashboard/pending-shipment-count')
      expect(mockRequestGet).toHaveBeenCalledWith('/api/admin/dashboard/processing-shipment-count')
      expect(mockRequestGet).toHaveBeenCalledWith(
        '/api/admin/products/low-stock-by-color',
        expect.objectContaining({ params: expect.objectContaining({ threshold: 100, limit: 200 }) }),
      )
    })
  })

  it('should display pending shipment counts', async () => {
    const { container } = render(<DashboardPage />)
    await waitFor(() => {
      // 待发货订单 = 8 — 定位到 "待发货订单" 标题后的 count 节点
      const card1 = container.querySelector('p:has(+ p)') // 不够精确
      // 改用更直接的：找到所有 PendingCard 容器，断言 count 数字
      // PendingCard 渲染：<p className="text-xs">title</p><p className="text-xl">count</p>
      const allTitles = Array.from(container.querySelectorAll('p.text-xs'))
      const findCount = (title: string) => {
        const titleEl = allTitles.find((el) => el.textContent === title)
        return titleEl?.nextElementSibling?.textContent
      }
      // fmtNum 不会改小数字（< 1000 直接返回原值），所以 '8' / '3' / '2'
      expect(findCount('待发货订单')).toContain('8')
      expect(findCount('含加工待发货订单')).toContain('3')
      expect(findCount('待补库存商品')).toContain('2')
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

  // ── Bug #942: SVG 趋势图布局修复 ──

  it('SVG trend chart should NOT use preserveAspectRatio="none"', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      const svgs = document.querySelectorAll('svg[viewBox]')
      // Must have at least one SVG with viewBox (trend charts)
      expect(svgs.length).toBeGreaterThanOrEqual(1)
      svgs.forEach((svg) => {
        const ar = svg.getAttribute('preserveAspectRatio')
        expect(ar).not.toBe('none')
      })
    })
  })

  it('SVG trend chart viewBox height should accommodate date labels', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      const svgs = document.querySelectorAll('svg[viewBox]')
      expect(svgs.length).toBeGreaterThanOrEqual(1)
      svgs.forEach((svg) => {
        const vb = svg.getAttribute('viewBox')
        expect(vb).toBeTruthy()
        const parts = vb!.split(/\s+/)
        const h = parseInt(parts[3], 10)
        // viewBox height should be > 200 to leave room for date labels + padding
        expect(h).toBeGreaterThanOrEqual(220)
      })
    })
  })

  it('SVG chart date labels y-position should have bottom padding (not at edge)', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      const dateTexts = document.querySelectorAll('svg[viewBox] text')
      // Must have date labels rendered
      expect(dateTexts.length).toBeGreaterThanOrEqual(1)
      dateTexts.forEach((text) => {
        const y = parseFloat(text.getAttribute('y') || '0')
        const svg = text.closest('svg')
        const vb = svg?.getAttribute('viewBox')
        if (vb) {
          const vbH = parseInt(vb.split(/\s+/)[3], 10)
          // Date labels should not be at the very bottom (need padding)
          // bottomGap = vbH - y should be >= 15px for proper padding
          const bottomGap = vbH - y
          expect(bottomGap).toBeGreaterThanOrEqual(15)
          // And not at the very top either
          expect(y).toBeGreaterThan(vbH * 0.5)
        }
      })
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
