// case_ids: CH-001, CH-005, UI-007
/**
 * 小布对话页 E2E 验收
 * 覆盖：入口渲染（品牌导航）→ 会话就绪 → 快捷操作发消息（真实后端 SSE）→ 新对话 → 键盘模式输入发消息
 * 依赖真实后端（app.migaozn.com 测试环境）；LLM 回复较慢，等待窗口 120s。
 */
const {
  capture,
  sleep,
  waitForPageReady,
  waitForElement,
  waitForText,
  waitForBubble,
  waitForBubbleText,
  waitForStreamEnd,
  lastBubbleText,
  makeReporter,
} = require('../lib/harness')

const SCENARIO = 'chat'
const ENTRY_PAGE = 'pages/chat/index/index'

async function run(mp) {
  const rep = makeReporter('对话页验收')
  const shot = (name) => rep.screenshot(SCENARIO, name)

  // ── 1. 入口页面 ──
  const page = await waitForPageReady(mp)
  rep.step('入口页面为对话页', !!page && page.path === ENTRY_PAGE,
    page ? `path=${page.path}` : '无法获取当前页面')
  await capture(mp, SCENARIO, '01-entry.png')

  // ── 2. 品牌导航栏 ──
  const navName = await waitForText(page, '.chat-page__navbar-name', '小布', 15000)
  rep.step('导航栏品牌名「小布」', !!navName, navName ? `text=${navName}` : '未找到')
  const navSub = await waitForText(page, '.chat-page__navbar-sub', '米高窗帘', 5000)
  rep.step('导航栏副标「米高窗帘 · 智能购物助手」', !!navSub, navSub ? `text=${navSub}` : '未找到')

  // ── 3. 等待会话就绪（空态欢迎语 / 快捷操作 / 历史消息任一出现）──
  const ready = await (async () => {
    for (let i = 0; i < 40; i++) {
      const qa = await page.$('.quick-actions')
      const empty = await page.$('.message-list__empty-title')
      const bubbles = await page.$$('.message-bubble')
      if (qa || empty || (bubbles && bubbles.length > 0)) return { qa, empty, bubbleCount: bubbles ? bubbles.length : 0 }
      await sleep(500)
    }
    return null
  })()
  rep.step('会话初始化完成（快捷操作/空态/消息任一出现）', !!ready,
    ready ? `quickActions=${!!ready.qa} empty=${!!ready.empty} bubbles=${ready.bubbleCount}` : '20s 内未就绪')

  // ── 4. 新对话（确定性回到空态，快捷操作必然重现）──
  const newChat = await waitForElement(page, '.chat-page__new-chat', 10000)
  if (newChat) {
    await newChat.tap()
    await sleep(2000)
  }
  const qa2 = await waitForElement(page, '.quick-actions', 15000)
  rep.step('「🔄 新对话」回到空会话（快捷操作重现）', !!qa2, qa2 ? '快捷操作已重现' : '未重现')
  await capture(mp, SCENARIO, '02-ready.png')
  shot('02-ready.png')

  // ── 5. 快捷操作发消息（真实链路：点卡片 → SSE 回复）──
  if (qa2) {
    const items = await page.$$('.quick-actions__item')
    const label = items && items.length > 0 ? await items[0].text() : ''
    rep.step('快捷操作卡片存在（查订单/找产品/退换货/转人工）', items && items.length >= 4,
      `items=${items ? items.length : 0} first=${label || ''}`)
    await items[0].tap()
    const userBubble = await waitForBubble(page, 'user', 30000)
    rep.step('点击快捷操作后用户消息上屏', !!userBubble, userBubble ? userBubble.slice(0, 50) : '未出现')
    const aiReply = await waitForBubble(page, 'assistant', 120000)
    rep.step('AI 助手回复（SSE 流式）', !!aiReply,
      aiReply ? `${aiReply.replace(/\n/g, ' ').slice(0, 60)}…(len=${aiReply.length})` : '120s 内无回复')
    await waitForStreamEnd(page, 60000) // 等流结束，避免下一次发送被 isStreaming 守卫吞掉
    await capture(mp, SCENARIO, '03-quick-action-reply.png')
    shot('03-quick-action-reply.png')
  } else {
    rep.step('快捷操作发消息', false, '新对话后快捷操作未出现')
  }

  // ── 6. 键盘模式输入并发送（UI-007：默认按住说话，可切换键盘）──
  const holdBtn = await page.$('.message-input__hold-btn')
  rep.step('输入条默认语音模式（按住说话）', !!holdBtn, holdBtn ? '按住说话按钮存在' : '当前非语音模式')
  if (holdBtn) {
    const modeBtn = await page.$('.message-input__mode-btn')
    if (modeBtn) {
      await modeBtn.tap()
      await sleep(800)
    }
  }
  const textarea = await waitForElement(page, '.message-input__textarea', 10000)
  rep.step('切换至键盘模式（输入框可见）', !!textarea, textarea ? 'textarea 可见' : '未找到输入框')
  if (textarea) {
    const QUESTION = '你好，有什么热销的窗帘推荐？'
    await textarea.input(QUESTION)
    await sleep(500)
    const sendBtn = await waitForElement(page, '.message-input__btn', 5000)
    if (sendBtn) {
      const btnText = (await sendBtn.text()) || ''
      rep.step('发送按钮激活（内容非空）', btnText.includes('↑'), `btn=${btnText}`)
      await sendBtn.tap()
      // 精确断言：出现包含输入内容的新用户气泡
      const userBubble2 = await waitForBubbleText(page, 'user', QUESTION, 30000)
      rep.step('键盘输入消息上屏（新气泡+新内容）', !!userBubble2,
        userBubble2 ? `${userBubble2.slice(0, 50)}` : '未出现新用户气泡')
      const prevAiText = await lastBubbleText(page, 'assistant')
      const aiReply2 = await waitForBubble(page, 'assistant', 120000)
      const isNewAi = !!aiReply2 && aiReply2 !== prevAiText
      rep.step('AI 回复第二条（SSE 流式，新内容）', isNewAi,
        aiReply2 ? `${aiReply2.replace(/\n/g, ' ').slice(0, 60)}…(len=${aiReply2.length})` : '120s 内无回复')
      await waitForStreamEnd(page, 60000)
      await capture(mp, SCENARIO, '04-typed-reply.png')
    } else {
      rep.step('发送按钮激活', false, '未找到发送按钮')
    }
  }

  // ── 7. 终态截图 ──
  await capture(mp, SCENARIO, '05-final.png')
  shot('01-entry.png')
  shot('02-ready.png')
  shot('03-quick-action-reply.png')
  shot('04-typed-reply.png')
  shot('05-final.png')

  return rep.result()
}

module.exports = { run }
