import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from '../base.page'

/**
 * ProductListPage POM — src/app/(dashboard)/products/page.tsx
 *
 * Search form: 商品ID, 商品标题, 商品货号, 状态, 创建时间(from/to), search/reset.
 * Toolbar: batch off-shelf, batch on-shelf, batch export, new product.
 * ProductTable: sort, pagination, multi-select, row actions.
 * Confirmation modal.
 */
export class ProductListPage extends BasePage {
  // ─── Search Form (6 fields) ─────────────────────────────────
  readonly searchSection: Locator
  readonly productIdInput: Locator
  readonly productTitleInput: Locator
  readonly productSkuCodeInput: Locator
  readonly statusSelect: Locator
  readonly createdFromInput: Locator
  readonly createdToInput: Locator
  readonly searchButton: Locator
  readonly resetButton: Locator

  // ─── Toolbar ─────────────────────────────────────────────────
  readonly batchOffShelfButton: Locator
  readonly batchOnShelfButton: Locator
  readonly batchExportButton: Locator
  readonly newProductButton: Locator
  readonly selectionCount: Locator

  // ─── Table ───────────────────────────────────────────────────
  readonly productTable: Locator
  readonly tableRows: Locator
  readonly selectAllCheckbox: Locator
  readonly pagination: Locator
  readonly emptyState: Locator

  // ─── Confirmation Modal ──────────────────────────────────────
  readonly confirmModal: Locator
  readonly confirmModalTitle: Locator
  readonly confirmModalDescription: Locator
  readonly confirmModalCancel: Locator
  readonly confirmModalOk: Locator

