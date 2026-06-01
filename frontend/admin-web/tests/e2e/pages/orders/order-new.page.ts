import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from '../base.page'

/**
 * OrderNewPage POM — src/app/(dashboard)/orders/new/page.tsx
 *
 * Multi-line-item order creation with product search modal,
 * color/SKU/processing selection, customer info, and cost summary.
 */
export class OrderNewPage extends BasePage {
  // ─── Header ──────────────────────────────────────────────────
  readonly backButton: Locator
  readonly pageTitle: Locator
  readonly pageSubtitle: Locator

  // ─── Product Line Items ──────────────────────────────────────
  readonly lineItemsContainer: Locator
  readonly addProductButton: Locator
  readonly lineItemCount: Locator

  // ─── Customer / Shipping Info ────────────────────────────────
  readonly customerNameInput: Locator
  readonly customerPhoneInput: Locator
  readonly customerAddressInput: Locator
  readonly remarkTextarea: Locator

  // ─── Cost Summary (right sidebar) ───────────────────────────
  readonly costSummarySection: Locator
  readonly productSubtotal: Locator
  readonly processingFee: Locator
  readonly orderTotal: Locator
  readonly actualAmountInput: Locator

  // ─── Submit / Cancel ────────────────────────────────────────
  readonly submitButton: Locator
  readonly cancelButton: Locator

  // ─── Product Search Modal ───────────────────────────────────
  readonly productModal: Locator
  readonly productSearchInput: Locator
  readonly productSearchButton: Locator
  readonly productResults: Locator
  readonly productModalCloseButton: Locator

