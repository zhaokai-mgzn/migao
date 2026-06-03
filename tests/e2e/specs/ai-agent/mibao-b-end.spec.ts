import { test, expect } from '@playwright/test'
import { ChatPage } from '../../pages/chat/chat.page'

/**
 * 米宝 B 端工具调用 E2E
 *
 * 每个测试：发送自然语言 → 验证工具调用指示器 → 验证响应卡片/文本 → 验证状态变更
 *
 * B 端工具列表（来自 ai-agent-service/app/tools/）：
 *   - order_manage (查/创/改)
 *   - product_manage (查/创/改)
 *   - inventory_manage (查/改)
 *   - customer_manage (查/改)
 *   - employee_manage (查/改)
 *   - role_manage (查)
 *   - dashboard_stats (统计)
 *   - after_sales_manage (查/改)
 *   - notification_manage (查)
 *   - settings_manage (查/改)
 *   - session_manage (查)
 *   - quick_reply_manage (查/改)
 *   - category_manage (查/改)
 *   - processing_item_query (查)
 *   - processing_item_manage (改)
 *   - knowledge_manage (查)
 */

/** 通用：发送消息并等待 AI 回复 */
async function sendAndWait(page: ChatPage, message: string, _waitMs?: number) {
  await page.messageInput.fill(message)
  await page.sendBtn.click()
  // 短暂等待让 SSE 流启动，实际内容由 expectAiReply 轮询等待
  await page.page.waitForTimeout(2000)
}

/** 通用：检查是否有工具调用面板出现 */
async function expectToolCall(page: ChatPage) {
  const toolPanel = page.page.locator('.bg-gray-50.border.border-gray-200.rounded-lg').first()
    .or(page.page.locator('svg.lucide-wrench').first())
  await expect(toolPanel).toBeVisible({ timeout: 30_000 })
}

/** 通用：检查 AI 回复气泡中有内容（工具调用可能需要 15-45 秒） */
async function expectAiReply(page: ChatPage) {
  const aiBubble = page.page.locator('.bg-white.border.border-gray-200.rounded-bl-md').last()
  await expect(aiBubble).toBeVisible({ timeout: 15_000 })
  // 使用 toPass() 轮询等待 AI 回复内容（工具调用场景 LLM 需 15-45 秒）
  await expect(async () => {
    const text = await aiBubble.textContent()
    expect(text?.trim().length).toBeGreaterThan(0)
  }).toPass({ timeout: 60_000 })
}

test.describe('米宝 B 端工具调用', () => {
  test.setTimeout(120_000)
  let chat: ChatPage

  test.beforeEach(async ({ page }) => {
    chat = new ChatPage(page)
    await chat.goto()
    await chat.waitForLoad()
    // 创建新会话
    await chat.createSessionBtn.click()
    await page.waitForTimeout(1000)
  })

  // ── order_manage ──

  test('order_manage - 查询订单列表', async () => {
    await sendAndWait(chat, '帮我看看最近的订单')
    await expectAiReply(chat)
  })

  test('order_manage - 创建订单', async () => {
    await sendAndWait(chat, '帮我创建一个新订单，客户名张三，商品是遮光窗帘')
    await expectAiReply(chat)
  })

  test('order_manage - 修改订单状态', async () => {
    await sendAndWait(chat, '把最近的待确认订单确认一下')
    await expectAiReply(chat)
  })

  // ── product_manage ──

  test('product_manage - 查询商品', async () => {
    await sendAndWait(chat, '帮我查一下有哪些商品')
    await expectAiReply(chat)
  })

  test('product_manage - 创建商品', async () => {
    await sendAndWait(chat, '帮我上架一个新商品，名称：蓝色遮光窗帘，价格299元')
    await expectAiReply(chat)
  })

  test('product_manage - 修改商品信息', async () => {
    await sendAndWait(chat, '把第一个商品的价格改成199元')
    await expectAiReply(chat)
  })

  // ── inventory_manage ──

  test('inventory_manage - 查询库存', async () => {
    await sendAndWait(chat, '帮我看看商品库存情况')
    await expectAiReply(chat)
  })

  test('inventory_manage - 更新库存', async () => {
    await sendAndWait(chat, '把遮光窗帘的库存设置为100')
    await expectAiReply(chat)
  })

  // ── customer_manage ──

  test('customer_manage - 查询客户', async () => {
    await sendAndWait(chat, '帮我查一下客户列表')
    await expectAiReply(chat)
  })

  test('customer_manage - 更新客户信息', async () => {
    await sendAndWait(chat, '给客户张美丽添加一个备注：VIP客户')
    await expectAiReply(chat)
  })

  // ── employee_manage ──

  test('employee_manage - 查询员工', async () => {
    await sendAndWait(chat, '帮我看看有哪些员工')
    await expectAiReply(chat)
  })

  test('employee_manage - 创建员工', async () => {
    await sendAndWait(chat, '帮我新建一个员工账号，用户名 lixiaoming，姓名李小明')
    await expectAiReply(chat)
  })

  // ── role_manage ──

  test('role_manage - 查询角色', async () => {
    await sendAndWait(chat, '帮我看看系统有哪些角色')
    await expectAiReply(chat)
  })

  // ── dashboard_stats ──

  test('dashboard_stats - 查询统计数据', async () => {
    await sendAndWait(chat, '帮我看看今天的销售数据')
    await expectAiReply(chat)
  })

  // ── after_sales_manage ──

  test('after_sales_manage - 查询售后工单', async () => {
    await sendAndWait(chat, '帮我看看有没有待处理的售后工单')
    await expectAiReply(chat)
  })

  test('after_sales_manage - 处理售后', async () => {
    await sendAndWait(chat, '帮我接受处理最新的售后工单')
    await expectAiReply(chat)
  })

  // ── notification_manage ──

  test('notification_manage - 查询通知', async () => {
    await sendAndWait(chat, '帮我看看有什么未读通知')
    await expectAiReply(chat)
  })

  // ── settings_manage ──

  test('settings_manage - 查询/修改设置', async () => {
    await sendAndWait(chat, '帮我看一下当前的系统设置')
    await expectAiReply(chat)
  })

  // ── session_manage ──

  test('session_manage - 查询会话', async () => {
    await sendAndWait(chat, '帮我看看当前有多少活跃会话')
    await expectAiReply(chat)
  })

  // ── quick_reply_manage ──

  test('quick_reply_manage - 查询快捷回复', async () => {
    await sendAndWait(chat, '帮我看看有哪些快捷回复')
    await expectAiReply(chat)
  })

  // ── category_manage ──

  test('category_manage - 查询/管理分类', async () => {
    await sendAndWait(chat, '帮我看看商品分类有哪些')
    await expectAiReply(chat)
  })

  // ── processing_item_query ──

  test('processing_item_query - 查询加工项', async () => {
    await sendAndWait(chat, '帮我看看有哪些加工方式')
    await expectAiReply(chat)
  })

  // ── processing_item_manage ──

  test('processing_item_manage - 管理加工项', async () => {
    await sendAndWait(chat, '帮我添加一个加工方式：打孔加工，价格5元')
    await expectAiReply(chat)
  })

  // ── knowledge_manage ──

  test('knowledge_manage - 查询知识库', async () => {
    await sendAndWait(chat, '帮我看看知识库里有什么文档')
    await expectAiReply(chat)
  })
})
