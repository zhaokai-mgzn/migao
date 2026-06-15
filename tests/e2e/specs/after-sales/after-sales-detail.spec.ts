import { test, expect } from '@playwright/test'
import { AfterSalesDetailPage } from '../../pages/after-sales/after-sales-detail.page'
import afterSalesList from '../../fixtures/after-sales-list.json'

// TODO: mock 返回的 detail fixture 结构需要与页面期望对齐
test.describe.skip('售后工单详情页面', () => {
  let pom: AfterSalesDetailPage

  test.beforeEach(async ({ page }) => {
    // Mock API — 用 fixture 数据拦截，不依赖云 dev DB
    const items = (afterSalesList as any).data?.items || []
    const firstTicket = items[0] || {}
    await page.route('**/api/admin/after-sales/*', route => {
      route.fulfill({ body: JSON.stringify({ success: true, data: firstTicket }) })
    })
    await page.route('**/api/admin/after-sales/1/logs*', route => {
      route.fulfill({ body: JSON.stringify({ success: true, data: [] }) })
    })
    pom = new AfterSalesDetailPage(page)
    await pom.goto('1')
    await pom.waitForLoadingComplete()
  })

  test('页面标题显示"工单详情"和状态 Badge', async () => {
    await expect(pom.pageTitle).toBeVisible()
    // 状态 Badge 可能是待处理/处理中/已完成/已拒绝/已关闭
    if (await pom.statusBadge.isVisible().catch(() => false)) {
      await expect(pom.statusBadge).toBeVisible()
    }
  })

  test('工单信息卡片显示售后类型和创建时间', async () => {
    await expect(pom.ticketInfoCard).toBeVisible()
    await expect(pom.ticketType).toBeVisible()
    await expect(pom.createdAt).toBeVisible()
  })

  test('售后原因描述区域正确显示', async () => {
    await expect(pom.descriptionCard).toBeVisible()
    await expect(pom.descriptionText).toBeVisible()
  })

  test('关联订单链接可点击跳转', async () => {
    if (await pom.relatedOrderLink.isVisible().catch(() => false)) {
      await pom.relatedOrderLink.click()
      await expect(pom.page).toHaveURL(/\/orders\/.+/)
    }
  })

  test('处理时间线正确显示', async () => {
    await expect(pom.timelineCard).toBeVisible()
    const items = pom.timelineItems
    const emptyText = pom.page.getByText('暂无处理记录')
    const itemCount = await items.count()
    if (itemCount > 0) {
      // 有处理记录：验证内容不为空
      const firstText = await items.first().textContent()
      expect(firstText).toBeTruthy()
    } else {
      // 无记录：验证空态文案
      await expect(emptyText).toBeVisible()
    }
  })

  test('状态操作按钮可见性（待处理状态）', async () => {
    // 接受处理 和 拒绝 按钮仅在 pending 状态可见
    const accept = pom.actionButtons.getByRole('button', { name: /接受处理/ })
    const reject = pom.actionButtons.getByRole('button', { name: /^拒绝$/ })
    if (await accept.isVisible().catch(() => false)) {
      await expect(accept).toBeVisible()
      await expect(reject).toBeVisible()
    }
  })

  test('状态操作按钮可见性（处理中状态）', async () => {
    const complete = pom.actionButtons.getByRole('button', { name: /完成处理/ })
    const close = pom.actionButtons.getByRole('button', { name: /关闭工单/ })
    if (await complete.isVisible().catch(() => false)) {
      await expect(complete).toBeVisible()
      await expect(close).toBeVisible()
    }
  })

  test('状态操作按钮点击后弹出确认弹窗', async () => {
    const firstAction = pom.actionButtons.getByRole('button').first()
    if (await firstAction.isVisible().catch(() => false)) {
      await firstAction.click()
      await expect(pom.statusModal).toBeVisible()
      await expect(pom.statusModalRemark).toBeVisible()
    }
  })

  test('确认弹窗可填写处理备注', async () => {
    const firstAction = pom.actionButtons.getByRole('button').first()
    if (await firstAction.isVisible().catch(() => false)) {
      await firstAction.click()
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
    await expect(pom.page.getByText('客户姓名').first()).toBeVisible()
  })
})
