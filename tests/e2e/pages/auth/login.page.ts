import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from './base.page'

/**
 * LoginPage POM — src/app/login/page.tsx
 *
 * SMS-only login: phone input + code input + send-code button + submit.
 */
export class LoginPage extends BasePage {
  // ─── SMS Form ────────────────────────────────────────────────
  readonly phoneInput: Locator
  readonly codeInput: Locator
  readonly sendCodeButton: Locator
  readonly smsSubmitButton: Locator
  readonly smsLoginError: Locator

  // ─── Shared ──────────────────────────────────────────────────
  readonly registerLink: Locator
  readonly loadingSpinner: Locator

  constructor(page: Page) {
    super(page)

    // SMS form
    this.phoneInput = page.locator('#phone')
    this.codeInput = page.locator('#code')
    this.sendCodeButton = page.getByRole('button', { name: /获取验证码|重新发送/ })
    this.smsSubmitButton = page.locator('form button[type="submit"]').first()
    this.smsLoginError = page.locator('.bg-red-50.border-red-100 p')

    // Shared
    this.registerLink = page.getByRole('link', { name: /企业入驻申请/ })
    this.loadingSpinner = page.locator('.animate-spin')
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(): Promise<void> {
    await this.page.goto('/login')
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

  // ─── Assertions ──────────────────────────────────────────────

  async expectValidationError(field: 'phone' | 'code', text: string | RegExp): Promise<void> {
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
