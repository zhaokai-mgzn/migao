import { test, expect } from '@playwright/test'

/**
 * 订单发货 E2E 测试
 *
 * 验证发货页面：商品确认、收货信息、物流表单、无需物流选项、确认/取消操作。
 */

const MOCK_ORDER = {
  id: 'order_ship_001',
  orderNo: 'ORD-20250115-0001',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '浙江省杭州市西湖区文三路100号',
  totalAmount: 536.0,
  actualAmount: 536.0,
  status: 'pending_shipment',
  hasProcessing: false,
  items: [
    {
      id: 'item_001',
      productId: 'prod_001',
      productName: '天鹅绒遮光窗帘',
      productCode: 'SKU-001',
      color: '灰色',
      specification: '门幅2.8米',
      quantity: 2,
      unitPrice: 168.0,
      amount: 336.0,
      subtotal: 336.0,
    },
  ],
  processingItems: [],
  paidAt: '2025-01-15T11:00:00Z',
  createdAt: '2025-01-15T10:30:00Z',
}

test.describe('订单发货', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/admin/orders/order_ship_001', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: MOCK_ORDER }),
      })
    })

    await page.goto('/orders/order_ship_001/ship')
    await expect(page.getByRole('heading', { name: '商品发货' })).toBeVisible({ timeout: 10_000 })
  })

  test.describe('页面加载', () => {
    test('应显示商品发货标题', async ({ page }) => {
      await expect(page.getByRole('heading', { name: '商品发货' })).toBeVisible()
    })

    test('应显示面包屑导航', async ({ page }) => {
      // scope to breadcrumb area to avoid matching sidebar nav links
      const breadcrumb = page.locator('.text-sm.text-gray-500').filter({ hasText: /首页/ }).first()
      await expect(breadcrumb).toBeVisible()
      await expect(breadcrumb.getByText('订单管理')).toBeVisible()
      await expect(breadcrumb.getByText('订单列表')).toBeVisible()
      await expect(breadcrumb.getByText('订单详情')).toBeVisible()
      await expect(breadcrumb.getByText('商品发货')).toBeVisible()
    })
  })

  test.describe('确认商品信息', () => {
    test('应显示商品表格', async ({ page }) => {
      await expect(page.getByText('确认商品信息')).toBeVisible()
      await expect(page.getByText('天鹅绒遮光窗帘')).toBeVisible()
    })

    test('应显示订单实收款', async ({ page }) => {
      await expect(page.getByText(/订单实收款/)).toBeVisible()
    })
  })

  test.describe('确认收货信息', () => {
    test('应显示收货人信息', async ({ page }) => {
      await expect(page.getByText('确认收货信息')).toBeVisible()
      await expect(page.getByText('张三')).toBeVisible()
      await expect(page.getByText('13800138000')).toBeVisible()
      await expect(page.getByText('浙江省杭州市西湖区文三路100号')).toBeVisible()
    })
  })

  test.describe('物流表单', () => {
    test('默认应选择物流发货', async ({ page }) => {
      const logisticsRadio = page.locator('input[type="radio"]').first()
      await expect(logisticsRadio).toBeChecked()
    })

    test('应显示物流公司下拉', async ({ page }) => {
      await expect(page.getByText('物流公司')).toBeVisible()
      const companySelect = page.locator('select')
      await expect(companySelect).toBeVisible()
    })

    test('物流公司默认应为德邦快递', async ({ page }) => {
      const companySelect = page.locator('select')
      await expect(companySelect).toHaveValue('德邦快递')
    })

    test('应显示快递单号输入框', async ({ page }) => {
      await expect(page.getByText('快递单号')).toBeVisible()
      const trackingInput = page.locator('input[placeholder="请输入快递单号"]')
      await expect(trackingInput).toBeVisible()
    })

    test('应选择"无需物流"隐藏物流字段', async ({ page }) => {
      // 选择"无需物流"
      const noneRadio = page.getByLabel('无需物流')
      await noneRadio.click()
      // 物流公司和快递单号应隐藏
      await expect(page.locator('select')).toBeHidden()
      await expect(page.locator('input[placeholder="请输入快递单号"]')).toBeHidden()
    })
  })

  test.describe('表单校验', () => {
    test('物流发货时快递单号为空应提示错误', async ({ page }) => {
      // 不填快递单号直接确认
      await page.getByRole('button', { name: '确认发货' }).click()
      // 应提示输入快递单号
      await expect(page.getByText('请输入快递单号')).toBeVisible()
    })
  })

  test.describe('确认发货', () => {
    test('填写快递单号后应成功发货', async ({ page }) => {
      // 拦截发货 API
      let shipCalled = false
      await page.route('**/api/admin/orders/order_ship_001/logistics', async (route) => {
        shipCalled = true
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
      })

      await page.route('**/api/admin/orders/order_ship_001/status', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
      })

      // 填写快递单号
      const trackingInput = page.locator('input[placeholder="请输入快递单号"]')
      await trackingInput.fill('DB9876543210')

      await page.getByRole('button', { name: '确认发货' }).click()
      await page.waitForTimeout(500)
      expect(shipCalled).toBe(true)
    })

    test('无需物流模式应直接提交成功', async ({ page }) => {
      let shipCalled = false
      await page.route('**/api/admin/orders/order_ship_001/logistics', async (route) => {
        shipCalled = true
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
      })

      await page.route('**/api/admin/orders/order_ship_001/status', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200 }) })
      })

      // 选择无需物流
      const noneRadio = page.getByLabel('无需物流')
      await noneRadio.click()

      await page.getByRole('button', { name: '确认发货' }).click()
      await page.waitForTimeout(500)
      expect(shipCalled).toBe(true)
    })
  })

  test.describe('取消发货', () => {
    test('点击取消应返回订单详情', async ({ page }) => {
      await page.getByRole('button', { name: '取消发货' }).click()
      await page.waitForURL(/\/orders\/order_ship_001/)
    })
  })
})
