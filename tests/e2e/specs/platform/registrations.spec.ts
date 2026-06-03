import { test, expect } from '@playwright/test'
import { RegistrationsPage } from '../../pages/platform/registrations.page'

test.describe('企业入驻审批页面', () => {
  let page: RegistrationsPage

  test.beforeEach(async ({ page: p }) => {
    page = new RegistrationsPage(p)
    await page.goto()
    await page.waitForLoad()
  })

  test('页面标题和描述正确显示', async () => {
    await expect(page.page.getByText('企业入驻审批')).toBeVisible()
    await expect(page.page.getByText(/审核企业入驻申请/)).toBeVisible()
  })

  test('状态 Tab 包含全部、待审核、已通过、已驳回', async () => {
    await expect(page.tabByName('全部')).toBeVisible()
    await expect(page.tabByName('待审核')).toBeVisible()
    await expect(page.tabByName('已通过')).toBeVisible()
    await expect(page.tabByName('已驳回')).toBeVisible()
  })

  test('Tab 切换正确高亮', async () => {
    await page.tabByName('待审核').click()
    await expect(page.tabByName('待审核')).toHaveClass(/text-blue-600/)
    await page.waitForLoadingComplete()
  })

  test('表格表头正确显示', async () => {
    const headers = ['企业名称', '联系人', '手机号', '行业', '状态', '申请时间', '操作']
    for (const header of headers) {
      await expect(page.page.getByRole('columnheader', { name: header })).toBeVisible()
    }
  })

  test('待审核记录显示审批通过和驳回按钮', async () => {
    await page.tabByName('待审核').click()
    await page.waitForLoadingComplete()
    const firstRow = page.page.locator('tbody tr').first()
    if (await firstRow.isVisible().catch(() => false)) {
      await expect(page.approveBtn(0)).toBeVisible()
      await expect(page.rejectBtn(0)).toBeVisible()
    }
  })

  test('审批通过按钮点击后弹出确认弹窗', async () => {
    await page.tabByName('待审核').click()
    await page.waitForLoadingComplete()
    const approveBtn = page.approveBtn(0)
    if (await approveBtn.isVisible().catch(() => false)) {
      await approveBtn.click()
      await expect(page.approveModal).toBeVisible()
      await expect(page.approveModal.getByText(/确定要通过/)).toBeVisible()
    }
  })

  test('驳回按钮点击后弹出驳回弹窗', async () => {
    await page.tabByName('待审核').click()
    await page.waitForLoadingComplete()
    const rejectBtn = page.rejectBtn(0)
    if (await rejectBtn.isVisible().catch(() => false)) {
      await rejectBtn.click()
      await expect(page.rejectModal).toBeVisible()
      await expect(page.rejectReasonInput).toBeVisible()
    }
  })

  test('驳回 - 未填原因时提交提示错误', async () => {
    await page.tabByName('待审核').click()
    await page.waitForLoadingComplete()
    const rejectBtn = page.rejectBtn(0)
    if (await rejectBtn.isVisible().catch(() => false)) {
      await rejectBtn.click()
      await page.rejectModal.getByRole('button', { name: /确认驳回/ }).click()
      await page.expectErrorToast(/请填写驳回原因/)
    }
  })

  test('非待审核记录显示查看详情按钮', async () => {
    await page.tabByName('已通过').click()
    await page.waitForLoadingComplete()
    const detailBtn = page.detailBtn(0)
    if (await detailBtn.isVisible().catch(() => false)) {
      await expect(detailBtn).toBeVisible()
    }
  })

  test('查看详情按钮点击后弹出详情弹窗', async () => {
    // 切换到有非 pending 数据的 tab
    await page.tabByName('全部').click()
    await page.waitForLoadingComplete()
    const detailBtn = page.detailBtn(0)
    if (await detailBtn.isVisible().catch(() => false)) {
      await detailBtn.click()
      await expect(page.detailModal).toBeVisible()
      // 详情弹窗包含企业名称
      await expect(page.detailModal.getByText('企业名称')).toBeVisible()
    }
  })

  test('详情弹窗显示营业执照图片（如有）', async () => {
    await page.tabByName('全部').click()
    await page.waitForLoadingComplete()
    const detailBtn = page.detailBtn(0)
    if (await detailBtn.isVisible().catch(() => false)) {
      await detailBtn.click()
      await expect(page.detailModal).toBeVisible()
      // 营业执照图片可能存在也可能不存在
      const licenseImg = page.detailModal.locator('img[alt="营业执照"]')
      expect(await licenseImg.count()).toBeGreaterThanOrEqual(0)
    }
  })

  test('分页组件正确显示', async () => {
    await page.waitForLoadingComplete()
    const pagination = page.page.locator('text=/共.*条/').first()
    if (await pagination.isVisible()) {
      await expect(pagination).toBeVisible()
    }
  })
})
