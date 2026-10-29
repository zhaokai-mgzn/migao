// case_ids: UI-003, UI-004, DA-005, DA-006, DA-007
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react'

/**
 * 经营看板**首屏**判据（issue #8012：简报空态压缩 + 加载骨架 + 环比大基数保护；
 * issue #8105：待处理提到简报之前；**issue #8114：速览条 + 简报卡合并成一张「黄金策 · 今日经营」卡**）
 *
 * 病灶（2026-10-24 真栈截图 `acceptance/2026-10-24/merchant-ui-smoke-t46/out/screenshots/`）：
 *   ① 简报空态是一个约 300px 的常驻盒子（标题 + 三行说明 + 「去开启」）⇒ 「待处理」被挤到折叠线以下；
 *   ② 加载态等于空白：5 张待处理卡显示 `…`、4 个经营数据格是**白底白块**（脉冲看不见）；
 *   ③ 环比被小基数放大成误导：`+2300%`（昨日 2 单）—— 数学对、可读性为零。
 *
 * #8114 病灶（用户 2026-10-29 截图）：顶部**两块** AI 内容各占一张卡、各带 AI 标记，
 * 重复说同一件事（库存偏低 / 订单 / 销售额）—— 违反 `migao-dev-flow` §31 P2「信息不重复」。
 * ⇒ 合并成一张卡：收起态 = 速览那一句话，展开态 = 那句话 + 简报完整内容；
 *   **简报未开启时卡片仍然在**（速览不依赖简报开关），展开说「未开启」+ 去开启入口。
 *
 * 本文件的判据**只看商家第一眼看到的东西**（屏上有没有 / 是不是那个形态），不测实现细节。
 * 口径边界（不改）：分母为 0 ⇒ `—`（#5792 裁定）；加载失败 ⇒ 既有分块失败态 `dashboard-load-failed`；
 * 读不到（`stats=null`）⇒ 说「没读到」，**不说**「今日 0 单」（#6701）。
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

/** 简报已开启且**有数据**（issue #8105 的收起判据针对这一态：改前是约 400px 的完整卡片） */
function mockBriefingWithData() {
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
        // 主动检查面板：要有采集结果才渲染（收起态不应看到它）
        proactive_status: {
          low_stock: {
            rule_id: 'low_stock', rule_name: '库存告急', status: 'not_wired',
            reason: null, missing: [], gaps: [], caveats: [], display: '这项检查还没有可用数据',
          },
        },
      },
    },
  })
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

  // ── ① 合并后的一体化 AI 卡（issue #8114 四态） ──

  it('① 顶部**只有一张** AI 卡：独立的速览条 / 简报块都不在了，且它在「待处理」之前', async () => {
    mockBriefingWithData()
    render(<DashboardPage />)

    // 结构判据：一张合并卡（`daily-business-card`）承载速览那一句话
    const cards = await screen.findAllByTestId('daily-business-card')
    expect(cards).toHaveLength(1)
    expect(within(cards[0]).getByTestId('today-overview-sentence')).toBeInTheDocument()
    // 负控：改前那两块**各自**的容器不得再出现（否则又是两块 AI 内容）
    expect(screen.queryByTestId('today-overview-bar')).toBeNull()
    expect(screen.queryByTestId('dashboard-briefing-section')).toBeNull()

    // 顺序：合并卡在「待处理」之前（结构判据；真机 1440×900 的 y 坐标见 PR body）
    const pendingSection = screen.getByTestId('dashboard-pending-section')
    expect(cards[0].compareDocumentPosition(pendingSection) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    // 待处理 5 卡仍在（首屏不回归的存在性判据）
    expect(document.querySelectorAll('[data-testid="pending-card"]')).toHaveLength(5)
  })

  it('①【态 1·开启 + 有数据】收起态只有速览一句；展开出完整简报；再收起消失', async () => {
    mockBriefingWithData()
    render(<DashboardPage />)

    const toggle = await screen.findByTestId('briefing-toggle')
    // 一行摘要 = 速览那一句话 + 展开触发器（可聚焦按钮 + aria-expanded）
    expect(toggle.tagName).toBe('BUTTON')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle.textContent).toContain('展开')
    expect(screen.getByTestId('today-overview-sentence').textContent).toContain('今日订单 10 单')
    // 展开前简报内容**不在 DOM**（不是 CSS 隐藏）
    expect(screen.queryByText('昨日回顾')).toBeNull()
    expect(screen.queryByText('主动检查')).toBeNull()

    fireEvent.click(toggle)
    await waitFor(() => expect(screen.getByText('昨日回顾')).toBeInTheDocument())
    expect(screen.getByText('主动检查')).toBeInTheDocument()
    // 展开态 = 速览那句 + 简报完整内容（摘要来自 getToday）
    expect(screen.getByTestId('today-overview-sentence')).toBeInTheDocument()
    expect(screen.getByText('昨日订单 5 单，经营平稳')).toBeInTheDocument()
    expect(screen.getByTestId('briefing-toggle')).toHaveAttribute('aria-expanded', 'true')

    fireEvent.click(screen.getByTestId('briefing-toggle'))
    await waitFor(() => expect(screen.queryByText('昨日回顾')).toBeNull())
    expect(screen.getByTestId('briefing-toggle')).toHaveAttribute('aria-expanded', 'false')
    // 空态提示与「有数据」是**两套**形态，不许同屏
    expect(screen.queryByTestId('briefing-collapsed-hint')).toBeNull()
  })

  it('①【态 2·开启 + 未生成】卡片仍在，展开说「今日简报尚未生成」+ 生成入口', async () => {
    mockBriefingGetConfig.mockResolvedValue({ data: { data: { enabled: true } } })
    mockBriefingGetToday.mockResolvedValue({ data: { data: { generated: false, verifyStatus: null, content: null } } })

    render(<DashboardPage />)

    expect(await screen.findByTestId('today-overview-sentence')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('briefing-toggle'))

    const hint = await screen.findByTestId('briefing-collapsed-hint')
    expect(hint.textContent).toContain('今日简报尚未生成')
    // 行动入口仍在（不是把「怎么生成 / 怎么看」也删掉）
    const cta = within(hint).getByText('查看设置').closest('a')
    expect(cta).toHaveAttribute('href', '/settings?tab=basic')
    // 旧的大盒子空态整块不渲染
    expect(screen.queryByTestId('briefing-empty-state')).toBeNull()
    expect(screen.queryByText(/开启「智能每日经营简报」后/)).toBeNull()
    // 卡片与速览那句话仍在（空态不等于整块消失）
    expect(screen.getByTestId('daily-business-card')).toBeInTheDocument()
    expect(screen.getByTestId('today-overview-sentence')).toBeInTheDocument()
  })

  it('①【态 3·未开启】🔴 简报关掉 ⇒ 合并卡**仍在**（速览不依赖简报开关），展开说「未开启」+ 去开启入口', async () => {
    // 基线就是「企业开关关闭」（mockApiSuccess 的默认值）
    render(<DashboardPage />)

    // 核心判据：卡片在、速览照常说话
    const card = await screen.findByTestId('daily-business-card')
    expect(card).toBeInTheDocument()
    expect(screen.getByTestId('today-overview-sentence').textContent).toContain('今日订单 10 单')
    // 收起态不带任何简报空态文字（收起态就是速览那一句话）
    expect(screen.queryByTestId('briefing-collapsed-hint')).toBeNull()

    fireEvent.click(screen.getByTestId('briefing-toggle'))
    const hint = await screen.findByTestId('briefing-collapsed-hint')
    expect(hint.textContent).toContain('每日经营简报未开启')
    const cta = within(hint).getByText('开启').closest('a')
    expect(cta).toHaveAttribute('href', '/settings?tab=basic')
    // 未开启时不出简报骨架（不是「加载中」）
    expect(screen.queryByTestId('briefing-skeleton')).toBeNull()
  })

  it('①【态 4·加载中】收起态**不等简报**（先显示速览），展开才出简报骨架', async () => {
    mockBriefingGetConfig.mockResolvedValue({ data: { data: { enabled: true } } })
    mockBriefingGetToday.mockReturnValue(new Promise(() => {})) // 永不落定
    render(<DashboardPage />)

    const sentence = await screen.findByTestId('today-overview-sentence')
    await waitFor(() => expect(sentence.textContent).toContain('今日订单 10 单'))
    // 收起态不带简报骨架（速览先显示，不被简报请求拖住）
    expect(screen.queryByTestId('briefing-skeleton')).toBeNull()
    expect(screen.getByTestId('briefing-toggle')).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(screen.getByTestId('briefing-toggle'))
    expect(await screen.findByTestId('briefing-skeleton')).toBeInTheDocument()
    // 展开加载中时速览那句仍在（不是被骨架顶掉）
    expect(screen.getByTestId('today-overview-sentence')).toBeInTheDocument()
  })

  it('①【态 4·加载中】开关接口还没回来 ⇒ 不先闪「未开启」（#8012 口径在合并卡里不回退）', async () => {
    mockBriefingGetConfig.mockReturnValue(new Promise(() => {}))
    render(<DashboardPage />)

    expect(await screen.findByTestId('today-overview-sentence')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('briefing-toggle'))
    expect(await screen.findByTestId('briefing-skeleton')).toBeInTheDocument()
    expect(screen.queryByText('每日经营简报未开启')).toBeNull()
  })

  it('① 负控：`stats` 读不到 ⇒ 速览说「没读到」，**不说**「今日 0 单」（#6701 不回退）', async () => {
    mockGetStats.mockRejectedValue(new Error('boom'))
    render(<DashboardPage />)

    const sentence = await screen.findByTestId('today-overview-sentence')
    await waitFor(() => expect(sentence.textContent).toContain('经营数据没读到'))
    expect(sentence.textContent).toContain('今日订单数 —')
    // 不得把「读不到」印成经营事实
    expect(sentence.textContent).not.toContain('今日暂无新订单')
    expect(sentence.textContent).not.toMatch(/今日订单 0 单/)
    // 卡片本身仍在（读面失败不等于把整张卡藏起来）
    expect(screen.getByTestId('daily-business-card')).toBeInTheDocument()
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
