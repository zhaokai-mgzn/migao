// case_ids: OR-001, DF-002, UI-014, UI-016
/**
 * 小布 H5 视觉回归 — 无会话 UX + 快捷入口六格 + 订单卡片
 *
 * 目的：验证 C 端 mini-app 渲染效果（用户直接看到的 UI），
 * 弥补 API 层验收覆盖不到的视觉/布局回归。
 *
 * 运行前提：mini-app 已 build:h5（dist/ 为 H5 产物），
 * 用静态服务器提供 dist/（见 playwright.xiaobu.config.ts webServer）。
 *
 * Mock 策略：拦截 API 返回固定数据，保证视觉断言确定性（不依赖真实 LLM/后端）。
 *
 * UI-014: 快捷入口（M1-A/issue #3978 起为六格等权：算料报价/推荐热门商品/查订单/找产品/售后咨询/查物流）
 * UI-016: 导航副标题企业名取自企业设置 tenantName（mock='米高窗帘'）
 *
 * 2026-09-17 同步 M1-A（UI-044）：空态**不再展示商品推荐卡**（NewArrivals 组件与
 * 「新品推荐」区块已删除，推荐改由「推荐热门商品」快捷对话入口承载）
 * ⇒ 移除本 spec 对「新品推荐/遮光窗帘」的断言与 /chat/products/new-arrivals mock，
 *    并新增「快捷入口六格可见 + 商品推荐卡不得出现」的负向断言。
 */

import { test, expect } from '../../fixtures'

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
    // auth_user 的形状 = 后端登录响应 data.user 的 JSON 原样（camelCase，见 mini-app
    // src/types 的 `User`）：租户 ID 键名是 `tenantId`，生产从不产生 `tenant_id`
    // （下一行的 `tenant_id` 是 Taro storage 键，与 user 对象字段无关，勿混同）
    localStorage.setItem('auth_user', JSON.stringify({ data: JSON.stringify({ id: 'u-visual', nickname: '视觉测试', avatar: null, tenantId: 1, tenantName: '米高窗帘' }) }))
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
  // M1-A（issue #3978）：空态已移除商品推荐卡 → 不再 mock /chat/products/new-arrivals
}

// ═══════════════════════════════════════════════════════════════
// 测试
// ═══════════════════════════════════════════════════════════════

test.describe('小布 H5 视觉回归', () => {
  test('空态欢迎屏：无会话概念 + 快捷入口六格（无商品推荐卡）', async ({ page }) => {
    await setupMocks(page)
    await page.goto('/#/pages/chat/index/index')

    // 品牌区（导航栏标题）
    await expect(page.locator('.chat-page__navbar-name')).toBeVisible()
    // UI-016：副标题企业名来自企业设置（mock tenantName='米高窗帘'），非硬编码默认值
    await expect(page.getByText('米高窗帘 · 智能购物助手')).toBeVisible()
    // UI-014（M1-A/issue #3978 修订）：六格等权快捷入口全部可见（算料报价为其中之一，不再全宽）
    for (const label of ['算料报价', '推荐热门商品', '查订单', '找产品', '售后咨询', '查物流']) {
      await expect(page.getByText(label, { exact: true })).toBeVisible()
    }
    // 无「会话」tab（2 tab：对话/我的）
    await expect(page.getByText('会话', { exact: true })).toHaveCount(0)
    // UI-044（M1-A）：空态**不得**再出现商品推荐卡/商品名（推荐改由快捷对话入口承载）
    await expect(page.getByText(/新品推荐/)).toHaveCount(0)
    await expect(page.getByText('遮光窗帘')).toHaveCount(0)
    // 视觉基线
    await expect(page).toHaveScreenshot('xiaobu-empty-welcome.png', {
      maxDiffPixelRatio: 0.02,
    })
  })

  test('快捷入口「推荐热门商品」点击唤起对话（替代已移除的商品卡入口）', async ({ page }) => {
    await setupMocks(page)
    await page.goto('/#/pages/chat/index/index')

    // UI-044：推荐能力由快捷对话入口承载 —— 点击后应发送推荐 prompt（用户气泡可见）
    const entry = page.getByText('推荐热门商品', { exact: true })
    await expect(entry).toBeVisible()
    await entry.click()
    await expect(page.getByText('推荐一下热门商品')).toBeVisible()
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
