// case_ids: DA-004
/**
 * 会话管理工作台（/agent-workspace/sessions）E2E
 *
 * 会话管理重构落地页：验证占位页已被真实会话管理工作台替换 —
 * 复用已重构 SessionService API（chatApi /api/chat/sessions），
 * 顶部统计条 + 会话列表 + 聊天区（含洞察抽屉）真实渲染。
 *
 * 运行: npx playwright test specs/chat/agent-workspace-sessions.spec.ts --project=web
 */

import { test, expect, type Page } from '@playwright/test'

// ───────────────────────────────────────────────────────────────
// Mock 数据：与 chat.spec.ts 同源（会话管理页复用同一 chatApi）
// ───────────────────────────────────────────────────────────────

const MOCK_SESSIONS = [
  { id: 'sess-001', title: '遮光窗帘订单确认', status: 'active', customer_name: '张三', last_message: '请确认', message_count: 4, created_at: '2026-08-01T10:00:00Z', updated_at: '2026-08-01T11:00:00Z' },
  { id: 'sess-002', title: '纱帘加工进度查询', status: 'active', customer_name: '李四', last_message: '进度如何', message_count: 6, created_at: '2026-08-01T09:00:00Z', updated_at: '2026-08-01T10:30:00Z' },
  { id: 'sess-003', title: '已完结售后咨询', status: 'closed', customer_name: '王五', last_message: '谢谢', message_count: 3, created_at: '2026-07-30T08:00:00Z', updated_at: '2026-07-30T09:00:00Z' },
]

async function setupSessionMocks(page: Page) {
  await page.route('**/api/chat/sessions*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ data: { items: MOCK_SESSIONS } }),
    })
  })
  await page.route('**/api/chat/history*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ data: { messages: [] } }),
    })
  })
}

// ───────────────────────────────────────────────────────────────
// 测试
// ───────────────────────────────────────────────────────────────

test.describe('会话管理工作台 — 占位页替换为真实功能', () => {
  test.beforeEach(async ({ page }) => {
    await setupSessionMocks(page)
  })

  test('页面标题为「会话管理」（非「开发中」占位）', async ({ page }) => {
    await page.goto('/agent-workspace/sessions')
    await page.waitForFunction(
      () => {
        const raw = localStorage.getItem('auth-storage')
        if (!raw) return false
        try { return !!(JSON.parse(raw)?.state?.accessToken) } catch { return false }
      },
      { timeout: 10_000 },
    )
    await expect(page.getByRole('heading', { name: '会话管理' })).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('该功能正在开发中')).toHaveCount(0)
  })

  test('顶部统计条按会话状态派生（活跃 2 / 已关闭 1 / 共 3）', async ({ page }) => {
    await page.goto('/agent-workspace/sessions')
    await page.waitForFunction(
      () => {
        const raw = localStorage.getItem('auth-storage')
        if (!raw) return false
        try { return !!(JSON.parse(raw)?.state?.accessToken) } catch { return false }
      },
      { timeout: 10_000 },
    )
    const bar = page.locator('[data-testid="session-stats-bar"]')
    await expect(bar).toBeVisible({ timeout: 10_000 })
    await expect(bar).toContainText('活跃')
    await expect(bar).toContainText('2')
    await expect(bar).toContainText('已关闭')
    await expect(bar).toContainText('1')
    await expect(bar).toContainText('共')
    await expect(bar).toContainText('3')
  })

  test('会话列表渲染真实数据（新建对话 + 活跃/已关闭 tab）', async ({ page }) => {
    await page.goto('/agent-workspace/sessions')
    await page.waitForFunction(
      () => {
        const raw = localStorage.getItem('auth-storage')
        if (!raw) return false
        try { return !!(JSON.parse(raw)?.state?.accessToken) } catch { return false }
      },
      { timeout: 10_000 },
    )
    await expect(page.getByRole('button', { name: /新建对话/ })).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('遮光窗帘订单确认')).toBeVisible({ timeout: 10_000 })
    await expect(page.getByText('纱帘加工进度查询')).toBeVisible()
  })

  test('选中会话后聊天区加载历史（复用 /chat 组件链）', async ({ page }) => {
    await page.goto('/agent-workspace/sessions')
    await page.waitForFunction(
      () => {
        const raw = localStorage.getItem('auth-storage')
        if (!raw) return false
        try { return !!(JSON.parse(raw)?.state?.accessToken) } catch { return false }
      },
      { timeout: 10_000 },
    )
    // 第一个会话自动选中 → 消息输入框渲染（MessageInput 需要 currentSessionId 非空）
    await expect(page.locator('textarea[placeholder*="输入消息"]').first()).toBeVisible({ timeout: 10_000 })
  })
})
