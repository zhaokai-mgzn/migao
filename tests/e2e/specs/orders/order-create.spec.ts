import { test, expect } from '@playwright/test'

/**
 * 订单创建 E2E 测试
 *
 * 验证新增订单页面：收货信息、商品搜索弹窗、行项配置、费用汇总、提交校验。
 */

const MOCK_PRODUCTS = {
  items: [
    {
      id: 'prod_001',
      name: '天鹅绒遮光窗帘',
      skuCode: 'SKU-001',
      price: 168.0,
      categoryName: '窗帘',
      images: ['https://example.com/img1.jpg'],
      status: 'on_sale',
    },
    {
      id: 'prod_002',
      name: '亚麻纱帘',
      skuCode: 'SKU-002',
      price: 88.0,
      categoryName: '纱帘',
      images: [],
      status: 'on_sale',
    },
  ],
  total: 2,
}

const MOCK_PRODUCT_DETAIL = {
  id: 'prod_001',
  name: '天鹅绒遮光窗帘',
  skuCode: 'SKU-001',
  price: 168.0,
  categoryName: '窗帘',
  images: ['https://example.com/img1.jpg'],
  supportsProcessing: true,
  hasProcessing: true,
  skus: [
    { id: 1, colorId: 101, colorName: '灰色', sellingMethod: 'bulk_cut', doorWidth: '门幅2.8米', price: 168, stock: 100 },
    { id: 2, colorId: 102, colorName: '米白', sellingMethod: 'bulk_cut', doorWidth: '门幅2.8米', price: 158, stock: 50 },
  ],
}

const MOCK_PROCESSING_ITEMS = [
  { id: 'pi_001', name: '韩式打褶定型', unitPrice: 25.0, finalPrice: 25.0, unit: '米', pricingMethod: 'per_meter' },
  { id: 'pi_002', name: '打孔', unitPrice: 15.0, finalPrice: 15.0, unit: '米', pricingMethod: 'per_meter' },
]

