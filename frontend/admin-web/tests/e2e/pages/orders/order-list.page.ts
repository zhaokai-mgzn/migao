import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from '../base.page'

/**
 * OrderListPage POM — src/app/(dashboard)/orders/page.tsx
 *
 * Search: 订单ID, 收货人, 下单时间(from/to), 商品货号, 商品标题, 是否加工.
 * 8 status tabs: all, pending_payment, pending_shipment, shipped, completed, closed, refund, processing.
 * Table with per-status actions (view, ship, confirm payment, confirm receive, close, remark).
 * CloseOrderModal, RemarkModal.
 */
export class OrderListPage extends BasePage {
  // ─── Header ──────────────────────────────────────────────────
  readonly pageTitle: Locator
  readonly newOrderButton: Locator

  // ─── Search Form ─────────────────────────────────────────────
  readonly searchSection: Locator
  readonly orderIdInput: Locator
  readonly receiverInput: Locator
  readonly startDateInput: Locator
  readonly endDateInput: Locator
  readonly productCodeInput: Locator
  readonly productTitleInput: Locator
  readonly hasProcessingSelect: Locator
  readonly searchButton: Locator
  readonly resetButton: Locator

  // ─── Status Tabs ─────────────────────────────────────────────
  readonly tabBar: Locator
  readonly allTab: Locator
  readonly pendingPaymentTab: Locator
  readonly pendingShipmentTab: Locator
  readonly shippedTab: Locator
  readonly completedTab: Locator
  readonly closedTab: Locator
  readonly refundTab: Locator
  readonly processingTab: Locator

  // ─── Table ───────────────────────────────────────────────────
  readonly orderTable: Locator
  readonly tableRows: Locator
  readonly totalLabel: Locator

  // ─── Pagination ──────────────────────────────────────────────
  readonly prevPageButton: Locator
  readonly nextPageButton: Locator
  readonly pageButtons: Locator

  // ─── Close Order Modal ──────────────────────────────────────
  readonly closeModal: Locator
  readonly closeReasonInput: Locator
  readonly closeModalConfirm: Locator
  readonly closeModalCancel: Locator

  // ─── Remark Modal ───────────────────────────────────────────
  readonly remarkModal: Locator
  readonly remarkTextarea: Locator
  readonly remarkModalConfirm: Locator
  readonly remarkModalCancel: Locator

