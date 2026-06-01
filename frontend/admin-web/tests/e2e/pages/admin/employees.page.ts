import { type Page, type Locator } from '@playwright/test'
import { BasePage } from '../base.page'

export class EmployeesPage extends BasePage {
  readonly searchInput: Locator
  readonly statusSelect: Locator
  readonly table: Locator
  readonly createBtn: Locator
  readonly employeeModal: Locator

  constructor(page: Page) {
    super(page)
    this.searchInput = page.locator('input[placeholder="姓名、用户名"]')
    this.statusSelect = page.locator('select').first()
    this.table = page.locator('table')
    this.createBtn = page.getByRole('button', { name: /新增员工/ })
    this.employeeModal = page.locator('[role="dialog"]').filter({ hasText: /新增员工|编辑员工/ })
  }

  async goto(): Promise<void> {
    await this.page.goto('/employees')
  }

  editBtn(n: number): Locator {
    return this.page.locator('tbody tr').nth(n).getByRole('button', { name: /编辑/ })
  }

  resetPasswordBtn(n: number): Locator {
    return this.page.locator('tbody tr').nth(n).getByRole('button', { name: /重置密码/ })
  }

  toggleStatusBtn(n: number): Locator {
    return this.page.locator('tbody tr').nth(n).getByRole('button', { name: /禁用|启用/ })
  }

  deleteBtn(n: number): Locator {
    return this.page.locator('tbody tr').nth(n).getByRole('button', { name: /删除/ })
  }

  get username() { return this.employeeModal.locator('input[placeholder="请输入用户名"]') }
  get password() { return this.employeeModal.locator('input[type="password"]') }
  get name() { return this.employeeModal.locator('input[placeholder="请输入姓名"]') }
  get phone() { return this.employeeModal.locator('input[placeholder="请输入手机号"]') }
  get email() { return this.employeeModal.locator('input[placeholder="请输入邮箱"]') }
  get roleSelect() { return this.employeeModal.locator('button').filter({ hasText: /^[^创取保取]+$/ }) }

  get resetPasswordModal() { return this.page.locator('[role="dialog"]').filter({ hasText: '重置密码' }) }
}
