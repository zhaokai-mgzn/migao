import { test, expect } from '@playwright/test'

/**
 * 订单详情 E2E 测试
 *
 * 验证订单详情页面各区块渲染、状态操作按钮、弹窗交互等。
 */

const MOCK_ORDER_PENDING = {
  id: 'order_001',
  orderNo: 'ORD-20250101-0001',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '浙江省杭州市西湖区文三路100号',
  totalAmount: 536.0,
  actualAmount: 536.0,
  status: 'pending_payment',
  hasProcessing: true,
  paymentDeadline: '2025-12-31T23:59:59Z',
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
  processingItems: [
    { id: 'pi_001', name: '韩式打褶定型', unitPrice: 25.0, quantity: 2, amount: 50.0 },
  ],
  logistics: null,
  createdAt: '2025-01-15T10:30:00Z',
  paidAt: null,
  shippedAt: null,
  receivedAt: null,
}

const MOCK_ORDER_SHIPPED = {
  ...MOCK_ORDER_PENDING,
  id: 'order_002',
  status: 'shipped',
  paidAt: '2025-01-15T11:00:00Z',
  shippedAt: '2025-01-16T09:00:00Z',
  logistics: {
    company: '德邦快递',
    trackingNo: 'DB1234567890',
    shippingMethod: 'logistics',
  },
}

const MOCK_ORDER_COMPLETED = {
  ...MOCK_ORDER_PENDING,
  id: 'order_003',
  status: 'completed',
  paidAt: '2025-01-15T11:00:00Z',
  shippedAt: '2025-01-16T09:00:00Z',
  receivedAt: '2025-01-18T14:00:00Z',
  logistics: {
    company: '德邦快递',
    trackingNo: 'DB1234567890',
    shippingMethod: 'logistics',
  },
}

test.describe('订单详情 - 待付款状态', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/admin/orders/order_001', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: MOCK_ORDER_PENDING }),
      })
    })

    await page.goto('/orders/order_001')
    await page.waitForSelector('text=订单详情')
  })

  test('应显示页面标题和面包屑', async ({ page }) => {
    await expect(page.getByRole('heading', { name: '订单详情' })).toBeVisible()
    await expect(page.getByText('订单列表')).toBeVisible()
  })

  test('待付款应显示"待买家付款"', async ({ page }) => {
    await expect(page.getByText('待买家付款')).toBeVisible()
  })

  test('应显示支付倒计时', async ({ page }) => {
    await expect(page.getByText('支付倒计时')).toBeVisible()
  })

  test('应显示关闭订单和确认付款按钮', async ({ page }) => {
    await expect(page.getByRole('button', { name: '关闭订单' })).toBeVisible()
    await expect(page.getByRole('button', { name: /确认付款/ })).toBeVisible()
  })

  test('基础信息应显示订单编号', async ({ page }) => {
    await expect(page.getByText('订单编号')).toBeVisible()
    await expect(page.getByText('ORD-20250101-0001')).toBeVisible()
  })

  test('商品信息表格应显示商品名和金额', async ({ page }) => {
    await expect(page.getByText('商品信息')).toBeVisible()
    await expect(page.getByText('天鹅绒遮光窗帘')).toBeVisible()
    await expect(page.getByText('订单实收款')).toBeVisible()
  })

  test('加工项表格应显示加工项名称和金额', async ({ page }) => {
    await expect(page.getByText('韩式打褶定型')).toBeVisible()
  })

  test('收货信息应显示收货人、电话、地址', async ({ page }) => {
    await expect(page.getByText('收货信息')).toBeVisible()
    await expect(page.getByText('张三')).toBeVisible()
    await expect(page.getByText('13800138000')).toBeVisible()
    await expect(page.getByText('浙江省杭州市西湖区文三路100号')).toBeVisible()
  })

  test('点击关闭订单应弹出确认对话框', async ({ page }) => {
    await page.getByRole('button', { name: '关闭订单' }).click()
    await expect(page.getByText('关闭订单')).toBeVisible()
    await expect(page.getByText(/确定关闭当前订单/)).toBeVisible()
  })

  test('关闭订单对话框应显示预设原因', async ({ page }) => {
    await page.getByRole('button', { name: '关闭订单' }).click()
    await expect(page.getByText('缺货')).toBeVisible()
    await expect(page.getByText('过期未付款')).toBeVisible()
    await expect(page.getByText('协商一致')).toBeVisible()
    await expect(page.getByText('备注其它原因')).toBeVisible()
  })

  test('点击确认付款应弹出确认对话框', async ({ page }) => {
    await page.getByRole('button', { name: /确认付款/ }).click()
    await expect(page.getByText('确认付款')).toBeVisible()
    await expect(page.getByText(/确认已收到付款/)).toBeVisible()
  })
})

test.describe('订单详情 - 待发货状态', () => {
  test.beforeEach(async ({ page }) => {
    const pendingShipOrder = { ...MOCK_ORDER_PENDING, id: 'order_pending_ship', status: 'pending_shipment', paidAt: '2025-01-15T11:00:00Z' }
    await page.route('**/api/admin/orders/order_pending_ship', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: pendingShipOrder }),
      })
    })
    await page.goto('/orders/order_pending_ship')
    await page.waitForSelector('text=订单详情')
  })

  test('待发货应显示发货按钮', async ({ page }) => {
    await expect(page.getByRole('button', { name: /发货/ })).toBeVisible()
  })

  test('点击发货应跳转到发货页面', async ({ page }) => {
    await page.getByRole('button', { name: /发货/ }).click()
    await page.waitForURL(/\/orders\/order_pending_ship\/ship/)
  })
})

test.describe('订单详情 - 已发货状态', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/admin/orders/order_002', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: MOCK_ORDER_SHIPPED }),
      })
    })

    await page.goto('/orders/order_002')
    await page.waitForSelector('text=订单详情')
  })

  test('已发货应显示编辑物流和确认收货按钮', async ({ page }) => {
    await expect(page.getByRole('button', { name: '编辑物流' })).toBeVisible()
    await expect(page.getByRole('button', { name: /确认收货/ })).toBeVisible()
  })

  test('点击确认收货应弹出确认对话框', async ({ page }) => {
    await page.getByRole('button', { name: /确认收货/ }).click()
    await expect(page.getByText('确认收货')).toBeVisible()
    await expect(page.getByText(/确认客户已收到货物/)).toBeVisible()
  })
})

test.describe('订单详情 - 已完成状态', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/admin/orders/order_003', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: MOCK_ORDER_COMPLETED }),
      })
    })

    await page.goto('/orders/order_003')
    await page.waitForSelector('text=订单详情')
  })

  test('已完成状态不应显示操作按钮', async ({ page }) => {
    await expect(page.getByRole('button', { name: '关闭订单' })).toBeHidden()
    await expect(page.getByRole('button', { name: '发货' })).toBeHidden()
  })

  test('面包屑应可点击返回订单列表', async ({ page }) => {
    await page.getByText('订单列表').click()
    await page.waitForURL(/\/orders/)
  })
})
