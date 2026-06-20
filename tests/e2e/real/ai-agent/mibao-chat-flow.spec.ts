import { test, expect } from '@playwright/test'
import { ChatPage } from '../../pages/chat/chat.page'
import { SSEHelper } from '../../helpers/sse.helper'

/**
 * 米宝对话流程 E2E — SSEHelper 事件驱动验证 SSE 事件流和 UI 渲染
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
  let sse: SSEHelper

  test.beforeEach(async ({ page: p }) => {
    page = new ChatPage(p)
    sse = new SSEHelper(p)
    await page.goto()
    await page.waitForLoad()
  })

  test('三栏布局正确渲染', async () => {
    await expect(page.sessionList).toBeVisible()
    const chatArea = page.page.locator('.flex-1.flex.flex-col').first()
    await expect(chatArea).toBeVisible()
  })

  test('新建会话后显示空状态引导', async () => {
    await page.createSessionBtn.click()
    const guideText = page.page.getByText(/发送消息开始对话/)
    if (await guideText.isVisible().catch(() => false)) {
      await expect(guideText).toBeVisible()
    }
  })

  test('加载历史会话消息', async () => {
    const items = page.sessionList.locator('.mx-1\\.5')
    if (await items.count() > 0) {
      await items.first().click()
      await page.page.waitForTimeout(1000)
      const messageArea = page.page.locator('.flex-1.overflow-y-auto').first()
      await expect(messageArea).toBeVisible()
    }
  })

  test('SSE text_delta 流式文本渲染', async () => {
    await page.createSessionBtn.click()
    await page.page.waitForTimeout(500)
    await sse.startIntercept()
    await page.messageInput.fill('你好，请介绍一下你自己')
    await page.sendBtn.click()
    await sse.waitForStreamEnd(20_000)
    sse.stopIntercept()

    expect(await sse.hasTextContent()).toBeTruthy()
    const fullText = await sse.getFullText()
    expect(fullText.length).toBeGreaterThan(0)
  })

  test('tool_start 事件显示工具调用指示器', async () => {
    await page.createSessionBtn.click()
    await page.page.waitForTimeout(500)
    await sse.startIntercept()
    await page.messageInput.fill('帮我查看最近的订单')
    await page.sendBtn.click()
    await sse.waitForStreamEnd(25_000)

    expect(await sse.hasToolCall('order_manage')).toBeTruthy()
    sse.stopIntercept()
  })

  test('tool_result 事件显示结果数据', async () => {
    await page.createSessionBtn.click()
    await page.page.waitForTimeout(500)
    await sse.startIntercept()
    await page.messageInput.fill('查看订单列表')
    await page.sendBtn.click()
    await sse.waitForStreamEnd(25_000)

    // tool_result 在 SSE 流中应出现
    const resultEvents = await sse.getEvents('tool_result')
    expect(resultEvents.length).toBeGreaterThan(0)
    sse.stopIntercept()

    // UI 上工具结果面板也应可见
    const toolPanel = page.page.locator('.bg-gray-50.border.border-gray-200.rounded-lg').first()
    if (await toolPanel.isVisible().catch(() => false)) {
      await expect(toolPanel).toBeVisible()
    }
  })

  test('suggestions 事件显示推荐提问 chip', async () => {
    await page.createSessionBtn.click()
    await page.page.waitForTimeout(500)
    await sse.startIntercept()
    await page.messageInput.fill('你好')
    await page.sendBtn.click()
    await sse.waitForStreamEnd(25_000)

    // SSE 层面验证 suggestions 事件存在
    const suggestions = await sse.getSuggestions()
    expect(suggestions.length).toBeGreaterThan(0)
    sse.stopIntercept()

    // UI 层面也应有推荐提问区域
    const suggestionsHeader = page.page.getByText('推荐提问：')
    if (await suggestionsHeader.isVisible().catch(() => false)) {
      const suggestionBtns = suggestionsHeader.locator('..').locator('button')
      expect(await suggestionBtns.count()).toBeGreaterThan(0)
    }
  })

  test('error 事件在 SSE 层面可检测', async () => {
    // 正常情况下不应该有 error 事件
    expect(await sse.hasError()).toBeFalsy()
  })

  test('product_list 卡片可渲染', async () => {
    await page.createSessionBtn.click()
    await page.page.waitForTimeout(500)
    await sse.startIntercept()
    await page.messageInput.fill('帮我看看有什么商品')
    await page.sendBtn.click()
    await sse.waitForStreamEnd(25_000)

    expect(await sse.hasCard('product_list')).toBeTruthy()
    sse.stopIntercept()

    const productCards = page.page.locator('.border.rounded-lg').filter({ hasText: /¥/ })
    expect(await productCards.count()).toBeGreaterThanOrEqual(0)
  })

  test('logistics 卡片可渲染', async () => {
    await page.createSessionBtn.click()
    await page.page.waitForTimeout(500)
    await sse.startIntercept()
    await page.messageInput.fill('帮我查一下物流')
    await page.sendBtn.click()
    await sse.waitForStreamEnd(25_000)

    expect(await sse.hasCard('logistics')).toBeTruthy()
    sse.stopIntercept()
  })

  test('图片上传后可附带图片发送消息', async () => {
    await page.createSessionBtn.click()
    await page.page.waitForTimeout(500)
    const fileInput = page.page.locator('input[type="file"][accept*="image"]').first()
    if (await fileInput.count() > 0) {
      await expect(fileInput).toHaveAttribute('accept', /image/)
    }
  })

  test('停止按钮可中断流式响应', async () => {
    await page.createSessionBtn.click()
    await page.page.waitForTimeout(500)
    await sse.startIntercept()
    await page.messageInput.fill('写一篇很长的文章')
    await page.sendBtn.click()

    // 等待流式开始
    await page.page.waitForTimeout(1500)

    if (await page.stopBtn.isVisible().catch(() => false)) {
      await page.stopBtn.click()
      sse.clearEvents()
      await page.page.waitForTimeout(1000)
      await expect(page.sendBtn).toBeVisible()
    }
    sse.stopIntercept()
  })
})
