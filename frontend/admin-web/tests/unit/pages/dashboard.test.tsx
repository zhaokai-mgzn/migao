// case_ids: UI-003, UI-004, DA-005
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
        // #1396: lowStockItems 从 stats 获取，不再调 low-stock-by-color
        lowStockItems: 2,
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

  // ── 米宝「今日经营速览」洞察条 ──

  it('洞察条置于经营看板顶部，渲染一句话经营解读（订单/环比/加工/库存串联）', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText(/今日经营速览/)).toBeInTheDocument()
      // 一句话解读：主句（订单+销售额）
      expect(screen.getByText(/今日订单 10 单、销售额 ¥3\.98万/)).toBeInTheDocument()
      // 环比句（订单+销售额）
      expect(screen.getByText(/较昨日订单 \+25\.5%、销售额 -12\.3%/)).toBeInTheDocument()
      // 提醒句（含加工占比 + 低库存）
      expect(screen.getByText(/含加工订单占 38%/)).toBeInTheDocument()
      expect(screen.getByText(/2 款商品库存偏低/)).toBeInTheDocument()
    })
    // 顶部定位：洞察条先于「待处理」区块
    const bar = screen.getByTestId('today-overview-bar')
    const pending = screen.getByText('待处理')
    expect(bar.compareDocumentPosition(pending) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('洞察句数字全部来自 API 返回值（无硬编码假数据）', async () => {
    // 改 stats → 洞察句随之变化
    mockGetStats.mockResolvedValue({
      data: {
        data: {
          todayOrders: 6,
          todaySales: 9000,
          todayOrdersChange: 8.8,
          todaySalesChange: 2.1,
          monthRevenue: 5000000,
          monthRevenueChange: 15.8,
          lowStockItems: 1,
        },
      },
    })
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText(/今日订单 6 单、销售额 ¥9,000/)).toBeInTheDocument()
      expect(screen.getByText(/较昨日订单 \+8\.8%、销售额 \+2\.1%/)).toBeInTheDocument()
      expect(screen.getByText(/1 款商品库存偏低/)).toBeInTheDocument()
    })
  })

  // ── 经营数据 ──

  it('should render business stats section (4 cards)', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('经营数据')).toBeInTheDocument()
      expect(screen.getByText('今日订单数')).toBeInTheDocument()
      expect(screen.getByText('今日销售额')).toBeInTheDocument()
      expect(screen.getByText('客单价')).toBeInTheDocument()
      expect(screen.getByText('本月销售额')).toBeInTheDocument()
    })
  })

  it('客单价 = 今日销售额 ÷ 今日订单数（数字自洽）', async () => {
    // mock: todaySales=39800, todayOrders=10 → 客单价 ¥3,980
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('¥3,980')).toBeInTheDocument()
    })
  })

  it('经营数据徽章文案口径统一：较昨日/较上月，带符号百分比', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      // 今日订单数：较昨日 +25.5%（正数带加号）
      expect(screen.getByText(/较昨日 \+25\.5%/)).toBeInTheDocument()
      // 今日销售额：较昨日 -12.3%（负数带负号）
      expect(screen.getByText(/较昨日 -12\.3%/)).toBeInTheDocument()
      // 本月销售额：较上月 +15.8% — 不再拼接「较昨天 X 较上月」
      expect(screen.getByText(/较上月 \+15\.8%/)).toBeInTheDocument()
      expect(screen.queryByText(/较昨天/)).not.toBeInTheDocument()
    })
  })

  it('涨跌语义色：上涨=绿色（好事）、下跌=红色（需关注）', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('今日订单数')).toBeInTheDocument()
    })
    // 今日订单数：+25.5% 上涨 → emerald（绿）
    const upBadge = screen.getByText(/较昨日 \+25\.5%/).closest('span')!
    expect(upBadge.className).toContain('bg-emerald-50')
    expect(upBadge.className).toContain('text-emerald-600')
    // 今日销售额：-12.3% 下跌 → red（红）
    const downBadge = screen.getByText(/较昨日 -12\.3%/).closest('span')!
    expect(downBadge.className).toContain('bg-red-50')
    expect(downBadge.className).toContain('text-red-600')
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

  it('should fetch dashboard pending counts via separate endpoints (#1396: lowStockItems from stats)', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(mockRequestGet).toHaveBeenCalledWith('/api/admin/dashboard/pending-shipment-count')
      expect(mockRequestGet).toHaveBeenCalledWith('/api/admin/dashboard/processing-shipment-count')
      // #1396: lowStockItems 从 stats.lowStockItems 获取，不再调 low-stock-by-color
      expect(mockRequestGet).not.toHaveBeenCalledWith(
        '/api/admin/products/low-stock-by-color',
        expect.anything(),
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

  it('SVG viewBox height should be ≥ 230 for date label space (A1 fix)', async () => {
    const { container } = render(<DashboardPage />)
    await waitFor(() => {
      const trendSvg = container.querySelector('svg[viewBox]')
      expect(trendSvg).toBeTruthy()
      const viewBox = trendSvg!.getAttribute('viewBox') || ''
      const parts = viewBox.split(' ')
      const height = parseInt(parts[3] || '0', 10)
      expect(height).toBeGreaterThanOrEqual(230)
    })
  })

  it('SVG should not use preserveAspectRatio="none" (A3 fix)', async () => {
    const { container } = render(<DashboardPage />)
    await waitFor(() => {
      const trendSvg = container.querySelector('svg[viewBox]')
      expect(trendSvg).toBeTruthy()
      const preserveAspectRatio = trendSvg!.getAttribute('preserveAspectRatio')
      expect(preserveAspectRatio).not.toBe('none')
    })
  })

  it('date labels should exist with proper y-coordinate above data baseline', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      const textElements = document.querySelectorAll('svg text')
      const dateLabels = Array.from(textElements).filter(
        (el) => el.textContent?.match(/^\d{2}-\d{2}$/)
      )
      expect(dateLabels.length).toBeGreaterThan(0)
      for (const label of dateLabels) {
        const y = parseFloat(label.getAttribute('y') || '0')
        expect(y).toBeGreaterThan(210)
        expect(y).toBeLessThan(240)
      }
    })
  })

  it('data circles should be positioned above date labels', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      const circles = document.querySelectorAll('svg circle')
      const textElements = document.querySelectorAll('svg text')
      const dateLabels = Array.from(textElements).filter(
        (el) => el.textContent?.match(/^\d{2}-\d{2}$/)
      )
      expect(circles.length).toBeGreaterThan(0)
      const maxLabelY = Math.max(...dateLabels.map((el) => parseFloat(el.getAttribute('y') || '0')))
      for (const circle of circles) {
        const cy = parseFloat(circle.getAttribute('cy') || '0')
        expect(cy).toBeLessThan(maxLabelY)
      }
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
      expect(screen.getByText('暂无排行数据')).toBeInTheDocument()
    })
  })

  // ── #2537 密度治理：表头「日涨」不截断 + 订单趋势 x 轴降采样 ──

  it('商品销量排行表头「日涨」列 whitespace-nowrap 不截断', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      const th = screen.getByText('日涨')
      expect(th.tagName).toBe('TH')
      expect(th.className).toContain('whitespace-nowrap')
    })
  })

  it('订单趋势 30 天数据 x 轴刻度自动降采样（标签数 ≤ 7，不密集重叠）', async () => {
    mockGetOrderTrend.mockResolvedValue({
      data: {
        data: Array.from({ length: 30 }, (_, i) => ({
          date: `2026-06-${String(30 - i).padStart(2, '0')}`,
          orders: i + 1,
        })),
      },
    })
    const { container } = render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('订单趋势')).toBeInTheDocument()
    })
    await waitFor(() => {
      // 只数订单趋势图（第一个 svg[viewBox]）的日期标签；页面有两个 TrendChart（订单趋势+销售额数据）
      const trendSvg = container.querySelector('svg[viewBox]')
      const dateLabels = trendSvg
        ? Array.from(trendSvg.querySelectorAll('text')).filter(
            (el) => el.textContent?.match(/^\d{2}-\d{2}$/)
          )
        : []
      expect(dateLabels.length).toBeGreaterThan(0)
      expect(dateLabels.length).toBeLessThanOrEqual(7)
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
      expect(screen.getByText('暂无订单数据')).toBeInTheDocument()
      expect(screen.getByText('暂无销售额数据')).toBeInTheDocument()
    })
  })

  // ── #2434: 空数据趋势图不渲染占位虚线网格 ──

  function mockEmptyTrend() {
    mockGetOrderTrend.mockResolvedValue({ data: { data: [] } })
  }

  it('空数据时订单趋势图区域不渲染占位虚线网格 (#2434)', async () => {
    mockEmptyTrend()
    const { container } = render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('暂无订单数据')).toBeInTheDocument()
    })
    // 占位虚线网格的唯一标记：svg[preserveAspectRatio="none"]（空态 loading=false，无 ChartSkeleton）
    const orderCard = screen.getByText('订单趋势').closest('.bg-white')!
    expect(orderCard.querySelectorAll('svg[preserveAspectRatio="none"]').length).toBe(0)
    expect(container.querySelectorAll('svg[preserveAspectRatio="none"]').length).toBe(0)
  })

  it('空数据时销售额趋势图区域不渲染占位虚线网格 (#2434)', async () => {
    mockEmptyTrend()
    const { container } = render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('暂无销售额数据')).toBeInTheDocument()
    })
    const salesCard = screen.getByText('销售额数据').closest('.bg-white')!
    expect(salesCard.querySelectorAll('svg[preserveAspectRatio="none"]').length).toBe(0)
    expect(container.querySelectorAll('svg[preserveAspectRatio="none"]').length).toBe(0)
  })

  it('空状态保留图标+标题+描述+创建订单CTA (#2434)', async () => {
    mockEmptyTrend()
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('暂无订单数据')).toBeInTheDocument()
      expect(screen.getByText('创建订单后，趋势图将在此展示')).toBeInTheDocument()
      expect(screen.getByText('暂无销售额数据')).toBeInTheDocument()
      expect(screen.getByText('产生订单后，销售趋势将在此展示')).toBeInTheDocument()
    })
    const ctas = screen.getAllByText('创建订单')
    expect(ctas).toHaveLength(2)
    for (const cta of ctas) {
      expect(cta.closest('a')).toHaveAttribute('href', '/orders/new')
    }
    // 图标保留：TrendingUp/DollarSign 在页面出现多次（经营数据卡片/标题也复用），
    // 这里断言空状态容器内仍保留对应图标
    const orderEmpty = screen.getByText('暂无订单数据').closest('.h-full')!
    const salesEmpty = screen.getByText('暂无销售额数据').closest('.h-full')!
    expect(orderEmpty.querySelector('[data-testid="icon-trending-up"]')).toBeTruthy()
    expect(salesEmpty.querySelector('[data-testid="icon-dollar-sign"]')).toBeTruthy()
  })

  it('有数据时订单趋势渲染折线图、销售额渲染面积图 (#2434)', async () => {
    // beforeEach 的 mockApiSuccess 已含 2 个趋势点
    const { container } = render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('订单趋势')).toBeInTheDocument()
    })
    const orderCard = screen.getByText('订单趋势').closest('.bg-white')!
    const salesCard = screen.getByText('销售额数据').closest('.bg-white')!
    // 图表 SVG 在数据加载后异步挂载：waitFor 等 SVG 到位，避免竞态 flaky
    // （曾致 deploy-frontend 单测偶发失败：expected null to be truthy）
    await waitFor(() => {
      expect(orderCard.querySelector('svg polyline')).toBeTruthy()
      expect(salesCard.querySelector('svg path')).toBeTruthy()
      expect(salesCard.querySelector('svg linearGradient')).toBeTruthy()
    })
    // 有数据时不渲染占位虚线网格
    expect(container.querySelectorAll('svg[preserveAspectRatio="none"]').length).toBe(0)
  })

  it('加载中渲染 ChartSkeleton 骨架屏 (#2434)', () => {
    // 初始 loading=true，图表区域渲染 ChartSkeleton（骨架网格 + animate-pulse 柱条）
    const { container } = render(<DashboardPage />)
    expect(container.querySelectorAll('svg[preserveAspectRatio="none"]').length).toBeGreaterThan(0)
    expect(container.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)
  })

  it('should have refresh button', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      const refreshIcon = screen.getByTestId('icon-refresh-cw')
      expect(refreshIcon).toBeInTheDocument()
    })
  })

  // ── 线上修复：织物质感 token 全面生效（#2544）──

  it('近期订单状态渲染为语义色 chips（新样式，非旧 bg-amber-100 内联徽章）', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('张三')).toBeInTheDocument()
    })
    // mock 状态：confirmed → 未知 → neutral「暂无数据」；shipped → info「已发货」
    const shipped = screen.getByText('已发货')
    expect(shipped.className).toContain('bg-primary-50')
    expect(shipped.className).toContain('border')
    // 旧内联 StatusBadge（rounded-full、bg-blue-100/bg-amber-100）不应再出现于看板近期订单
    expect(shipped.className).not.toContain('rounded-full')
    expect(shipped.className).not.toContain('bg-blue-100')
    expect(shipped.className).not.toContain('bg-amber-100')
  })

  it('看板页图标无默认蓝/紫/橙残留（text-blue/purple/orange-*）', async () => {
    const { container } = render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('本月销售额')).toBeInTheDocument()
    })
    const icons = Array.from(container.querySelectorAll('[data-testid^="icon-"]'))
    expect(icons.length).toBeGreaterThan(0)
    for (const icon of icons) {
      const cls = icon.getAttribute('class') || ''
      expect(cls).not.toMatch(/text-(blue|purple|orange)-/)
    }
  })

  it('经营数据/待处理图标使用织物质感 token 色', async () => {
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('今日订单数')).toBeInTheDocument()
    })
    // 待发货订单图标 → primary-600（原 blue-600）
    const pendingCard = screen.getByText('待发货订单').closest('a')!
    const pendingIcon = pendingCard.querySelector('[data-testid="icon-package"]')!
    expect(pendingIcon.getAttribute('class')).toContain('text-primary-600')
    // 含加工待发货图标 → accent-600（原 purple-600）
    const processCard = screen.getByText('含加工待发货订单').closest('a')!
    const processIcon = processCard.querySelector('[data-testid="icon-settings"]')!
    expect(processIcon.getAttribute('class')).toContain('text-accent-600')
    // 今日订单数图标 → primary-600（原 blue-600）
    const orderCard = screen.getByText('今日订单数').closest('.bg-white')!
    const orderIcon = orderCard.querySelector('[data-testid="icon-clipboard-list"]')!
    expect(orderIcon.getAttribute('class')).toContain('text-primary-600')
    // 本月销售额图标 → accent-600（原 orange-600）
    const monthCard = screen.getByText('本月销售额').closest('.bg-white')!
    const monthIcon = monthCard.querySelector('[data-testid="icon-dollar-sign"]')!
    expect(monthIcon.getAttribute('class')).toContain('text-accent-600')
  })

  it('近期订单空态显示「暂无近期订单」（RecentOrders emptyText prop）', async () => {
    mockGetRecentOrders.mockResolvedValue({ data: { data: [] } })
    render(<DashboardPage />)
    await waitFor(() => {
      expect(screen.getByText('暂无近期订单')).toBeInTheDocument()
    })
  })
})

