import { type Page, type Locator, expect } from '@playwright/test'
import { BasePage } from './base.page'

/**
 * RegisterPage POM — src/app/register/page.tsx
 *
 * 3 steps:
 *   Step 1: phone + SMS code verification
 *   Step 2: company info form + business license upload
 *   Step 3: success screen
 */
export class RegisterPage extends BasePage {
  // ─── Step Indicator ──────────────────────────────────────────
  readonly stepIndicator: Locator
  readonly step1Indicator: Locator
  readonly step2Indicator: Locator

  // ─── Step 1: Phone Verification ─────────────────────────────
  readonly phoneInput: Locator
  readonly codeInput: Locator
  readonly sendCodeButton: Locator
  readonly step1NextButton: Locator
  readonly phoneError: Locator
  readonly codeError: Locator

  // ─── Step 2: Company Form ───────────────────────────────────
  readonly companyNameInput: Locator
  readonly contactNameInput: Locator
  readonly industryInput: Locator
  readonly addressInput: Locator
  readonly descriptionTextarea: Locator
  readonly fileUploadInput: Locator
  readonly fileUploadLabel: Locator
  readonly uploadProgress: Locator
  readonly uploadedFileBadge: Locator
  readonly removeFileButton: Locator
  readonly step2PrevButton: Locator
  readonly step2SubmitButton: Locator
  readonly companyNameError: Locator
  readonly contactNameError: Locator

  // ─── Step 3: Success ────────────────────────────────────────
  readonly successHeading: Locator
  readonly backToLoginLink: Locator
  readonly backToLoginButton: Locator

  // ─── Shared ──────────────────────────────────────────────────
  readonly backToLoginBottomLink: Locator

  constructor(page: Page) {
    super(page)

    // Step indicator
    this.stepIndicator = page.locator('.flex.items-center.justify-center.gap-3.mb-6')
    this.step1Indicator = this.stepIndicator.locator('div').first()
    this.step2Indicator = this.stepIndicator.locator('div').last()

    // Step 1
    this.phoneInput = page.locator('#reg-phone')
    this.codeInput = page.locator('#reg-code')
    this.sendCodeButton = page.getByRole('button', { name: /获取验证码|重新发送/ })
    this.step1NextButton = page.getByRole('button', { name: /下一步/ })
    this.phoneError = page.locator('#reg-phone').locator('xpath=ancestor::div[1]').locator('p.text-red-500')
    this.codeError = page.locator('#reg-code').locator('xpath=ancestor::div[1]').locator('p.text-red-500')

    // Step 2
    this.companyNameInput = page.locator('#companyName')
    this.contactNameInput = page.locator('#contactName')
    this.industryInput = page.locator('#industry')
    this.addressInput = page.locator('#address')
    this.descriptionTextarea = page.locator('#description')
    this.fileUploadInput = page.locator('input[type="file"]')
    this.fileUploadLabel = page.locator('label').filter({ hasText: /点击上传营业执照/ })
    this.uploadProgress = page.locator('.animate-spin').filter({ has: page.locator('text=上传中') })
    this.uploadedFileBadge = page.locator('.bg-green-50').filter({ hasText: /已上传营业执照/ })
    this.removeFileButton = page.getByRole('button', { name: /移除/ })
    this.step2PrevButton = page.getByRole('button', { name: /上一步/ })
    this.step2SubmitButton = page.getByRole('button', { name: /提交申请|提交中/ })
    this.companyNameError = page.locator('#companyName').locator('xpath=ancestor::div[1]').locator('p.text-red-500')
    this.contactNameError = page.locator('#contactName').locator('xpath=ancestor::div[1]').locator('p.text-red-500')

    // Step 3
    this.successHeading = page.getByText('申请已提交')
    this.backToLoginLink = page.getByRole('link', { name: /返回登录/ })
    this.backToLoginButton = page.locator('a').filter({ hasText: /返回登录/ }).first()

    // Shared
    this.backToLoginBottomLink = page.locator('a').filter({ hasText: /← 返回登录/ })
  }

  // ─── Navigation ──────────────────────────────────────────────

  async goto(): Promise<void> {
    await this.page.goto('/register')
  }

  // ─── Step 1 Actions ──────────────────────────────────────────

  async fillPhoneAndCode(phone: string, code: string): Promise<void> {
    await this.phoneInput.fill(phone)
    await this.codeInput.fill(code)
  }

  async clickSendCode(): Promise<void> {
    await this.sendCodeButton.click()
  }

  async proceedToStep2(phone: string, code: string): Promise<void> {
    await this.fillPhoneAndCode(phone, code)
    await this.step1NextButton.click()
  }

  // ─── Step 2 Actions ──────────────────────────────────────────

  async fillCompanyForm(data: {
    companyName: string
    contactName: string
    industry?: string
    address?: string
    description?: string
  }): Promise<void> {
    await this.companyNameInput.fill(data.companyName)
    await this.contactNameInput.fill(data.contactName)
    if (data.industry) await this.industryInput.fill(data.industry)
    if (data.address) await this.addressInput.fill(data.address)
    if (data.description) await this.descriptionTextarea.fill(data.description)
  }

  async uploadBusinessLicense(filePath: string): Promise<void> {
    await this.fileUploadInput.setInputFiles(filePath)
  }

  async removeUploadedFile(): Promise<void> {
    await this.removeFileButton.click()
  }

  async goBackToStep1(): Promise<void> {
    await this.step2PrevButton.click()
  }

  async submitRegistration(): Promise<void> {
    await this.step2SubmitButton.click()
  }

  // ─── Assertions ──────────────────────────────────────────────

  async expectOnStep(step: 1 | 2 | 3): Promise<void> {
    if (step === 1) {
      await expect(this.phoneInput).toBeVisible()
    } else if (step === 2) {
      await expect(this.companyNameInput).toBeVisible()
    } else {
      await expect(this.successHeading).toBeVisible()
    }
  }

  async expectStep1Active(): Promise<void> {
    // Step 1 circle has bg-primary-600
    const circle = this.stepIndicator.locator('div').first().locator('div').first()
    await expect(circle).toHaveClass(/bg-primary-600/)
  }

  async expectStep2Active(): Promise<void> {
    // Step 2 circle should have bg-primary-600 when step >= 2
    const circles = this.stepIndicator.locator('div.w-7')
    await expect(circles.nth(1)).toHaveClass(/bg-primary-600/)
  }

  async expectFileUploaded(): Promise<void> {
    await expect(this.uploadedFileBadge).toBeVisible()
  }

  async expectSuccessPage(): Promise<void> {
    await expect(this.successHeading).toBeVisible()
    await expect(this.page.getByText(/1-3 个工作日/)).toBeVisible()
  }
}
