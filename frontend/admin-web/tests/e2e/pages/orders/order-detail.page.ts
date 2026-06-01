import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from '../base.page'

/**
 * OrderDetailPage POM — src/app/(dashboard)/orders/[id]/OrderDetail.tsx
 *
 * Status section (varies by order status), basic info, product table,
 * processing table, shipping info, and action buttons/modals.
 */
export class OrderDetailPage extends BasePage {
  // ─── Breadcrumb ──────────────────────────────────────────────
  readonly breadcrumb: Locator

  // ─── Status Section ─────────────────────────────────────────
  readonly statusSection: Locator
  readonly statusHeading: Locator
  readonly countdownDisplay: Locator
  readonly closeOrderButton: Locator
  readonly confirmPaymentButton: Locator
  readonly shipButton: Locator
  readonly editLogisticsButton: Locator
  readonly confirmReceiveButton: Locator

  // ─── Progress Steps ─────────────────────────────────────────
  readonly progressSteps: Locator

  // ─── Basic Info ─────────────────────────────────────────────
  readonly basicInfoSection: Locator
  readonly orderNoValue: Locator
  readonly createdAtValue: Locator
  readonly paidAtValue: Locator
  readonly shippedAtValue: Locator

  // ─── Product Table ──────────────────────────────────────────
  readonly productSection: Locator
  readonly actualAmountLabel: Locator
  readonly productTable: Locator
  readonly productRows: Locator

  // ─── Processing Table ───────────────────────────────────────
  readonly processingTable: Locator
  readonly processingRows: Locator
  readonly processingTotal: Locator

  // ─── Shipping Info ──────────────────────────────────────────
  readonly shippingInfoSection: Locator
  readonly receiverName: Locator
  readonly receiverPhone: Locator
  readonly receiverAddress: Locator

  // ─── Modals ─────────────────────────────────────────────────
  readonly closeModal: Locator
  readonly confirmPaymentModal: Locator
  readonly confirmReceiveModal: Locator
  readonly logisticsModal: Locator
  readonly modalConfirmButton: Locator
  readonly modalCancelButton: Locator

