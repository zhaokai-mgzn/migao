/**
 * E2E 测试 — 订单列表查询按钮图标对齐验证 (Issue #1831)
 *
 * 业务真值:
 * 1. 「查询」按钮内搜索图标 + 文字垂直水平居中，与按钮边框无视觉偏移
 * 2. 按钮高度与同行的「是否加工」下拉框一致
 * 3. 点击「查询」仍正常触发列表筛选（功能不退化）
 *
 * 运行: npx playwright test specs/orders/search-icon.spec.ts
 */
import { test, expect } from '@playwright/test'

const MOCK_ORDERS = [
  {
    id: 'o001',
    orderNo: 'YK20260601001',
    customerName: '张三',
    customerPhone: '13800138001',
    customerAddress: '浙江省杭州市西湖区文三路 100 号',
    totalAmount: 1280.5,
    actualAmount: 1280.5,
    status: 'pending_payment',
    createdAt: '2026-06-01T10:30:00Z',
    items: [{ id: 'i1', productId: 'p001', productName: '北欧简约遮光窗帘', productCode: 'CL-GY-001', color: '灰色', specification: '门幅2.8米', quantity: 5, unitPrice: 256.1, amount: 1280.5, subtotal: 1280.5 }],
    processingItems: [],
  },
]

async function mockOrderApi(page: import('@playwright/test').Page) {
  await page.route('**/api/admin/orders*', async (route) => {
    if (route.request().method() !== 'GET') return route.continue()
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 200, data: { items: MOCK_ORDERS, total: 1, page: 1, size: 20 } }),
    })
  })
}

test.describe('订单列表 — 查询按钮图标对齐', () => {
  test.beforeEach(async ({ page }) => {
    await mockOrderApi(page)
    await page.goto('/orders')
    await page.waitForTimeout(2000)
  })

  test('L3-01: 查询按钮可见且包含 Search 图标', async ({ page }) => {
    const queryBtn = page.getByRole('button', { name: '查询' })
    await expect(queryBtn).toBeVisible()

    const icon = queryBtn.locator('svg')
    await expect(icon).toBeVisible()
  })

  test('L3-02: 查询按钮图标垂直居中 — bbox 中心差 ≤ 2px', async ({ page }) => {
    const queryBtn = page.getByRole('button', { name: '查询' })
    await expect(queryBtn).toBeVisible()

    const btnBox = await queryBtn.boundingBox()
    if (!btnBox) throw new Error('Cannot get button bounding box')

    const icon = queryBtn.locator('svg')
    const iconBox = await icon.boundingBox()
    if (!iconBox) throw new Error('Cannot get icon bounding box')

    const btnCenterY = btnBox.y + btnBox.height / 2
    const iconCenterY = iconBox.y + iconBox.height / 2

    expect(Math.abs(iconCenterY - btnCenterY)).toBeLessThanOrEqual(2)
  })

  test('L3-03: 图标 bbox 水平方向在按钮 bbox 内', async ({ page }) => {
    const queryBtn = page.getByRole('button', { name: '查询' })
    await expect(queryBtn).toBeVisible()

    const btnBox = await queryBtn.boundingBox()
    if (!btnBox) throw new Error('Cannot get button bounding box')

    const icon = queryBtn.locator('svg')
    const iconBox = await icon.boundingBox()
    if (!iconBox) throw new Error('Cannot get icon bounding box')

    expect(iconBox.x).toBeGreaterThanOrEqual(btnBox.x + 4)
    expect(iconBox.x + iconBox.width).toBeLessThanOrEqual(btnBox.x + btnBox.width)
  })

  test('L4-02: 查询按钮与同行下拉框高度一致（容差 2px）', async ({ page }) => {
    const queryBtn = page.getByRole('button', { name: '查询' })
    await expect(queryBtn).toBeVisible()

    const selectEl = page.locator('.grid select').first()
    await expect(selectEl).toBeVisible()

    const btnBox = await queryBtn.boundingBox()
    const selectBox = await selectEl.boundingBox()
    if (!btnBox || !selectBox) throw new Error('Cannot get bounding boxes')

    expect(Math.abs(btnBox.height - selectBox.height)).toBeLessThanOrEqual(2)
  })

  test('L3-04: 点击查询按钮触发列表筛选（功能不退化）', async ({ page }) => {
    const orderIdInput = page.locator('input[placeholder="请输入订单ID"]')
    await orderIdInput.fill('YK20260601001')

    const queryBtn = page.getByRole('button', { name: '查询' })
    await queryBtn.click()
    await page.waitForTimeout(500)

    await expect(page.getByText('YK20260601001')).toBeVisible()
  })
})
