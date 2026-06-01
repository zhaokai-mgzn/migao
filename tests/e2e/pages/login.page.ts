import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from './base.page'

/**
 * LoginPage POM — src/app/login/page.tsx
 *
 * Two tabs: "企业管理员登录" (SMS) | "员工登录" (password).
 * SMS form: #phone, #code, send-code button, submit.
 * Password form: #tenantCode, #username, #password, show/hide, remember-me, submit.
 */
export class LoginPage extends BasePage {
  // ─── Tab Switching ───────────────────────────────────────────
  readonly smsTab: Locator
  readonly passwordTab: Locator

  // ─── SMS Form ────────────────────────────────────────────────
  readonly phoneInput: Locator
  readonly codeInput: Locator
  readonly sendCodeButton: Locator
  readonly smsSubmitButton: Locator
  readonly smsLoginError: Locator

  // ─── Password Form ──────────────────────────────────────────
  readonly tenantCodeInput: Locator
  readonly usernameInput: Locator
  readonly passwordInput: Locator
  readonly showPasswordToggle: Locator
  readonly rememberMeCheckbox: Locator
  readonly passwordSubmitButton: Locator
  readonly passwordLoginError: Locator

  // ─── Shared ──────────────────────────────────────────────────
  readonly registerLink: Locator
  readonly loadingSpinner: Locator

  constructor(page: Page) {
    super(page)

    // Tabs — exact text from source
    this.smsTab = page.getByRole('button', { name: /企业管理员登录/ })
    this.passwordTab = page.getByRole('button', { name: /员工登录/ })

    // SMS form
    this.phoneInput = page.locator('#phone')
    this.codeInput = page.locator('#code')
    this.sendCodeButton = page.getByRole('button', { name: /获取验证码|重新发送/ })
    this.smsSubmitButton = page.locator('form button[type="submit"]').first()
    this.smsLoginError = page.locator('.bg-red-50.border-red-100 p')

    // Password form
    this.tenantCodeInput = page.locator('#tenantCode')
    this.usernameInput = page.locator('#username')
    this.passwordInput = page.locator('#password')
    this.showPasswordToggle = page.locator('#password').locator('..').locator('button').last()
    this.rememberMeCheckbox = page.locator('input[type="checkbox"]')
    this.passwordSubmitButton = page.locator('form button[type="submit"]').last()
    this.passwordLoginError = page.locator('.bg-red-50.border-red-100 p')

    // Shared
    this.registerLink = page.getByRole('link', { name: /企业入驻申请/ })
    this.loadingSpinner = page.locator('.animate-spin')
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(): Promise<void> {
    await this.page.goto('/login')
  }

  // ─── Tab Actions ─────────────────────────────────────────────

  async switchToSmsTab(): Promise<void> {
    await this.smsTab.click()
  }

  async switchToPasswordTab(): Promise<void> {
    await this.passwordTab.click()
  }

  // ─── SMS Login Flow ──────────────────────────────────────────

  async fillSmsForm(phone: string, code: string): Promise<void> {
    await this.phoneInput.fill(phone)
    await this.codeInput.fill(code)
  }

  async clickSendCode(): Promise<void> {
    await this.sendCodeButton.click()
  }

  async submitSmsLogin(phone: string, code: string): Promise<void> {
    await this.fillSmsForm(phone, code)
    await this.smsSubmitButton.click()
  }

  // ─── Password Login Flow ─────────────────────────────────────

  async fillPasswordForm(
    username: string,
    password: string,
    options?: { tenantCode?: string },
  ): Promise<void> {
    if (options?.tenantCode) {
      await this.tenantCodeInput.fill(options.tenantCode)
    }
    await this.usernameInput.fill(username)
    await this.passwordInput.fill(password)
  }

  async togglePasswordVisibility(): Promise<void> {
    // The toggle is the sibling button inside the password field's relative container
    await this.page.locator('#password').locator('xpath=..').locator('button').click()
  }

  async toggleRememberMe(): Promise<void> {
    await this.rememberMeCheckbox.click()
  }

  async submitPasswordLogin(
    username: string,
    password: string,
    options?: { tenantCode?: string; expectSuccess?: boolean },
  ): Promise<void> {
    await this.switchToPasswordTab()
    await this.fillPasswordForm(username, password, options)
    await this.passwordSubmitButton.click()
    if (options?.expectSuccess !== false) {
      await this.page.waitForURL(/\/dashboard/, { timeout: 15_000 })
    }
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectSmsTabActive(): Promise<void> {
    await expect(this.smsTab).toHaveClass(/bg-white/)
  }

  async expectPasswordTabActive(): Promise<void> {
    await expect(this.passwordTab).toHaveClass(/bg-white/)
  }

  async expectValidationError(field: 'phone' | 'code' | 'tenantCode' | 'username' | 'password', text: string | RegExp): Promise<void> {
    const errorEl = this.page.locator(`#${field}`).locator('xpath=ancestor::div[1]').locator('p.text-red-500')
    await expect(errorEl).toContainText(text)
  }

  async expectSendCodeCountdown(): Promise<void> {
    await expect(this.sendCodeButton).toContainText(/重新发送\(\d+s\)/)
  }

  async expectLoadingState(): Promise<void> {
    await expect(this.loadingSpinner).toBeVisible()
  }

  async expectLoginError(text: string | RegExp): Promise<void> {
    const errorBox = this.page.locator('.bg-red-50.border-red-100 p').first()
    await expect(errorBox).toContainText(text)
  }

  async expectRegisterLinkVisible(): Promise<void> {
    await expect(this.registerLink).toBeVisible()
  }

  async expectOnLoginPage(): Promise<void> {
    await expect(this.page).toHaveURL(/\/login/)
  }
}
