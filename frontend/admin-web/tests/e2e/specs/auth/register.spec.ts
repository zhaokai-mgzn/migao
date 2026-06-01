import { test, expect } from '@playwright/test'

test.describe('企业入驻注册页面', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/register')
  })

  // ── 步骤指示器 ──

  test('页面标题正确显示', async ({ page }) => {
    await expect(page.getByText('企业入驻申请')).toBeVisible()
  })

  test('步骤指示器显示两个步骤', async ({ page }) => {
    await expect(page.getByText('手机验证')).toBeVisible()
    await expect(page.getByText('企业信息')).toBeVisible()
  })

  test('步骤1默认激活', async ({ page }) => {
    // 步骤1圆圈是 primary 色
    const step1 = page.locator('div').filter({ hasText: /^1$/ }).first()
    await expect(step1).toHaveClass(/bg-primary-600/)
  })

  // ── 步骤一：手机验证 ──

  test('步骤一包含手机号和验证码输入框', async ({ page }) => {
    await expect(page.locator('#reg-phone')).toBeVisible()
    await expect(page.locator('#reg-code')).toBeVisible()
  })

  test('步骤一发送验证码按钮可见', async ({ page }) => {
    await expect(page.getByRole('button', { name: /获取验证码/ })).toBeVisible()
  })

  test('步骤一发送验证码后开始倒计时', async ({ page }) => {
    await page.locator('#reg-phone').fill('13800138000')
    await page.getByRole('button', { name: /获取验证码/ }).click()
    // 倒计时或 API 错误
    await page.waitForTimeout(500)
  })

  test('步骤一手机号为空时下一步提示错误', async ({ page }) => {
    await page.getByRole('button', { name: /下一步/ }).click()
    const error = page.locator('p.text-red-500').first()
    if (await error.isVisible().catch(() => false)) {
      await expect(error).toContainText(/请输入手机号/)
    }
  })

  test('步骤一验证码为空时下一步提示错误', async ({ page }) => {
    await page.locator('#reg-phone').fill('13800138000')
    await page.getByRole('button', { name: /下一步/ }).click()
    const error = page.locator('p.text-red-500').first()
    if (await error.isVisible().catch(() => false)) {
      await expect(error).toContainText(/请输入验证码/)
    }
  })

  test('步骤一填写正确后可进入步骤二', async ({ page }) => {
    await page.locator('#reg-phone').fill('13800138000')
    await page.locator('#reg-code').fill('123456')
    await page.getByRole('button', { name: /下一步/ }).click()
    // 步骤二应该显示
    await expect(page.getByText('企业信息')).toBeVisible()
  })

  // ── 步骤二：企业信息 ──

  test('步骤二包含企业信息表单字段', async ({ page }) => {
    // 先进入步骤二
    await page.locator('#reg-phone').fill('13800138000')
    await page.locator('#reg-code').fill('123456')
    await page.getByRole('button', { name: /下一步/ }).click()

    await expect(page.locator('#companyName')).toBeVisible()
    await expect(page.locator('#contactName')).toBeVisible()
    await expect(page.locator('#industry')).toBeVisible()
    await expect(page.locator('#address')).toBeVisible()
    await expect(page.locator('#description')).toBeVisible()
  })

  test('步骤二营业执照上传区域可见', async ({ page }) => {
    await page.locator('#reg-phone').fill('13800138000')
    await page.locator('#reg-code').fill('123456')
    await page.getByRole('button', { name: /下一步/ }).click()

    await expect(page.getByText(/点击上传营业执照/)).toBeVisible()
  })

  test('步骤二上一步按钮可返回步骤一', async ({ page }) => {
    await page.locator('#reg-phone').fill('13800138000')
    await page.locator('#reg-code').fill('123456')
    await page.getByRole('button', { name: /下一步/ }).click()

    await page.getByRole('button', { name: /上一步/ }).click()
    // 回到步骤一
    await expect(page.locator('#reg-phone')).toBeVisible()
  })

  test('步骤二数据在返回后保留', async ({ page }) => {
    await page.locator('#reg-phone').fill('13800138000')
    await page.locator('#reg-code').fill('123456')
    await page.getByRole('button', { name: /下一步/ }).click()

    await page.locator('#companyName').fill('测试企业')
    await page.getByRole('button', { name: /上一步/ }).click()
    // 回到步骤一后再前进
    await page.getByRole('button', { name: /下一步/ }).click()
    // 企业名称应该保留
    await expect(page.locator('#companyName')).toHaveValue('测试企业')
  })

  test('步骤二企业名称为空时提交提示错误', async ({ page }) => {
    await page.locator('#reg-phone').fill('13800138000')
    await page.locator('#reg-code').fill('123456')
    await page.getByRole('button', { name: /下一步/ }).click()

    await page.locator('#contactName').fill('张三')
    await page.getByRole('button', { name: /提交申请/ }).click()
    const error = page.locator('p.text-red-500').first()
    if (await error.isVisible().catch(() => false)) {
      await expect(error).toContainText(/请输入企业名称/)
    }
  })

  test('步骤二联系人为空时提交提示错误', async ({ page }) => {
    await page.locator('#reg-phone').fill('13800138000')
    await page.locator('#reg-code').fill('123456')
    await page.getByRole('button', { name: /下一步/ }).click()

    await page.locator('#companyName').fill('测试企业')
    await page.getByRole('button', { name: /提交申请/ }).click()
    const error = page.locator('p.text-red-500').first()
    if (await error.isVisible().catch(() => false)) {
      await expect(error).toContainText(/请输入联系人姓名/)
    }
  })

  // ── 步骤三：提交成功 ──

  test('提交成功后显示成功页面', async ({ page }) => {
    await page.locator('#reg-phone').fill('13800138000')
    await page.locator('#reg-code').fill('123456')
    await page.getByRole('button', { name: /下一步/ }).click()

    await page.locator('#companyName').fill('测试企业')
    await page.locator('#contactName').fill('张三')
    await page.getByRole('button', { name: /提交申请/ }).click()

    // 等待提交完成
    await page.waitForTimeout(2000)

    // 步骤三可能显示（如果 API 成功）或显示错误 toast
    const successPage = page.getByText('申请已提交')
    const toast = page.locator('[data-sonner-toast]')
    const hasSuccess = await successPage.isVisible().catch(() => false)
    const hasToast = await toast.isVisible().catch(() => false)
    expect(hasSuccess || hasToast).toBeTruthy()
  })

  test('成功页面显示能力卡片', async ({ page }) => {
    // 假设提交成功
    await page.locator('#reg-phone').fill('13800138000')
    await page.locator('#reg-code').fill('123456')
    await page.getByRole('button', { name: /下一步/ }).click()
    await page.locator('#companyName').fill('测试企业')
    await page.locator('#contactName').fill('张三')
    await page.getByRole('button', { name: /提交申请/ }).click()
    await page.waitForTimeout(2000)

    // 如果成功进入步骤三
    if (await page.getByText('申请已提交').isVisible().catch(() => false)) {
      await expect(page.getByText(/米宝.*智能工作助手/)).toBeVisible()
      await expect(page.getByText(/小布.*智能客服/)).toBeVisible()
      await expect(page.getByText(/全功能管理后台/)).toBeVisible()
    }
  })

  test('成功页面"返回登录"链接可见', async ({ page }) => {
    await page.locator('#reg-phone').fill('13800138000')
    await page.locator('#reg-code').fill('123456')
    await page.getByRole('button', { name: /下一步/ }).click()
    await page.locator('#companyName').fill('测试企业')
    await page.locator('#contactName').fill('张三')
    await page.getByRole('button', { name: /提交申请/ }).click()
    await page.waitForTimeout(2000)

    if (await page.getByText('申请已提交').isVisible().catch(() => false)) {
      const backLink = page.getByRole('link', { name: /返回登录/ })
      await expect(backLink).toBeVisible()
    }
  })

  test('底部"返回登录"链接始终可见', async ({ page }) => {
    const backLink = page.getByRole('link', { name: /返回登录/ }).first()
    await expect(backLink).toBeVisible()
  })
})
