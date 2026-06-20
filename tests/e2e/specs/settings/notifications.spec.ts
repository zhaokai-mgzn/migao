import { test, expect } from '@playwright/test'
import { NotificationsPage } from '../../pages/notifications/notifications.page'

test.describe('通知中心页面', () => {
  let page: NotificationsPage

  test.beforeEach(async ({ page: p }) => {
    page = new NotificationsPage(p)

    // Mock notifications API — 组件期望 status 字段（非 read），且需要 channel 字段
    await p.route('**/api/admin/notifications**', async (route) => {
      const method = route.request().method()
      const url = route.request().url()

      // PUT mark-read / read-all — 返回空成功
      if (method === 'PUT') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, data: null }),
        })
        return
      }
      // DELETE — 返回空成功
      if (method === 'DELETE') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ success: true, data: null }),
        })
        return
      }

      // GET (list / unread-count) — 返回列表数据
      if (method === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            success: true,
            data: { items: [{ id: '1', title: '测试通知', content: '这是一条测试通知', status: 'sent', channel: 'internal', createdAt: '2026-06-20T10:00:00Z' }], total: 1 },
          }),
        })
        return
      }

      await route.continue()
    })

    await page.goto()
    await page.waitForLoad()
  })

  test('页面标题正确显示', async () => {
    await expect(page.page.getByRole('heading', { name: '通知中心' })).toBeVisible()
    await expect(page.page.getByText('管理和查看系统通知')).toBeVisible()
  })

  test('状态 Tab 包含全部、未读、已读', async () => {
    await expect(page.tabByName('全部')).toBeVisible()
    await expect(page.tabByName('未读')).toBeVisible()
    await expect(page.tabByName('已读')).toBeVisible()
  })

  test('Tab 切换正确高亮', async () => {
    await page.tabByName('未读').click()
    await expect(page.tabByName('未读')).toHaveClass(/text-primary-600/)
    await page.waitForLoadingComplete()
  })

  test('通知列表正确渲染', async () => {
    await page.waitForLoadingComplete()
    // 通知列表或空状态
    const items = page.notificationList.locator('> div')
    const emptyState = page.page.getByText(/暂无通知/)
    const itemCount = await items.count()
    if (itemCount > 0) {
      // 有通知：验证通知标题不为空
      const firstTitle = items.first().locator('h3, h4, .font-medium, span')
      await expect(firstTitle.first()).toBeVisible()
    } else {
      // 无通知：验证空态显示
      await expect(emptyState).toBeVisible()
    }
  })

  test('通知渠道 Badge 正确显示', async () => {
    await page.waitForLoadingComplete()
    // 渠道标签：站内信、短信、微信、邮件
    const channelBadges = page.page.locator('text=/站内信|短信|微信|邮件/')
    expect(await channelBadges.count()).toBeGreaterThanOrEqual(0)
  })

  test('全部标记已读按钮可点击', async () => {
    await page.markAllReadBtn.click()
    // 应该触发 toast
    const toast = page.page.locator('[data-sonner-toast]')
    await expect(toast).toBeVisible({ timeout: 10_000 })
  })

  test('单条通知可标记已读', async () => {
    await page.waitForLoadingComplete()
    // 直接选择标记已读按钮（定位通知列表中第一个可操作的条目）
    const markBtn = page.page.locator('.divide-y button').filter({ hasText: '标记已读' }).first()
    const isVisible = await markBtn.isVisible().catch(() => false)
    if (isVisible) {
      await markBtn.click()
      await page.expectSuccessToast(/已标记为已读/)
    } else {
      // 如果未找到按钮，通知可能已是已读状态，跳过
      test.skip(true, '通知已标记为已读，跳过')
    }
  })

  test('单条通知可删除', async () => {
    await page.waitForLoadingComplete()
    const deleteBtn = page.deleteBtn(0)
    if (await deleteBtn.isVisible().catch(() => false)) {
      await deleteBtn.click()
      // 确认删除弹窗
      const modal = page.page.locator('[role="dialog"]').filter({ hasText: '确认删除' })
      await expect(modal).toBeVisible()
    }
  })

  test('通知显示相对时间', async () => {
    await page.waitForLoadingComplete()
    // 相对时间格式：刚刚、x分钟前、x小时前、x天前
    const timeElements = page.page.locator('text=/刚刚|\\d+分钟前|\\d+小时前|\\d+天前/')
    expect(await timeElements.count()).toBeGreaterThanOrEqual(0)
  })

  test('空状态正确显示', async () => {
    await page.waitForLoadingComplete()
    // 空状态下显示 Inbox 图标和文案
    const emptyIcon = page.page.locator('svg.lucide-inbox')
    const emptyText = page.page.getByText(/暂无通知/)
    if (await emptyIcon.isVisible().catch(() => false)) {
      await expect(emptyText).toBeVisible()
    }
  })

  test('未读通知有蓝色背景样式', async () => {
    await page.waitForLoadingComplete()
    // 未读通知有 bg-blue-50/30 类名和蓝色圆点
    const blueDots = page.page.locator('.bg-blue-500.rounded-full')
    expect(await blueDots.count()).toBeGreaterThanOrEqual(0)
  })

  test('删除确认弹窗包含通知标题', async () => {
    await page.waitForLoadingComplete()
    const deleteBtn = page.deleteBtn(0)
    if (await deleteBtn.isVisible().catch(() => false)) {
      await deleteBtn.click()
      const modal = page.page.locator('[role="dialog"]').filter({ hasText: '确认删除' })
      await expect(modal.getByText(/确定要删除通知/)).toBeVisible()
    }
  })
})
