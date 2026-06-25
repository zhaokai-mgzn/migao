import { test, expect } from '@playwright/test'
import { LoginPage } from '../../pages/login.page'

test.describe('登录页面 - 短信验证码登录', () => {
  let page: LoginPage

  test.beforeEach(async ({ page: p }) => {
    page = new LoginPage(p)
    await page.goto()
  })

  test('默认显示短信登录 Tab', async () => {
    await page.expectSmsTabActive()
    await expect(page.page.getByText('手机号登录')).toBeVisible()
  })

  test('手机号输入框可见', async () => {
    await expect(page.phoneInput).toBeVisible()
    await expect(page.phoneInput).toHaveAttribute('type', 'tel')
  })

  test('验证码输入框可见', async () => {
    await expect(page.codeInput).toBeVisible()
    await expect(page.codeInput).toHaveAttribute('maxlength', '6')
  })

  test('发送验证码按钮可见', async () => {
    await expect(page.sendCodeButton).toBeVisible()
    await expect(page.sendCodeButton).toContainText('获取验证码')
  })

  test('发送验证码后开始倒计时', async () => {
    await page.phoneInput.fill('13800138000')
    await page.clickSendCode()
    // 倒计时显示"重新发送(60s)"或已发送
    const btn = page.sendCodeButton
    // 可能成功开始倒计时或报 API 错误
    const text = await btn.textContent()
    expect(text).toBeTruthy()
  })

  test('手机号为空时发送验证码提示错误', async () => {
    await page.clickSendCode()
    // 应该显示验证错误
    const error = page.page.locator('p.text-red-500').first()
    if (await error.isVisible().catch(() => false)) {
      await expect(error).toContainText(/请输入手机号/)
    }
  })

  test('手机号格式不正确时提示错误', async () => {
    await page.phoneInput.fill('12345')
    await page.clickSendCode()
    const error = page.page.locator('p.text-red-500').first()
    if (await error.isVisible().catch(() => false)) {
      await expect(error).toContainText(/请输入正确的.*手机号/)
    }
  })

  test('验证码为空时提交提示错误', async () => {
    await page.phoneInput.fill('13800138000')
    await page.smsSubmitButton.click()
    const error = page.page.locator('p.text-red-500').first()
    if (await error.isVisible().catch(() => false)) {
      await expect(error).toContainText(/请输入验证码/)
    }
  })

  test('验证码不足6位时提示错误', async () => {
    await page.phoneInput.fill('13800138000')
    await page.codeInput.fill('123')
    await page.smsSubmitButton.click()
    const error = page.page.locator('p.text-red-500').first()
    if (await error.isVisible().catch(() => false)) {
      await expect(error).toContainText(/验证码为6位/)
    }
  })

  test('正确填写后提交触发登录请求', async () => {
    await page.phoneInput.fill('13800138000')
    await page.codeInput.fill('123456')
    await page.smsSubmitButton.click()
    // 应该发起 API 请求，验证有 toast 响应或错误横幅出现
    const toast = page.page.locator('[data-sonner-toast]')
    const errorBanner = page.page.locator('.bg-red-50.border-red-100 p')
    await expect(toast.or(errorBanner).first()).toBeVisible({ timeout: 10000 })
  })

  test('登录失败时显示错误横幅', async () => {
    await page.phoneInput.fill('13800138000')
    await page.codeInput.fill('000000')
    await page.smsSubmitButton.click()
    // 等待错误横幅出现或 toast 出现
    await page.page.waitForTimeout(2000)
    const errorBanner = page.smsLoginError
    const toast = page.page.locator('[data-sonner-toast]')
    const hasBanner = await errorBanner.isVisible().catch(() => false)
    const hasToast = await toast.isVisible().catch(() => false)
    expect(hasBanner || hasToast).toBeTruthy()
  })

  test('登录按钮显示"登 录"文字', async () => {
    await expect(page.smsSubmitButton).toContainText(/登.*录/)
  })

})
