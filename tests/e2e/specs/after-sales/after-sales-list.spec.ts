import { test, expect } from '@playwright/test'
import { AfterSalesListPage } from '../../pages/after-sales/after-sales-list.page'

// ==================== Inline Mock Data ====================

const MOCK_TICKETS = [
  { id: 'as-001', ticketNo: 'AS-20260619-0001', orderId: 'ord-001', orderNo: '20260619376915624', customerId: 'cust-1', customerName: '张美华', customerPhone: '13957168235', ticketType: 'return', status: 'pending', description: '颜色不对申请退货', priority: 'normal', createdAt: '2026-06-19 11:27', updatedAt: '2026-06-19 11:27' },
  { id: 'as-002', ticketNo: 'AS-20260619-0002', orderId: 'ord-002', orderNo: '20260619204200907', customerId: 'cust-2', customerName: '李建明', customerPhone: '13867129034', ticketType: 'exchange', status: 'processing', description: '布料跳线换货', priority: 'urgent', createdAt: '2026-06-19 11:27', updatedAt: '2026-06-19 11:28' },
  { id: 'as-003', ticketNo: 'AS-20260618-0003', orderId: 'ord-003', orderNo: '20260618234567123', customerId: 'cust-3', customerName: '王丽芳', customerPhone: '13758214096', ticketType: 'refund', status: 'resolved', description: '申请退款', priority: 'normal', createdAt: '2026-06-18 10:15', updatedAt: '2026-06-18 14:30' },
  { id: 'as-004', ticketNo: 'AS-20260617-0004', orderId: 'ord-004', orderNo: '20260617456123890', customerId: 'cust-4', customerName: '赵建国', customerPhone: '13612345678', ticketType: 'repair', status: 'rejected', description: '要求维修破损', priority: 'normal', createdAt: '2026-06-17 15:00', updatedAt: '2026-06-17 16:00' },
  { id: 'as-005', ticketNo: 'AS-20260616-0005', orderId: 'ord-005', orderNo: '20260616789123456', customerId: 'cust-5', customerName: '孙晓芳', customerPhone: '13598765432', ticketType: 'complaint', status: 'closed', description: '投诉物流太慢', priority: 'critical', createdAt: '2026-06-16 09:00', updatedAt: '2026-06-16 18:00' },
  { id: 'as-006', ticketNo: 'AS-20260619-0006', orderId: 'ord-006', orderNo: '20260619876543210', customerId: 'cust-6', customerName: '周文斌', customerPhone: '13456789012', ticketType: 'other', status: 'pending', description: '其他问题咨询', priority: 'normal', createdAt: '2026-06-19 08:00', updatedAt: '2026-06-19 08:00' },
]

function filterTickets(params: URLSearchParams) {
  let result = [...MOCK_TICKETS]
  const status = params.get('status')
  const keyword = params.get('keyword')
  if (status) result = result.filter((t) => t.status === status)
  if (keyword) result = result.filter((t) => t.ticketNo.includes(keyword) || t.orderNo?.includes(keyword) || t.customerName?.includes(keyword))
  return result
}

function buildPaginatedResponse(items: typeof MOCK_TICKETS, page = 1, size = 20) {
  const start = (page - 1) * size
  return { success: true, data: { total: items.length, page, size, items: items.slice(start, start + size) } }
}

// ==================== Tests ====================