  constructor(page: Page) {
    super(page)

    // Search form — field labels match source: 商品ID, 商品标题, 商品货号, 状态, 创建时间
    this.searchSection = page.locator('.bg-white.rounded-lg.border').first()
    this.productIdInput = page.locator('input[placeholder="请输入商品ID"]').first()
    this.productTitleInput = page.locator('input[placeholder="请输入商品标题"]')
    this.productSkuCodeInput = page.locator('input[placeholder="请输入商品ID"]').last()
    this.statusSelect = this.searchSection.locator('select')
    this.createdFromInput = this.searchSection.locator('input[type="date"]').first()
    this.createdToInput = this.searchSection.locator('input[type="date"]').last()
    this.searchButton = page.getByRole('button', { name: '搜索' })
    this.resetButton = page.getByRole('button', { name: '重置' })

    // Toolbar
    this.batchOffShelfButton = page.getByRole('button', { name: '批量下架' })
    this.batchOnShelfButton = page.getByRole('button', { name: '批量上架' })
    this.batchExportButton = page.getByRole('button', { name: '批量导出' })
    this.newProductButton = page.getByRole('button', { name: /新增商品/ })
    this.selectionCount = page.locator('span').filter({ hasText: /已选.*项/ })

    // Table
    this.productTable = page.locator('table')
    this.tableRows = page.locator('tbody tr')
    this.selectAllCheckbox = page.locator('thead input[type="checkbox"]')
    this.pagination = page.locator('.flex.items-center.justify-end').last()
    this.emptyState = page.locator('text=暂无数据')

    // Confirmation modal
    this.confirmModal = page.locator('[role="dialog"]')
    this.confirmModalTitle = this.confirmModal.locator('h3, [class*="title"]')
    this.confirmModalDescription = this.confirmModal.locator('p')
    this.confirmModalCancel = this.confirmModal.getByRole('button', { name: '取消' })
    this.confirmModalOk = this.confirmModal.getByRole('button', { name: '确定' })
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(): Promise<void> {
    await this.page.goto('/products')
    await this.waitForLoadingComplete()
  }

  // ─── Search Actions ──────────────────────────────────────────

  async searchByProductId(id: string): Promise<void> {
    await this.productIdInput.fill(id)
    await this.searchButton.click()
    await this.waitForLoadingComplete()
  }

  async searchByTitle(title: string): Promise<void> {
    await this.productTitleInput.fill(title)
    await this.searchButton.click()
    await this.waitForLoadingComplete()
  }

  async searchBySkuCode(skuCode: string): Promise<void> {
    await this.productSkuCodeInput.fill(skuCode)
    await this.searchButton.click()
    await this.waitForLoadingComplete()
  }

  async searchByStatus(status: string): Promise<void> {
    await this.statusSelect.selectOption(status)
    await this.searchButton.click()
    await this.waitForLoadingComplete()
  }

  async searchByDateRange(from: string, to: string): Promise<void> {
    await this.createdFromInput.fill(from)
    await this.createdToInput.fill(to)
    await this.searchButton.click()
    await this.waitForLoadingComplete()
  }

  async resetSearch(): Promise<void> {
    await this.resetButton.click()
    await this.waitForLoadingComplete()
  }

  // ─── Toolbar Actions ─────────────────────────────────────────

  async clickNewProduct(): Promise<void> {
    await this.newProductButton.click()
  }

  async clickBatchExport(): Promise<void> {
    await this.batchExportButton.click()
  }

  async selectRowsAndBatchOnShelf(indices: number[]): Promise<void> {
    for (const idx of indices) {
      await this.tableRows.nth(idx).locator('input[type="checkbox"]').click()
    }
    await this.batchOnShelfButton.click()
  }

  async selectRowsAndBatchOffShelf(indices: number[]): Promise<void> {
    for (const idx of indices) {
      await this.tableRows.nth(idx).locator('input[type="checkbox"]').click()
    }
    await this.batchOffShelfButton.click()
  }

  async selectAll(): Promise<void> {
    await this.selectAllCheckbox.click()
  }

  // ─── Row Actions ─────────────────────────────────────────────

  async viewProduct(rowText: string): Promise<void> {
    const row = this.tableRow(rowText)
    await row.getByRole('button', { name: /查看/ }).or(row.getByText('查看')).click()
  }

  async editProduct(rowText: string): Promise<void> {
    const row = this.tableRow(rowText)
    await row.getByRole('button', { name: /编辑/ }).or(row.getByText('编辑')).click()
  }

  async putOnShelf(rowText: string): Promise<void> {
    const row = this.tableRow(rowText)
    await row.getByText('上架').click()
  }

  async takeOffShelf(rowText: string): Promise<void> {
    const row = this.tableRow(rowText)
    await row.getByText('下架').click()
  }

  async deleteProduct(rowText: string): Promise<void> {
    const row = this.tableRow(rowText)
    await row.getByText('删除').click()
  }

  // ─── Modal Actions ───────────────────────────────────────────

  async confirmModalAction(): Promise<void> {
    await this.confirmModalOk.click()
  }

  async cancelModalAction(): Promise<void> {
    await this.confirmModalCancel.click()
  }

  // ─── Pagination ──────────────────────────────────────────────

  async goToPage(pageNum: number): Promise<void> {
    await this.page.getByRole('button', { name: String(pageNum), exact: true }).click()
    await this.waitForLoadingComplete()
  }

  async changePageSize(size: number): Promise<void> {
    await this.pagination.locator('select').selectOption(String(size))
    await this.waitForLoadingComplete()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectProductVisible(name: string): Promise<void> {
    await expect(this.tableRow(name)).toBeVisible()
  }

  async expectBatchButtonsDisabled(): Promise<void> {
    await expect(this.batchOffShelfButton).toBeDisabled()
    await expect(this.batchOnShelfButton).toBeDisabled()
  }

  async expectSelectionCount(count: number): Promise<void> {
    await expect(this.selectionCount).toContainText(String(count))
  }

  async expectConfirmModalVisible(title?: string): Promise<void> {
    await expect(this.confirmModal).toBeVisible()
    if (title) {
      await expect(this.confirmModal).toContainText(title)
    }
  }

  async expectOnProductListPage(): Promise<void> {
    await expect(this.page).toHaveURL(/\/products/)
  }

  async expectPageTitle(): Promise<void> {
    await expect(this.page.locator('h1')).toContainText('商品列表')
  }
}
