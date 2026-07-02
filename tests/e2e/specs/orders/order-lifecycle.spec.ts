/**
 * 订单全生命周期 E2E 测试
 *
 * 覆盖：创建订单页面渲染 → 订单列表 → 状态标签验证
 *
 * 运行：cd tests && BASE_URL=http://localhost:3001 npx playwright test specs/orders/order-lifecycle.spec.ts
 */
import { test, expect } from '@playwright/test'

// ========== Mock Data ==========

const ORDERS = [
  { id: 'o1', orderNo: 'YK20260702001', customerName: '测试客户', customerPhone: '13800138000', customerAddress: '浙江省杭州市西湖区', totalAmount: 1280.5, actualAmount: 1280.5, status: 'pending_payment', createdAt: new Date().toISOString() },
  { id: 'o2', orderNo: 'YK20260702002', customerName: '李四', customerPhone: '13900139002', customerAddress: '江苏省南京市', totalAmount: 3560.0, actualAmount: 3560.0, status: 'pending_shipment', createdAt: new Date().toISOString() },
  { id: 'o3', orderNo: 'YK20260702003', customerName: '王五', customerPhone: '13700137003', customerAddress: '上海市浦东新区', totalAmount: 890.0, actualAmount: 890.0, status: 'shipped', createdAt: new Date().toISOString() },
  { id: 'o4', orderNo: 'YK20260702004', customerName: '赵六', customerPhone: '13600136004', customerAddress: '北京市朝阳区', totalAmount: 2200.0, actualAmount: 2200.0, status: 'completed', createdAt: new Date().toISOString() },
  { id: 'o5', orderNo: 'YK20260702005', customerName: '孙七', customerPhone: '13500135005', customerAddress: '广东省深圳市', totalAmount: 450.0, actualAmount: 450.0, status: 'closed', createdAt: new Date().toISOString() },
]

// ========== Helpers ==========

function mockAuth(page: any) {
  return page.route('**/api/auth/me', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ code: 200, data: { id: '1', username: 'admin', name: '管理员', roles: ['admin'], tenantId: 1, tenantName: '测试企业' } }) })
  })
}

function mockOrderList(page: any) {
  return page.route(/\/api\/admin\/orders(\?.*)?$/, async (route: any) => {
    if (route.request().method() !== 'GET') { await route.fallback(); return }
    await route.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ code: 200, data: { items: ORDERS, total: ORDERS.length, page: 1, size: 20 } }) })
  })
}

// ========== Tests ==========

test.describe('订单全生命周期', () => {

  test.describe('创建订单页面', () => {
    test.beforeEach(async ({ page }) => { await mockAuth(page) })

    test('页面完整渲染：sidebar + 收货信息 + 商品信息区块', async ({ page }) => {
      await page.goto('/orders/new')
      await expect(page.locator('aside')).toBeVisible({ timeout: 15000 })
      await expect(page.getByText('收货信息').first()).toBeVisible({ timeout: 10000 })
      await expect(page.getByText('商品信息').first()).toBeAttached()
      await expect(page.locator('h1').filter({ hasText: '新增订单' })).toBeAttached()
    })
  })

  test.describe('订单列表', () => {
    test.beforeEach(async ({ page }) => {
      await mockAuth(page)
      await mockOrderList(page)
    })

    test('列表渲染：所有状态标签正确展示', async ({ page }) => {
      await page.goto('/orders')
      await expect(page.locator('aside')).toBeVisible({ timeout: 15000 })
      // 验证核心订单状态标签都能正确渲染
      // (默认 tab 可能不显示所有状态，已关闭在单独 tab)
      await expect(page.getByText('待付款').first()).toBeVisible({ timeout: 5000 })
      await expect(page.getByText('待发货').first()).toBeAttached()
      await expect(page.getByText('已发货').first()).toBeAttached()
      await expect(page.getByText('已完成').first()).toBeAttached()
    })

    test('列表数据：订单号和客户名正确展示', async ({ page }) => {
      await page.goto('/orders')
      await expect(page.locator('aside')).toBeVisible({ timeout: 15000 })
      await expect(page.getByText(ORDERS[0].orderNo).first()).toBeAttached({ timeout: 5000 })
      await expect(page.getByText(ORDERS[1].customerName).first()).toBeAttached()
    })
  })
})
