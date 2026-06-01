import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from '../base.page'

/**
 * AfterSalesListPage POM — src/app/(dashboard)/after-sales/page.tsx
 *
 * Status tabs: 全部, 待处理, 处理中, 已完成, 已拒绝, 已关闭.
 * Search: keyword + status filter.
 * Table with view action per row.
 * Create ticket modal: order search, type selector, priority, description.
 */
export class AfterSalesListPage extends BasePage {
  // ─── Header ──────────────────────────────────────────────────
  readonly pageTitle: Locator
  readonly createTicketButton: Locator

  // ─── Status Tabs ─────────────────────────────────────────────
  readonly tabBar: Locator
  readonly allTab: Locator
  readonly pendingTab: Locator
  readonly processingTab: Locator
  readonly resolvedTab: Locator
  readonly rejectedTab: Locator
  readonly closedTab: Locator

  // ─── Search ──────────────────────────────────────────────────
  readonly keywordInput: Locator
  readonly statusSelect: Locator
  readonly searchButton: Locator
  readonly resetButton: Locator

  // ─── Table ───────────────────────────────────────────────────
  readonly table: Locator
  readonly tableRows: Locator
  readonly emptyState: Locator

  // ─── Create Ticket Modal ─────────────────────────────────────
  readonly createModal: Locator
  readonly orderSearchInput: Locator
  readonly orderSearchButton: Locator
  readonly orderResults: Locator
  readonly selectedOrderBadge: Locator
  readonly changeOrderButton: Locator
  readonly typeButtons: Locator
  readonly priorityButtons: Locator
  readonly descriptionTextarea: Locator
  readonly submitTicketButton: Locator
  readonly cancelCreateButton: Locator

  constructor(page: Page) {
    super(page)

    // Header
    this.pageTitle = page.locator('h1').filter({ hasText: /售后管理/ })
    this.createTicketButton = page.getByRole('button', { name: /新建工单/ })

    // Status tabs
    this.tabBar = page.locator('.flex.items-center.gap-0.bg-white.border')
    this.allTab = this.tabBar.getByRole('button', { name: /^全部$/ })
    this.pendingTab = this.tabBar.getByRole('button', { name: /待处理/ })
    this.processingTab = this.tabBar.getByRole('button', { name: /处理中/ })
    this.resolvedTab = this.tabBar.getByRole('button', { name: /已完成/ })
    this.rejectedTab = this.tabBar.getByRole('button', { name: /已拒绝/ })
    this.closedTab = this.tabBar.getByRole('button', { name: /已关闭/ })

    // Search
    this.keywordInput = page.locator('input[placeholder*="工单号"]')
    this.statusSelect = page.locator('select').first()
    this.searchButton = page.getByRole('button', { name: /搜索/ })
    this.resetButton = page.getByRole('button', { name: /重置/ })

    // Table
    this.table = page.locator('table')
    this.tableRows = page.locator('tbody tr')
    this.emptyState = page.getByText(/暂无售后工单/)

    // Create ticket modal
    this.createModal = page.locator('[role="dialog"]').filter({ hasText: /新建售后工单/ })
    this.orderSearchInput = this.createModal.locator('input[placeholder*="订单号"]')
    this.orderSearchButton = this.createModal.locator('button').filter({ has: page.locator('svg') }).first()
    this.orderResults = this.createModal.locator('button').filter({ hasText: /ORD|orderNo/ })
    this.selectedOrderBadge = this.createModal.locator('.bg-primary-50')
    this.changeOrderButton = this.createModal.getByRole('button', { name: /更换/ })
    this.typeButtons = this.createModal.locator('button').filter({ hasText: /退货|换货|维修|退款|投诉|其他/ })
    this.priorityButtons = this.createModal.locator('button').filter({ hasText: /普通|紧急|严重/ })
    this.descriptionTextarea = this.createModal.locator('textarea')
    this.submitTicketButton = this.createModal.getByRole('button', { name: /提交工单/ })
    this.cancelCreateButton = this.createModal.getByRole('button', { name: /取消/ })
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(): Promise<void> {
    await this.page.goto('/after-sales')
    await this.waitForLoadingComplete()
  }

  // ─── Tab Actions ─────────────────────────────────────────────

  async switchTab(tab: 'all' | 'pending' | 'processing' | 'resolved' | 'rejected' | 'closed'): Promise<void> {
    const map = { all: this.allTab, pending: this.pendingTab, processing: this.processingTab, resolved: this.resolvedTab, rejected: this.rejectedTab, closed: this.closedTab }
    await map[tab].click()
    await this.waitForLoadingComplete()
  }

  // ─── Search Actions ──────────────────────────────────────────

  async search(keyword: string): Promise<void> {
    await this.keywordInput.fill(keyword)
    await this.searchButton.click()
    await this.waitForLoadingComplete()
  }

  async resetSearch(): Promise<void> {
    await this.resetButton.click()
    await this.waitForLoadingComplete()
  }

  // ─── Row Actions ─────────────────────────────────────────────

  async viewTicket(ticketNo: string): Promise<void> {
    await this.tableRow(ticketNo).getByText('查看').click()
  }

  // ─── Create Ticket ──────────────────────────────────────────

  async openCreateModal(): Promise<void> {
    await this.createTicketButton.click()
  }

  async searchOrder(keyword: string): Promise<void> {
    await this.orderSearchInput.fill(keyword)
    await this.orderSearchButton.click()
  }

  async selectOrder(orderNo: string): Promise<void> {
    await this.orderResults.filter({ hasText: orderNo }).click()
  }

  async selectTicketType(type: string): Promise<void> {
    await this.typeButtons.filter({ hasText: type }).click()
  }

  async selectPriority(priority: string): Promise<void> {
    await this.priorityButtons.filter({ hasText: priority }).click()
  }

  async fillDescription(text: string): Promise<void> {
    await this.descriptionTextarea.fill(text)
  }

  async submitTicket(): Promise<void> {
    await this.submitTicketButton.click()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectTicketVisible(ticketNo: string): Promise<void> {
    await expect(this.tableRow(ticketNo)).toBeVisible()
  }

  async expectTabActive(tab: string): Promise<void> {
    const map: Record<string, Locator> = { all: this.allTab, pending: this.pendingTab, processing: this.processingTab, resolved: this.resolvedTab, rejected: this.rejectedTab, closed: this.closedTab }
    await expect(map[tab]).toHaveClass(/text-primary-600/)
  }

  async expectCreateModalVisible(): Promise<void> {
    await expect(this.createModal).toBeVisible()
  }

  async expectEmptyState(): Promise<void> {
    await expect(this.emptyState).toBeVisible()
  }

  async expectOnAfterSalesPage(): Promise<void> {
    await expect(this.page).toHaveURL(/\/after-sales/)
  }
}
