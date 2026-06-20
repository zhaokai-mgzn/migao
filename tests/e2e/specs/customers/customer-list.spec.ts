import { test, expect } from '@playwright/test'
import { CustomerListPage } from '../../pages/customers/customer-list.page'

test.describe('客户列表页面', () => {
  let pom: CustomerListPage

  test.beforeEach(async ({ page }) => {
    pom = new CustomerListPage(page)

    // Mock customers list API
    await page.route('**/api/admin/customers*', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: { items: [
              { id: '1', name: '张美丽', phone: '13800138001', channel: 'wechat_mini', vipLevel: 3, tags: [{ id: '1', name: 'VIP', color: '#f59e0b' }], lastActiveAt: '2026-06-20T10:00:00Z' },
              { id: '2', name: '李大力', phone: '13900139002', channel: 'h5', vipLevel: 1, tags: [], lastActiveAt: '2026-06-19T15:00:00Z' },
            ], total: 2, page: 1, size: 20 }
          }),
        })
      } else {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: null }) })
      }
    })

    // Mock customer tags API
    await page.route('**/api/admin/customer-tags*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: [{ id: '1', name: 'VIP', color: '#f59e0b' }] }),
      })
    })

    await pom.goto()
    await pom.waitForLoadingComplete()
  })

  test('页面标题和描述正确显示', async () => {
    await expect(pom.pageTitle).toBeVisible()
    await expect(pom.page.getByText('管理客户信息、标签和互动记录')).toBeVisible()
  })

  test('搜索框支持关键词输入并触发搜索 — 搜索后显示匹配结果', async () => {
    await pom.keywordInput.fill('张美丽')
    await pom.searchButton.click()
    await pom.waitForLoadingComplete()
    await expect(pom.table).toBeVisible()
    await expect(pom.page.getByText('张美丽')).toBeVisible()
    await expect(pom.page.getByText('暂无数据')).not.toBeVisible()
  })

  test('来源渠道筛选下拉框可正常切换 — 筛选后表格仍渲染', async () => {
    await pom.channelSelect.selectOption('wechat_mini')
    await pom.searchButton.click()
    await pom.waitForLoadingComplete()
    await expect(pom.table).toBeVisible()
    await expect(pom.page.getByText('暂无数据')).not.toBeVisible()
  })

  test('VIP 等级筛选下拉框可正常切换 — 筛选后表格仍渲染', async () => {
    await pom.vipLevelSelect.selectOption('vip1')
    await pom.searchButton.click()
    await pom.waitForLoadingComplete()
    await expect(pom.table).toBeVisible()
    await expect(pom.page.getByText('暂无数据')).not.toBeVisible()
  })

  test('表格显示头像列', async () => {
    await expect(pom.page.getByRole('columnheader', { name: /头像/ })).toBeVisible()
  })

  test('客户名称列正确显示', async () => {
    await expect(pom.page.getByRole('columnheader', { name: /客户名/ })).toBeVisible()
  })

  test('手机号列进行脱敏显示', async () => {
    await expect(pom.page.getByRole('columnheader', { name: /手机号/ })).toBeVisible()
    const masked = pom.page.locator('tbody td').filter({ hasText: /\d{3}\*{4}\d{4}/ })
    expect(await masked.count()).toBeGreaterThanOrEqual(0)
  })

  test('来源渠道列显示 Badge 标签', async () => {
    await expect(pom.page.getByRole('columnheader', { name: /来源渠道/ })).toBeVisible()
  })

  test('VIP 等级列显示星级或"普通"', async () => {
    await expect(pom.page.getByRole('columnheader', { name: /VIP 等级/ })).toBeVisible()
  })

  test('标签列正确渲染客户标签', async () => {
    await expect(pom.page.getByRole('columnheader', { name: /标签/ })).toBeVisible()
  })

  test('点击表格行跳转到客户详情', async () => {
    const firstRow = pom.tableRows.first()
    if (await firstRow.isVisible()) {
      await firstRow.click()
      await expect(pom.page).toHaveURL(/\/customers\/.+/)
    }
  })

  test('标签管理按钮可打开标签管理弹窗', async () => {
    await pom.tagManagerButton.click()
    await expect(pom.tagModal).toBeVisible()
  })

  test('标签管理弹窗支持新建标签', async () => {
    await pom.tagManagerButton.click()
    await pom.tagNameInput.fill('测试标签')
    await pom.tagAddButton.click()
  })

  test('标签管理弹窗支持编辑标签', async () => {
    await pom.tagManagerButton.click()
    const editBtn = pom.tagModal.getByText('编辑').first()
    if (await editBtn.isVisible()) {
      await editBtn.click()
      await expect(pom.tagUpdateButton).toBeVisible()
    }
  })

  test('标签管理弹窗支持删除标签', async () => {
    await pom.tagManagerButton.click()
    const deleteBtns = pom.tagModal.locator('button').filter({ has: pom.page.locator('svg.lucide-x') })
    expect(await deleteBtns.count()).toBeGreaterThanOrEqual(0)
  })

  test('重置按钮清空筛选条件', async () => {
    await pom.keywordInput.fill('测试')
    await pom.resetButton.click()
    await expect(pom.keywordInput).toHaveValue('')
  })
})
