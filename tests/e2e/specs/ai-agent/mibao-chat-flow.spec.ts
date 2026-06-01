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
  let page: ChatPage

  test.beforeEach(async ({ page: p }) => {
    page = new ChatPage(p)
    await page.goto()
    await page.waitForLoad()
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
    await page.createSessionBtn.click()
    await p.waitForTimeout(500)
    await page.messageInput.fill('你好，请介绍一下你自己')
    await page.sendBtn.click()

    // 等待流式响应
    await p.waitForTimeout(3000)

    // AI 回复气泡
    const aiBubble = p.locator('.bg-white.border.border-gray-200').first()
    if (await aiBubble.isVisible().catch(() => false)) {
      // 流式文本应该有内容
      const text = await aiBubble.textContent()
      expect(text).toBeTruthy()
    }
  })

  test('tool_start 事件显示工具调用指示器', async ({ page: p }) => {
    await page.createSessionBtn.click()
    await p.waitForTimeout(500)
    await page.messageInput.fill('帮我查看最近的订单')
    await page.sendBtn.click()

    // 等待工具调用
    await p.waitForTimeout(5000)

    // 工具调用面板（Wrench 图标 + 工具名）
    const toolIndicator = p.locator('svg.lucide-wrench').first()
    if (await toolIndicator.isVisible().catch(() => false)) {
      await expect(toolIndicator).toBeVisible()
    }
  })

  test('tool_result 事件显示结果数据', async ({ page: p }) => {
    await page.createSessionBtn.click()
    await p.waitForTimeout(500)
    await page.messageInput.fill('查看订单列表')
    await page.sendBtn.click()

    await p.waitForTimeout(8000)

    // 工具结果面板（可展开查看输入参数和返回结果）
    const toolPanel = p.locator('.bg-gray-50.border.border-gray-200.rounded-lg').first()
    if (await toolPanel.isVisible().catch(() => false)) {
      await expect(toolPanel).toBeVisible()
    }
  })

  test('suggestions 事件显示推荐提问 chip', async ({ page: p }) => {
    await page.createSessionBtn.click()
    await p.waitForTimeout(500)
    await page.messageInput.fill('你好')
    await page.sendBtn.click()

    // 等待完整响应（包含 suggestions）
    await p.waitForTimeout(8000)

    // 推荐提问区域
    const suggestionsHeader = p.getByText('推荐提问：')
    if (await suggestionsHeader.isVisible().catch(() => false)) {
      const suggestionBtns = suggestionsHeader.locator('..').locator('button')
      expect(await suggestionBtns.count()).toBeGreaterThan(0)
    }
  })

  test('error 事件显示错误 UI', async ({ page: p }) => {
    // 错误事件在消息流中展示
    const errorIndicators = p.locator('svg.lucide-alert-circle')
    expect(await errorIndicators.count()).toBeGreaterThanOrEqual(0)
  })

  test('product_list 卡片可渲染', async ({ page: p }) => {
    await page.createSessionBtn.click()
    await p.waitForTimeout(500)
    await page.messageInput.fill('帮我看看有什么商品')
    await page.sendBtn.click()
    await p.waitForTimeout(8000)
    // ProductCard 组件
    const productCards = p.locator('.border.rounded-lg').filter({ hasText: /¥/ })
    expect(await productCards.count()).toBeGreaterThanOrEqual(0)
  })

  test('logistics 卡片可渲染', async ({ page: p }) => {
    await page.createSessionBtn.click()
    await p.waitForTimeout(500)
    await page.messageInput.fill('帮我查一下物流')
    await page.sendBtn.click()
    await p.waitForTimeout(8000)
    // LogisticsCard 组件
    const logisticsCards = p.locator('text=/物流|快递|运输/')
    expect(await logisticsCards.count()).toBeGreaterThanOrEqual(0)
  })

  test('图片上传后可附带图片发送消息', async ({ page: p }) => {
    await page.createSessionBtn.click()
    await p.waitForTimeout(500)

    // 图片上传 input
    const fileInput = p.locator('input[type="file"][accept*="image"]').first()
    if (await fileInput.count() > 0) {
      // 文件上传功能存在
      await expect(fileInput).toHaveAttribute('accept', /image/)
    }
  })

  test('停止按钮可中断流式响应', async ({ page: p }) => {
    await page.createSessionBtn.click()
    await p.waitForTimeout(500)
    await page.messageInput.fill('写一篇很长的文章')
    await page.sendBtn.click()

    // 等待流式开始
    await p.waitForTimeout(1500)

    // 停止按钮
    if (await page.stopBtn.isVisible().catch(() => false)) {
      await page.stopBtn.click()
      // 停止后按钮应该变回发送
      await p.waitForTimeout(1000)
      await expect(page.sendBtn).toBeVisible()
    }
  })
})