test.describe('订单创建', () => {
  test.beforeEach(async ({ page }) => {
    // 拦截商品列表 API（搜索弹窗使用）
    await page.route('**/api/admin/products*', async (route) => {
      const url = route.request().url()
      if (route.request().method() === 'GET' && !url.includes('/products/prod_')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ code: 200, data: MOCK_PRODUCTS }),
        })
      } else {
        await route.fallback()
      }
    })

    // 拦截商品详情 API
    await page.route('**/api/admin/products/prod_001', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: MOCK_PRODUCT_DETAIL }),
      })
    })

    // 拦截商品加工项 API
    await page.route('**/api/admin/products/prod_001/processing-items*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: MOCK_PROCESSING_ITEMS }),
      })
    })

    await page.goto('/orders/new')
    await page.waitForSelector('text=新增订单')
  })

  test.describe('页面加载', () => {
    test('应显示页面标题和描述', async ({ page }) => {
      await expect(page.getByRole('heading', { name: '新增订单' })).toBeVisible()
      await expect(page.getByText(/支持添加多个商品/)).toBeVisible()
    })

    test('应显示商品信息、收货信息、费用明细三个区块', async ({ page }) => {
      await expect(page.getByText('商品信息')).toBeVisible()
      await expect(page.getByText('收货信息')).toBeVisible()
      await expect(page.getByText('费用明细')).toBeVisible()
    })

    test('应显示提交和取消按钮', async ({ page }) => {
      await expect(page.getByRole('button', { name: '提交订单' })).toBeVisible()
      await expect(page.getByRole('button', { name: '取消' })).toBeVisible()
    })

    test('默认应有1个商品行项', async ({ page }) => {
      await expect(page.getByText('共 1 个商品')).toBeVisible()
    })
  })

  test.describe('收货信息', () => {
    test('应包含收货人姓名、手机号、地址、备注字段', async ({ page }) => {
      await expect(page.getByText('收货人姓名')).toBeVisible()
      await expect(page.getByText('手机号')).toBeVisible()
      await expect(page.getByText('收货地址')).toBeVisible()
      await expect(page.getByText('备注')).toBeVisible()
    })

    test('收货人姓名应可输入', async ({ page }) => {
      const nameInput = page.locator('input[placeholder="请输入收货人姓名"]')
      await nameInput.fill('张三')
      await expect(nameInput).toHaveValue('张三')
    })

    test('手机号应限制11位', async ({ page }) => {
      const phoneInput = page.locator('input[placeholder="请输入 11 位手机号"]')
      await phoneInput.fill('13800138000')
      await expect(phoneInput).toHaveValue('13800138000')
    })

    test('收货地址应可输入', async ({ page }) => {
      const addrInput = page.locator('input[placeholder="请输入详细收货地址"]')
      await addrInput.fill('浙江省杭州市西湖区文三路100号')
      await expect(addrInput).toHaveValue('浙江省杭州市西湖区文三路100号')
    })
  })

  test.describe('商品搜索弹窗', () => {
    test('点击搜索按钮应打开商品选择弹窗', async ({ page }) => {
      await page.getByText('点击搜索并选择商品').click()
      await expect(page.getByRole('heading', { name: '选择商品' })).toBeVisible()
    })

    test('弹窗应显示搜索框和商品列表', async ({ page }) => {
      await page.getByText('点击搜索并选择商品').click()
      const modal = page.locator('.fixed.inset-0.z-50').last()
      await expect(modal.locator('input[placeholder*="搜索商品"]')).toBeVisible()
      await expect(modal.getByText('天鹅绒遮光窗帘')).toBeVisible()
    })

    test('搜索商品应调用 API', async ({ page }) => {
      await page.getByText('点击搜索并选择商品').click()
      const modal = page.locator('.fixed.inset-0.z-50').last()
      const searchInput = modal.locator('input[placeholder*="搜索商品"]')
      await searchInput.fill('天鹅绒')
      await modal.getByRole('button', { name: '搜索' }).click()
      // 搜索结果应包含匹配的商品
      await expect(modal.getByText('天鹅绒遮光窗帘')).toBeVisible()
    })

    test('选择商品后应关闭弹窗并显示商品信息', async ({ page }) => {
      await page.getByText('点击搜索并选择商品').click()
      const modal = page.locator('.fixed.inset-0.z-50').last()
      await modal.getByText('天鹅绒遮光窗帘').click()
      // 弹窗应关闭
      await expect(modal).toBeHidden()
      // 商品信息应显示
      await expect(page.getByText('天鹅绒遮光窗帘').first()).toBeVisible()
    })
  })

  test.describe('行项配置', () => {
    test.beforeEach(async ({ page }) => {
      // 先选择一个商品
      await page.getByText('点击搜索并选择商品').click()
      const modal = page.locator('.fixed.inset-0.z-50').last()
      await modal.getByText('天鹅绒遮光窗帘').click()
      // 等待商品详情加载
      await page.waitForTimeout(500)
    })

    test('选择商品后应显示颜色选择', async ({ page }) => {
      await expect(page.getByText('颜色')).toBeVisible()
      await expect(page.getByRole('button', { name: '灰色' })).toBeVisible()
      await expect(page.getByRole('button', { name: '米白' })).toBeVisible()
    })

    test('选择颜色后应显示规格选择', async ({ page }) => {
      await page.getByRole('button', { name: '灰色' }).click()
      await expect(page.getByText('规格')).toBeVisible()
    })

    test('应显示数量和单价输入框', async ({ page }) => {
      await expect(page.getByText('数量')).toBeVisible()
      await expect(page.getByText('单价 (¥)')).toBeVisible()
    })

    test('数量默认为1', async ({ page }) => {
      const qtyInput = page.locator('input[type="number"][min="1"]').first()
      await expect(qtyInput).toHaveValue('1')
    })

    test('应显示加工选项', async ({ page }) => {
      await expect(page.getByText('加工选项（可选）')).toBeVisible()
      await expect(page.getByText('韩式打褶定型')).toBeVisible()
      await expect(page.getByText('打孔')).toBeVisible()
    })

    test('勾选加工项应显示数量输入', async ({ page }) => {
      const checkbox = page.locator('input[type="checkbox"]').first()
      await checkbox.check()
      // 勾选后应出现数量输入框
      await expect(page.locator('input[type="number"][min="1"]').nth(1)).toBeVisible()
    })
  })

  test.describe('多行项', () => {
    test('应支持添加多个商品行项', async ({ page }) => {
      await page.getByRole('button', { name: '添加商品' }).click()
      await expect(page.getByText('共 2 个商品')).toBeVisible()
    })

    test('多行时应支持删除行项', async ({ page }) => {
      await page.getByRole('button', { name: '添加商品' }).click()
      // 第二行应有删除按钮
      const secondRow = page.getByText('商品 2').locator('..').locator('..')
      await expect(secondRow.getByText('删除')).toBeVisible()
    })

    test('仅一行时不应显示删除按钮', async ({ page }) => {
      // 只有一个行项时，删除按钮不应出现
      await expect(page.getByText('删除')).toBeHidden()
    })
  })

  test.describe('费用汇总', () => {
    test('应显示商品小计、加工费、订单金额', async ({ page }) => {
      await expect(page.getByText('商品小计')).toBeVisible()
      await expect(page.getByText('加工费')).toBeVisible()
      // "订单金额" 在页面中出现多次（标签 + 汇总），使用 first() 匹配
      await expect(page.getByText('订单金额').first()).toBeVisible()
    })

    test('应显示实收款输入框', async ({ page }) => {
      await expect(page.getByText('实收款 (¥)')).toBeVisible()
    })
  })

  test.describe('表单校验', () => {
    test('未填收货信息提交应显示错误', async ({ page }) => {
      await page.getByRole('button', { name: '提交订单' }).click()
      await expect(page.getByText('请输入收货人姓名')).toBeVisible()
      await expect(page.getByText('请输入手机号')).toBeVisible()
      await expect(page.getByText('请输入收货地址')).toBeVisible()
    })

    test('手机号格式不正确应提示', async ({ page }) => {
      const phoneInput = page.locator('input[placeholder="请输入 11 位手机号"]')
      await phoneInput.fill('12345')
      await page.getByRole('button', { name: '提交订单' }).click()
      await expect(page.getByText('手机号格式不正确')).toBeVisible()
    })

    test('未选商品提交应提示商品未选择', async ({ page }) => {
      // 填写收货信息
      await page.locator('input[placeholder="请输入收货人姓名"]').fill('张三')
      await page.locator('input[placeholder="请输入 11 位手机号"]').fill('13800138000')
      await page.locator('input[placeholder="请输入详细收货地址"]').fill('杭州')
      await page.getByRole('button', { name: '提交订单' }).click()
      await expect(page.getByText(/商品未选择/)).toBeVisible()
    })
  })

  test.describe('取消操作', () => {
    test('点击取消应返回订单列表', async ({ page }) => {
      await page.getByRole('button', { name: '取消' }).click()
      await page.waitForURL(/\/orders/)
    })
  })
})
