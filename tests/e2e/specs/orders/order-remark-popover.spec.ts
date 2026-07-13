/**
 * E2E: 订单列表备注浮窗 (#1289)
 *
 * 验证 RemarkPopover 的 hover 触发、内容完整、时间倒序、不遮挡关键列。
 */
import { test, expect } from '@playwright/test'

// ========== Mock Data ==========

const MOCK_ORDERS = [
  {
    id: 'o-rp-001',
    orderNo: 'YK20260713001',
    customerName: '测试客户A',
    customerPhone: '13800138001',
    totalAmount: 299,
    actualAmount: 299,
    status: 'pending_shipment',
    createdAt: '2026-07-13T10:00:00Z',
    remark: '[2026-07-13 10:00] 客户催单\n[2026-07-12 09:00] 已联系供应商\n[2026-07-10 08:00] 首条备注',
    items: [
      {
        id: 'i1', productId: 'p001', productName: '窗帘', productCode: 'CL-001',
        quantity: 3, unitPrice: 99, amount: 297, subtotal: 297,
      },
    ],
    processingItems: [],
    hasProcessing: false,
  },
  {
    id: 'o-rp-002',
    orderNo: 'YK20260713002',
    customerName: '测试客户B',
    customerPhone: '13800138002',
    totalAmount: 599,
    actualAmount: 599,
    status: 'pending_shipment',
    createdAt: '2026-07-13T11:00:00Z',
    remark: null, // 无备注订单
    items: [
      {
        id: 'i2', productId: 'p002', productName: '纱帘', productCode: 'CL-002',
        quantity: 5, unitPrice: 119.8, amount: 599, subtotal: 599,
      },
    ],
    processingItems: [],
    hasProcessing: false,
  },
  {
    id: 'o-rp-003',
    orderNo: 'YK20260713003',
    customerName: '测试客户C',
    customerPhone: '13800138003',
    totalAmount: 199,
    actualAmount: 199,
    status: 'pending_shipment',
    createdAt: '2026-07-13T12:00:00Z',
    remark: '[2026-07-13 12:00] 已发货，物流单号 SF123',
    items: [
      {
        id: 'i3', productId: 'p003', productName: '罗马帘', productCode: 'CL-003',
        quantity: 2, unitPrice: 99.5, amount: 199, subtotal: 199,
      },
    ],
    processingItems: [],
    hasProcessing: false,
  },
]

async function mockOrderApis(page: import('@playwright/test').Page) {
  // GET /api/admin/orders (list)
  await page.route('**/api/admin/orders*', async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue()
      return
    }
    const url = new URL(route.request().url())
    const status = url.searchParams.get('status') || ''

    let filtered = [...MOCK_ORDERS]
    if (status) {
      filtered = filtered.filter(o => o.status === status)
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 0,
        data: {
          records: filtered,
          total: filtered.length,
          page: 1,
          pageSize: 20,
        },
      }),
    })
  })

  // 其他 API 放行
  await page.route('**/api/**', async (route) => {
    if (route.request().url().includes('/api/admin/orders') && route.request().method() === 'GET') {
      return // already handled above
    }
    await route.continue()
  })
}

test.describe('订单列表备注浮窗 (#1289)', () => {
  test('有备注订单 hover 后应显示浮窗', async ({ page }) => {
    await mockOrderApis(page)

    await page.goto('/orders')
    // 等待订单数据加载
    await page.waitForSelector('text=YK20260713001', { timeout: 10000 })

    // 找到有备注的订单行中的备注触发区域
    const remarkCell = page.locator('td:has-text("💬")').first()
    await expect(remarkCell).toBeVisible()

    // Hover 触发浮窗
    await remarkCell.hover()

    // 验证浮窗出现（role="tooltip"）
    const tooltip = page.locator('[role="tooltip"]')
    await expect(tooltip).toBeVisible({ timeout: 2000 })

    // 验证浮窗内容：应包含备注条目
    await expect(tooltip).toContainText('客户催单')
    await expect(tooltip).toContainText('已联系供应商')
    await expect(tooltip).toContainText('首条备注')
  })

  test('无备注订单 hover 不显示空浮窗', async ({ page }) => {
    await mockOrderApis(page)

    await page.goto('/orders')
    await page.waitForSelector('text=YK20260713002', { timeout: 10000 })

    // 找到无备注订单行中的 "-" 占位符
    const noRemarkCell = page.locator('td:has-text("-")').first()
    await noRemarkCell.hover()

    // 确保没有 role="tooltip" 元素出现
    await page.waitForTimeout(300)
    const tooltip = page.locator('[role="tooltip"]')
    // 浮窗不应可见（或包含"暂无备注"而非空浮窗）
    const tooltipCount = await tooltip.count()
    // 如果浮窗出现，其内容应为"暂无备注"而非空内容
    if (tooltipCount > 0) {
      await expect(tooltip.first()).toContainText('暂无备注')
    }
  })

  test('浮窗内备注应按时间倒序排列', async ({ page }) => {
    await mockOrderApis(page)

    await page.goto('/orders')
    await page.waitForSelector('text=YK20260713001', { timeout: 10000 })

    const remarkCell = page.locator('td:has-text("💬")').first()
    await remarkCell.hover()

    const tooltip = page.locator('[role="tooltip"]')
    await expect(tooltip).toBeVisible({ timeout: 2000 })

    // 获取浮窗内所有 listitem，验证倒序
    const items = tooltip.locator('li')
    const count = await items.count()
    expect(count).toBe(3)

    // 第一条应为最新（2026-07-13），最后一条应为最旧（2026-07-10）
    const firstItemText = await items.nth(0).textContent()
    const lastItemText = await items.nth(count - 1).textContent()
    expect(firstItemText).toContain('客户催单')
    expect(lastItemText).toContain('首条备注')
  })

  test('浮窗内容应包含完整时间信息', async ({ page }) => {
    await mockOrderApis(page)

    await page.goto('/orders')
    await page.waitForSelector('text=YK20260713001', { timeout: 10000 })

    const remarkCell = page.locator('td:has-text("💬")').first()
    await remarkCell.hover()

    const tooltip = page.locator('[role="tooltip"]')
    await expect(tooltip).toBeVisible({ timeout: 2000 })

    // 浮窗内应包含时间信息（YYYY-MM-DD HH:mm 格式）
    const timePattern = /\d{4}-\d{2}-\d{2} \d{2}:\d{2}/
    const tooltipText = await tooltip.textContent()
    expect(tooltipText).toMatch(timePattern)
    // 具体验证至少两条时间
    await expect(tooltip).toContainText('2026-07-13 10:00')
    await expect(tooltip).toContainText('2026-07-12 09:00')
    await expect(tooltip).toContainText('2026-07-10 08:00')
  })

  test('浮窗不遮挡订单号列', async ({ page }) => {
    await mockOrderApis(page)

    await page.goto('/orders')
    await page.waitForSelector('text=YK20260713001', { timeout: 10000 })

    const remarkCell = page.locator('td:has-text("💬")').first()
    await remarkCell.hover()

    const tooltip = page.locator('[role="tooltip"]')
    await expect(tooltip).toBeVisible({ timeout: 2000 })

    // 验证订单号仍然可见（未被遮挡）
    const orderNo = page.locator('text=YK20260713001')
    await expect(orderNo).toBeVisible()
  })
})
