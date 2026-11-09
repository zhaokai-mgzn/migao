// case_ids: UI-150, DA-005
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

/**
 * 经营报表页（issue #8852）：把原「经营概览」（`/dashboard`）与「报表中心」（`/reports`）合并为
 * **一个**页面 `/dashboard`，按「查看 → 分析 → 管理」分区 —— 本文件钉的是**合并后的页面形态**：
 *
 *   ① 页面标题逐字 =「经营报表」，且**只有一处**（不出现第二个旧页头）；
 *   ② 三个分区按 DOM 顺序排列：今日经营（查看）→ 经营分析（分析）→ 经营明细（管理）；
 *   ③ 「今日经营」段 = 黄金策卡 + 待处理 5 卡 + 经营数据 3 卡（客单价已按用户 2026-11-09 要求去掉）；
 *   ④ 「经营分析」段 = 趋势/状态 + **原报表中心五张卡**（含区间筛选与说明），不是另开一页；
 *   ⑤ 「经营明细」段 = 近期订单 + 商品销量排行（下钻面）；
 *   ⑥ 页面级「刷新」同时重取看板与报表段（合并后只有一个刷新按钮）；
 *   ⑦ 旧 `/reports` 入口 = 重定向薄壳 → `/dashboard`（旧深链不 404）。
 *
 * 报表五卡自身的口径判据（空数据 ≠ 0 / 未知不填 0 / 合计不完整标注 / 一张慢不拖累其余）仍在
 * `BusinessReportsSection.test.tsx`（组件级，逐条原样保留）；本文件只判「它挂在哪、和谁同段」。
 */

const dashboardApi = vi.hoisted(() => ({
  getStats: vi.fn(),
  getOrderTrend: vi.fn(),
  getRecentOrders: vi.fn(),
  getProductRanking: vi.fn(),
  getOrderStatusDistribution: vi.fn(),
}))
const briefingApi = vi.hoisted(() => ({
  getConfig: vi.fn(),
  getToday: vi.fn(),
}))
const reportApi = vi.hoisted(() => ({
  orderMargins: vi.fn(),
  inventoryAging: vi.fn(),
  staffPerformance: vi.fn(),
  qualityCost: vi.fn(),
  receivableAging: vi.fn(),
  qualityCostBreakdown: vi.fn(),
}))
const warehouseApi = vi.hoisted(() => ({ list: vi.fn() }))

vi.mock('@/lib/api', () => ({ dashboardApi, briefingApi, reportApi, warehouseApi }))
vi.mock('@/store/auth', () => ({
  useAuthStore: (selector: any) => selector({ user: { capabilities: {} } }),
}))
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))
const redirectMock = vi.hoisted(() => vi.fn())
vi.mock('next/navigation', () => ({ redirect: (...args: any[]) => redirectMock(...args) }))

import DashboardPage from '@/app/(dashboard)/dashboard/page'
import ReportsRedirectPage from '@/app/(dashboard)/reports/page'

const wrap = <T,>(data: T) => Promise.resolve({ data: { success: true, data } })

