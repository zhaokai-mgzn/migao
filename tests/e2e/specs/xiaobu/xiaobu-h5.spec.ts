// case_ids: OR-001, PR-001, DF-002
/**
 * 小布 H5 视觉回归 — 无会话 UX + 新品推荐 + 订单卡片
 *
 * 目的：验证 C 端 mini-app 渲染效果（用户直接看到的 UI），
 * 弥补 API 层验收覆盖不到的视觉/布局回归。
 *
 * 运行前提：mini-app 已 build:h5（dist/ 为 H5 产物），
 * 用静态服务器提供 dist/（见 playwright.xiaobu.config.ts webServer）。
 *
 * Mock 策略：拦截 API 返回固定数据，保证视觉断言确定性（不依赖真实 LLM/后端）。
 */

import { test, expect } from '@playwright/test'

// ═══════════════════════════════════════════════════════════════
// Mock 数据
// ═══════════════════════════════════════════════════════════════

const MOCK_SESSION = {
  id: 'sess-vr-001',
  session_id: 'sess-vr-001',
  title: '视觉回归会话',
  status: 'active',
  customer_name: '视觉测试用户',
  last_message: '',
  created_at: '2026-06-20T10:00:00Z',
  updated_at: '2026-06-20T10:00:00Z',
}

const MOCK_NEW_ARRIVALS = {
  success: true,
  data: {
    items: [
      { id: 'p1', name: '遮光窗帘', price: 199, image: '' },
      { id: 'p2', name: '北欧风窗帘', price: 299, image: '' },
      { id: 'p3', name: '雪尼尔窗帘', price: 399, image: '' },
    ],
    total: 3,
  },
}

/** 订单卡片 mock（OrderCard 渲染依据：order 类型卡片） */
const MOCK_ORDER_CARD = {
  type: 'order',
  data: {
    orders: [
      {
        order_no: 'ORD-20260601-001',
        status: 'shipped',
        status_text: '已发货',
        total_amount: 299.5,
        items: [{ product_name: '遮光窗帘', quantity: 2, amount: 199 }],
        created_at: '2026-06-01T10:00:00Z',
      },
    ],
  },
}

// ═══════════════════════════════════════════════════════════════
// Mock 设置
// ═══════════════════════════════════════════════════════════════

async function setupMocks(page: import('@playwright/test').Page) {
  // 注入测试 token（绕过 checkAuth→login 链路，直接进入 ensureLatestSession 续聊）
  // 注意：Taro H5 getStorageSync 只认 {"data": <value>} 格式（由 Taro.setStorage 写入）；
  // token 需为三段式 JWT 且无 exp（checkTokenValidity 无 exp 视为有效）
  await page.addInitScript(() => {
    const b64 = (s: string) => btoa(unescape(encodeURIComponent(s)))
    const fakeJwt = `${b64('{"alg":"none","typ":"JWT"}' as any)}.${b64('{"userId":"u-visual"}' as any)}.sig`
    localStorage.setItem('auth_token', JSON.stringify({ data: fakeJwt }))
    localStorage.setItem('auth_user', JSON.stringify({ data: JSON.stringify({ id: 'u-visual', nickname: '视觉测试', avatar: null, tenant_id: 1 }) }))
    localStorage.setItem('tenant_id', JSON.stringify({ data: '1' }))
  })

  // 无会话 UX：latest 返回会话（续聊）
  await page.route('**/api/chat/sessions/latest', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { session: MOCK_SESSION } }),
    })
  })
  // 会话历史为空（空态欢迎屏 → 展示新品推荐）
  await page.route('**/api/chat/history/*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { items: [] } }),
    })
  })
  // 新品推荐
  await page.route('**/api/chat/products/new-arrivals*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_NEW_ARRIVALS),
    })
  })
}

// ═══════════════════════════════════════════════════════════════
// 测试
// ═══════════════════════════════════════════════════════════════

