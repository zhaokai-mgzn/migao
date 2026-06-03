import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from './base.page'

/**
 * CategoriesPage POM — src/app/(dashboard)/categories/page.tsx
 *
 * Layout: Category tree (left 2/3) + detail panel (right 1/3).
 * Add/edit dialog via CategoryDialog component.
 * Delete confirmation modal.
 */
export class CategoriesPage extends BasePage {
  // ─── Header ──────────────────────────────────────────────────
  readonly pageTitle: Locator
  readonly addCategoryButton: Locator

  // ─── Category Tree ───────────────────────────────────────────
  readonly treeSection: Locator
  readonly treeNodes: Locator
  readonly loadingState: Locator

  // ─── Detail Panel ────────────────────────────────────────────
  readonly detailPanel: Locator
  readonly detailName: Locator
  readonly detailId: Locator
  readonly detailSort: Locator
  readonly detailChildCount: Locator
  readonly detailEditButton: Locator
  readonly detailDeleteButton: Locator
  readonly detailPlaceholder: Locator

  // ─── Add/Edit Dialog (CategoryDialog) ───────────────────────
  readonly categoryDialog: Locator
  readonly dialogNameInput: Locator
  readonly dialogParentSelect: Locator
  readonly dialogSortInput: Locator
  readonly dialogSaveButton: Locator
  readonly dialogCancelButton: Locator

  // ─── Delete Confirmation ─────────────────────────────────────
  readonly deleteModal: Locator
  readonly deleteModalTitle: Locator
  readonly deleteModalWarning: Locator
  readonly deleteModalCancel: Locator
  readonly deleteModalConfirm: Locator

  constructor(page: Page) {
    super(page)

    // Header
    this.pageTitle = page.locator('h1').filter({ hasText: /分类管理/ })
    this.addCategoryButton = page.getByRole('button', { name: /添加分类/ })

    // Category tree
    this.treeSection = page.locator('.bg-gray-50').filter({ hasText: /分类结构/ })
    this.treeNodes = this.treeSection.locator('[class*="category"], li, [role="treeitem"]')
    this.loadingState = this.treeSection.locator('.animate-spin, .py-12')

    // Detail panel
    this.detailPanel = page.locator('.bg-gray-50').filter({ hasText: /分类详情/ })
    this.detailName = this.detailPanel.locator('dd').nth(0)
    this.detailId = this.detailPanel.locator('dd').nth(1)
    this.detailSort = this.detailPanel.locator('dd').nth(2)
    this.detailChildCount = this.detailPanel.locator('dd').nth(3)
    this.detailEditButton = this.detailPanel.getByRole('button', { name: /编辑/ })
    this.detailDeleteButton = this.detailPanel.getByRole('button', { name: /删除/ })
    this.detailPlaceholder = this.detailPanel.getByText(/点击左侧分类查看详情/)

    // Category dialog
    this.categoryDialog = page.locator('[role="dialog"]')
    this.dialogNameInput = this.categoryDialog.locator('input').first()
    this.dialogParentSelect = this.categoryDialog.locator('select')
    this.dialogSortInput = this.categoryDialog.locator('input[type="number"]')
    this.dialogSaveButton = this.categoryDialog.getByRole('button', { name: /保存|确定|创建/ })
    this.dialogCancelButton = this.categoryDialog.getByRole('button', { name: /取消/ })

    // Delete confirmation
    this.deleteModal = page.locator('[role="dialog"]').filter({ hasText: /确认删除/ })
    this.deleteModalTitle = this.deleteModal.locator('h3, [class*="title"]')
    this.deleteModalWarning = this.deleteModal.locator('.text-amber-600')
    this.deleteModalCancel = this.deleteModal.getByRole('button', { name: /取消/ })
    this.deleteModalConfirm = this.deleteModal.getByRole('button', { name: /确认删除/ })
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(): Promise<void> {
    await this.page.goto('/categories')
    await this.waitForLoadingComplete()
  }

  // ─── Actions ─────────────────────────────────────────────────

  async clickAddCategory(): Promise<void> {
    await this.addCategoryButton.click()
  }

  async selectCategory(name: string): Promise<void> {
    await this.treeNodes.filter({ hasText: name }).click()
  }

  async editCategoryFromTree(name: string): Promise<void> {
    // Tree node edit buttons are rendered by CategoryTree component
    const node = this.treeNodes.filter({ hasText: name })
    await node.locator('button').filter({ hasText: /编辑/ }).or(node.locator('[title="编辑"]')).click()
  }

  async deleteCategoryFromTree(name: string): Promise<void> {
    const node = this.treeNodes.filter({ hasText: name })
    await node.locator('button').filter({ hasText: /删除/ }).or(node.locator('[title="删除"]')).click()
  }

  async fillCategoryDialog(name: string, options?: { sort?: number }): Promise<void> {
    await this.dialogNameInput.fill(name)
    if (options?.sort !== undefined) {
      await this.dialogSortInput.fill(String(options.sort))
    }
  }

  async saveCategoryDialog(): Promise<void> {
    await this.dialogSaveButton.click()
  }

  async confirmDelete(): Promise<void> {
    await this.deleteModalConfirm.click()
  }

  async cancelDelete(): Promise<void> {
    await this.deleteModalCancel.click()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectCategoryInTree(name: string): Promise<void> {
    await expect(this.treeNodes.filter({ hasText: name })).toBeVisible()
  }

  async expectDetailPanelVisible(): Promise<void> {
    await expect(this.detailName).toBeVisible()
  }

  async expectDetailName(name: string): Promise<void> {
    await expect(this.detailName).toContainText(name)
  }

  async expectDeleteModalVisible(): Promise<void> {
    await expect(this.deleteModal).toBeVisible()
  }

  async expectDeleteWarning(childCount: number): Promise<void> {
    await expect(this.deleteModalWarning).toContainText(String(childCount))
  }

  async expectOnCategoriesPage(): Promise<void> {
    await expect(this.page).toHaveURL(/\/categories/)
  }
}
