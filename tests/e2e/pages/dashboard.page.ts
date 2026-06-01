import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from './base.page'

/**
 * DashboardPage POM — src/app/(dashboard)/dashboard/page.tsx
 *
 * Components:
 *   - 4 StatCards (今日订单, 客户总数, 活跃会话, 本月收入)
 *   - OrderTrendChart with 7/30 day selectors
 *   - OrderStatusChart (pie chart)
 *   - RecentOrders table
 *   - ActiveSessions panel
 */
export class DashboardPage extends BasePage {
  // ─── Header ──────────────────────────────────────────────────
  readonly welcomeHeading: Locator
  readonly dateDisplay: Locator

  // ─── Stat Cards ──────────────────────────────────────────────
  readonly statCards: Locator
  readonly todayOrdersCard: Locator
  readonly totalCustomersCard: Locator
  readonly activeSessionsCard: Locator
  readonly monthRevenueCard: Locator

  // ─── Order Trend Chart ───────────────────────────────────────
  readonly trendChart: Locator
  readonly trendChartTitle: Locator
  readonly sevenDayButton: Locator
  readonly thirtyDayButton: Locator

  // ─── Order Status Pie Chart ──────────────────────────────────
  readonly statusChart: Locator

  // ─── Recent Orders ───────────────────────────────────────────
  readonly recentOrdersSection: Locator
  readonly recentOrdersTable: Locator

  // ─── Active Sessions ─────────────────────────────────────────
  readonly activeSessionsSection: Locator

  // ─── Loading ─────────────────────────────────────────────────
  readonly skeletonCards: Locator

  constructor(page: Page) {
    super(page)

    // Header
    this.welcomeHeading = page.locator('h1').filter({ hasText: /欢迎回来/ })
    this.dateDisplay = page.locator('p').filter({ hasText: /\d{4}年\d{1,2}月\d{1,2}日/ })

    // Stat cards (grid of 4)
    this.statCards = page.locator('.grid.grid-cols-1.sm\\:grid-cols-2.lg\\:grid-cols-4 > div')
    this.todayOrdersCard = this.statCards.nth(0)
    this.totalCustomersCard = this.statCards.nth(1)
    this.activeSessionsCard = this.statCards.nth(2)
    this.monthRevenueCard = this.statCards.nth(3)

    // Trend chart
    this.trendChart = page.locator('.bg-white.rounded-xl.border').filter({ hasText: /订单趋势/ })
    this.trendChartTitle = page.getByText('订单趋势')
    this.sevenDayButton = page.getByRole('button', { name: '近7天' })
    this.thirtyDayButton = page.getByRole('button', { name: '近30天' })

    // Pie chart
    this.statusChart = page.locator('.bg-white.rounded-xl.border').nth(1)

    // Recent orders
    this.recentOrdersSection = page.locator('.grid.grid-cols-1.lg\\:grid-cols-2 > div').first()
    this.recentOrdersTable = this.recentOrdersSection.locator('table')

    // Active sessions
    this.activeSessionsSection = page.locator('.grid.grid-cols-1.lg\\:grid-cols-2 > div').last()

    // Loading
    this.skeletonCards = page.locator('.animate-pulse')
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(): Promise<void> {
    await this.page.goto('/dashboard')
    await this.waitForLoadingComplete()
  }

  // ─── Actions ─────────────────────────────────────────────────

  async selectTrendRange(days: 7 | 30): Promise<void> {
    if (days === 7) {
      await this.sevenDayButton.click()
    } else {
      await this.thirtyDayButton.click()
    }
  }

  async clickRecentOrder(orderId: string): Promise<void> {
    await this.recentOrdersTable.locator('tr').filter({ hasText: orderId }).click()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectStatCardsVisible(): Promise<void> {
    await expect(this.statCards).toHaveCount(4)
  }

  async expectTodayOrdersCardVisible(): Promise<void> {
    await expect(this.todayOrdersCard).toContainText('今日订单')
  }

  async expectTotalCustomersCardVisible(): Promise<void> {
    await expect(this.totalCustomersCard).toContainText('客户总数')
  }

  async expectActiveSessionsCardVisible(): Promise<void> {
    await expect(this.activeSessionsCard).toContainText('活跃会话')
  }

  async expectMonthRevenueCardVisible(): Promise<void> {
    await expect(this.monthRevenueCard).toContainText('本月收入')
  }

  async expectTrendChartVisible(): Promise<void> {
    await expect(this.trendChartTitle).toBeVisible()
  }

  async expectSevenDaySelected(): Promise<void> {
    await expect(this.sevenDayButton).toHaveClass(/bg-white/)
  }

  async expectThirtyDaySelected(): Promise<void> {
    await expect(this.thirtyDayButton).toHaveClass(/bg-white/)
  }

  async expectRecentOrdersVisible(): Promise<void> {
    await expect(this.recentOrdersSection).toBeVisible()
  }

  async expectActiveSessionsVisible(): Promise<void> {
    await expect(this.activeSessionsSection).toBeVisible()
  }

  async expectWelcomeMessage(name?: string): Promise<void> {
    const text = name ? `欢迎回来，${name}` : /欢迎回来/
    await expect(this.welcomeHeading).toContainText(text)
  }

  async expectOnDashboard(): Promise<void> {
    await expect(this.page).toHaveURL(/\/dashboard/)
  }
}
