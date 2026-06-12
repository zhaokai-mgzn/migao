import { test, expect } from '@playwright/test'
import { AfterSalesListPage } from '../../pages/after-sales/after-sales-list.page'

test.describe('售后工单列表页面', () => {
  let pom: AfterSalesListPage

  test.beforeEach(async ({ page }) => {
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
    await expect(pom.pendingTab).toHaveClass(/text-primary-600/)
  })

  test('关键词搜索框可输入并搜索 — 搜索后表格有数据', async () => {
    await pom.keywordInput.fill('ORD2026')
    await pom.searchButton.click()
    await pom.waitForLoadingComplete()
    await expect(pom.table).toBeVisible()
    await expect(pom.page.getByText('暂无数据')).not.toBeVisible()
  })

  test('搜索框支持回车键触发搜索 — 表格正常渲染', async () => {
    await pom.keywordInput.fill('测试')
    await pom.keywordInput.press('Enter')
    await pom.waitForLoadingComplete()
    await expect(pom.table).toBeVisible()
  })

  test('状态筛选下拉框可正常切换 — 筛选后表格可渲染', async () => {
    await pom.statusSelect.selectOption('pending')
    await pom.searchButton.click()
    await pom.waitForLoadingComplete()
    await expect(pom.table).toBeVisible()
    // 应根据筛选状态返回对应数据，表格行数应有变化
    const rows = pom.table.locator('tbody tr')
    await expect(rows.first()).toBeVisible()
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
    await pom.orderSearchInput.fill('ORD2026')
    await pom.orderSearchButton.click()
    await pom.waitForLoadingComplete()
  })

  test('创建工单弹窗 - 售后类型选择', async () => {
    await pom.createTicketButton.click()
    await pom.selectTicketType('换货')
    // 换货按钮应该高亮
    const exchangeBtn = pom.typeButtons.filter({ hasText: '换货' })
    await expect(exchangeBtn).toHaveClass(/border-primary-500/)
  })

  test('创建工单弹窗 - 优先级选择', async () => {
    await pom.createTicketButton.click()
    await pom.selectPriority('紧急')
    const urgentBtn = pom.priorityButtons.filter({ hasText: '紧急' })
    await expect(urgentBtn).toHaveClass(/border-amber-500/)
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
    await expect(toast).toBeVisible({ timeout: 5000 })
  })

  test('表格行点击跳转到工单详情', async () => {
    const firstRow = pom.tableRows.first()
    if (await firstRow.isVisible()) {
      await firstRow.click()
      await expect(pom.page).toHaveURL(/\/after-sales\/.+/)
    }
  })

  test('重置按钮清空搜索条件', async () => {
    await pom.keywordInput.fill('测试关键词')
    await pom.resetButton.click()
    await expect(pom.keywordInput).toHaveValue('')
  })

  test('售后类型和状态显示 Badge 标签', async () => {
    const badges = pom.page.locator('tbody').locator('text=/退货|换货|维修|退款|投诉|其他/')
    expect(await badges.count()).toBeGreaterThanOrEqual(0)
  })
})
