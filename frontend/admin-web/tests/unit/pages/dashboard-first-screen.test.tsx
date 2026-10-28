// case_ids: UI-003, UI-004, DA-005, DA-006, DA-007
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'

/**
 * 经营看板**首屏**判据（issue #8012：简报空态压缩 + 加载骨架 + 环比大基数保护）
 *
 * 病灶（2026-10-24 真栈截图 `acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/`）：
 *   ① 简报空态是一个约 300px 的常驻盒子（标题 + 三行说明 + 「去开启」）⇒ 「待处理」被挤到折叠线以下；
 *   ② 加载态等于空白：5 张待处理卡显示 `…`、4 个经营数据格是**白底白块**（脉冲看不见）；
 *   ③ 环比被小基数放大成误导：`+2300%`（昨日 2 单）—— 数学对、可读性为零。
 *
 * 本文件的判据**只看商家第一眼看到的东西**（屏上有没有 / 是不是那个形态），不测实现细节。
 * 口径边界（不改）：分母为 0 ⇒ `—`（#5792 裁定）；加载失败 ⇒ 既有分块失败态 `dashboard-load-failed`。
 */

const mockRequestGet = vi.fn()
vi.mock('@/lib/request', () => ({
  default: { get: (...args: any[]) => mockRequestGet(...args) },
}))

const mockUseAuthStore = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: (...args: any[]) => mockUseAuthStore(...args),
}))

const mockGetStats = vi.fn()
const mockGetOrderTrend = vi.fn()
const mockGetRecentOrders = vi.fn()
const mockGetProductRanking = vi.fn()
const mockGetOrderStatus = vi.fn()
const mockBriefingGetConfig = vi.fn()
const mockBriefingGetToday = vi.fn()

vi.mock('@/lib/api', () => ({
  dashboardApi: {
    getStats: (...args: any[]) => mockGetStats(...args),
    getOrderTrend: (...args: any[]) => mockGetOrderTrend(...args),
    getRecentOrders: (...args: any[]) => mockGetRecentOrders(...args),
    getProductRanking: (...args: any[]) => mockGetProductRanking(...args),
    getOrderStatusDistribution: (...args: any[]) => mockGetOrderStatus(...args),
  },
  briefingApi: {
    getConfig: (...args: any[]) => mockBriefingGetConfig(...args),
    getToday: (...args: any[]) => mockBriefingGetToday(...args),
  },
}))

vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

import DashboardPage, { changeBadge } from '@/app/(dashboard)/dashboard/page'

/** 全成功基线；`stats` 用 overrides 做单变量对照 */
function mockApiSuccess(overrides: Record<string, unknown> = {}) {
  mockGetStats.mockResolvedValue({
    data: {
      data: {
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
        ...overrides,
      },
    },
  })
  mockGetOrderTrend.mockResolvedValue({
    data: { data: [{ date: '2026-10-27', orders: 5, amount: 200 }, { date: '2026-10-26', orders: 3, amount: 100 }] },
  })
  mockGetRecentOrders.mockResolvedValue({ data: { data: [] } })
  mockGetProductRanking.mockResolvedValue({ data: { data: [] } })
  mockGetOrderStatus.mockResolvedValue({ data: { data: [] } })
  // 简报企业开关：默认**未开启**（issue #8012 的空态压缩针对这一态）
  mockBriefingGetConfig.mockResolvedValue({ data: { data: { enabled: false } } })
  mockBriefingGetToday.mockResolvedValue({ data: { data: { generated: false, verifyStatus: null, content: null } } })
}

/** 永不落定的请求 ⇒ 页面停在「加载中」（判据只看骨架，不看时序） */
function holdLoading() {
  const pending = () => new Promise(() => {})
  mockGetStats.mockReturnValue(pending())
  mockGetOrderTrend.mockReturnValue(pending())
  mockGetRecentOrders.mockReturnValue(pending())
  mockGetProductRanking.mockReturnValue(pending())
  mockGetOrderStatus.mockReturnValue(pending())
  mockBriefingGetConfig.mockReturnValue(pending())
}

