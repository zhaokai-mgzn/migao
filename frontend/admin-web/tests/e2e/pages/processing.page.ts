import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from './base.page'

/**
 * ProcessingPage POM — src/app/(dashboard)/processing/page.tsx
 *
 * Table listing processing items with add/edit modal and delete confirmation.
 */
export class ProcessingPage extends BasePage {
  // ─── Header ──────────────────────────────────────────────────
  readonly pageTitle: Locator
  readonly addButton: Locator

  // ─── Table ───────────────────────────────────────────────────
  readonly table: Locator
  readonly tableRows: Locator
  readonly loadingState: Locator
  readonly emptyState: Locator

  // ─── Add/Edit Modal ─────────────────────────────────────────
  readonly formModal: Locator
  readonly modalTitle: Locator
  readonly nameInput: Locator
  readonly priceInput: Locator
  readonly pricingMethodSelect: Locator
  readonly discountSelect: Locator
  readonly discountQtySelect: Locator
  readonly discountRateInput: Locator
  readonly modalSaveButton: Locator
  readonly modalCancelButton: Locator

  // ─── Validation Errors ──────────────────────────────────────
  readonly nameError: Locator
  readonly priceError: Locator
  readonly pricingMethodError: Locator

  // ─── Delete Confirmation ─────────────────────────────────────
  readonly deleteModal: Locator
  readonly deleteModalCancel: Locator
  readonly deleteModalConfirm: Locator

  constructor(page: Page) {
    super(page)

    // Header
    this.pageTitle = page.locator('h1').filter({ hasText: /加工项配置/ })
    this.addButton = page.getByRole('button', { name: /添加加工项/ })

    // Table
    this.table = page.locator('table')
    this.tableRows = page.locator('tbody tr')
    this.loadingState = page.locator('.animate-spin')
    this.emptyState = page.getByText(/暂无加工项/)

    // Add/Edit modal
    this.formModal = page.locator('[role="dialog"]').filter({ hasText: /新增加工项|编辑加工项/ })
    this.modalTitle = this.formModal.locator('h3, [class*="title"]')
    this.nameInput = this.formModal.locator('input[type="text"]')
    this.priceInput = this.formModal.locator('input[type="number"]')
    this.pricingMethodSelect = this.formModal.locator('select').first()
    this.discountSelect = this.formModal.locator('select').nth(1)
    this.discountQtySelect = this.formModal.locator('select').nth(2)
    this.discountRateInput = this.formModal.locator('input[placeholder="请输入折扣力度"]')
    this.modalSaveButton = this.formModal.getByRole('button', { name: /保存/ })
    this.modalCancelButton = this.formModal.getByRole('button', { name: /取消/ })

    // Validation errors inside modal
    this.nameError = this.formModal.locator('p.text-red-600').nth(0)
    this.priceError = this.formModal.locator('p.text-red-600').nth(1)
    this.pricingMethodError = this.formModal.locator('p.text-red-600').nth(2)

    // Delete modal
    this.deleteModal = page.locator('[role="dialog"]').filter({ hasText: /确认删除/ })
    this.deleteModalCancel = this.deleteModal.getByRole('button', { name: /取消/ })
    this.deleteModalConfirm = this.deleteModal.getByRole('button', { name: /确定/ })
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(): Promise<void> {
    await this.page.goto('/processing')
    await this.waitForLoadingComplete()
  }

  // ─── Actions ─────────────────────────────────────────────────

  async clickAdd(): Promise<void> {
    await this.addButton.click()
  }

  async editItem(name: string): Promise<void> {
    const row = this.tableRow(name)
    await row.getByText('编辑').click()
  }

  async deleteItem(name: string): Promise<void> {
    const row = this.tableRow(name)
    await row.getByText('删除').click()
  }

  async fillForm(data: {
    name: string
    price: string
    pricingMethod: string
  }): Promise<void> {
    await this.nameInput.fill(data.name)
    await this.priceInput.fill(data.price)
    await this.pricingMethodSelect.selectOption(data.pricingMethod)
  }

  async saveForm(): Promise<void> {
    await this.modalSaveButton.click()
  }

  async cancelForm(): Promise<void> {
    await this.modalCancelButton.click()
  }

  async confirmDelete(): Promise<void> {
    await this.deleteModalConfirm.click()
  }

  async cancelDelete(): Promise<void> {
    await this.deleteModalCancel.click()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectItemInTable(name: string): Promise<void> {
    await expect(this.tableRow(name)).toBeVisible()
  }

  async expectItemPrice(name: string, price: string): Promise<void> {
    const row = this.tableRow(name)
    await expect(row.locator('td').nth(1)).toContainText(price)
  }

  async expectItemPricingMethod(name: string, method: string): Promise<void> {
    const row = this.tableRow(name)
    await expect(row.locator('td').nth(2)).toContainText(method)
  }

  async expectFormModalVisible(title?: string): Promise<void> {
    await expect(this.formModal).toBeVisible()
    if (title) await expect(this.modalTitle).toContainText(title)
  }

  async expectDeleteModalVisible(): Promise<void> {
    await expect(this.deleteModal).toBeVisible()
  }

  async expectEmptyState(): Promise<void> {
    await expect(this.emptyState).toBeVisible()
  }

  async expectNameError(text: string | RegExp): Promise<void> {
    await expect(this.nameError).toContainText(text)
  }

  async expectPriceError(text: string | RegExp): Promise<void> {
    await expect(this.priceError).toContainText(text)
  }

  async expectOnProcessingPage(): Promise<void> {
    await expect(this.page).toHaveURL(/\/processing/)
  }
}