  constructor(page: Page) {
    super(page)

    // Header
    this.pageTitle = page.locator('h1').filter({ hasText: /订单列表/ })
    this.newOrderButton = page.getByRole('button', { name: /新增订单/ })

    // Search form — exact field labels from source: 订单ID, 收货人, 下单时间, 商品货号, 商品标题, 是否加工
    this.searchSection = page.locator('.bg-white.rounded-lg.border').first()
    this.orderIdInput = page.locator('input[placeholder="请输入订单ID"]')
    this.receiverInput = page.locator('input[placeholder="请输入收货人姓名或手机号"]')
    this.startDateInput = this.searchSection.locator('input[type="date"]').first()
    this.endDateInput = this.searchSection.locator('input[type="date"]').last()
    this.productCodeInput = page.locator('input[placeholder="请输入商品货号"]')
    this.productTitleInput = page.locator('input[placeholder="请输入商品标题"]')
    this.hasProcessingSelect = this.searchSection.locator('select')
    this.searchButton = page.getByRole('button', { name: /查询/ })
    this.resetButton = page.getByRole('button', { name: /重置/ })

    // Status tabs — from OrderStatusTabs in types
    this.tabBar = page.locator('.flex.items-center.gap-6').filter({ has: page.locator('button') })
    this.allTab = this.tabBar.getByRole('button', { name: /全部/ })
    this.pendingPaymentTab = this.tabBar.getByRole('button', { name: /待付款/ })
    this.pendingShipmentTab = this.tabBar.getByRole('button', { name: /待发货/ })
    this.shippedTab = this.tabBar.getByRole('button', { name: /已发货/ })
    this.completedTab = this.tabBar.getByRole('button', { name: /已完成/ })
    this.closedTab = this.tabBar.getByRole('button', { name: /已关闭/ })
    this.refundTab = this.tabBar.getByRole('button', { name: /退款/ })
    this.processingTab = this.tabBar.getByRole('button', { name: /含加工/ })

    // Table
    this.orderTable = page.locator('table')
    this.tableRows = page.locator('tbody tr')
    this.totalLabel = page.locator('span').filter({ hasText: /共.*条/ })

    // Pagination
    this.prevPageButton = page.getByRole('button', { name: '‹' })
    this.nextPageButton = page.getByRole('button', { name: '›' })
    this.pageButtons = page.locator('button').filter({ hasText: /^\d+$/ })

    // Close order modal (CloseOrderModal component)
    this.closeModal = page.locator('[role="dialog"]').filter({ hasText: /关闭订单|关闭原因/ })
    this.closeReasonInput = this.closeModal.locator('textarea, input[type="text"]').first()
    this.closeModalConfirm = this.closeModal.getByRole('button', { name: /确认|确定/ })
    this.closeModalCancel = this.closeModal.getByRole('button', { name: /取消/ })

    // Remark modal (RemarkModal component)
    this.remarkModal = page.locator('[role="dialog"]').filter({ hasText: /添加备注|备注/ })
    this.remarkTextarea = this.remarkModal.locator('textarea')
    this.remarkModalConfirm = this.remarkModal.getByRole('button', { name: /确认|确定|添加/ })
    this.remarkModalCancel = this.remarkModal.getByRole('button', { name: /取消/ })
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(): Promise<void> {
    await this.page.goto('/orders')
    await this.waitForLoadingComplete()
  }

  // ─── Search Actions ──────────────────────────────────────────

  async searchByOrderId(orderId: string): Promise<void> {
    await this.orderIdInput.fill(orderId)
    await this.searchButton.click()
    await this.waitForLoadingComplete()
  }

  async searchByReceiver(receiver: string): Promise<void> {
    await this.receiverInput.fill(receiver)
    await this.searchButton.click()
    await this.waitForLoadingComplete()
  }

  async searchByDateRange(from: string, to: string): Promise<void> {
    await this.startDateInput.fill(from)
    await this.endDateInput.fill(to)
    await this.searchButton.click()
    await this.waitForLoadingComplete()
  }

  async searchByProductCode(code: string): Promise<void> {
    await this.productCodeInput.fill(code)
    await this.searchButton.click()
    await this.waitForLoadingComplete()
  }

  async resetSearch(): Promise<void> {
    await this.resetButton.click()
    await this.waitForLoadingComplete()
  }

  // ─── Tab Actions ─────────────────────────────────────────────

  async switchTab(tab: 'all' | 'pending_payment' | 'pending_shipment' | 'shipped' | 'completed' | 'closed' | 'refund' | 'processing'): Promise<void> {
    const tabMap = {
      all: this.allTab,
      pending_payment: this.pendingPaymentTab,
      pending_shipment: this.pendingShipmentTab,
      shipped: this.shippedTab,
      completed: this.completedTab,
      closed: this.closedTab,
      refund: this.refundTab,
      processing: this.processingTab,
    }
    await tabMap[tab].click()
    await this.waitForLoadingComplete()
  }

  // ─── Row Actions ─────────────────────────────────────────────

  async viewOrder(rowText: string): Promise<void> {
    await this.tableRow(rowText).getByText('查看').click()
  }

  async shipOrder(rowText: string): Promise<void> {
    await this.tableRow(rowText).getByText('发货').click()
  }

  async confirmPayment(rowText: string): Promise<void> {
    await this.tableRow(rowText).getByText('确认付款').click()
    // Confirm the window.confirm dialog
    this.page.once('dialog', dialog => dialog.accept())
  }

  async confirmReceive(rowText: string): Promise<void> {
    await this.tableRow(rowText).getByText('确认收货').click()
    this.page.once('dialog', dialog => dialog.accept())
  }

  async openCloseModal(rowText: string): Promise<void> {
    await this.tableRow(rowText).getByText('关闭').click()
  }

  async openRemarkModal(rowText: string): Promise<void> {
    await this.tableRow(rowText).getByText('备注').click()
  }

  // ─── Modal Actions ───────────────────────────────────────────

  async submitCloseOrder(reason: string): Promise<void> {
    await this.closeReasonInput.fill(reason)
    await this.closeModalConfirm.click()
  }

  async submitRemark(content: string): Promise<void> {
    await this.remarkTextarea.fill(content)
    await this.remarkModalConfirm.click()
  }

  // ─── Navigation ──────────────────────────────────────────────

  async clickNewOrder(): Promise<void> {
    await this.newOrderButton.click()
  }

  // ─── Pagination ──────────────────────────────────────────────

  async goToPage(num: number): Promise<void> {
    await this.page.getByRole('button', { name: String(num), exact: true }).click()
    await this.waitForLoadingComplete()
  }

  async goNextPage(): Promise<void> {
    await this.nextPageButton.click()
    await this.waitForLoadingComplete()
  }

  async goPrevPage(): Promise<void> {
    await this.prevPageButton.click()
    await this.waitForLoadingComplete()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectOrderVisible(orderId: string): Promise<void> {
    await expect(this.tableRow(orderId)).toBeVisible()
  }

  async expectTotalCount(count: number): Promise<void> {
    await expect(this.totalLabel).toContainText(String(count))
  }

  async expectTabActive(tab: string): Promise<void> {
    const tabMap: Record<string, Locator> = {
      all: this.allTab,
      pending_payment: this.pendingPaymentTab,
      pending_shipment: this.pendingShipmentTab,
      shipped: this.shippedTab,
      completed: this.completedTab,
      closed: this.closedTab,
      refund: this.refundTab,
      processing: this.processingTab,
    }
    await expect(tabMap[tab]).toHaveClass(/text-primary-600/)
  }

  async expectCloseModalVisible(): Promise<void> {
    await expect(this.closeModal).toBeVisible()
  }

  async expectRemarkModalVisible(): Promise<void> {
    await expect(this.remarkModal).toBeVisible()
  }

  async expectOnOrderListPage(): Promise<void> {
    await expect(this.page).toHaveURL(/\/orders/)
  }
}
