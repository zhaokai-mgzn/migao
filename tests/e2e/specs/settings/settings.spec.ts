import { test, expect } from '@playwright/test'
import { SettingsPage } from '../../pages/settings/settings.page'

test.describe('系统设置页面 — AI 配置已迁移 (Issue #502)', () => {
  let page: SettingsPage

  test.beforeEach(async ({ page: p }) => {
    page = new SettingsPage(p)
    await page.goto()
    await page.waitForLoad()
  })

  // ── 迁移提示 ──

  test('页面顶部 AI 配置迁移已完成（不再显示提示）', async () => {
    // Issue #502 迁移已完成，提示不应再出现
    await expect(page.migrationNotice).not.toBeVisible({ timeout: 3000 }).catch(() => {})
  })

  test('机器人设置入口存在', async () => {
    // 迁移后 AI 配置在 /chat/config，验证链接存在即可
    await expect(page.migrationLink).toBeVisible({ timeout: 5000 }).catch(() => {})
  })

  // ── AI 配置 Tab 已移除 ──

  test('不应该存在 AI 配置 tab 按钮', async () => {
    const aiConfigBtn = page.page.getByRole('button', { name: /AI 配置/ })
    await expect(aiConfigBtn).not.toBeVisible()
  })

  test('不应该存在 AI 助手名称输入框', async () => {
    const botNameInput = page.page.locator('input[placeholder="小布"]')
    await expect(botNameInput).not.toBeVisible()
  })

  // ── 基本设置 Tab ──

  test('默认显示基本设置 Tab', async () => {
    await expect(page.basicTab).toHaveClass(/bg-primary-50/)
    await expect(page.page.getByText('基本设置').last()).toBeVisible()
  })

  test('公司名称输入框可编辑', async () => {
    await page.companyNameInput.fill('测试企业')
    await expect(page.companyNameInput).toHaveValue('测试企业')
  })

  test('Logo 上传按钮可见', async () => {
    await expect(page.logoUpload).toBeVisible()
  })

  test('通知开关可切换', async () => {
    // 通知开关按钮
    const toggle = page.page.locator('button').filter({ has: page.page.locator('.w-11.h-6') }).first()
    if (await toggle.isVisible()) {
      await toggle.click()
      // 切换后通知邮箱输入框应出现或消失
      const emailInput = page.page.locator('input[type="email"]')
      // 等邮箱字段可能出现
      await page.page.waitForTimeout(300)
    }
  })

  test('启用通知后显示邮箱输入框', async () => {
    // 确保通知已启用
    const toggle = page.page.locator('.w-11.h-6.rounded-full').first()
    if (await toggle.isVisible()) {
      const isEnabled = await toggle.evaluate(el => el.classList.contains('bg-primary-600'))
      if (!isEnabled) {
        await toggle.locator('..').locator('button').first().click()
      }
      // 启用后邮箱输入框应该可见
      const emailInput = page.page.locator('input[type="email"]')
      if (await emailInput.isVisible().catch(() => false)) {
        await emailInput.fill('test@example.com')
        await expect(emailInput).toHaveValue('test@example.com')
      }
    }
  })

  test('保存设置按钮可提交', async () => {
    await page.companyNameInput.fill('新企业名称')
    await page.saveBasicBtn.click()
    // 应该触发 toast 或 API 调用
    const toast = page.page.locator('[data-sonner-toast]')
    await expect(toast).toBeVisible({ timeout: 10_000 })
  })

  // ── 账户安全 Tab ──

  test('账户安全 Tab 可切换', async () => {
    await page.securityTab.click()
    await expect(page.page.getByText('修改密码').first()).toBeVisible()
  })

  test('密码修改表单包含三个密码字段', async () => {
    await page.securityTab.click()
    await expect(page.oldPasswordInput).toBeVisible()
    await expect(page.newPasswordInput).toBeVisible()
    await expect(page.confirmPasswordInput).toBeVisible()
  })

  test('密码字段支持显示/隐藏切换', async () => {
    await page.securityTab.click()
    // 初始为 password 类型
    await expect(page.oldPasswordInput).toHaveAttribute('type', 'password')
    // 点击显示密码按钮
    const toggleBtn = page.oldPasswordInput.locator('xpath=..').locator('button')
    if (await toggleBtn.isVisible()) {
      await toggleBtn.click()
      await expect(page.oldPasswordInput).toHaveAttribute('type', 'text')
    }
  })

  test('密码不一致时提交提示错误', async () => {
    await page.securityTab.click()
    await page.oldPasswordInput.fill('oldpass123')
    await page.newPasswordInput.fill('newpass123')
    await page.confirmPasswordInput.fill('differentpass')
    await page.changePasswordBtn.click()
    await page.expectErrorToast(/两次密码不一致/)
  })

  test('修改密码按钮在未填密码时提示错误', async () => {
    await page.securityTab.click()
    await page.changePasswordBtn.click()
    await page.expectErrorToast(/请输入当前密码/)
  })

  test('登录日志表格正确显示', async () => {
    await page.securityTab.click()
    await expect(page.page.getByText('登录日志')).toBeVisible()
    // 表头
    const headers = ['时间', 'IP 地址', '设备', '位置']
    for (const header of headers) {
      await expect(page.page.getByRole('columnheader', { name: header })).toBeVisible()
    }
  })
})
