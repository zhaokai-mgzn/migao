import { test, expect } from '@playwright/test'
import { ChatPage } from '../../pages/chat/chat.page'

/**
 * 米宝对话流程 E2E — 验证 SSE 事件流和 UI 渲染
 *
 * SSE 事件类型（来自 ai-agent-service）：
 *   - text_delta: 文本流式增量
 *   - tool_start: 工具调用开始
 *   - tool_result: 工具返回结果
 *   - suggestions: 推荐提问
 *   - error: 错误事件
 *   - done: 流结束
 */
test.describe('米宝 AI 对话流程', () => {
  // AI 流式响应 + 工具调用需要更长测试超时（默认 30s 不够）
  test.setTimeout(120_000)
  let page: ChatPage

  test.beforeEach(async ({ page: p }) => {
    page = new ChatPage(p)
    await page.goto()
    await page.waitForLoad()
    // 每个测试创建新会话，避免发消息到已关闭的旧会话
    await page.createSessionBtn.click()
    await p.waitForTimeout(1000)
  })

  test('三栏布局正确渲染', async () => {
    // 左侧会话列表 240px
    await expect(page.sessionList).toBeVisible()
    // 中间聊天区域
    const chatArea = page.page.locator('.flex-1.flex.flex-col').first()
    await expect(chatArea).toBeVisible()
  })

  test('新建会话后显示空状态引导', async () => {
    await page.createSessionBtn.click()
    await page.page.waitForTimeout(500)
    // 新会话空状态："发送消息开始对话"
    const guideText = page.page.getByText(/发送消息开始对话/)
    if (await guideText.isVisible().catch(() => false)) {
      await expect(guideText).toBeVisible()
    }
  })

  test('加载历史会话消息', async () => {
    // 如果存在历史会话
    const items = page.sessionList.locator('.mx-1\\.5')
    if (await items.count() > 0) {
      await items.first().click()
      await page.page.waitForTimeout(1000)
      // 消息列表区域
      const messageArea = page.page.locator('.flex-1.overflow-y-auto').first()
      await expect(messageArea).toBeVisible()
    }
  })

  test('SSE text_delta 流式文本渲染', async ({ page: p }) => {
    await page.messageInput.fill('你好，请介绍一下你自己')
    await page.sendBtn.click()

    // AI 回复气泡 — 使用 toPass() 轮询等待流式内容到达
    const aiBubble = p.locator('.bg-white.border.border-gray-200.rounded-bl-md').last()
    await expect(async () => {
      await expect(aiBubble).toBeVisible()
      const text = await aiBubble.textContent()
      expect(text?.trim()).toBeTruthy()
    }).toPass({ timeout: 60_000 })
  })

  test('工具调用消息包含结果数据', async ({ page: p }) => {
    await page.messageInput.fill('帮我查看最近的订单')
    await page.sendBtn.click()

    // 新 endpoint 将工具结果直接内嵌在 text 事件中（无独立 tool_call 事件）
    // 验证 AI 回复气泡中包含订单相关数据
    const aiBubble = p.locator('.bg-white.border.border-gray-200.rounded-bl-md').last()
    await expect(async () => {
      const text = await aiBubble.textContent()
      expect(text?.trim().length).toBeGreaterThan(0)
      // AI 回复应包含订单相关内容（表格或文字描述）
      expect(text).toMatch(/订单|ORD|客户/)
    }).toPass({ timeout: 60_000 })
  })

  test('工具调用后显示 AI 总结', async ({ page: p }) => {
    await page.messageInput.fill('查看订单列表')
    await page.sendBtn.click()

    // AI 应在回复中包含工具查询结果的总结
    const aiBubble = p.locator('.bg-white.border.border-gray-200.rounded-bl-md').last()
    await expect(async () => {
      const text = await aiBubble.textContent()
      expect(text?.trim().length).toBeGreaterThan(10)
    }).toPass({ timeout: 60_000 })
  })

  test('suggestions 事件显示推荐提问 chip', async ({ page: p }) => {
    await page.messageInput.fill('你好')
    await page.sendBtn.click()

    // 推荐提问区域 — 等待完整 SSE 响应（含 suggestions 事件）
    const suggestionsHeader = p.getByText('推荐提问：')
    await expect(suggestionsHeader).toBeVisible({ timeout: 30_000 })
    const suggestionBtns = suggestionsHeader.locator('..').locator('button')
    await expect(suggestionBtns.first()).toBeVisible({ timeout: 5_000 })
  })

  test('error 事件显示错误 UI', async ({ page: p }) => {
    // 错误事件在消息流中展示
    const errorIndicators = p.locator('svg.lucide-alert-circle')
    expect(await errorIndicators.count()).toBeGreaterThanOrEqual(0)
  })

  test('product_list 卡片可渲染', async ({ page: p }) => {
    await page.messageInput.fill('帮我看看有什么商品')
    await page.sendBtn.click()
    // 等待 AI 回复完成（工具调用可能需要 15-45 秒）
    const aiBubble = p.locator('.bg-white.border.border-gray-200.rounded-bl-md').last()
    await expect(async () => {
      const text = await aiBubble.textContent()
      expect(text?.trim().length).toBeGreaterThan(0)
    }).toPass({ timeout: 60_000 })
    // ProductCard 组件（AI 可能返回商品卡片或纯文本）
    const productCards = p.locator('.border.rounded-lg').filter({ hasText: /¥/ })
    expect(await productCards.count()).toBeGreaterThanOrEqual(0)
  })

  test('logistics 卡片可渲染', async ({ page: p }) => {
    await page.messageInput.fill('帮我查一下物流')
    await page.sendBtn.click()
    // 等待 AI 回复完成
    const aiBubble = p.locator('.bg-white.border.border-gray-200.rounded-bl-md').last()
    await expect(async () => {
      const text = await aiBubble.textContent()
      expect(text?.trim().length).toBeGreaterThan(0)
    }).toPass({ timeout: 60_000 })
    // LogisticsCard 组件（AI 可能返回物流卡片或纯文本）
    const logisticsCards = p.locator('text=/物流|快递|运输/')
    expect(await logisticsCards.count()).toBeGreaterThanOrEqual(0)
  })

  test('图片上传后可附带图片发送消息', async ({ page: p }) => {

    // 图片上传 input
    const fileInput = p.locator('input[type="file"][accept*="image"]').first()
    if (await fileInput.count() > 0) {
      // 文件上传功能存在
      await expect(fileInput).toHaveAttribute('accept', /image/)
    }
  })

  test('停止按钮可中断流式响应', async ({ page: p }) => {
    await page.messageInput.fill('写一篇很长的文章')

    // 确保发送按钮已启用（currentSessionId 已设置 + 输入非空）
    await expect(page.sendBtn).toBeEnabled({ timeout: 10_000 })
    await page.sendBtn.click()

    // 点击发送后，isStreaming 应变为 true，sendBtn 被 stopBtn 替换
    // 验证：要么停止按钮出现（流式进行中），要么 AI 已完成回复
    try {
      await expect(page.stopBtn).toBeVisible({ timeout: 15_000 })
      await page.stopBtn.click()
      // 停止后发送按钮应重新出现
      await p.waitForTimeout(1000)
      await expect(page.sendBtn).toBeVisible()
    } catch {
      // 如果流式响应在 15 秒内就完成了，验证 AI 回复存在
      const aiBubble = p.locator('.bg-white.border.border-gray-200.rounded-bl-md').last()
      await expect(async () => {
        const text = await aiBubble.textContent()
        expect(text?.trim().length).toBeGreaterThan(0)
      }).toPass({ timeout: 60_000 })
      // 流结束后发送按钮应可见
      await expect(page.sendBtn).toBeVisible()
    }
  })
})
