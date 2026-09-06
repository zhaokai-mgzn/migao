import { type Page, type Locator } from '@playwright/test'
import { BasePage } from '../base.page'

export class RolesPage extends BasePage {
  readonly roleCards: Locator
  readonly createBtn: Locator
  readonly roleModal: Locator

  constructor(page: Page) {
    super(page)
    this.roleCards = page.locator('.grid > div').filter({ has: page.locator('h3') })
    this.createBtn = page.getByRole('button', { name: /新增岗位/ }).or(page.getByText('新增岗位'))
    this.roleModal = page.getByRole('dialog').filter({ hasText: /新增岗位|编辑岗位/ })
  }

  async goto(): Promise<void> {
    await this.page.goto('/roles')
    await this.waitForLoad()
  }

  editBtn(n: number): Locator {
    return this.roleCards.nth(n).locator('button[title="编辑"]')
  }

  deleteBtn(n: number): Locator {
    return this.roleCards.nth(n).locator('button[title="删除"]')
  }

  get name() { return this.roleModal.locator('input[placeholder*="管理员"]').or(this.roleModal.locator('input[label="岗位名称"]')) }
  get code() { return this.roleModal.locator('input[placeholder*="admin"]').or(this.roleModal.locator('input[label="岗位编码"]')) }
  get description() { return this.roleModal.locator('textarea[placeholder*="岗位描述"]') }
  get permissionTree() { return this.roleModal.locator('.border.border-gray-200.rounded-lg') }

  permissionGroup(name: string): Locator {
    return this.permissionTree.locator('div').filter({ hasText: new RegExp(name) }).first()
  }

  permissionCheckbox(group: string, perm: string): Locator {
    return this.permissionTree.locator('label').filter({ hasText: perm }).locator('input[type="checkbox"]')
  }
}
