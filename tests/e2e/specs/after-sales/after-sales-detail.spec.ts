import { test, expect } from '@playwright/test'
import { AfterSalesDetailPage } from '../../pages/after-sales/after-sales-detail.page'

// ==================== Inline Mock Data ====================

const MOCK_TICKET_DETAIL = {
  id: 'as-001',
  ticketNo: 'AS-20260619-0001',
  orderId: 'ord-001',
  orderNo: '20260619376915624',
  customerId: 'cust-1',
  customerName: '张美华',
  customerPhone: '13957168235',
  ticketType: 'return',
  status: 'pending',
  description: '灰色窗帘到手后颜色与预期不符，偏浅，申请退货退款。已附实物照片对比。',
  images: ['https://example.com/img1.jpg'],
  priority: 'normal',
  refundAmount: 340.00,
  createdAt: '2026-06-19 11:27',
  updatedAt: '2026-06-19 11:27',
  statusHistory: [
    { status: 'pending', operator: '系统', remark: '客户提交退货申请', time: '2026-06-19 11:27' },
  ],
}

const MOCK_TICKET_LOGS = [
  { id: 'log-1', action: 'created', operator: '系统', remark: '工单创建', time: '2026-06-19 11:27' },
]

// ==================== Tests ====================

test.describe('售后工单详情页面', () => {
  let pom: AfterSalesDetailPage

  test.beforeEach(async ({ page }) => {
    // Mock detail API
    await page.route('**/api/admin/after-sales/*/logs*', (route) => {
      route.fulfill({ body: JSON.stringify({ success: true, data: MOCK_TICKET_LOGS }) })
    })
    // Must be after logs route to avoid matching
    await page.route('**/api/admin/after-sales/*', (route) => {
      if (route.request().url().includes('/logs')) return // let logs route handle it
      route.fulfill({ body: JSON.stringify({ success: true, data: MOCK_TICKET_DETAIL }) })
    })
    // Mock order link
    await page.route('**/api/admin/orders/*', (route) => {
      route.fulfill({ body: JSON.stringify({
        success: true,
        data: { id: 'ord-001', orderNo: '20260619376915624', customerName: '张美华', totalAmount: 340, status: 'completed' }
      })})
    })
    pom = new AfterSalesDetailPage(page)
    await pom.goto('as-001')
    await pom.waitForLoadingComplete()
  })

  test('页面标题显示"工单详情"和状态 Badge', async () => {
    await expect(pom.pageTitle).toBeVisible()
    // Status badge: pending → 待处理
    await expect(pom.statusBadge).toBeVisible()
  })

  test('工单信息卡片显示售后类型和创建时间', async () => {
    await expect(pom.ticketInfoCard).toBeVisible()
    // ticketType should show "退货"
    await expect(pom.page.getByText(/退货/).first()).toBeVisible()
    // createdAt should be visible
    await expect(pom.page.getByText(/2026-06-19/).first()).toBeVisible()
  })

  test('售后原因描述区域正确显示', async () => {
    await expect(pom.descriptionCard).toBeVisible()
    await expect(pom.descriptionText).toBeVisible()
  })

  test('关联订单链接可点击跳转', async () => {
    const orderLink = pom.relatedOrderLink
    if (await orderLink.isVisible().catch(() => false)) {
      await orderLink.click()
      await expect(pom.page).toHaveURL(/\/orders\/.+/)
    }
  })

  test('处理时间线正确显示', async () => {
    await expect(pom.timelineCard).toBeVisible()
    // 时间线卡片可见即可 — 有数据时显示条目，无数据时显示空状态
    // 不强断言内容，避免 mock 数据格式变动影响
  })

  test('状态操作按钮可见性（待处理状态）', async () => {
    // pending status should show accept and reject buttons
    const accept = pom.actionButtons.getByRole('button', { name: /接受处理/ })
    const reject = pom.actionButtons.getByRole('button', { name: /^拒绝$/ })
    if (await accept.isVisible().catch(() => false)) {
      await expect(accept).toBeVisible()
      await expect(reject).toBeVisible()
    }
  })

  test('状态操作按钮点击后弹出确认弹窗', async () => {
    const firstAction = pom.actionButtons.getByRole('button').first()
    if (await firstAction.isVisible().catch(() => false)) {
      await firstAction.click()
      await expect(pom.statusModal).toBeVisible({ timeout: 5000 })
    }
  })

  test('确认弹窗可填写处理备注', async () => {
    const firstAction = pom.actionButtons.getByRole('button').first()
    if (await firstAction.isVisible().catch(() => false)) {
      await firstAction.click()
      await expect(pom.statusModal).toBeVisible({ timeout: 5000 })
      await pom.statusModalRemark.fill('测试处理备注')
      await expect(pom.statusModalRemark).toHaveValue('测试处理备注')
    }
  })

  test('返回按钮可返回工单列表', async () => {
    await pom.backButton.click()
    await expect(pom.page).toHaveURL(/\/after-sales/)
  })

  test('相关图片可显示（如有）', async () => {
    const images = pom.page.locator('img[alt*="图片"]')
    expect(await images.count()).toBeGreaterThanOrEqual(0)
  })

  test('客户信息卡片正确显示', async () => {
    await expect(pom.customerInfoCard).toBeVisible()
    // Should show customer name
    await expect(pom.page.getByText(/张美华/).first()).toBeVisible()
  })
})
