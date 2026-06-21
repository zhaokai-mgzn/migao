import { type Page, type Locator } from '@playwright/test'
import { BasePage } from '../base.page'

export class SettingsPage extends BasePage {
  readonly basicTab: Locator
  readonly securityTab: Locator
  readonly companyNameInput: Locator
  readonly logoUpload: Locator
  readonly notificationToggle: Locator
  readonly notificationEmail: Locator
  readonly saveBasicBtn: Locator
  readonly oldPasswordInput: Locator
  readonly newPasswordInput: Locator
  readonly confirmPasswordInput: Locator
  readonly changePasswordBtn: Locator
  readonly loginLogsTable: Locator

  constructor(page: Page) {
    super(page)
    this.basicTab = page.getByRole('button', { name: /基本设置/ })
    this.securityTab = page.getByRole('button', { name: /账户安全/ })
    this.companyNameInput = page.locator('input[type="text"]').first()
    this.logoUpload = page.getByRole('button', { name: /上传 Logo/ })
    this.notificationToggle = page.locator('button').filter({ has: page.locator('.w-11.h-6') }).first()
    this.notificationEmail = page.locator('input[type="email"]')
    this.saveBasicBtn = page.getByRole('button', { name: /保存设置/ })
    this.oldPasswordInput = page.locator('input[placeholder="请输入当前密码"]')
    this.newPasswordInput = page.locator('input[placeholder="请输入新密码"]')
    this.confirmPasswordInput = page.locator('input[placeholder="请输入确认新密码"]')
    this.changePasswordBtn = page.getByRole('button', { name: /修改密码/ }).last()
    this.loginLogsTable = page.locator('table').first()
  }

  async goto(): Promise<void> {
    await this.page.goto('/settings')
  }
}
