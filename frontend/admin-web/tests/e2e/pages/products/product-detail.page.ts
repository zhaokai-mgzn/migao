import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from '../base.page'

/**
 * ProductDetailPage POM — src/app/(dashboard)/products/[id]/ProductDetail.tsx
 *
 * Sections: image gallery, basic info, attributes, SKU table, processing items, description.
 * Action buttons: back, edit, on-shelf/off-shelf.
 */
export class ProductDetailPage extends BasePage {
  // ─── Header ──────────────────────────────────────────────────
  readonly backButton: Locator
  readonly productName: Locator
  readonly statusBadge: Locator
  readonly skuLabel: Locator
  readonly onShelfButton: Locator
  readonly offShelfButton: Locator
  readonly editButton: Locator

  // ─── Image Gallery ───────────────────────────────────────────
  readonly imageSection: Locator
  readonly mainImage: Locator
  readonly detailImages: Locator
  readonly noImagePlaceholder: Locator

  // ─── Basic Info ──────────────────────────────────────────────
  readonly basicInfoSection: Locator
  readonly categoryValue: Locator
  readonly brandValue: Locator
  readonly pricingTypeValue: Locator
  readonly priceValue: Locator
  readonly costPriceValue: Locator
  readonly stockValue: Locator
  readonly stockDeductionValue: Locator

  // ─── Attributes ──────────────────────────────────────────────
  readonly attributesSection: Locator

  // ─── SKU Table ───────────────────────────────────────────────
  readonly skuSection: Locator
  readonly skuTable: Locator
  readonly skuRows: Locator

  // ─── Processing Items ────────────────────────────────────────
  readonly processingSection: Locator

  // ─── Description ─────────────────────────────────────────────
  readonly descriptionSection: Locator

  // ─── Image Preview Overlay ───────────────────────────────────
  readonly imagePreviewOverlay: Locator

  constructor(page: Page) {
    super(page)

    // Header
    this.backButton = page.locator('button').filter({ has: page.locator('svg') }).first()
    this.productName = page.locator('h1')
    this.statusBadge = page.locator('span').filter({ hasText: /出售中|仓库中|草稿|审核中/ }).first()
    this.skuLabel = page.locator('span.font-mono').filter({ hasText: /SKU:/ })
    this.onShelfButton = page.getByRole('button', { name: /上架/ })
    this.offShelfButton = page.getByRole('button', { name: /下架/ })
    this.editButton = page.getByRole('button', { name: /编辑/ })

    // Image gallery
    this.imageSection = page.locator('.bg-gray-50').filter({ hasText: /商品图片/ })
    this.mainImage = this.imageSection.locator('img').first()
    this.detailImages = this.imageSection.locator('.grid.grid-cols-3 img')
    this.noImagePlaceholder = this.imageSection.getByText('暂无图片')

    // Basic info
    this.basicInfoSection = page.locator('.bg-gray-50').filter({ hasText: /基本信息/ })
    this.categoryValue = this.basicInfoSection.locator('dd').nth(0)
    this.brandValue = this.basicInfoSection.locator('dd').nth(1)
    this.pricingTypeValue = this.basicInfoSection.locator('dd').nth(2)
    this.priceValue = this.basicInfoSection.locator('dd').nth(3)
    this.costPriceValue = this.basicInfoSection.locator('dd').nth(4)
    this.stockValue = this.basicInfoSection.locator('dd').nth(5)
    this.stockDeductionValue = this.basicInfoSection.locator('dd').filter({ hasText: /拍下减|付款减/ })

    // Attributes
    this.attributesSection = page.locator('.bg-gray-50').filter({ hasText: /商品属性/ })

    // SKU table
    this.skuSection = page.locator('.bg-gray-50').filter({ hasText: /SKU 规格/ })
    this.skuTable = this.skuSection.locator('table')
    this.skuRows = this.skuTable.locator('tbody tr')

    // Processing
    this.processingSection = page.locator('.bg-gray-50').filter({ hasText: /加工项/ })

    // Description
    this.descriptionSection = page.locator('.bg-gray-50').filter({ hasText: /商品描述/ })

    // Image preview overlay
    this.imagePreviewOverlay = page.locator('.fixed.inset-0.z-50')
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(productId: string): Promise<void> {
    await this.page.goto(`/products/${productId}`)
    await this.waitForLoadingComplete()
  }

  // ─── Actions ─────────────────────────────────────────────────

  async goBack(): Promise<void> {
    await this.backButton.click()
  }

  async clickEdit(): Promise<void> {
    await this.editButton.click()
  }

  async clickOnShelf(): Promise<void> {
    await this.onShelfButton.click()
  }

  async clickOffShelf(): Promise<void> {
    await this.offShelfButton.click()
  }

  async clickMainImage(): Promise<void> {
    await this.mainImage.click()
  }

  async closeImagePreview(): Promise<void> {
    await this.imagePreviewOverlay.click()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectProductTitle(name: string): Promise<void> {
    await expect(this.productName).toContainText(name)
  }

  async expectStatus(status: string): Promise<void> {
    await expect(this.statusBadge).toContainText(status)
  }

  async expectOnShelfButtonVisible(): Promise<void> {
    await expect(this.onShelfButton).toBeVisible()
  }

  async expectOffShelfButtonVisible(): Promise<void> {
    await expect(this.offShelfButton).toBeVisible()
  }

  async expectEditButtonVisible(): Promise<void> {
    await expect(this.editButton).toBeVisible()
  }

  async expectBasicInfoVisible(): Promise<void> {
    await expect(this.basicInfoSection).toBeVisible()
  }

  async expectSkuTableVisible(): Promise<void> {
    await expect(this.skuSection).toBeVisible()
    await expect(this.skuTable).toBeVisible()
  }

  async expectSkuRowCount(count: number): Promise<void> {
    await expect(this.skuRows).toHaveCount(count)
  }

  async expectImagePreviewVisible(): Promise<void> {
    await expect(this.imagePreviewOverlay).toBeVisible()
  }

  async expectProcessingSectionVisible(): Promise<void> {
    await expect(this.processingSection).toBeVisible()
  }

  async expectOnDetailPage(productId?: string): Promise<void> {
    const pattern = productId ? new RegExp(`/products/${productId}`) : /\/products\/[^/]+$/
    await expect(this.page).toHaveURL(pattern)
  }
}
