import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from '../base.page'

/**
 * CustomerListPage POM — src/app/(dashboard)/customers/page.tsx
 *
 * SearchBar (keyword, channel, VIP level).
 * Table: avatar, name, phone, channel, VIP, tags, last active.
 * Tag management modal with create/edit/delete.
 */
export class CustomerListPage extends BasePage {
  // ─── Header ──────────────────────────────────────────────────
  readonly pageTitle: Locator
  readonly tagManagerButton: Locator

  // ─── Search Bar ─────────────────────────────────────────────
  readonly keywordInput: Locator
  readonly channelSelect: Locator
  readonly vipLevelSelect: Locator
  readonly searchButton: Locator
  readonly resetButton: Locator

  // ─── Table ───────────────────────────────────────────────────
  readonly table: Locator
  readonly tableRows: Locator
  readonly pagination: Locator

  // ─── Tag Management Modal ───────────────────────────────────
  readonly tagModal: Locator
  readonly tagNameInput: Locator
  readonly tagColorSwatches: Locator
  readonly tagAddButton: Locator
  readonly tagUpdateButton: Locator
  readonly tagCancelButton: Locator
  readonly tagList: Locator
  readonly tagCloseButton: Locator

  constructor(page: Page) {
    super(page)

    // Header
    this.pageTitle = page.locator('h1').filter({ hasText: /客户管理/ })
    this.tagManagerButton = page.getByRole('button', { name: /标签管理/ })

    // Search bar — 使用 nth(0)/nth(1) 替代 first()/last() 避免选中分页下拉
    this.keywordInput = page.locator('input[placeholder*="客户名"]')
    this.channelSelect = page.locator('select').nth(0)
    this.vipLevelSelect = page.locator('select').nth(1)
    this.searchButton = page.getByRole('button', { name: /搜索/ })
    this.resetButton = page.getByRole('button', { name: /重置/ })

    // Table
    this.table = page.locator('table')
    this.tableRows = page.locator('tbody tr')
    this.pagination = page.locator('[class*="pagination"]').first()

    // Tag modal
    this.tagModal = page.locator('[role="dialog"]').filter({ hasText: /标签管理/ })
    this.tagNameInput = this.tagModal.locator('input[placeholder="标签名称"]')
    this.tagColorSwatches = this.tagModal.locator('button.rounded-full, button .rounded-full')
    this.tagAddButton = this.tagModal.getByRole('button', { name: /添加/ })
    this.tagUpdateButton = this.tagModal.getByRole('button', { name: /更新/ })
    this.tagCancelButton = this.tagModal.getByRole('button', { name: /取消/ })
    this.tagList = this.tagModal.locator('.space-y-2')
    this.tagCloseButton = this.tagModal.getByRole('button', { name: /关闭/ })
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(): Promise<void> {
    await this.page.goto('/customers')
    await this.waitForLoadingComplete()
  }

  // ─── Search ──────────────────────────────────────────────────

  async search(keyword: string): Promise<void> {
    await this.keywordInput.fill(keyword)
    await this.searchButton.click()
    await this.waitForLoadingComplete()
  }

  async filterByChannel(channel: string): Promise<void> {
    await this.channelSelect.selectOption(channel)
    await this.searchButton.click()
    await this.waitForLoadingComplete()
  }

  async filterByVipLevel(level: string): Promise<void> {
    await this.vipLevelSelect.selectOption(level)
    await this.searchButton.click()
    await this.waitForLoadingComplete()
  }

  async resetSearch(): Promise<void> {
    await this.resetButton.click()
    await this.waitForLoadingComplete()
  }

  // ─── Row Actions ─────────────────────────────────────────────

  async viewCustomer(name: string): Promise<void> {
    await this.tableRow(name).click()
  }

  // ─── Tag Management ─────────────────────────────────────────

  async openTagManager(): Promise<void> {
    await this.tagManagerButton.click()
  }

  async createTag(name: string, colorIndex = 0): Promise<void> {
    await this.tagNameInput.fill(name)
    await this.tagColorSwatches.nth(colorIndex).click()
    await this.tagAddButton.click()
  }

  async editTag(tagName: string): Promise<void> {
    const item = this.tagList.locator('.flex.items-center').filter({ hasText: tagName })
    await item.getByText('编辑').click()
  }

  async deleteTag(tagName: string): Promise<void> {
    const item = this.tagList.locator('.flex.items-center').filter({ hasText: tagName })
    await item.locator('button').last().click()
  }

  async closeTagManager(): Promise<void> {
    await this.tagCloseButton.click()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectCustomerVisible(name: string): Promise<void> {
    await expect(this.tableRow(name)).toBeVisible()
  }

  async expectTagManagerVisible(): Promise<void> {
    await expect(this.tagModal).toBeVisible()
  }

  async expectTagInList(tagName: string): Promise<void> {
    await expect(this.tagList).toContainText(tagName)
  }

  async expectOnCustomerListPage(): Promise<void> {
    await expect(this.page).toHaveURL(/\/customers/)
  }
}
