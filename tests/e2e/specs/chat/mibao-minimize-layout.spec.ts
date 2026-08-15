/**
 * E2E — 米宝最小化浮窗布局断言
 *
 * 业务真值（frontend-fix.layout）：米宝点击「收起」后，最小化浮窗应为横向 560×480，
 * 长宽比约 1.17（与居中大窗 920×720 的横向方向一致），而非窄竖条。
 *
 * 曾 bug：最小化浮窗 360×480（竖向 3:4），因无几何断言而漏网（#2485）。
 */
import { test, expect } from '@playwright/test'
import { assertSize, assertAspectRatio } from '../../pages/layout'

async function mockChatApis(page: import('@playwright/test').Page): Promise<void> {
  // 打开米宝会拉会话列表/快捷操作，mock 为空避免依赖后端
  await page.route('**/api/chat/sessions', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { items: [], page: 1, size: 20, total: 0 } }),
    }),
  )
  await page.route('**/api/chat/quick-actions', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { actions: [] } }),
    }),
  )
}

test.describe('米宝最小化浮窗布局', () => {
  test('点击收起后浮窗为横向 560×480，长宽比约 1.17', async ({ page }) => {
    await mockChatApis(page)
    await page.goto('/products', { waitUntil: 'load' })

    // 打开米宝 FAB
    await page.getByTitle('打开米宝').click()
    await expect(page.getByText('米宝 · 智能助手')).toBeVisible()

    // 收起（最小化）— Minus 图标按钮
    await page.locator('button').filter({ has: page.locator('svg.lucide-minus') }).click()

    // 最小化浮窗：含「展开」按钮的 fixed 容器
    const minimized = page.locator('div.fixed').filter({ has: page.getByTitle('展开') })
    await expect(minimized).toBeVisible()

    await assertSize(minimized, { width: 560, height: 480 })
    await assertAspectRatio(minimized, 560 / 480, 0.05)
  })
})
