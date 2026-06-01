import { type Page, type Locator } from '@playwright/test'
import { BasePage } from '../base.page'

export class KnowledgePage extends BasePage {
  readonly searchInput: Locator
  readonly typeSelect: Locator
  readonly statusSelect: Locator
  readonly table: Locator
  readonly uploadBtn: Locator
  readonly uploadModal: Locator
  readonly searchTestModal: Locator

  constructor(page: Page) {
    super(page)
    this.searchInput = page.locator('input[placeholder="请输入文档名称"]')
    this.typeSelect = page.locator('select').first()
    this.statusSelect = page.locator('select').nth(1)
    this.table = page.locator('table')
    this.uploadBtn = page.getByRole('button', { name: /上传文档/ })
    this.uploadModal = page.locator('[role="dialog"]').filter({ hasText: '上传文档' })
    this.searchTestModal = page.locator('[role="dialog"]').filter({ hasText: '知识库搜索测试' })
  }

  async goto(): Promise<void> {
    await this.page.goto('/knowledge')
  }

  resyncBtn(n: number): Locator {
    return this.page.locator('tbody tr').nth(n).locator('button[title="重新同步"]')
  }

  deleteBtn(n: number): Locator {
    return this.page.locator('tbody tr').nth(n).locator('button[title="删除"]')
  }

  get uploadName() { return this.uploadModal.locator('input[placeholder="请输入文档名称"]') }
  get uploadType() { return this.uploadModal.locator('select') }
  get uploadFile() { return this.uploadModal.locator('#file-upload') }
  get uploadDescription() { return this.uploadModal.locator('textarea[placeholder="请输入文档描述（可选）"]') }
  get uploadProgress() { return this.uploadModal.locator('.bg-primary-600.h-2') }
}