test.describe('小布 H5 视觉回归', () => {
  test.beforeEach(async ({ page }) => {
    // 调试：捕获页面 JS 运行时异常与 console error（issue #2693 定位）
    page.on('pageerror', (e) => console.log('🔴 PAGEERROR:', e.message, e.stack?.split('\n')[1] || ''))
    page.on('console', (m) => { if (m.type() === 'error') console.log('🟠 CONSOLE_ERROR:', m.text()) })
  })

  test('空态欢迎屏：无会话概念 + 新品推荐展示', async ({ page }) => {
    await setupMocks(page)
    await page.goto('/#/pages/chat/index/index')

    // 品牌区（导航栏标题）
    await expect(page.locator('.chat-page__navbar-name')).toBeVisible()
    // 无「会话」tab（2 tab：对话/我的）
    await expect(page.getByText('会话', { exact: true })).toHaveCount(0)
    // 新品推荐区
    await expect(page.getByText(/新品推荐/)).toBeVisible()
    await expect(page.getByText('遮光窗帘')).toBeVisible()
    // 视觉基线
    await expect(page).toHaveScreenshot('xiaobu-empty-welcome.png', {
      maxDiffPixelRatio: 0.02,
    })
  })

  test('新品推荐横滑卡片：点击唤起对话', async ({ page }) => {
    await setupMocks(page)
    await page.goto('/#/pages/chat/index/index')

    await expect(page.getByText('遮光窗帘')).toBeVisible()
    // 点击商品 → 唤起对话询问该商品
    await page.getByText('遮光窗帘').click()
  })

  test('对话页无「会话列表」入口（2 tab 结构）', async ({ page }) => {
    await setupMocks(page)
    await page.goto('/#/pages/chat/index/index')
    // tabBar 只应有「对话」和「我的」
    await expect(page.getByText('对话', { exact: true })).toBeVisible()
    await expect(page.getByText('我的', { exact: true })).toBeVisible()
    await expect(page.getByText('会话', { exact: true })).toHaveCount(0)
  })

  test('订单卡片渲染（OrderCard 视觉验收）', async ({ page }) => {
    await setupMocks(page)
    // 等待 latest 请求完成（会话建立 → currentSessionId 生效 → input 可用）
    const latestDone = page.waitForResponse(
      (r) => r.url().includes('/api/chat/sessions/latest') && r.status() === 200,
    )
    await page.goto('/#/pages/chat/index/index')
    await latestDone
    await expect(page.locator('.chat-page__navbar-name')).toBeVisible()

    // 等待会话就绪（latest mock 返回 session → ensureLatestSession 建立 currentSessionId → input 可用）
    const input = page.locator('input, textarea').first()
    await expect(input).toBeEnabled({ timeout: 10_000 })

    // 注册订单卡片 SSE mock（发消息时才被请求）
    // 注意：X-Client-Type 自定义头会触发浏览器 CORS preflight（OPTIONS），需一并 mock
    await page.route('**/api/chat/send', async (route) => {
      const method = route.request().method()
      if (method === 'OPTIONS') {
        await route.fulfill({
          status: 204,
          headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, X-Client-Type, Authorization',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
          },
        })
        return
      }
      const card = JSON.stringify(MOCK_ORDER_CARD)
      const done = JSON.stringify({ session_id: 'sess-vr-001', message_id: 'm1' })
      // 标准 SSE 格式：每个事件以空行分隔（Taro 按行解析 event:/data:）
      const body = [
        `event: card\ndata: ${card}\n`,
        `event: done\ndata: ${done}\n`,
      ].join('\n')
      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream',
        headers: {
          'Content-Type': 'text/event-stream',
          'Cache-Control': 'no-cache',
          'Access-Control-Allow-Origin': '*',
        },
        body,
      })
    })

    // 发消息触发订单卡片渲染
    await input.fill('查我的订单')
    await input.press('Enter')

    // 订单号 + 状态 + 金额可见
    await expect(page.getByText(/ORD-20260601-001/)).toBeVisible()
    await expect(page.getByText('已发货')).toBeVisible()
    await expect(page.getByText(/299\.50/)).toBeVisible()
    // 视觉基线（订单卡片样式）
    await expect(page).toHaveScreenshot('xiaobu-order-card.png', {
      maxDiffPixelRatio: 0.02,
    })
  })
})
