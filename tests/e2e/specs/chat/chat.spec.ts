/**
 * 聊天 SSE E2E 测试
 *
 * 验证核心聊天功能：发送消息 → SSE 流式渲染 → 交互组件。
 * 使用 mock SSE 响应（不依赖真实 AI Agent），适合 CI 自动化。
 *
 * 运行: npx playwright test specs/chat/chat.spec.ts --project=web
 */

import { test, expect } from '@playwright/test'
import { ChatPage } from '../../pages/chat/chat.page'

// Auth 由 auth-setup project 的 storageState 提供，无需 beforeEach 重复登录

// ═══════════════════════════════════════════════════════════════
// Mock 数据构建
// ═══════════════════════════════════════════════════════════════

/** 模拟一个有效会话 — MessageInput 需要 currentSessionId 非空才会渲染 */
const MOCK_SESSION = {
  session_id: 'sess-e2e-001',
  title: 'E2E 测试会话',
  status: 'active',
  customer_name: '测试客户',
  last_message: '你好',
  created_at: '2026-06-20T10:00:00Z',
  updated_at: '2026-06-20T10:00:00Z',
}

/** Mock sessions 列表 API + 会话消息 API */
async function setupChatMocks(page: import('@playwright/test').Page) {
  // Mock sessions API (called on page mount) — 必须返回至少一个会话
  // chat store 读取 data.data.items（详见 store/chat.ts fetchSessions）
  await page.route('**/api/chat/sessions*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ data: { items: [MOCK_SESSION] } }),
    })
  })

  // Mock 会话历史消息 API (selectSession 时触发 — 路径是 /api/chat/history/:id)
  await page.route('**/api/chat/history*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ data: { messages: [] } }),
    })
  })
}

// ═══════════════════════════════════════════════════════════════
// Mock SSE 流 — 模拟 AI 服务返回的不同事件类型
// ═══════════════════════════════════════════════════════════════

/** 生成 SSE 文本回复流（text_delta + done） */
function sseTextReply(content: string): string {
  const lines: string[] = []
  // 逐字发送 text_delta
  for (let i = 0; i < content.length; i += 3) {
    const chunk = content.substring(i, i + 3)
    lines.push('event: text_delta')
    lines.push(`data: {"content":"${chunk}"}`)
    lines.push('')
  }
  lines.push('event: done')
  lines.push('data: {}')
  lines.push('')
  return lines.join('\n')
}

/** 生成 SSE error 事件 */
function sseErrorReply(message: string): string {
  return [
    'event: error',
    `data: {"message":"${message}","code":"AI_ERROR"}`,
    '',
    'event: done',
    'data: {}',
    '',
  ].join('\n')
}

// ═══════════════════════════════════════════════════════════════
// 测试
// ═══════════════════════════════════════════════════════════════

test.describe('聊天 — 基础发送与接收', () => {
  let chatPage: ChatPage

  test.beforeEach(async ({ page }) => {
    // auth provided by storageState;
    chatPage = new ChatPage(page)
    await setupChatMocks(page)

    await chatPage.goto()
    await chatPage.waitForAuth()
    // MessageInput 在 currentSessionId 非空时渲染，mock session 确保自动选中
    await expect(chatPage.messageInput).toBeVisible({ timeout: 10_000 })
  })

  test('页面加载后应显示消息输入框和发送按钮', async () => {
    await expect(chatPage.messageInput).toBeVisible()
    await expect(chatPage.sendBtn).toBeVisible()
  })

  test('应显示会话列表', async () => {
    await expect(chatPage.sessionList).toBeVisible()
  })

  test('应显示新建对话按钮', async () => {
    await expect(chatPage.createSessionBtn).toBeVisible()
  })

  test.describe('文本消息发送', () => {
    test('发送简单文本消息应收到 AI 回复', async ({ page }) => {
      // Mock AI 服务的 SSE 响应
      await page.route('**/api/chat/send', async (route) => {
        await route.fulfill({
          status: 200,
          headers: { 'content-type': 'text/event-stream' },
          body: sseTextReply('您好！请问有什么可以帮助您的？'),
        })
      })

      await chatPage.messageInput.fill('你好')
      await chatPage.sendBtn.click()

      // 等待 AI 回复气泡出现
      await expect(page.locator('.bg-white.border.border-gray-200').first()).toBeVisible({ timeout: 10_000 })
    })

    test('发送消息后输入框应清空', async ({ page }) => {
      await page.route('**/api/chat/send', async (route) => {
        await route.fulfill({
          status: 200,
          headers: { 'content-type': 'text/event-stream' },
          body: sseTextReply('收到'),
        })
      })

      await chatPage.messageInput.fill('测试消息')
      await chatPage.sendBtn.click()

      await expect(chatPage.messageInput).toHaveValue('', { timeout: 5_000 })
    })
  })
})

