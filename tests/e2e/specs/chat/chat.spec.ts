// case_ids: UI-009
/**
 * 聊天 SSE E2E 测试
 *
 * 验证核心聊天功能：发送消息 → SSE 流式渲染 → 交互组件。
 * 使用 mock SSE 响应（不依赖真实 AI Agent），适合 CI 自动化。
 *
 * 运行: npx playwright test specs/chat/chat.spec.ts --project=web
 */

import { test, expect } from '../../fixtures'
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

      // 等待 AI 回复气泡出现（AI 气泡样式：白底 + gray-100 边框）
      await expect(page.locator('.bg-white.border.border-gray-100').first()).toBeVisible({ timeout: 10_000 })
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
    chatPage = new ChatPage(page)
    await setupChatMocks(page)

    await chatPage.goto()
    await chatPage.waitForAuth()
    await expect(chatPage.messageInput).toBeVisible({ timeout: 10_000 })
  })

  test.skip('商品搜索 tool_call 应渲染 product_list 卡片', async ({ page }) => {
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
    expect(hasError).toBe(true) // 至少页面不崩溃
  })

  test.skip('网络断开时发送消息应有反馈', async ({ page }) => {
    await page.route('**/api/chat/send', async (route) => {
      await route.abort('failed')
    })

    await chatPage.messageInput.fill('断网测试')
    await chatPage.sendBtn.click()
    await page.waitForTimeout(2000)

    // 输入框不应清空（发送失败）
    const inputValue = await chatPage.messageInput.inputValue()
    expect(inputValue.length).toBeGreaterThan(0)
  })
})

test.describe('聊天 — 洞察抽屉', () => {
  let chatPage: ChatPage

  test.beforeEach(async ({ page }) => {
    chatPage = new ChatPage(page)
    await setupChatMocks(page)

    await chatPage.goto()
    await chatPage.waitForAuth()
    await expect(chatPage.messageInput).toBeVisible({ timeout: 10_000 })
  })

  test('默认状态下洞察抽屉收起', async () => {
    await expect(chatPage.insightDrawer).toBeHidden()
    await expect(chatPage.insightOverlay).not.toBeVisible()
  })

  test('点击洞察按钮展开抽屉', async ({ page }) => {
    await chatPage.insightToggleBtn.click()
    await expect(chatPage.insightDrawer).toBeVisible()
    await expect(page.getByText('会话洞察')).toBeVisible()
  })

  test('点击遮罩关闭抽屉', async ({ page }) => {
    await chatPage.insightToggleBtn.click()
    await expect(chatPage.insightDrawer).toBeVisible()

    await chatPage.insightOverlay.click({ position: { x: 10, y: 10 } })
    await expect(chatPage.insightDrawer).toBeHidden()
    await expect(chatPage.insightOverlay).not.toBeVisible()
  })
})

// ═══════════════════════════════════════════════════════════════
// UI-009 拖拽图片附件上传（渲染→拖拽→上传→发送→验证 链路）
// ═══════════════════════════════════════════════════════════════
test.describe('聊天 — 拖拽图片上传（UI-009）', () => {
  let chatPage: ChatPage

  test.beforeEach(async ({ page }) => {
    chatPage = new ChatPage(page)
    await setupChatMocks(page)
    // fixture 模式：补 refresh mock 防 token 刷新清态（同 dashboard.spec）
    await page.route('**/api/auth/refresh', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { accessToken: 'e2e-refreshed', refreshToken: 'e2e-refresh' } }) })
    })
    // Mock 图片上传接口（chatApi.uploadChatImages → /api/chat/upload-image）
    await page.route('**/api/chat/upload-image', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            files: [
              { id: 'img-001', url: 'https://cdn.test/uploads/photo.png', name: 'photo.png', size: 2048 },
            ],
          },
        }),
      })
    })

    await chatPage.goto()
    await chatPage.waitForAuth()
    await expect(chatPage.messageInput).toBeVisible({ timeout: 10_000 })
  })

  /** 模拟把图片文件拖拽进输入区（dragOver 高亮 + drop 触发上传） */
  async function dragImageIntoZone(page: import('@playwright/test').Page, fileName = 'photo.png', fileType = 'image/png') {
    await chatPage.inputZone.evaluate(
      (zone, { fname, ftype }) => {
        const dt = new DataTransfer()
        dt.items.add(new File(['fake-image-bytes'], fname, { type: ftype }))
        zone.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }))
        zone.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }))
      },
      { fname: fileName, ftype: fileType },
    )
  }

  test('拖拽图片到输入区应上传附件并显示预览，可随消息发送', async ({ page }) => {
    // Mock SSE 发送接口（发送后应有图片附件）
    let sentBody: Record<string, unknown> | null = null
    await page.route('**/api/chat/send', async (route) => {
      sentBody = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
        body: sseTextReply('收到您的图片，我来看看'),
      })
    })

    await dragImageIntoZone(page)

    // 上传成功后应显示图片预览缩略图（alt=文件名）
    await expect(page.locator('img[alt="photo.png"]')).toBeVisible({ timeout: 10_000 })

    // 发送消息，验证请求携带 images 附件
    await chatPage.messageInput.fill('请查看这张图片')
    await chatPage.sendBtn.click()

    await expect(page.getByText('收到您的图片，我来看看').first()).toBeVisible({ timeout: 10_000 })
    expect(sentBody).not.toBeNull()
    expect((sentBody as { images?: string[] }).images).toEqual([
      'https://cdn.test/uploads/photo.png',
    ])
  })

  test('拖拽悬停时输入区显示高亮提示，松开后消失', async ({ page }) => {
    await chatPage.inputZone.evaluate((zone) => {
      const dt = new DataTransfer()
      dt.items.add(new File(['x'], 'photo.png', { type: 'image/png' }))
      zone.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: dt }))
    })
    await expect(page.getByText('松开上传图片')).toBeVisible()

    await chatPage.inputZone.evaluate((zone) => {
      zone.dispatchEvent(new DragEvent('dragleave', { bubbles: true, cancelable: true }))
    })
    await expect(page.getByText('松开上传图片')).toBeHidden()
  })

  test('拖拽非图片文件应被拒绝且不触发上传', async ({ page }) => {
    let uploadCalled = false
    await page.route('**/api/chat/upload-image', async (route) => {
      uploadCalled = true
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
    })

    await chatPage.inputZone.evaluate((zone) => {
      const dt = new DataTransfer()
      dt.items.add(new File(['hello'], 'note.txt', { type: 'text/plain' }))
      zone.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }))
    })

    // 非图片不调用上传接口；toast 提示不支持
    await expect(page.getByText('不支持的文件类型: note.txt')).toBeVisible({ timeout: 5_000 })
    expect(uploadCalled).toBe(false)
    // 无预览
    await expect(page.locator('img[alt="note.txt"]')).toHaveCount(0)
  })
})
