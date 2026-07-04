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

  // ── #942: 趋势图日期标签/数据点布局修复 ──

  // 辅助：找到订单趋势的 SVG（带 viewBox + polyline + text 元素）
  function findOrderTrendSvg(): SVGElement | null {
    const svgs = Array.from(document.querySelectorAll('svg'))
    for (const svg of svgs) {
      if (svg.getAttribute('viewBox') && svg.querySelector('polyline') && svg.querySelector('text')) {
        return svg as unknown as SVGElement
      }
    }
    return null
  }

  it('#942: 数据全零时 polyline y 坐标不应全部压在图表底部', async () => {
    mockGetOrderTrend.mockResolvedValue({
      data: { data: [
        { date: '2026-06-28', orders: 0 },
        { date: '2026-06-29', orders: 0 },
        { date: '2026-06-30', orders: 0 },
        { date: '2026-07-01', orders: 0 },
        { date: '2026-07-02', orders: 0 },
        { date: '2026-07-03', orders: 0 },
        { date: '2026-07-04', orders: 0 },
      ] },
    })
    render(<DashboardPage />)
    await waitFor(() => {
      const svg = findOrderTrendSvg()
      expect(svg).toBeTruthy()
      if (!svg) return
      const polyline = svg.querySelector('polyline')!
      const points = polyline.getAttribute('points')!
      // 解析所有 y 坐标
      const yValues = points.split(' ').map(p => parseFloat(p.split(',')[1]))
      const viewBoxH = parseFloat(svg.getAttribute('viewBox')!.split(/\s+/)[3])
      // 数据全零时，y 坐标不应全贴在视图底部，应有部分点在中上部
      const hasPointsAboveMiddle = yValues.some(y => y < viewBoxH * 0.7)
      expect(hasPointsAboveMiddle).toBe(true)
      // 同时不应有 y 坐标超出 viewBox
      yValues.forEach(y => {
        expect(y).toBeGreaterThanOrEqual(0)
        expect(y).toBeLessThanOrEqual(viewBoxH)
      })
    })
  })

  it('#942: 日期标签 y 坐标不应贴在 viewBox 最底部边缘', async () => {
    mockGetOrderTrend.mockResolvedValue({
      data: { data: [
        { date: '2026-06-28', orders: 12 },
        { date: '2026-06-29', orders: 8 },
        { date: '2026-06-30', orders: 15 },
        { date: '2026-07-01', orders: 10 },
        { date: '2026-07-02', orders: 14 },
        { date: '2026-07-03', orders: 9 },
        { date: '2026-07-04', orders: 11 },
      ] },
    })
    render(<DashboardPage />)
    await waitFor(() => {
      const svg = findOrderTrendSvg()
      expect(svg).toBeTruthy()
      if (!svg) return
      const viewBoxH = parseFloat(svg.getAttribute('viewBox')!.split(/\s+/)[3])
      const texts = svg.querySelectorAll('text')
      expect(texts.length).toBeGreaterThan(0)
      // 每个 text 的 y 坐标应离开 viewBox 底部至少 3% 的空间
      texts.forEach(t => {
        const y = parseFloat(t.getAttribute('y') || '0')
        expect(y).toBeLessThan(viewBoxH * 0.97)
      })
      // 验证包含日期标签（MM-DD 格式）
      const datePattern = /\d{2}-\d{2}/
      const hasDate = Array.from(texts).some(t => datePattern.test(t.textContent || ''))
      expect(hasDate).toBe(true)
    })
  })

  it('#942: 数据全零时趋势图正常渲染无报错', async () => {
    mockGetOrderTrend.mockResolvedValue({
      data: { data: [
        { date: '2026-06-28', orders: 0 },
        { date: '2026-06-29', orders: 0 },
      ] },
    })
    render(<DashboardPage />)
    await waitFor(() => {
      const svg = findOrderTrendSvg()
      expect(svg).toBeTruthy()
      // polyline 和 circle 都应正常渲染
      expect(svg!.querySelectorAll('polyline').length).toBeGreaterThan(0)
      expect(svg!.querySelectorAll('circle').length).toBeGreaterThan(0)
    })
  })
})
