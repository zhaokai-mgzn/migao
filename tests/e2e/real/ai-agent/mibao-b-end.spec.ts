import { test, expect } from '@playwright/test'
import { ChatPage } from '../../pages/chat/chat.page'
import { SSEHelper } from '../../helpers/sse.helper'

/**
 * 米宝 B 端工具调用 E2E
 *
 * 每个测试：发送自然语言 → SSEHelper 捕获事件 → 验证工具调用 + 响应内容
 * 使用 SSEHelper 事件驱动等待替代 waitForTimeout 固定延时，更快更可靠。
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

/** 发送消息，用 SSEHelper 等待流结束（事件驱动，不靠固定延时） */
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

test.describe('米宝 B 端工具调用', () => {
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

  // ── order_manage ──

  test('order_manage - 查询订单列表', async () => {
    await sendAndWait(chat, sse, '帮我看看最近的订单')
    await expectAiReply(chat)
    expect(await sse.hasCard('order')).toBeTruthy()
  })

  test('order_manage - 创建订单', async () => {
    await sendAndWait(chat, sse, '帮我创建一个新订单，客户名张三，商品是遮光窗帘')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('order_manage')).toBeTruthy()
  })

  test('order_manage - 修改订单状态', async () => {
    await sendAndWait(chat, sse, '把最近的待确认订单确认一下')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('order_manage')).toBeTruthy()
  })

  // ── product_manage ──

  test('product_manage - 查询商品', async () => {
    await sendAndWait(chat, sse, '帮我查一下有哪些商品')
    await expectAiReply(chat)
    expect(await sse.hasCard('product_list')).toBeTruthy()
  })

  test('product_manage - 创建商品', async () => {
    await sendAndWait(chat, sse, '帮我上架一个新商品，名称：蓝色遮光窗帘，价格299元')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('product_manage')).toBeTruthy()
  })

  test('product_manage - 修改商品信息', async () => {
    await sendAndWait(chat, sse, '把第一个商品的价格改成199元')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('product_manage')).toBeTruthy()
  })

  // ── inventory_manage ──

  test('inventory_manage - 查询库存', async () => {
    await sendAndWait(chat, sse, '帮我看看商品库存情况')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('inventory_manage')).toBeTruthy()
  })

  test('inventory_manage - 更新库存', async () => {
    await sendAndWait(chat, sse, '把遮光窗帘的库存设置为100')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('inventory_manage')).toBeTruthy()
  })

  // ── customer_manage ──

  test('customer_manage - 查询客户', async () => {
    await sendAndWait(chat, sse, '帮我查一下客户列表')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('customer_manage')).toBeTruthy()
  })

  test('customer_manage - 更新客户信息', async () => {
    await sendAndWait(chat, sse, '给客户张美丽添加一个备注：VIP客户')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('customer_manage')).toBeTruthy()
  })

  // ── employee_manage ──

  test('employee_manage - 查询员工', async () => {
    await sendAndWait(chat, sse, '帮我看看有哪些员工')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('employee_manage')).toBeTruthy()
  })

  test('employee_manage - 创建员工', async () => {
    await sendAndWait(chat, sse, '帮我新建一个员工账号，用户名 lixiaoming，姓名李小明')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('employee_manage')).toBeTruthy()
  })

  // ── role_manage ──

  test('role_manage - 查询角色', async () => {
    await sendAndWait(chat, sse, '帮我看看系统有哪些角色')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('role_manage')).toBeTruthy()
  })

  // ── dashboard_stats ──

  test('dashboard_stats - 查询统计数据', async () => {
    await sendAndWait(chat, sse, '帮我看看今天的销售数据')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('dashboard_stats')).toBeTruthy()
  })

  // ── after_sales_manage ──

  test('after_sales_manage - 查询售后工单', async () => {
    await sendAndWait(chat, sse, '帮我看看有没有待处理的售后工单')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('after_sales_manage')).toBeTruthy()
  })

  test('after_sales_manage - 处理售后', async () => {
    await sendAndWait(chat, sse, '帮我接受处理最新的售后工单')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('after_sales_manage')).toBeTruthy()
  })

  // ── notification_manage ──

  test('notification_manage - 查询通知', async () => {
    await sendAndWait(chat, sse, '帮我看看有什么未读通知')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('notification_manage')).toBeTruthy()
  })

  // ── settings_manage ──

  test('settings_manage - 查询/修改设置', async () => {
    await sendAndWait(chat, sse, '帮我看一下当前的系统设置')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('settings_manage')).toBeTruthy()
  })

  // ── session_manage ──

  test('session_manage - 查询会话', async () => {
    await sendAndWait(chat, sse, '帮我看看当前有多少活跃会话')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('session_manage')).toBeTruthy()
  })

  // ── quick_reply_manage ──

  test('quick_reply_manage - 查询快捷回复', async () => {
    await sendAndWait(chat, sse, '帮我看看有哪些快捷回复')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('quick_reply_manage')).toBeTruthy()
  })

  // ── category_manage ──

  test('category_manage - 查询/管理分类', async () => {
    await sendAndWait(chat, sse, '帮我看看商品分类有哪些')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('category_manage')).toBeTruthy()
  })

  // ── processing_item_query ──

  test('processing_item_query - 查询加工项', async () => {
    await sendAndWait(chat, sse, '帮我看看有哪些加工方式')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('processing_item_query')).toBeTruthy()
  })

  // ── processing_item_manage ──

  test('processing_item_manage - 管理加工项', async () => {
    await sendAndWait(chat, sse, '帮我添加一个加工方式：打孔加工，价格5元')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('processing_item_manage')).toBeTruthy()
  })

  // ── knowledge_manage ──

  test('knowledge_manage - 查询知识库', async () => {
    await sendAndWait(chat, sse, '帮我看看知识库里有什么文档')
    await expectAiReply(chat)
    expect(await sse.hasToolCall('knowledge_manage')).toBeTruthy()
  })
})