function mockSuccess() {
  dashboardApi.getStats.mockResolvedValue(wrap({
    todayOrders: 10,
    todayOrdersChange: 25.5,
    todaySales: 39800,
    todaySalesChange: -12.3,
    monthRevenue: 5000000,
    monthRevenueChange: 15.8,
    lowStockItems: 2,
    pendingShipOrders: 8,
    pendingPaymentOrders: 6,
    overdueTickets: 4,
    processingPendingOrders: 3,
  }))
  dashboardApi.getOrderTrend.mockResolvedValue(wrap([
    { date: '2026-11-08', orders: 5, amount: 2000 },
    { date: '2026-11-09', orders: 10, amount: 39800 },
  ]))
  dashboardApi.getRecentOrders.mockResolvedValue(wrap([
    { id: '1', orderNo: 'ORD-001', customerName: '张三', totalAmount: 398, status: 'confirmed', createdAt: '2026-11-09T08:00:00Z' },
  ]))
  dashboardApi.getProductRanking.mockResolvedValue(wrap([
    { rank: 1, productId: 'p1', productName: '遮光窗帘A款', salesQty: 230, salesAmount: 46000, qtyDisplay: '230', amountDisplay: '¥46,000', dailyChange: 12 },
  ]))
  dashboardApi.getOrderStatusDistribution.mockResolvedValue(wrap([
    { status: 'pending_ship', label: '待发货', count: 14, color: '#48618f' },
  ]))
  briefingApi.getConfig.mockResolvedValue(wrap({ enabled: false }))
  briefingApi.getToday.mockResolvedValue(wrap({ generated: false, verifyStatus: null, content: null }))

  reportApi.orderMargins.mockResolvedValue(wrap({
    hasData: true,
    rows: [],
    totals: { revenue: 33600, refunded: 0, fabricCost: 12000, laborCost: 3000, grossMargin: 18600 },
    unknownCostOrders: 0,
  }))
  reportApi.inventoryAging.mockResolvedValue(wrap({
    slowMovingDays: 90, hasData: true, rows: [],
    totals: { onHand: 8420.5, slowMovingOnHand: 2310.4, slowMovingBatches: 7 }, undeterminedRows: 0,
  }))
  reportApi.staffPerformance.mockResolvedValue(wrap({
    hasData: true,
    rows: [{ staffId: 'u1', staffName: '王小美', orderCount: 11, revenue: 2117, avgOrderValue: 192.45 }],
    totals: { orderCount: 11, revenue: 2117 },
    unattributedOrders: 0,
  }))
  reportApi.qualityCost.mockResolvedValue(wrap({
    components: [{ code: 'rework_labor', label: '返工工时', amount: 100, known: true, note: '', unknownItems: 0 }],
    total: 100,
    complete: true,
    unknownComponents: [],
  }))
  reportApi.receivableAging.mockResolvedValue(wrap({
    asOf: '2026-11-09',
    hasData: true,
    customerCount: 1,
    buckets: [{ bucket: 'NOT_DUE', label: '未到期', amount: 1200, orderCount: 1 }],
    customers: [],
    totals: { outstanding: 1200, overdue: 0, orderCount: 1 },
  }))
  reportApi.qualityCostBreakdown.mockImplementation((dim: string) => wrap({
    dimension: dim,
    scope: 'x',
    startDate: null,
    endDate: null,
    hasData: false,
    rows: [],
    totals: null,
    unattributed: { rework: 0, reworkLines: 0, compensation: 0, compensationCount: 0, total: 0, reason: '' },
    notes: [],
  }))
  warehouseApi.list.mockResolvedValue(wrap([{ id: 1, code: 'WH01', name: '主仓' }]))
}