describe('经营看板首屏（issue #8012）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    for (const fn of [
      mockGetStats, mockGetOrderTrend, mockGetRecentOrders, mockGetProductRanking,
      mockGetOrderStatus, mockBriefingGetConfig, mockBriefingGetToday,
    ]) {
      fn.mockReset()
    }
    mockUseAuthStore.mockReturnValue({})
    mockApiSuccess()
  })

  // ── ① 简报空态压缩 ──

  it('① 简报未开启 ⇒ 一行摘要（briefing-collapsed-hint），旧的大盒子空态整块不渲染', async () => {
    render(<DashboardPage />)

    const hint = await screen.findByTestId('briefing-collapsed-hint')
    expect(hint.textContent).toContain('每日经营简报未开启')
    // 行动入口仍在（不是把「怎么开启」也删掉）
    const cta = within(hint).getByText('开启').closest('a')
    expect(cta).toHaveAttribute('href', '/settings?tab=basic')

    // 旧形态（约 300px：标题 + 三行说明 + 去开启）必须整块不在
    expect(screen.queryByTestId('briefing-empty-state')).toBeNull()
    expect(screen.queryByText(/开启「智能每日经营简报」后/)).toBeNull()
  })

  it('① 简报已开启但今日未生成 ⇒ 也压缩成一行（真栈截图里那 300px 大盒子就是这一态）', async () => {
    mockBriefingGetConfig.mockResolvedValue({ data: { data: { enabled: true } } })
    mockBriefingGetToday.mockResolvedValue({ data: { data: { generated: false, verifyStatus: null, content: null } } })

    render(<DashboardPage />)

    const hint = await screen.findByTestId('briefing-collapsed-hint')
    expect(hint.textContent).toContain('今日简报尚未生成')
    expect(screen.queryByTestId('briefing-empty-state')).toBeNull()
    expect(screen.queryByText(/开启「智能每日经营简报」后/)).toBeNull()
  })

  it('① 已开启且有数据 ⇒ 保持现有卡片形态（压缩只针对空态，不动有数据的卡）', async () => {
    mockBriefingGetConfig.mockResolvedValue({ data: { data: { enabled: true } } })
    mockBriefingGetToday.mockResolvedValue({
      data: {
        data: {
          generated: true,
          verifyStatus: 'verified',
          content: {
            summary: '昨日订单 5 单，经营平稳',
            review: [{ label: '今日订单', value: 5, unit: '单', change: '较昨日 +66.7%' }],
            todo: [],
            risks: [],
            suggestions: [],
          },
        },
      },
    })

    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText('每日经营简报')).toBeInTheDocument())
    // 卡片内容来自异步 getToday ⇒ 必须等渲染，否则断言的是「还没回来」
    await waitFor(() => expect(screen.getByText('昨日回顾')).toBeInTheDocument())
    expect(screen.queryByTestId('briefing-collapsed-hint')).toBeNull()
  })

  // ── ② 加载骨架 ──

  it('② 加载中 ⇒ 待处理卡渲染骨架（不渲染 `…`）、经营数据格是灰底脉冲骨架（不是白底白块）', () => {
    holdLoading()
    render(<DashboardPage />)

    const cards = document.querySelectorAll('[data-testid="pending-card"]')
    expect(cards.length).toBe(5)
    // 五张卡各有骨架块，且卡上没有 `…` 文本（「加载态等于空白」的反面）
    expect(screen.getAllByTestId('pending-skeleton')).toHaveLength(5)
    cards.forEach((card) => expect(card.textContent || '').not.toContain('…'))

    // 经营数据 4 格：骨架必须是**灰底 + 脉冲**（改前是 bg-white + animate-pulse ⇒ 屏上等于空白）
    const statsSkeletons = screen.getAllByTestId('stats-skeleton')
    expect(statsSkeletons).toHaveLength(4)
    for (const el of statsSkeletons) {
      expect(el.querySelectorAll('.animate-pulse').length).toBeGreaterThan(0)
      expect(el.querySelectorAll('.bg-neutral-200').length).toBeGreaterThan(0)
    }
  })

  it('② 负控：加载失败仍走既有分块失败态（骨架退场、dashboard-load-failed 在）', async () => {
    mockGetStats.mockRejectedValue(new Error('boom'))
    render(<DashboardPage />)

    const alert = await screen.findByTestId('dashboard-load-failed')
    expect(alert.textContent).toContain('经营数据与待处理')
    expect(screen.queryAllByTestId('pending-skeleton')).toHaveLength(0)
  })

  // ── ③ 环比大基数保护 ──

  it('③ |环比| ≥ 5（±500%）⇒ 倍数展示（+23× / -8×）+ 悬停说明「基数较小」', () => {
    const up = changeBadge('较昨日', 23)
    expect(up.text).toBe('较昨日 +23×')
    // 倍数形态下不得再叠一个百分比（两种口径同屏 = 又一次误导）
    expect(up.text).not.toContain('%')
    expect(up.title).toContain('基数较小')
    expect(up.up).toBe(true)

    const down = changeBadge('较昨日', -8)
    expect(down.text).toBe('较昨日 -8×')
    expect(down.title).toContain('基数较小')
    expect(down.up).toBe(false)

    // 边界含等号：正好 ±500% 也走倍数
    expect(changeBadge('较昨日', 5).text).toBe('较昨日 +5×')
  })

  it('③ 负控：|环比| < 5 仍是百分比；null 仍是「—」且中性（既有裁定不回退）', () => {
    expect(changeBadge('较昨日', 0.4).text).toBe('较昨日 +40%')
    expect(changeBadge('较昨日', 4.99).text).toBe('较昨日 +499%')

    const none = changeBadge('较昨日', null)
    expect(none.text).toBe('较昨日 —')
    expect(none.neutral).toBe(true)
    expect(none.title).toContain('无上期可比')
  })

  it('③ 页面徽章：后端百分比 2300 ⇒ 屏上 +23×（不是 +2300%），并带悬停说明', async () => {
    mockApiSuccess({ todayOrdersChange: 2300 })
    render(<DashboardPage />)

    await waitFor(() => expect(screen.getByText(/较昨日 \+23×/)).toBeInTheDocument())
    expect(screen.getByText(/较昨日 \+23×/).getAttribute('title')).toContain('基数较小')
    // 第一屏任何位置都不许再出现被小基数放大的 2300%
    expect(screen.queryByText(/2300%/)).toBeNull()
  })

  it('③ 洞察条同口径：+2300% ⇒ +23×（470% 未达阈值，仍保留百分比）', async () => {
    mockApiSuccess({ todayOrdersChange: 2300, todaySalesChange: 470 })
    render(<DashboardPage />)

    const sentence = await screen.findByTestId('today-overview-sentence')
    await waitFor(() => expect(sentence.textContent).toContain('较昨日订单 +23×'))
    expect(sentence.textContent).toContain('销售额 +470%')
    expect(sentence.textContent || '').not.toContain('2300%')
    expect(sentence.getAttribute('title')).toContain('基数较小')
  })
})
