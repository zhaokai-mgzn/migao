// case_ids: UI-008
/**
 * E2E — 米宝最小化浮窗布局断言
 *
 * 业务真值（frontend-fix.layout）：米宝点击「收起」后，最小化浮窗应为竖版聊天浮窗
 * 400×600（比例约 0.667），参照主流 AI 助手/客服聊天浮窗（Intercom/Zendesk/Crisp）。
 *
 * 曾 bug：360×480（偏小）→ 560×480（横向，方向错误）均不符合主流竖版聊天窗。
 */
import { test, expect } from '../../fixtures'
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
  test('点击收起后浮窗为竖版 400×600，长宽比约 0.667', async ({ page }) => {
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

    await assertSize(minimized, { width: 400, height: 600 })
    await assertAspectRatio(minimized, 400 / 600, 0.05)
  })
})
