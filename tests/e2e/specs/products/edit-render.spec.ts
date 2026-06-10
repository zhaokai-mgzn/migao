/**
 * 商品编辑页字段反显 E2E 测试
 * 验证米宝创建的商品在编辑页各字段是否正确展示
 */
import { test, expect } from '@playwright/test'
import { LoginPage } from '../../pages/login.page'

const TEST_PRODUCT_ID = 'f60ac4b060a4ebaf8542e890f03b3594' // 米宝创建的商品
const BASE_URL = process.env.BASE_URL || 'http://localhost:3001'

test.describe('商品编辑页 — 字段反显验证', () => {

  test.beforeEach(async ({ page }) => {
    const loginPage = new LoginPage(page)
    await page.goto(`${BASE_URL}/login`)
    await loginPage.login('13800138000', '123456')
  })

  test('基础信息反显', async ({ page }) => {
    await page.goto(`${BASE_URL}/products/${TEST_PRODUCT_ID}/edit`)
    await page.waitForLoadState('networkidle')

    // 商品标题
    const titleInput = page.locator('input[placeholder*="商品标题"]')
    await expect(titleInput).toHaveValue(/2699/)

    // 货号
    const skuInput = page.locator('input[placeholder*="货号"]')
    await expect(skuInput).not.toHaveValue('')

    // 分类已选择
    const categorySelect = page.locator('select').first()
    await expect(categorySelect).not.toHaveValue('')
  })

  test('售卖方式反显', async ({ page }) => {
    await page.goto(`${BASE_URL}/products/${TEST_PRODUCT_ID}/edit`)
    await page.waitForLoadState('networkidle')

    // 售卖方式下拉框应选中"散剪"(bulk_cut→散剪)和"整卷"(full_roll→整卷)
    const smSelects = page.locator('select').filter({ has: page.locator('option[value="bulk_cut"]') })
    // 查找显示 "散剪" 的选项
    await expect(page.getByText('散剪').first()).toBeVisible()
    await expect(page.getByText('整卷').first()).toBeVisible()
  })

  test('门幅尺寸反显', async ({ page }) => {
    await page.goto(`${BASE_URL}/products/${TEST_PRODUCT_ID}/edit`)
    await page.waitForLoadState('networkidle')

    // 门幅选项应该可见
    await expect(page.getByText('2.8米').first()).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('3.2米').first()).toBeVisible({ timeout: 5000 })
  })

  test('SKU表格渲染', async ({ page }) => {
    await page.goto(`${BASE_URL}/products/${TEST_PRODUCT_ID}/edit`)
    await page.waitForLoadState('networkidle')

    // SKU 表格应该有数据行
    const skuRows = page.locator('table tbody tr')
    const count = await skuRows.count()
    expect(count).toBeGreaterThanOrEqual(2) // 至少2行SKU
  })

  test('操作按钮可用', async ({ page }) => {
    await page.goto(`${BASE_URL}/products/${TEST_PRODUCT_ID}/edit`)
    await page.waitForLoadState('networkidle')

    // 关键按钮应该可见
    await expect(page.getByRole('button', { name: '保存修改' })).toBeVisible()
    await expect(page.getByRole('button', { name: '存草稿' })).toBeVisible()
    await expect(page.getByRole('button', { name: '重置' })).toBeVisible()
  })
})