describe('经营报表页（issue #8852 合并后的信息架构）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSuccess()
  })

  it('① 标题逐字「经营报表」，旧的两处页头不再出现', async () => {
    render(<DashboardPage />)
    await screen.findByTestId('daily-business-card')

    expect(screen.getByRole('heading', { level: 1, name: '经营报表' })).toBeInTheDocument()
    // 负控：合并后不允许再出现旧页名（否则用户会以为还是两页）
    expect(screen.queryByText('经营概览')).toBeNull()
    expect(screen.queryByText('报表中心')).toBeNull()
  })

  it('② 三段按「查看 → 分析 → 管理」的 DOM 顺序排列', async () => {
    render(<DashboardPage />)
    await screen.findByTestId('daily-business-card')

    const overview = screen.getByTestId('business-reports-section-overview')
    const analysis = screen.getByTestId('business-reports-section-analysis')
    const records = screen.getByTestId('business-reports-section-records')

    expect(overview.compareDocumentPosition(analysis) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(analysis.compareDocumentPosition(records) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    // 段标题与用途（查看 / 分析 / 管理）同屏可读，不是三条无名区块
    expect(within(overview).getByText('今日经营')).toBeInTheDocument()
    expect(within(overview).getByTestId('business-reports-section-overview-hint').textContent).toContain('查看')
    expect(within(analysis).getByText('经营分析')).toBeInTheDocument()
    expect(within(analysis).getByTestId('business-reports-section-analysis-hint').textContent).toContain('分析')
    expect(within(records).getByText('经营明细')).toBeInTheDocument()
    expect(within(records).getByTestId('business-reports-section-records-hint').textContent).toContain('管理')
  })

  it('③ 今日经营段：黄金策卡 + 待处理 5 卡 + 经营数据 3 卡都在（首屏内容不回退）', async () => {
    render(<DashboardPage />)
    const overview = await screen.findByTestId('business-reports-section-overview')

    expect(within(overview).getByTestId('daily-business-card')).toBeInTheDocument()
    expect(within(overview).getByTestId('dashboard-pending-section')).toBeInTheDocument()
    expect(overview.querySelectorAll('[data-testid="pending-card"]')).toHaveLength(5)
    // 经营数据 3 卡（今日订单/今日销售额/本月销售额）——「客单价」已去掉
    await waitFor(() => expect(within(overview).getByTestId('stats-card-today-orders')).toBeInTheDocument())
    expect(within(overview).getByTestId('stats-card-today-sales')).toBeInTheDocument()
    expect(within(overview).getByTestId('stats-card-month-revenue')).toBeInTheDocument()
    expect(within(overview).queryByTestId('stats-card-avg-order-value')).toBeNull()
  })

  it('④ 经营分析段：趋势/状态 + 原报表中心五张卡（含区间筛选）都挂在这一段里', async () => {
    render(<DashboardPage />)
    const analysis = await screen.findByTestId('business-reports-section-analysis')

    // 原经营概览的分析块
    expect(within(analysis).getByText('订单趋势')).toBeInTheDocument()
    expect(within(analysis).getByText('销售额数据')).toBeInTheDocument()
    expect(within(analysis).getByText('订单状态分布')).toBeInTheDocument()
    // 原报表中心整段（组件自带区间筛选、五张卡、导出与空态口径）
    const reports = within(analysis).getByTestId('business-reports-section')
    expect(reports).toBeInTheDocument()
    expect(within(reports).getByTestId('reports-filter')).toBeInTheDocument()
    await waitFor(() => expect(within(reports).getByTestId('reports-margin-body')).toBeInTheDocument())
    expect(within(reports).getByTestId('reports-margin-gross').textContent).toContain('18,600.00')
    expect(within(reports).getByTestId('reports-inventory-body')).toBeInTheDocument()
    expect(within(reports).getByTestId('reports-staff-body')).toBeInTheDocument()
    expect(within(reports).getByTestId('reports-quality-body')).toBeInTheDocument()
    expect(within(reports).getByTestId('reports-aging-body')).toBeInTheDocument()
    // 区间只作用三张表的说明必须跟着筛选条一起进「分析」段（不能丢在旧页面里）
    expect(within(reports).getByTestId('reports-filter-note').textContent).toContain('库存滞销与应收账龄是「此刻」读数')
  })

  it('⑤ 经营明细段：近期订单 + 商品销量排行（管理/下钻面）', async () => {
    render(<DashboardPage />)
    const records = await screen.findByTestId('business-reports-section-records')

    expect(within(records).getByText('近期订单')).toBeInTheDocument()
    expect(within(records).getByText('商品销量排行')).toBeInTheDocument()
    expect(within(records).getByText('遮光窗帘A款')).toBeInTheDocument()
    // 明细段不得出现报表五卡（同一类数据只出现在一个段里）
    expect(within(records).queryByTestId('reports-filter')).toBeNull()
  })

  it('⑥ 页面级「刷新」同时重取报表段（合并后只有一个刷新按钮）', async () => {
    render(<DashboardPage />)
    await screen.findByTestId('reports-margin-body')
    const before = reportApi.orderMargins.mock.calls.length

    fireEvent.click(screen.getByRole('button', { name: /刷新/ }))
    await waitFor(() => expect(reportApi.orderMargins.mock.calls.length).toBeGreaterThan(before))
  })

  it('⑦ 旧 /reports 入口 = 重定向薄壳 → /dashboard', () => {
    redirectMock.mockClear()
    ReportsRedirectPage()
    expect(redirectMock).toHaveBeenCalledWith('/dashboard')
  })
})
