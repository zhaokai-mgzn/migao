/**
 * 米宝对话面板高度调整 + 拖拽缩放 E2E 测试
 *
 * 验证 issue #1402：默认高度调高、鼠标拖拽缩放、localStorage 持久化。
 *
 * 运行: npx playwright test specs/chat/chat-panel-resize.spec.ts --project=web
 */

import { test, expect } from '@playwright/test'
import { ChatPage } from '../../pages/chat/chat.page'

const STORAGE_KEY = 'mibao_chat_panel_height'

async function getPanelHeight(page: import('@playwright/test').Page): Promise<number> {
  const handle = page.locator('[data-testid="chat-panel-resize-container"]')
  const box = await handle.boundingBox()
  return box?.height ?? 0
}

test.describe('Chat Panel Resize', () => {
  test.beforeEach(async ({ page }) => {
    const chatPage = new ChatPage(page)
    await chatPage.goto()
    await chatPage.waitForAuth()
  })

  // L4-1: 对话面板默认渲染高度 ≥ 600px
  test('default panel height >= 600px', async ({ page }) => {
    const height = await getPanelHeight(page)
    expect(height).toBeGreaterThanOrEqual(600)
  })

  // L4-2: resize handle 可见且 cursor = ns-resize
  test('resize handle is visible with ns-resize cursor', async ({ page }) => {
    const handle = page.locator('[data-testid="chat-panel-resize-handle"]')
    await expect(handle).toBeVisible()
    const cursor = await handle.evaluate((el) => window.getComputedStyle(el).cursor)
    expect(['ns-resize', 'row-resize']).toContain(cursor)
  })

  // L4-3: 向下拖拽 handle 100px → panel 高度增加约 100px
  test('dragging handle down increases panel height', async ({ page }) => {
    const handle = page.locator('[data-testid="chat-panel-resize-handle"]')
    const beforeHeight = await getPanelHeight(page)
    const box = await handle.boundingBox()
    if (!box) throw new Error('Handle not found')

    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 + 100, { steps: 5 })
    await page.mouse.up()

    const afterHeight = await getPanelHeight(page)
    expect(afterHeight - beforeHeight).toBeGreaterThanOrEqual(95)
  })

  // L4-5: 拖拽后刷新页面 → 高度保持
  test('panel height persists across page reload', async ({ page }) => {
    const handle = page.locator('[data-testid="chat-panel-resize-handle"]')
    const box = await handle.boundingBox()
    if (!box) throw new Error('Handle not found')

    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 + 80, { steps: 5 })
    await page.mouse.up()

    const stored = await page.evaluate((key) => localStorage.getItem(key), STORAGE_KEY)
    expect(stored).not.toBeNull()

    const heightBeforeReload = await getPanelHeight(page)
    await page.reload()
    await page.waitForSelector('[data-testid="chat-panel-resize-container"]')
    const heightAfterReload = await getPanelHeight(page)
    expect(heightAfterReload).toBe(heightBeforeReload)
  })

  // L4-6: 拖拽后内容区域仍然可见
  test('content area remains visible after resize', async ({ page }) => {
    const handle = page.locator('[data-testid="chat-panel-resize-handle"]')
    const box = await handle.boundingBox()
    if (!box) throw new Error('Handle not found')

    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.down()
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 + 50, { steps: 3 })
    await page.mouse.up()

    await expect(page.locator('[data-testid="chat-panel-content"]')).toBeVisible()
  })
})