  constructor(page: Page) {
    super(page)

    // Breadcrumb
    this.breadcrumb = page.locator('.flex.items-center.gap-1\\.5')

    // Status section — white card at top
    this.statusSection = page.locator('.bg-white.rounded-lg.border').first()
    this.statusHeading = this.statusSection.locator('.text-2xl').first()
    this.countdownDisplay = this.statusSection.locator('span').filter({ hasText: /支付倒计时|h.*m.*s/ })
    this.closeOrderButton = this.statusSection.getByRole('button', { name: /关闭订单/ })
    this.confirmPaymentButton = this.statusSection.getByRole('button', { name: /确认付款/ })
    this.shipButton = this.statusSection.getByRole('button', { name: /^发货$/ })
    this.editLogisticsButton = this.statusSection.getByRole('button', { name: /编辑物流/ })
    this.confirmReceiveButton = this.statusSection.getByRole('button', { name: /确认收货/ })

    // Progress steps (OrderProgressSteps component)
    this.progressSteps = page.locator('[class*="progress"], [class*="steps"]').first()

    // Basic info
    this.basicInfoSection = page.locator('.bg-white.rounded-lg.border').filter({ hasText: /基础信息/ })
    this.orderNoValue = this.basicInfoSection.locator('span').filter({ hasText: /ORD/ }).first()
    this.createdAtValue = this.basicInfoSection.locator('span.text-gray-900').nth(1)
    this.paidAtValue = this.basicInfoSection.locator('span.text-gray-900').nth(2)
    this.shippedAtValue = this.basicInfoSection.locator('span.text-gray-900').nth(4)

    // Product table
    this.productSection = page.locator('.bg-white.rounded-lg.border').filter({ hasText: /商品信息/ })
    this.actualAmountLabel = this.productSection.locator('span').filter({ hasText: /订单实收款/ })
    this.productTable = this.productSection.locator('table')
    this.productRows = this.productTable.locator('tbody tr')

    // Processing table
    this.processingTable = page.locator('table').filter({ hasText: /加工项/ })
    this.processingRows = this.processingTable.locator('tbody tr')
    this.processingTotal = this.processingTable.locator('td').filter({ hasText: /¥/ }).last()

    // Shipping info
    this.shippingInfoSection = page.locator('.bg-white.rounded-lg.border').filter({ hasText: /收货信息/ })
    this.receiverName = this.shippingInfoSection.locator('span.text-gray-900').nth(0)
    this.receiverPhone = this.shippingInfoSection.locator('span.text-gray-900').nth(1)
    this.receiverAddress = this.shippingInfoSection.locator('span.text-gray-900').nth(2)

    // Modals
    this.closeModal = page.locator('[role="dialog"]').filter({ hasText: /关闭订单|关闭原因/ })
    this.confirmPaymentModal = page.locator('[role="dialog"]').filter({ hasText: /确认付款/ })
    this.confirmReceiveModal = page.locator('[role="dialog"]').filter({ hasText: /确认收货/ })
    this.logisticsModal = page.locator('[role="dialog"]').filter({ hasText: /物流/ })
    this.modalConfirmButton = page.locator('[role="dialog"]').getByRole('button', { name: /确定|确认/ })
    this.modalCancelButton = page.locator('[role="dialog"]').getByRole('button', { name: /取消/ })
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(orderId: string): Promise<void> {
    await this.page.goto(`/orders/${orderId}`)
    await this.waitForLoadingComplete()
  }

  // ─── Actions ─────────────────────────────────────────────────

  async clickCloseOrder(): Promise<void> {
    await this.closeOrderButton.click()
  }

  async clickConfirmPayment(): Promise<void> {
    await this.confirmPaymentButton.click()
  }

  async clickShip(): Promise<void> {
    await this.shipButton.click()
  }

  async clickEditLogistics(): Promise<void> {
    await this.editLogisticsButton.click()
  }

  async clickConfirmReceive(): Promise<void> {
    await this.confirmReceiveButton.click()
  }

  async confirmModalAction(): Promise<void> {
    await this.modalConfirmButton.click()
  }

  async cancelModalAction(): Promise<void> {
    await this.modalCancelButton.click()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectStatus(text: string | RegExp): Promise<void> {
    await expect(this.statusHeading).toContainText(text)
  }

  async expectPendingPayment(): Promise<void> {
    await expect(this.statusHeading).toContainText(/待买家付款/)
    await expect(this.closeOrderButton).toBeVisible()
    await expect(this.confirmPaymentButton).toBeVisible()
  }

  async expectPendingShipment(): Promise<void> {
    await expect(this.shipButton).toBeVisible()
  }

  async expectShipped(): Promise<void> {
    await expect(this.editLogisticsButton).toBeVisible()
    await expect(this.confirmReceiveButton).toBeVisible()
  }

  async expectCompleted(): Promise<void> {
    await expect(this.progressSteps).toBeVisible()
  }

  async expectClosed(): Promise<void> {
    await expect(this.statusHeading).toContainText(/已关闭/)
  }

  async expectCountdownVisible(): Promise<void> {
    await expect(this.countdownDisplay).toBeVisible()
  }

  async expectOrderNo(orderNo: string): Promise<void> {
    await expect(this.orderNoValue).toContainText(orderNo)
  }

  async expectActualAmount(amount: string): Promise<void> {
    await expect(this.actualAmountLabel).toContainText(amount)
  }

  async expectProductTableVisible(): Promise<void> {
    await expect(this.productTable).toBeVisible()
  }

  async expectProcessingTableVisible(): Promise<void> {
    await expect(this.processingTable).toBeVisible()
  }

  async expectShippingInfo(receiver: string, phone: string): Promise<void> {
    await expect(this.receiverName).toContainText(receiver)
    await expect(this.receiverPhone).toContainText(phone)
  }

  async expectCloseModalVisible(): Promise<void> {
    await expect(this.closeModal).toBeVisible()
  }

  async expectConfirmPaymentModalVisible(): Promise<void> {
    await expect(this.confirmPaymentModal).toBeVisible()
  }

  async expectConfirmReceiveModalVisible(): Promise<void> {
    await expect(this.confirmReceiveModal).toBeVisible()
  }

  async expectOnOrderDetailPage(orderId?: string): Promise<void> {
    const pattern = orderId ? new RegExp(`/orders/${orderId}`) : /\/orders\/[^/]+$/
    await expect(this.page).toHaveURL(pattern)
  }
}