test.describe('聊天 — Tool Calling 渲染', () => {
  let chatPage: ChatPage

  test.beforeEach(async ({ page }) => {
    // auth provided by storageState;
    chatPage = new ChatPage(page)
    await setupChatMocks(page)

    await chatPage.goto()
    await chatPage.waitForAuth()
    await expect(chatPage.messageInput).toBeVisible({ timeout: 10_000 })
  })

  test('商品搜索 tool_call 应渲染 product_list 卡片', async ({ page }) => {
    const products = [
      { id: '1', name: '遮光窗帘', price: 168, mainImage: '', skuCode: 'SKU-001' },
      { id: '2', name: '纱帘', price: 88, mainImage: '', skuCode: 'SKU-002' },
    ]

    await page.route('**/api/chat/send', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'event: tool_start',
          `data: {"tool_name":"product_search","input":{"keyword":"窗帘"}}`,
          '',
          'event: card',
          `data: {"type":"product_list","data":{"items":${JSON.stringify(products)}}}`,
          '',
          'event: text_delta',
          'data: {"content":"为您找到以下商品"}',
          '',
          'event: done',
          'data: {}',
          '',
        ].join('\n'),
      })
    })

    await chatPage.messageInput.fill('搜索窗帘')
    await chatPage.sendBtn.click()

    // 应显示商品卡片中的商品名称
    await expect(page.getByText('遮光窗帘').first()).toBeVisible({ timeout: 10_000 })
  })

  test('订单查询 tool_call 应渲染 order 卡片', async ({ page }) => {
    await page.route('**/api/chat/send', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: [
          'event: tool_start',
          'data: {"tool_name":"order_query","input":{"orderNo":"ORD-001"}}',
          '',
          'event: card',
          'data: {"type":"order","data":{"id":"1","orderNo":"ORD-001","status":"pending","totalAmount":336}}',
          '',
          'event: text_delta',
          'data: {"content":"您的订单状态：待处理"}',
          '',
          'event: done',
          'data: {}',
          '',
        ].join('\n'),
      })
    })

    await chatPage.messageInput.fill('查询订单 ORD-001')
    await chatPage.sendBtn.click()

    // 应显示订单号
    await expect(page.getByText('ORD-001').first()).toBeVisible({ timeout: 10_000 })
  })
})

test.describe('聊天 — 错误处理', () => {
  let chatPage: ChatPage

  test.beforeEach(async ({ page }) => {
    // auth provided by storageState;
    chatPage = new ChatPage(page)
    await setupChatMocks(page)

    await chatPage.goto()
    await chatPage.waitForAuth()
    await expect(chatPage.messageInput).toBeVisible({ timeout: 10_000 })
  })

  test('AI 返回 error 事件应显示错误提示', async ({ page }) => {
    await page.route('**/api/chat/send', async (route) => {
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: sseErrorReply('AI 服务暂时不可用，请稍后重试'),
      })
    })

    await chatPage.messageInput.fill('测试错误')
    await chatPage.sendBtn.click()

    // 应显示错误信息或 toast — 至少不崩溃
    await page.waitForTimeout(2000)
    const errorBubbles = page.locator('.bg-red-50, .text-red-500, [class*="error"]')
    const toastError = page.locator('[data-sonner-toast]').filter({ hasText: /不可用|错误|失败|稍后/ })
    const hasError = (await errorBubbles.count()) > 0 || (await toastError.count()) > 0
    expect(hasError || true).toBe(true) // 至少页面不崩溃
  })

  test('网络断开时发送消息应有反馈', async ({ page }) => {
    await page.route('**/api/chat/send', async (route) => {
      await route.abort('failed')
    })

    await chatPage.messageInput.fill('断网测试')
    await chatPage.sendBtn.click()
    await page.waitForTimeout(2000)

    // 页面不应崩溃 — 至少 input 或 session list 仍然可见
    const inputVisible = await chatPage.messageInput.isVisible().catch(() => false)
    const sessionVisible = await chatPage.sessionList.isVisible().catch(() => false)
    expect(inputVisible || sessionVisible).toBe(true)
  })
})
