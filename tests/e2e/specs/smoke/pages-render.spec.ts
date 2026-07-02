/**
 * 最小可用性验证 — 确认 E2E auth 和基础页面渲染正常
 */
import { test, expect } from '@playwright/test'

test.describe('冒烟：页面基础渲染', () => {
  test.beforeEach(async ({ page }) => {
    // E2E mock token 不被真实后端识别，必须 mock /api/auth/me
    // 否则 AuthProvider.fetchUserInfo() 返回 401 → 清空认证 → 跳转登录
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: { id: '1', username: 'admin', name: '管理员', roles: ['admin'], tenantId: 1, tenantName: '测试企业' } }),
      })
    })
  })

  test('仪表盘 → 进入默认页面（商品列表）', async ({ page }) => {
    await page.goto('/products')
    await expect(page.locator('aside')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('h1, h2').filter({ hasText: /商品/ }).first()).toBeVisible({ timeout: 10000 })
  })

  test('商品列表 → 表格渲染', async ({ page }) => {
    await page.goto('/products')
    await expect(page.locator('aside')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('table, [role="grid"]').first()).toBeVisible({ timeout: 10000 })
  })

  test('订单列表 → 表格渲染', async ({ page }) => {
    await page.goto('/orders')
    await expect(page.locator('aside')).toBeVisible({ timeout: 15000 })
    await expect(page.locator('table, [role="grid"]').first()).toBeVisible({ timeout: 10000 })
  })

  test('新增订单 → 表单渲染', async ({ page }) => {
    await page.goto('/orders/new')
    await expect(page.locator('aside')).toBeVisible({ timeout: 15000 })
    // "收货信息"和"商品信息"都存在 → 用 first() 只检查第一个
    await expect(page.getByText('收货信息').first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('商品信息').first()).toBeVisible({ timeout: 10000 })
  })
})
