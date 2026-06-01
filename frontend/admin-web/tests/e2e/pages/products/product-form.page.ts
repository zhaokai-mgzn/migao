import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from '../base.page'

/**
 * ProductFormPage POM — src/components/products/ProductForm.tsx
 *
 * Used by both /products/new and /products/[id]/edit.
 * Sections: basic info, images, attributes, SKU matrix, processing, rich text.
 * Submit buttons: draft, in_warehouse, on_sale.
 */
export class ProductFormPage extends BasePage {
  // ─── Header ──────────────────────────────────────────────────
  readonly titleHeading: Locator
  readonly resetButtonTop: Locator

  // ─── Basic Info Section ──────────────────────────────────────
  readonly categorySelect: Locator
  readonly nameInput: Locator
  readonly nameCharCount: Locator
  readonly imageUploader: Locator
  readonly skuCodeInput: Locator
  readonly brandInput: Locator
  readonly unitSelect: Locator

  // ─── Sales Info / SKU Matrix ─────────────────────────────────
  readonly skuMatrixSection: Locator
  readonly addColorButton: Locator
  readonly addSellingMethodButton: Locator
  readonly addDoorWidthButton: Locator
  readonly totalStockInput: Locator
  readonly stockDeductionYes: Locator
  readonly stockDeductionNo: Locator
  readonly supportsProcessingYes: Locator
  readonly supportsProcessingNo: Locator

  // ─── Processing Config ───────────────────────────────────────
  readonly processingSelects: Locator
  readonly processingPriceInputs: Locator
  readonly addProcessingButton: Locator

  // ─── Rich Text & Detail Images ──────────────────────────────
  readonly descriptionEditor: Locator
  readonly detailImageUploader: Locator

  // ─── Bottom Submit Bar ──────────────────────────────────────
  readonly submitBar: Locator
  readonly resetButtonBottom: Locator
  readonly draftButton: Locator
  readonly warehouseButton: Locator
  readonly onSaleButton: Locator

  // ─── Validation errors ──────────────────────────────────────
  readonly errorMessages: Locator

  constructor(page: Page) {
    super(page)

    // Header
    this.titleHeading = page.locator('h2').filter({ hasText: /新增商品|编辑商品/ })
    this.resetButtonTop = page.getByRole('button', { name: /重置/ }).first()

    // Basic info — field IDs come from the Input/Select components
    this.categorySelect = page.locator('#pf-category').locator('select').or(page.locator('#pf-category select'))
    this.nameInput = page.locator('#pf-name').locator('input').or(page.locator('#pf-name input'))
    this.nameCharCount = page.locator('#pf-name').locator('span').last()
    this.imageUploader = page.locator('#pf-images')
    this.skuCodeInput = page.locator('#pf-sku-code').locator('input').or(page.locator('#pf-sku-code input'))
    this.brandInput = page.locator('input[placeholder*="品牌"]')
    this.unitSelect = page.locator('select').filter({ has: page.locator('option[value="米"]') })

    // SKU Matrix
    this.skuMatrixSection = page.locator('#pf-skus')
    this.addColorButton = page.locator('#pf-colors').getByRole('button', { name: /添加/ }).first()
    this.addSellingMethodButton = page.locator('#pf-selling-methods').getByRole('button', { name: /添加/ }).first()
    this.addDoorWidthButton = page.locator('#pf-door-widths').getByRole('button', { name: /添加/ }).first()
    this.totalStockInput = page.locator('input[readonly]')
    this.stockDeductionYes = page.getByText('是', { exact: true }).first()
    this.stockDeductionNo = page.getByText('否（付款减库存）', { exact: true })
    this.supportsProcessingYes = page.locator('label').filter({ hasText: /^是$/ }).first()
    this.supportsProcessingNo = page.locator('label').filter({ hasText: /^否$/ }).first()

    // Processing config
    this.processingSelects = page.locator('#pf-processing select')
    this.processingPriceInputs = page.locator('#pf-processing input[type="number"]')
    this.addProcessingButton = page.locator('#pf-processing').getByRole('button', { name: /添加/ }).or(
      page.locator('#pf-processing button[title="添加"]')
    )

    // Rich text
    this.descriptionEditor = page.locator('[contenteditable="true"]').first()
    this.detailImageUploader = page.locator('.border-dashed').last()

    // Bottom submit bar
    this.submitBar = page.locator('.fixed.bottom-0')
    this.resetButtonBottom = this.submitBar.getByRole('button', { name: /重置/ })
    this.draftButton = this.submitBar.getByRole('button', { name: /存草稿/ })
    this.warehouseButton = this.submitBar.getByRole('button', { name: /提交并放入仓库/ })
    this.onSaleButton = this.submitBar.getByRole('button', { name: /提交并上架|保存修改/ })

    // Validation
    this.errorMessages = page.locator('p.text-red-600, p.text-sm.text-red-600')
  }

