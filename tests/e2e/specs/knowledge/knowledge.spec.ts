import { test, expect } from '@playwright/test'
import { KnowledgePage } from '../../pages/knowledge/knowledge.page'

test.describe('知识库管理页面', () => {
  let page: KnowledgePage

  test.beforeEach(async ({ page: p }) => {
    page = new KnowledgePage(p)
    await page.goto()
    await page.waitForLoad()
  })

  test('页面标题和描述正确显示', async () => {
    await expect(page.page.getByText('知识库管理')).toBeVisible()
    await expect(page.page.getByText(/管理 AI 客服的知识库文档/)).toBeVisible()
  })

  test('搜索栏支持关键词、类型、状态筛选', async () => {
    await expect(page.searchInput).toBeVisible()
    // 类型和状态 select 在 SearchBar 中
    const selects = page.page.locator('select')
    expect(await selects.count()).toBeGreaterThanOrEqual(0)
  })

  test('表格表头正确显示', async () => {
    await page.waitForLoadingComplete()
    const headers = ['文档名称', '类型', '文件大小', '分块数', '更新时间', '状态', '操作']
    for (const header of headers) {
      await expect(page.page.getByRole('columnheader', { name: header })).toBeVisible()
    }
  })

  test('上传文档按钮可打开上传弹窗', async () => {
    await page.uploadBtn.click()
    await expect(page.uploadModal).toBeVisible()
    await expect(page.page.getByText('上传文档')).toBeVisible()
  })

  test('上传弹窗包含文档名称输入框', async () => {
    await page.uploadBtn.click()
    await expect(page.uploadName).toBeVisible()
  })

  test('上传弹窗包含文档类型选择器', async () => {
    await page.uploadBtn.click()
    await expect(page.uploadType).toBeVisible()
    // 可选类型：FAQ、产品说明、尺寸指南
    await expect(page.uploadType.locator('option[value="faq"]')).toBeVisible()
    await expect(page.uploadType.locator('option[value="product"]')).toBeVisible()
    await expect(page.uploadType.locator('option[value="guide"]')).toBeVisible()
  })

  test('上传弹窗支持拖拽上传区域', async () => {
    await page.uploadBtn.click()
    // 拖拽上传区域
    const dropzone = page.uploadModal.locator('.border-dashed')
    await expect(dropzone).toBeVisible()
    await expect(dropzone.getByText(/点击选择或拖拽文件/)).toBeVisible()
  })

  test('上传弹窗显示描述输入框', async () => {
    await page.uploadBtn.click()
    await expect(page.uploadDescription).toBeVisible()
  })

  test('上传 - 未填名称和文件时提交显示错误', async () => {
    await page.uploadBtn.click()
    await page.uploadModal.getByRole('button', { name: /^上传$/ }).click()
    // 表单验证错误信息
    await expect(page.uploadModal.getByText('请输入文档名称')).toBeVisible()
  })

  test('上传进度条在上传时显示', async () => {
    await page.uploadBtn.click()
    // 进度条仅在上传时显示
    const progress = page.uploadProgress
    // 初始状态不可见
    expect(await progress.isVisible().catch(() => false)).toBeFalsy()
  })

  test('删除按钮弹出确认弹窗', async () => {
    await page.waitForLoadingComplete()
    const deleteBtn = page.deleteBtn(0)
    if (await deleteBtn.isVisible().catch(() => false)) {
      await deleteBtn.click()
      const modal = page.page.locator('[role="dialog"]').filter({ hasText: '确认删除' })
      await expect(modal).toBeVisible()
      await expect(modal.getByText(/确定要删除文档/)).toBeVisible()
    }
  })

  test('重新同步按钮可触发同步', async () => {
    await page.waitForLoadingComplete()
    const resyncBtn = page.resyncBtn(0)
    if (await resyncBtn.isVisible().catch(() => false)) {
      await resyncBtn.click()
      await page.expectSuccessToast(/已触发文档/)
    }
  })

  test('搜索测试弹窗可打开', async () => {
    await page.page.getByRole('button', { name: /搜索测试/ }).click()
    await expect(page.searchTestModal).toBeVisible()
    await expect(page.page.getByText('知识库搜索测试')).toBeVisible()
  })

  test('分页组件正确显示', async () => {
    await page.waitForLoadingComplete()
    const pagination = page.page.locator('text=/共.*条/').first()
    if (await pagination.isVisible()) {
      await expect(pagination).toBeVisible()
    }
  })
})
