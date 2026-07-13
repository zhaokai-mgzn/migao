import { test, expect } from '@playwright/test'

/**
 * 商品详情 E2E 测试
 *
 * 通过 mock API 拦截商品详情接口，验证详情页面展示逻辑。
 */

const MOCK_PRODUCT = {
  id: 'prod_detail_001',
  name: '天鹅绒遮光窗帘',
  sku: 'SKU-DETAIL-001',
  skuCode: 'SKU-DETAIL-001',
  brand: '米高',
  categoryId: 'cat_001',
  categoryName: '窗帘布艺',
  description: '<p>优质天鹅绒材质，遮光率95%以上</p>',
  pricingType: 'per_meter',
  price: 168.0,
  costPrice: 85.0,
  unit: '米',
  totalStock: 250,
  status: 'on_sale',
  images: ['https://example.com/main.jpg', 'https://example.com/main2.jpg'],
  detailImages: ['https://example.com/detail1.jpg'],
  specifications: { weight: '300-400g', material: '绒布', function: '遮光', craft: '提花', style: '现代简约', pattern: '纯色' },
  processingItemConfigs: [
    { processingItemId: 'proc_001', processingItemName: '韩式打褶定型', customPrice: 25.0 },
  ],
  stockDeductionMode: 'on_place',
  colors: [
    { id: 1, colorName: '灰色', colorImageUrl: 'https://example.com/gray.jpg' },
    { id: 2, colorName: '米白', colorImageUrl: 'https://example.com/white.jpg' },
  ],
  sellingMethods: ['bulk_cut', 'full_roll'],
  doorWidths: ['门幅2.8米'],
  skus: [
    { id: 1, colorId: 1, colorName: '灰色', sellingMethod: 'bulk_cut', doorWidth: '门幅2.8米', price: 168, stock: 100, status: 'active' },
    { id: 2, colorId: 2, colorName: '米白', sellingMethod: 'bulk_cut', doorWidth: '门幅2.8米', price: 158, stock: 150, status: 'active' },
  ],
  createdAt: '2025-01-15 10:30:00',
  updatedAt: '2025-03-20 14:20:00',
}

test.describe('商品详情', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/admin/products/prod_detail_001', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: MOCK_PRODUCT }),
      })
    })

    await page.goto('/products/prod_detail_001')
    await expect(page.getByRole('heading', { name: '天鹅绒遮光窗帘' })).toBeVisible({ timeout: 10_000 })
  })

  test('应显示商品名称和状态徽章', async ({ page }) => {
    await expect(page.getByRole('heading', { name: '天鹅绒遮光窗帘' })).toBeVisible()
    await expect(page.getByText('出售中')).toBeVisible()
  })

  test('应显示 SKU 编号', async ({ page }) => {
    await expect(page.getByText('SKU: SKU-DETAIL-001')).toBeVisible()
  })

  test('应显示商品图片区域', async ({ page }) => {
    await expect(page.getByText('商品图片')).toBeVisible()
  })

  test('基本信息应显示分类、品牌、计价方式、单价', async ({ page }) => {
    await expect(page.getByRole('heading', { name: '基本信息' })).toBeVisible()
    await expect(page.getByText('窗帘布艺')).toBeVisible()
    // "米高" is also the app name in sidebar; scope to product info
    const infoSection = page.getByRole('heading', { name: '基本信息' }).locator('..')
    await expect(infoSection.getByText('米高')).toBeVisible()
    await expect(page.getByText('按米')).toBeVisible()
    await expect(page.getByText('¥168.00/米')).toBeVisible()
  })

  test('应显示 SKU 规格表格', async ({ page }) => {
    await expect(page.getByText('销售信息')).toBeVisible()
    // 验证表格中包含颜色名
    const table = page.locator('table').last()
    await expect(table.getByText('灰色')).toBeVisible()
    await expect(table.getByText('米白')).toBeVisible()
  })

  test('应显示加工项配置', async ({ page }) => {
    await expect(page.getByRole('heading', { name: '加工项' }).first()).toBeVisible()
    await expect(page.getByText('韩式打褶定型')).toBeVisible()
    await expect(page.getByText('¥25.00/米')).toBeVisible()
  })

  test('应显示商品描述', async ({ page }) => {
    await expect(page.getByText('商品描述')).toBeVisible()
    await expect(page.getByText(/优质天鹅绒材质/)).toBeVisible()
  })

  test('点击编辑按钮应跳转到编辑页', async ({ page }) => {
    await page.getByRole('button', { name: /编辑/ }).click()
    await page.waitForURL(/\/products\/prod_detail_001\/edit/)
  })

  test('已上架商品应显示下架按钮', async ({ page }) => {
    await expect(page.getByRole('button', { name: /下架/ })).toBeVisible()
  })

  test('点击返回按钮应回到商品列表', async ({ page }) => {
    // 返回按钮是 ArrowLeft 图标按钮，验证存在且可点击
    const backBtn = page.locator('button').filter({ has: page.locator('svg.lucide-arrow-left') })
    await expect(backBtn.first()).toBeVisible()
    await backBtn.first().click()
    await page.waitForURL(/\/products/)
  })
})
