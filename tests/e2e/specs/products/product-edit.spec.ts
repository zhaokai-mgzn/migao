import { test, expect } from '@playwright/test'

/**
 * 商品编辑 E2E 测试
 *
 * 前置条件：需要至少存在一个已创建的商品。
 * 测试使用动态路由 /products/[id]/edit，通过 mock API 拦截加载商品数据。
 */

const MOCK_PRODUCT = {
  id: 'prod_test_edit_001',
  name: '编辑测试商品-天鹅绒窗帘',
  sku: 'SKU-EDIT-001',
  skuCode: 'SKU-EDIT-001',
  brand: '米高',
  categoryId: 'cat_001',
  categoryName: '窗帘',
  description: '<p>这是商品描述</p>',
  pricingType: 'fixed',
  price: 128.0,
  costPrice: 65.0,
  unit: '米',
  totalStock: 100,
  status: 'on_sale',
  images: ['https://example.com/img1.jpg'],
  detailImages: [],
  specifications: { weight: '200-300g', material: '涤纶' },
  processingItemConfigs: [],
  supportsProcessing: false,
  stockDeductionMode: 'on_place',
  colors: [
    { id: 1, colorName: '红色', colorImageUrl: 'https://example.com/red.jpg', mainColorHex: '#FF0000' },
  ],
  sellingMethods: ['bulk_cut'],
  doorWidths: ['门幅2.8米'],
  skus: [
    { id: 1, colorId: 1, colorName: '红色', sellingMethod: 'bulk_cut', doorWidth: '门幅2.8米', price: 128, stock: 50, status: 'active' },
  ],
}

test.describe('商品编辑', () => {
  test.beforeEach(async ({ page }) => {
    // 拦截商品详情 API
    await page.route('**/api/admin/products/prod_test_edit_001', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: MOCK_PRODUCT }),
      })
    })

    // 拦截分类 API
    await page.route('**/api/admin/categories*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 200,
          data: [{ id: 'cat_001', name: '窗帘', children: [] }],
        }),
      })
    })

    // 拦截加工项 API
    await page.route('**/api/admin/processing-items*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: { items: [], total: 0 } }),
      })
    })

    await page.goto('/products/prod_test_edit_001/edit')
    await page.waitForSelector('text=编辑商品')
  })

  test('应显示编辑商品标题', async ({ page }) => {
    await expect(page.getByText('编辑商品')).toBeVisible()
  })

  test('应回填商品标题', async ({ page }) => {
    const titleInput = page.locator('#pf-name input')
    await expect(titleInput).toHaveValue('编辑测试商品-天鹅绒窗帘')
  })

  test('应回填货号', async ({ page }) => {
    const skuInput = page.locator('#pf-unit input[placeholder="请输入商品货号"]')
    await expect(skuInput).toHaveValue('SKU-EDIT-001')
  })

  test('应回填已有颜色', async ({ page }) => {
    // 颜色行应包含"红色"
    await expect(page.locator('input[placeholder="主色(必选)"]').first()).toHaveValue('红色')
  })

  test('应回填 SKU 矩阵数据', async ({ page }) => {
    // 销售规格表应展示已有的 SKU 行
    const skuTable = page.locator('table')
    await expect(skuTable).toBeVisible()
    // 验证颜色名称出现
    await expect(skuTable.getByText('红色')).toBeVisible()
  })

  test('提交按钮文字应为"保存修改"', async ({ page }) => {
    // 编辑模式下主按钮文字
    await expect(page.getByRole('button', { name: '保存修改' })).toBeVisible()
  })

  test('修改标题后保存应调用更新 API', async ({ page }) => {
    const titleInput = page.locator('#pf-name input')
    await titleInput.fill('修改后的标题')

    // 拦截更新 API
    let updateCalled = false
    await page.route('**/api/admin/products/prod_test_edit_001', async (route) => {
      if (route.request().method() === 'PUT' || route.request().method() === 'PATCH') {
        updateCalled = true
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
      } else {
        await route.fallback()
      }
    })

    await page.getByRole('button', { name: '存草稿' }).click()
    // 等待 API 调用
    await page.waitForTimeout(500)
    expect(updateCalled).toBe(true)
  })

  test('保存成功后应跳转到商品列表', async ({ page }) => {
    await page.route('**/api/admin/products/prod_test_edit_001', async (route) => {
      if (route.request().method() === 'PUT' || route.request().method() === 'PATCH') {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
      } else {
        await route.fallback()
      }
    })

    await page.getByRole('button', { name: '存草稿' }).click()
    await page.waitForURL(/\/products/, { timeout: 10_000 })
  })

  test('应回填分类选择', async ({ page }) => {
    const categorySelect = page.locator('#pf-category select')
    await expect(categorySelect).toHaveValue('cat_001')
  })

  test('应回填库存扣减方式', async ({ page }) => {
    // 默认选中"是"（on_place）
    const yesRadio = page.locator('input[type="radio"]:checked').first()
    await expect(yesRadio).toBeAttached()
  })

  test('空标题保存应显示错误', async ({ page }) => {
    const titleInput = page.locator('#pf-name input')
    await titleInput.fill('')
    await page.getByRole('button', { name: '存草稿' }).click()
    await expect(page.getByText('请输入商品标题')).toBeVisible()
  })

  test('重置应恢复到初始数据', async ({ page }) => {
    const titleInput = page.locator('#pf-name input')
    await titleInput.fill('被修改的标题')

    page.once('dialog', async (dialog) => {
      await dialog.accept()
    })
    await page.getByRole('button', { name: '重置' }).first().click()

    // 重置后应恢复原始标题
    await expect(titleInput).toHaveValue('编辑测试商品-天鹅绒窗帘')
  })
})
