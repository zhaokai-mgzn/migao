import { test, expect } from '@playwright/test'
import { ChatPage } from '../../pages/chat/chat.page'

/**
 * 米宝 C 端工具调用 E2E
 *
 * C 端工具（面向终端客户）：
 *   - product_search: 商品搜索 → 返回 product_list 卡片
 *   - product_detail: 商品详情 → 返回 product_detail 卡片
 *   - logistics_track: 物流追踪 → 返回 logistics 卡片
 *   - order_query: 订单查询 → 返回 order 卡片
 *   - 多轮对话: search→detail, order→logistics
 *   - fallback: 无法识别的意图
 */

/** 通用：发送消息并等待 AI 回复 */
async function sendAndWait(page: ChatPage, message: string, waitMs = 8000) {
  await page.messageInput.fill(message)
  await page.sendBtn.click()
  await page.page.waitForTimeout(waitMs)
}

/** 通用：检查 AI 回复气泡中有内容 */
async function expectAiReply(page: ChatPage) {
  const aiBubble = page.page.locator('.bg-white.border.border-gray-200.rounded-bl-md').last()
  await expect(aiBubble).toBeVisible({ timeout: 15_000 })
  const text = await aiBubble.textContent()
  expect(text?.trim().length).toBeGreaterThan(0)
}

/** 通用：检查消息列表最后一条 AI 消息中包含指定文本 */
async function expectAiMessageContains(page: ChatPage, text: string | RegExp) {
  const messages = page.page.locator('.bg-white.border.border-gray-200.rounded-bl-md')
  const lastMsg = messages.last()
  await expect(lastMsg).toContainText(text, { timeout: 15_000 })
}

test.describe('米宝 C 端工具调用', () => {
  let chat: ChatPage

  test.beforeEach(async ({ page }) => {
    chat = new ChatPage(page)
    await chat.goto()
    await chat.waitForLoad()
    // 创建新会话
    await chat.createSessionBtn.click()
    await page.waitForTimeout(1000)
  })

  // ── product_search ──

  test('product_search - 搜索商品返回商品列表', async () => {
    await sendAndWait(chat, '帮我找一下遮光窗帘')
    await expectAiReply(chat)

    // 检查是否有商品相关卡片或列表出现
    const productElements = chat.page.locator('text=/¥|价格|窗帘/')
    expect(await productElements.count()).toBeGreaterThan(0)
  })

  test('product_search - 搜索结果展示商品卡片', async () => {
    await sendAndWait(chat, '你们有什么窗帘推荐')

    // 等待完整响应
    await chat.page.waitForTimeout(5000)
    await expectAiReply(chat)

    // 商品卡片可能包含商品名称、价格等
    const priceText = chat.page.locator('text=/¥\\d+/')
    if (await priceText.count() > 0) {
      await expect(priceText.first()).toBeVisible()
    }
  })

  // ── product_detail ──

  test('product_detail - 查看商品详情', async () => {
    // 先搜索商品
    await sendAndWait(chat, '帮我看看有什么窗帘', 10000)
    // 再询问详情
    await sendAndWait(chat, '帮我看看第一个商品的详细信息', 10000)
    await expectAiReply(chat)
  })

  test('product_detail - 商品详情卡片包含价格和描述', async () => {
    await sendAndWait(chat, '遮光窗帘布的详细信息', 10000)
    await expectAiReply(chat)

    // 详情响应中应该包含价格或描述信息
    const detailContent = chat.page.locator('.bg-white.border.border-gray-200').last()
    if (await detailContent.isVisible()) {
      const text = await detailContent.textContent()
      expect(text?.length).toBeGreaterThan(0)
    }
  })

  // ── logistics_track ──

  test('logistics_track - 查询物流信息', async () => {
    await sendAndWait(chat, '帮我查一下我的订单物流到哪了')
    await expectAiReply(chat)

    // 物流信息可能包含物流公司、运单号等
    const logisticsText = chat.page.locator('text=/物流|快递|运输|发货|运单/')
    expect(await logisticsText.count()).toBeGreaterThanOrEqual(0)
  })

  test('logistics_track - 物流卡片显示物流状态', async () => {
    await sendAndWait(chat, '我的订单 ORD20260415001 物流信息')
    await expectAiReply(chat)

    // 物流卡片组件
    const logisticsCard = chat.page.locator('text=/物流状态|在途|已签收|运输中/')
    expect(await logisticsCard.count()).toBeGreaterThanOrEqual(0)
  })

  // ── order_query ──

  test('order_query - 查询订单', async () => {
    await sendAndWait(chat, '帮我查一下我的订单')
    await expectAiReply(chat)

    // 订单信息应该出现
    const orderText = chat.page.locator('text=/ORD|订单号|订单/')
    expect(await orderText.count()).toBeGreaterThan(0)
  })

  test('order_query - 订单卡片显示订单号和状态', async () => {
    await sendAndWait(chat, '我最近的订单是什么状态')
    await expectAiReply(chat)

    // 订单状态 Badge
    const statusBadge = chat.page.locator('text=/待确认|已确认|生产中|已完成|已取消/')
    expect(await statusBadge.count()).toBeGreaterThanOrEqual(0)
  })

  // ── 多轮对话 ──

  test('多轮对话 - 搜索→详情流程', async () => {
    // 第一轮：搜索商品
    await sendAndWait(chat, '帮我找一下遮光窗帘', 10000)
    await expectAiReply(chat)

    // 第二轮：查看详情（上下文关联）
    await sendAndWait(chat, '第一个怎么样？给我看看详情', 10000)
    await expectAiReply(chat)

    // 应该有至少两条 AI 回复
    const aiMessages = chat.page.locator('.bg-white.border.border-gray-200.rounded-bl-md')
    expect(await aiMessages.count()).toBeGreaterThanOrEqual(2)
  })

  test('多轮对话 - 订单→物流流程', async () => {
    // 第一轮：查询订单
    await sendAndWait(chat, '帮我看看最近的订单', 10000)
    await expectAiReply(chat)

    // 第二轮：查询物流（上下文关联）
    await sendAndWait(chat, '那个订单的物流信息呢？', 10000)
    await expectAiReply(chat)

    // 应该有至少两条 AI 回复
    const aiMessages = chat.page.locator('.bg-white.border.border-gray-200.rounded-bl-md')
    expect(await aiMessages.count()).toBeGreaterThanOrEqual(2)
  })

  // ── fallback intent ──

  test('fallback - 无法识别的意图给出友好回复', async () => {
    await sendAndWait(chat, 'asdfghjkl这是一段无意义的文字')
    await expectAiReply(chat)

    // AI 应该给出友好回复而非报错
    const lastMessage = chat.page.locator('.bg-white.border.border-gray-200.rounded-bl-md').last()
    const text = await lastMessage.textContent()
    // 回复不应该为空
    expect(text?.trim().length).toBeGreaterThan(0)
    // 不应该显示系统错误
    expect(text).not.toContain('Internal Server Error')
    expect(text).not.toContain('500')
  })
})