  constructor(page: Page) {
    super(page)

    // Header
    this.backButton = page.locator('button[aria-label="返回"]')
    this.pageTitle = page.locator('h1').filter({ hasText: /新增订单/ })
    this.pageSubtitle = page.locator('p').filter({ hasText: /支持添加多个商品/ })

    // Line items
    this.lineItemsContainer = page.locator('.space-y-4').first()
    this.addProductButton = page.getByRole('button', { name: /添加商品/ })
    this.lineItemCount = page.locator('span').filter({ hasText: /共.*个商品/ })

    // Customer info — Input components with labels
    this.customerNameInput = page.locator('input[placeholder="请输入收货人姓名"]')
    this.customerPhoneInput = page.locator('input[placeholder="请输入 11 位手机号"]')
    this.customerAddressInput = page.locator('input[placeholder="请输入详细收货地址"]')
    this.remarkTextarea = page.locator('textarea[placeholder*="发货要求"]')

    // Cost summary
    this.costSummarySection = page.locator('.space-y-6').last()
    this.productSubtotal = this.costSummarySection.locator('span').filter({ hasText: /商品小计/ }).locator('..').locator('span').last()
    this.processingFee = this.costSummarySection.locator('span').filter({ hasText: /加工费/ }).locator('..').locator('span').last()
    this.orderTotal = this.costSummarySection.locator('.text-lg.font-semibold')
    this.actualAmountInput = this.costSummarySection.locator('input[type="number"]')

    // Submit / Cancel
    this.submitButton = page.getByRole('button', { name: /提交订单/ })
    this.cancelButton = page.getByRole('button', { name: /取消/ })

    // Product search modal
    this.productModal = page.locator('[role="dialog"]').filter({ hasText: /选择商品/ })
    this.productSearchInput = this.productModal.locator('input[placeholder*="搜索商品"]')
    this.productSearchButton = this.productModal.getByRole('button', { name: /搜索/ })
    this.productResults = this.productModal.locator('button').filter({ has: page.locator('img, svg') })
    this.productModalCloseButton = this.productModal.getByRole('button', { name: /关闭/ })
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(): Promise<void> {
    await this.page.goto('/orders/new')
    await this.waitForLoadingComplete()
  }

  // ─── Line Item Actions ──────────────────────────────────────

  /** Click the "click to search and select product" button in a line item. */
  async openProductSearch(lineIndex = 0): Promise<void> {
    const lineBlocks = this.page.locator('.rounded-xl.border.border-gray-200')
    await lineBlocks.nth(lineIndex).getByRole('button', { name: /点击搜索并选择商品/ }).click()
  }

  /** Search for a product in the modal. */
  async searchProduct(keyword: string): Promise<void> {
    await this.productSearchInput.fill(keyword)
    await this.productSearchButton.click()
  }

  /** Pick the first product from search results. */
  async pickFirstProduct(): Promise<void> {
    await this.productResults.first().click()
  }

  /** Pick a product by name from search results. */
  async pickProductByName(name: string): Promise<void> {
    await this.productResults.filter({ hasText: name }).click()
  }

  /** Remove a line item by index. */
  async removeLineItem(lineIndex: number): Promise<void> {
    const lineBlocks = this.page.locator('.rounded-xl.border.border-gray-200')
    await lineBlocks.nth(lineIndex).getByRole('button', { name: /删除/ }).click()
  }

  /** Add a new line item. */
  async addLineItem(): Promise<void> {
    await this.addProductButton.click()
  }

  /** Select a color for a line item. */
  async selectColor(lineIndex: number, colorName: string): Promise<void> {
    const lineBlocks = this.page.locator('.rounded-xl.border.border-gray-200')
    const line = lineBlocks.nth(lineIndex)
    await line.getByRole('button', { name: colorName, exact: true }).click()
  }

  /** Select a SKU/spec for a line item. */
  async selectSku(lineIndex: number, specText: string): Promise<void> {
    const lineBlocks = this.page.locator('.rounded-xl.border.border-gray-200')
    const line = lineBlocks.nth(lineIndex)
    await line.locator('button').filter({ hasText: specText }).click()
  }

  /** Set quantity for a line item. */
  async setQuantity(lineIndex: number, quantity: number): Promise<void> {
    const lineBlocks = this.page.locator('.rounded-xl.border.border-gray-200')
    const qtyInput = lineBlocks.nth(lineIndex).locator('input[type="number"]').first()
    await qtyInput.fill(String(quantity))
  }

  /** Set unit price for a line item. */
  async setUnitPrice(lineIndex: number, price: number): Promise<void> {
    const lineBlocks = this.page.locator('.rounded-xl.border.border-gray-200')
    const priceInput = lineBlocks.nth(lineIndex).locator('input[type="number"]').last()
    await priceInput.fill(String(price))
  }

  /** Toggle a processing item checkbox. */
  async toggleProcessingItem(lineIndex: number, processingName: string): Promise<void> {
    const lineBlocks = this.page.locator('.rounded-xl.border.border-gray-200')
    const line = lineBlocks.nth(lineIndex)
    const item = line.locator('.flex.items-center.gap-3').filter({ hasText: processingName })
    await item.locator('input[type="checkbox"]').click()
  }

  // ─── Customer Info Actions ──────────────────────────────────

  async fillCustomerInfo(data: {
    name: string
    phone: string
    address: string
    remark?: string
  }): Promise<void> {
    await this.customerNameInput.fill(data.name)
    await this.customerPhoneInput.fill(data.phone)
    await this.customerAddressInput.fill(data.address)
    if (data.remark) await this.remarkTextarea.fill(data.remark)
  }

  // ─── Cost Summary Actions ──────────────────────────────────

  async setActualAmount(amount: string): Promise<void> {
    await this.actualAmountInput.fill(amount)
  }

  // ─── Submit ──────────────────────────────────────────────────

  async submitOrder(): Promise<void> {
    await this.submitButton.click()
  }

  async cancelOrder(): Promise<void> {
    await this.cancelButton.click()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectOnNewOrderPage(): Promise<void> {
    await expect(this.page).toHaveURL(/\/orders\/new/)
    await expect(this.pageTitle).toBeVisible()
  }

  async expectLineItemCount(count: number): Promise<void> {
    await expect(this.lineItemCount).toContainText(String(count))
  }

  async expectProductModalVisible(): Promise<void> {
    await expect(this.productModal).toBeVisible()
  }

  async expectProductInResults(name: string): Promise<void> {
    await expect(this.productResults.filter({ hasText: name })).toBeVisible()
  }

  async expectOrderTotal(amount: string): Promise<void> {
    await expect(this.orderTotal).toContainText(amount)
  }

  async expectValidationError(text: string | RegExp): Promise<void> {
    await expect(this.page.locator('p.text-red-600, .text-red-600').filter({ hasText: text })).toBeVisible()
  }

  async expectProductSelected(lineIndex: number, productName: string): Promise<void> {
    const lineBlocks = this.page.locator('.rounded-xl.border.border-gray-200')
    await expect(lineBlocks.nth(lineIndex)).toContainText(productName)
  }
}
