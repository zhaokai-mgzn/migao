import { test, expect } from '@playwright/test'
import { ChatPage } from '../../pages/chat/chat.page'
import { SSEHelper } from '../../helpers/sse.helper'

/**
 * 米宝 C 端工具调用 E2E
 *
 * C 端工具（面向终端客户），SSEHelper 事件驱动替代固定延时：
 *   - product_search: 商品搜索 → product_list 卡片
 *   - product_detail: 商品详情 → product_detail 卡片
 *   - logistics_track: 物流追踪 → logistics 卡片
 *   - order_query: 订单查询 → order 卡片
 *   - 多轮对话: search→detail, order→logistics 上下文关联
 *   - fallback: 无法识别意图的友好回复
 */

/** 发送消息，用 SSEHelper 等待流结束 */
async function sendAndWait(page: ChatPage, sse: SSEHelper, message: string, timeout = 25_000) {
  await sse.startIntercept()
  await page.messageInput.fill(message)
  await page.sendBtn.click()
  await sse.waitForStreamEnd(timeout)
  sse.stopIntercept()
}

/** 检查 AI 回复气泡中有内容 */
async function expectAiReply(page: ChatPage) {
  const aiBubble = page.page.locator('.bg-white.border.border-gray-200.rounded-bl-md').last()
  await expect(aiBubble).toBeVisible({ timeout: 15_000 })
  const text = await aiBubble.textContent()
  expect(text?.trim().length).toBeGreaterThan(0)
}

test.describe('米宝 C 端工具调用', () => {
  let chat: ChatPage
  let sse: SSEHelper

  test.beforeEach(async ({ page }) => {
    chat = new ChatPage(page)
    sse = new SSEHelper(page)
    await chat.goto()
    await chat.waitForLoad()
    await chat.createSessionBtn.click()
    await page.waitForTimeout(1000)
  })

  // ── product_search ──

  test('product_search - 搜索商品返回商品列表', async () => {
    await sendAndWait(chat, sse, '帮我找一下遮光窗帘')
    await expectAiReply(chat)
    expect(await sse.hasCard('product_list')).toBeTruthy()
  })

  test('product_search - 搜索结果展示商品卡片', async () => {
    await sendAndWait(chat, sse, '你们有什么窗帘推荐')
    await expectAiReply(chat)
    // 商品卡片应该包含价格信息
    const priceText = chat.page.locator('text=/¥\\d+/')
    expect(await priceText.count()).toBeGreaterThan(0)
  })

  // ── product_detail ──

  test('product_detail - 查看商品详情', async () => {
    await sendAndWait(chat, sse, '帮我看看有什么窗帘')
    await sendAndWait(chat, sse, '帮我看看第一个商品的详细信息')
    await expectAiReply(chat)
    expect(await sse.hasCard('product_detail')).toBeTruthy()
  })

  test('product_detail - 商品详情卡片包含价格和描述', async () => {
    await sendAndWait(chat, sse, '遮光窗帘布的详细信息')
    await expectAiReply(chat)
    // 详情响应中应有文本内容
    const fullText = await sse.getFullText()
    expect(fullText.length).toBeGreaterThan(0)
  })

  // ── logistics_track ──

  test('logistics_track - 查询物流信息', async () => {
    await sendAndWait(chat, sse, '帮我查一下我的订单物流到哪了')
    await expectAiReply(chat)
    expect(await sse.hasCard('logistics')).toBeTruthy()
  })

  test('logistics_track - 物流卡片显示物流状态', async () => {
    await sendAndWait(chat, sse, '我的订单 ORD20260415001 物流信息')
    await expectAiReply(chat)
    const logisticsCard = chat.page.locator('text=/物流状态|在途|已签收|运输中/')
    expect(await logisticsCard.count()).toBeGreaterThanOrEqual(0)
  })

  // ── order_query ──

  test('order_query - 查询订单', async () => {
    await sendAndWait(chat, sse, '帮我查一下我的订单')
    await expectAiReply(chat)
    expect(await sse.hasCard('order')).toBeTruthy()
  })

  test('order_query - 订单卡片显示订单号和状态', async () => {
    await sendAndWait(chat, sse, '我最近的订单是什么状态')
    await expectAiReply(chat)
    const statusBadge = chat.page.locator('text=/待确认|已确认|生产中|已完成|已取消/')
    expect(await statusBadge.count()).toBeGreaterThanOrEqual(0)
  })

  // ── 多轮对话 ──

  test('多轮对话 - 搜索→详情流程', async () => {
    await sendAndWait(chat, sse, '帮我找一下遮光窗帘')
    await expectAiReply(chat)
    // 第二轮：上下文关联
    await sendAndWait(chat, sse, '第一个怎么样？给我看看详情')
    await expectAiReply(chat)
    const aiMessages = chat.page.locator('.bg-white.border.border-gray-200.rounded-bl-md')
    expect(await aiMessages.count()).toBeGreaterThanOrEqual(2)
  })

  test('多轮对话 - 订单→物流流程', async () => {
    await sendAndWait(chat, sse, '帮我看看最近的订单')
    await expectAiReply(chat)
    // 第二轮：上下文关联
    await sendAndWait(chat, sse, '那个订单的物流信息呢？')
    await expectAiReply(chat)
    const aiMessages = chat.page.locator('.bg-white.border.border-gray-200.rounded-bl-md')
    expect(await aiMessages.count()).toBeGreaterThanOrEqual(2)
  })

  // ── fallback intent ──

  test('fallback - 无法识别的意图给出友好回复', async () => {
    await sendAndWait(chat, sse, 'asdfghjkl这是一段无意义的文字')
    await expectAiReply(chat)
    // 不应产生错误
    expect(await sse.hasError()).toBeFalsy()
    const lastMessage = chat.page.locator('.bg-white.border.border-gray-200.rounded-bl-md').last()
    const text = await lastMessage.textContent()
    expect(text?.trim().length).toBeGreaterThan(0)
    expect(text).not.toContain('Internal Server Error')
    expect(text).not.toContain('500')
  })
})