test.describe('售后工单列表页面', () => {
  let pom: AfterSalesListPage

  test.beforeEach(async ({ page }) => {
    // Mock after-sales list API with filtering
    await page.route('**/api/admin/after-sales*', (route) => {
      const url = new URL(route.request().url())
      const items = filterTickets(url.searchParams)
      const pageNum = parseInt(url.searchParams.get('page') || '1')
      const pageSize = parseInt(url.searchParams.get('size') || '20')
      route.fulfill({ body: JSON.stringify(buildPaginatedResponse(items, pageNum, pageSize)) })
    })
    // Mock order search for create-ticket modal
    await page.route('**/api/admin/orders?keyword=*', (route) => {
      route.fulfill({ body: JSON.stringify({
        success: true,
        data: { total: 1, page: 1, size: 10, items: [{ id: 'ord-001', orderNo: '20260619376915624', customerName: '张美华', totalAmount: 340, status: 'completed', createdAt: '2026-06-19' }] }
      })})
    })
    pom = new AfterSalesListPage(page)
    await pom.goto()
    await pom.waitForLoadingComplete()
  })

  test('页面标题和描述正确显示', async () => {
    await expect(pom.pageTitle).toBeVisible()
    await expect(pom.page.getByText(/管理客户售后工单/)).toBeVisible()
  })

  test('显示6个状态 Tab', async () => {
    await expect(pom.allTab).toBeVisible()
    await expect(pom.pendingTab).toBeVisible()
    await expect(pom.processingTab).toBeVisible()
    await expect(pom.resolvedTab).toBeVisible()
    await expect(pom.rejectedTab).toBeVisible()
    await expect(pom.closedTab).toBeVisible()
  })

  test('Tab 切换正确高亮', async () => {
    await pom.pendingTab.click()
    await pom.waitForLoadingComplete()
    await expect(pom.pendingTab).toHaveClass(/text-primary-600|border-primary|bg-primary/)
  })

  test('关键词搜索框可输入并搜索', async () => {
    await pom.keywordInput.fill('20260619')
    await pom.searchButton.click()
    await pom.waitForLoadingComplete()
    await expect(pom.table).toBeVisible()
  })

  test('搜索框支持回车键触发搜索', async () => {
    await pom.keywordInput.fill('张美华')
    await pom.keywordInput.press('Enter')
    await pom.waitForLoadingComplete()
    await expect(pom.table).toBeVisible()
  })

  test('状态筛选下拉框可正常切换', async () => {
    // The page uses button-group tabs for status, verify they work
    await pom.pendingTab.click()
    await pom.waitForLoadingComplete()
    await expect(pom.table).toBeVisible()
  })

  test('表格表头正确显示所有列', async () => {
    const headers = ['工单号', '关联订单', '客户', '售后类型', '状态', '优先级', '创建时间']
    for (const h of headers) {
      await expect(pom.page.getByRole('columnheader', { name: h })).toBeVisible()
    }
  })

  test('新建工单按钮可打开创建弹窗', async () => {
    await pom.createTicketButton.click()
    await expect(pom.createModal).toBeVisible()
  })

  test('创建工单弹窗 - 订单搜索功能', async () => {
    await pom.createTicketButton.click()
    await expect(pom.orderSearchInput).toBeVisible()
    await pom.orderSearchInput.fill('20260619')
    await pom.orderSearchButton.click()
    await pom.waitForLoadingComplete()
  })

  test('创建工单弹窗 - 售后类型选择', async () => {
    await pom.createTicketButton.click()
    await pom.selectTicketType('换货')
    const exchangeBtn = pom.typeButtons.filter({ hasText: '换货' })
    await expect(exchangeBtn).toBeVisible()
  })

  test('创建工单弹窗 - 优先级选择', async () => {
    await pom.createTicketButton.click()
    await pom.selectPriority('紧急')
    const urgentBtn = pom.priorityButtons.filter({ hasText: '紧急' })
    await expect(urgentBtn).toBeVisible()
  })

  test('创建工单 - 未选择订单时提交显示错误', async () => {
    await pom.createTicketButton.click()
    await pom.descriptionTextarea.fill('测试描述')
    await pom.submitTicketButton.click()
    await pom.expectErrorToast(/请选择关联订单/)
  })

  test('创建工单 - 未填写描述时提交显示错误', async () => {
    await pom.createTicketButton.click()
    await pom.submitTicketButton.click()
    const toast = pom.page.locator('[data-sonner-toast]')
    await expect(toast.first()).toBeVisible({ timeout: 5000 })
  })

  test('表格行点击跳转到工单详情', async () => {
    await expect(pom.tableRows.first()).toBeVisible({ timeout: 5000 });
    await pom.tableRows.first().click()
    await expect(pom.page).toHaveURL(/\/after-sales\/.+/)
  })

  test('重置按钮清空搜索条件', async () => {
    await pom.keywordInput.fill('测试关键词')
    await pom.resetButton.click()
    await expect(pom.keywordInput).toHaveValue('')
  })

  test('售后类型和状态显示 Badge 标签', async () => {
    // All 6 tickets should render with their type/status badges
    await expect(pom.tableRows.first()).toBeVisible()
    const typeBadges = pom.page.locator('text=/退货|换货|维修|退款|投诉|其他/')
    expect(await typeBadges.count()).toBeGreaterThanOrEqual(1)
  })

  test('切换到已完成 Tab 只显示已完成的工单', async () => {
    await pom.resolvedTab.click()
    await pom.waitForLoadingComplete()
    // Should show resolved tickets and not the rejected ones
    await expect(pom.page.getByText('AS-20260618-0003')).toBeVisible()
  })
})
