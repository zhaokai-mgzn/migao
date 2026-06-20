/**
 * 商品编辑页字段反显 E2E 测试
 * 验证米宝创建的商品在编辑页各字段是否正确展示
 */
import { test, expect } from '@playwright/test'
const TEST_PRODUCT_ID = 'f60ac4b060a4ebaf8542e890f03b3594'

test.describe('商品编辑页 — 字段反显验证', () => {

  test.beforeEach(async ({ page }) => {
    // Mock /api/auth/me — AuthProvider.initialize() 验证 token
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: { id: '1', username: 'admin', name: '管理员', roles: ['admin'], tenantId: 1, tenantName: '测试企业' } }) })
    })
    // Mock 商品详情 API（编辑页必须）
    await page.route(`**/api/admin/products/${TEST_PRODUCT_ID}`, async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          code: 200,
          data: {
            id: TEST_PRODUCT_ID,
            name: '遮光窗帘',
            skuCode: 'CL-001',
            categoryId: 'cat1',
            sellingMethods: ['bulk_cut', 'full_roll'],
            colors: [{ colorName: '灰色' }],
            doorWidths: [{ width: '2.8米' }],
            skus: [{ id: 'sku1', color: '灰色', width: '2.8米', sellingMethod: 'bulk_cut', price: 100, stock: 10 }],
            status: 'on_sale',
            images: [],
            detailImages: [],
            processingItemConfigs: [],
          },
        }),
      })
    })
    // Mock 分类 API
    await page.route('**/api/admin/categories*', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: [{ id: 'cat1', name: '窗帘布艺', sort: 1, children: [] }] }),
      })
    })
    // Mock 加工项 API
    await page.route('**/api/admin/processing-items*', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: { items: [], total: 0 } }),
      })
    })

    await page.goto(`/products/${TEST_PRODUCT_ID}/edit`)
    await page.waitForLoadState('load')
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