  // ─── Navigation ──────────────────────────────────────────────

  async gotoNew(): Promise<void> {
    await this.page.goto('/products/new')
    await this.waitForLoadingComplete()
  }

  async gotoEdit(productId: string): Promise<void> {
    await this.page.goto(`/products/${productId}/edit`)
    await this.waitForLoadingComplete()
  }

  // ─── Basic Info Actions ──────────────────────────────────────

  async selectCategory(categoryLabel: string): Promise<void> {
    await this.categorySelect.selectOption({ label: categoryLabel })
  }

  async fillName(name: string): Promise<void> {
    await this.nameInput.fill(name)
  }

  async fillSkuCode(code: string): Promise<void> {
    await this.skuCodeInput.fill(code)
  }

  async fillBrand(brand: string): Promise<void> {
    await this.brandInput.fill(brand)
  }

  // ─── Image Upload ────────────────────────────────────────────

  async uploadMainImages(paths: string[]): Promise<void> {
    const fileInput = this.imageUploader.locator('input[type="file"]')
    await fileInput.setInputFiles(paths)
  }

  async uploadDetailImages(paths: string[]): Promise<void> {
    const fileInput = this.detailImageUploader.locator('input[type="file"]')
    await fileInput.setInputFiles(paths)
  }

  // ─── SKU Matrix ─────────────────────────────────────────────

  async addColor(name: string, imagePath?: string): Promise<void> {
    await this.addColorButton.click()
    const inputs = this.page.locator('#pf-colors input[type="text"]')
    await inputs.last().fill(name)
    if (imagePath) {
      const fileInput = this.page.locator('#pf-colors input[type="file"]').last()
      await fileInput.setInputFiles(imagePath)
    }
  }

  // ─── Submit Actions ─────────────────────────────────────────

  async saveAsDraft(): Promise<void> {
    await this.draftButton.click()
  }

  async submitToWarehouse(): Promise<void> {
    await this.warehouseButton.click()
  }

  async submitAndPutOnSale(): Promise<void> {
    await this.onSaleButton.click()
  }

  async resetForm(): Promise<void> {
    await this.resetButtonTop.click()
    // Handle the confirm() dialog
    this.page.once('dialog', dialog => dialog.accept())
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectOnNewProductPage(): Promise<void> {
    await expect(this.page).toHaveURL(/\/products\/new/)
    await expect(this.titleHeading).toContainText('新增商品')
  }

  async expectOnEditProductPage(): Promise<void> {
    await expect(this.page).toHaveURL(/\/products\/.*\/edit/)
    await expect(this.titleHeading).toContainText('编辑商品')
  }

  async expectValidationError(text: string | RegExp): Promise<void> {
    await expect(this.errorMessages.filter({ hasText: text })).toBeVisible()
  }

  async expectSubmitBarVisible(): Promise<void> {
    await expect(this.submitBar).toBeVisible()
    await expect(this.draftButton).toBeVisible()
    await expect(this.warehouseButton).toBeVisible()
    await expect(this.onSaleButton).toBeVisible()
  }

  async expectNameCharCount(count: number): Promise<void> {
    await expect(this.nameCharCount).toContainText(`${count}/60`)
  }

  async expectTotalStock(value: string): Promise<void> {
    await expect(this.totalStockInput).toHaveValue(value)
  }
}

