import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from '../base.page'

/**
 * OrderShipPage POM — src/app/(dashboard)/orders/[id]/ship/ShipOrder.tsx
 *
 * Sections: confirm product info, confirm shipping address, logistics form.
 * Logistics: shipping method (radio), company (select), tracking number (input).
 * Buttons: confirm ship, cancel.
 */
export class OrderShipPage extends BasePage {
  // ─── Breadcrumb ──────────────────────────────────────────────
  readonly breadcrumb: Locator
  readonly pageTitle: Locator

  // ─── Product Confirmation Section ───────────────────────────
  readonly productSection: Locator
  readonly actualAmountLabel: Locator
  readonly productTable: Locator
  readonly processingTable: Locator

  // ─── Shipping Address Section ───────────────────────────────
  readonly addressSection: Locator
  readonly receiverName: Locator
  readonly receiverPhone: Locator
  readonly receiverAddress: Locator

  // ─── Logistics Form Section ─────────────────────────────────
  readonly logisticsSection: Locator
  readonly logisticsShippingRadio: Locator
  readonly noLogisticsRadio: Locator
  readonly companySelect: Locator
  readonly trackingNoInput: Locator

  // ─── Action Buttons ─────────────────────────────────────────
  readonly confirmShipButton: Locator
  readonly cancelShipButton: Locator

  constructor(page: Page) {
    super(page)

    // Breadcrumb & title
    this.breadcrumb = page.locator('.flex.items-center.gap-1\\.5')
    this.pageTitle = page.locator('h1').filter({ hasText: /商品发货/ })

    // Product section
    this.productSection = page.locator('.bg-white.rounded-lg.border').filter({ hasText: /商品信息/ })
    this.actualAmountLabel = this.productSection.locator('span').filter({ hasText: /订单实收款/ })
    this.productTable = this.productSection.locator('table')
    this.processingTable = page.locator('table').filter({ hasText: /加工项/ })

    // Address section
    this.addressSection = page.locator('.bg-white.rounded-lg.border').filter({ hasText: /收货信息/ })
    this.receiverName = this.addressSection.locator('span.text-gray-900').nth(0)
    this.receiverPhone = this.addressSection.locator('span.text-gray-900').nth(1)
    this.receiverAddress = this.addressSection.locator('span.text-gray-900').nth(2)

    // Logistics form — radio buttons: "物流发货" / "无需物流"
    this.logisticsSection = page.locator('.bg-white.rounded-lg.border').last()
    this.logisticsShippingRadio = page.locator('label').filter({ hasText: /物流发货/ }).locator('input[type="radio"]')
    this.noLogisticsRadio = page.locator('label').filter({ hasText: /无需物流/ }).locator('input[type="radio"]')
    this.companySelect = this.logisticsSection.locator('select')
    this.trackingNoInput = this.logisticsSection.locator('input[placeholder="请输入快递单号"]')

    // Action buttons
    this.confirmShipButton = page.getByRole('button', { name: /确认发货/ })
    this.cancelShipButton = page.getByRole('button', { name: /取消发货/ })
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(orderId: string): Promise<void> {
    await this.page.goto(`/orders/${orderId}/ship`)
    await this.waitForLoadingComplete()
  }

  // ─── Logistics Actions ──────────────────────────────────────

  async selectLogisticsShipping(): Promise<void> {
    await this.logisticsShippingRadio.click()
  }

  async selectNoLogistics(): Promise<void> {
    await this.noLogisticsRadio.click()
  }

  async selectCompany(company: string): Promise<void> {
    await this.companySelect.selectOption(company)
  }

  async fillTrackingNo(trackingNo: string): Promise<void> {
    await this.trackingNoInput.fill(trackingNo)
  }

  async fillLogisticsForm(company: string, trackingNo: string): Promise<void> {
    await this.selectCompany(company)
    await this.fillTrackingNo(trackingNo)
  }

  // ─── Submit Actions ─────────────────────────────────────────

  async confirmShip(): Promise<void> {
    await this.confirmShipButton.click()
  }

  async cancelShip(): Promise<void> {
    await this.cancelShipButton.click()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectOnShipPage(orderId?: string): Promise<void> {
    const pattern = orderId ? new RegExp(`/orders/${orderId}/ship`) : /\/orders\/[^/]+\/ship/
    await expect(this.page).toHaveURL(pattern)
  }

  async expectProductTableVisible(): Promise<void> {
    await expect(this.productTable).toBeVisible()
  }

  async expectAddressVisible(): Promise<void> {
    await expect(this.addressSection).toBeVisible()
  }

  async expectLogisticsFormVisible(): Promise<void> {
    await expect(this.companySelect).toBeVisible()
    await expect(this.trackingNoInput).toBeVisible()
  }

  async expectNoLogisticsSelected(): Promise<void> {
    await expect(this.companySelect).toBeHidden()
    await expect(this.trackingNoInput).toBeHidden()
  }

  async expectReceiverInfo(name: string, phone: string): Promise<void> {
    await expect(this.receiverName).toContainText(name)
    await expect(this.receiverPhone).toContainText(phone)
  }

  async expectActualAmount(amount: string): Promise<void> {
    await expect(this.actualAmountLabel).toContainText(amount)
  }

  async expectCompanyOptions(companies: string[]): Promise<void> {
    for (const company of companies) {
      await expect(this.companySelect.locator(`option[value="${company}"]`)).toBeAttached()
    }
  }
}
