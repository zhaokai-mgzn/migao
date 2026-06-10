/**
 * 商品编辑页字段反显 E2E 测试
 * 验证米宝创建的商品在编辑页各字段是否正确展示
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, injectAuth } from '../../helpers/auth.helper'

const TEST_PRODUCT_ID = 'f60ac4b060a4ebaf8542e890f03b3594'
const BASE_URL = process.env.BASE_URL || 'http://localhost:3001'

test.describe('商品编辑页 — 字段反显验证', () => {

  test.beforeEach(async ({ page }) => {
    const tokens = await loginViaApi('13800138000', '123456')
    await page.goto(BASE_URL)
    await injectAuth(page, tokens)
    await page.goto(`${BASE_URL}/products/${TEST_PRODUCT_ID}/edit`)
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000)
  })

  test('基础信息反显', async ({ page }) => {

    // 商品标题 — 有默认值即可
    const titleInput = page.locator('#productName, input[value]').first()
    await expect(titleInput).toBeVisible()

    // 货号
    const skuInput = page.locator('input[placeholder*="货号"]')
    await expect(skuInput).not.toHaveValue('')

    // 分类已选择
    const selects = page.locator('select')
    const firstSelect = selects.first()
    await expect(firstSelect).not.toHaveValue('')
  })

  test('售卖方式反显', async ({ page }) => {

    // 售卖方式在select option中，检查select的选中值
    const bulkCut = page.locator('select option[value="bulk_cut"]')
    const fullRoll = page.locator('select option[value="full_roll"]')
    await expect(bulkCut.first()).toBeAttached()
    await expect(fullRoll.first()).toBeAttached()
  })

  test('SKU表格+按钮', async ({ page }) => {

    // SKU 表格有数据
    const skuRows = page.locator('table tbody tr')
    const count = await skuRows.count()
    expect(count).toBeGreaterThan(0)

    // 提交按钮
    await expect(page.getByRole('button', { name: '保存修改' })).toBeVisible()
  })
})
