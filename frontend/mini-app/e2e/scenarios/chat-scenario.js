// case_ids: CH-001, CH-005, UI-007, UI-010, UI-016, UI-018
/**
 * 小布对话页 E2E 验收
 * 覆盖：入口渲染（品牌导航）→ 会话就绪 → 快捷操作发消息（真实后端 SSE）→ 新对话 → 键盘输入发消息
 * 依赖真实后端（app.migaozn.com 测试环境）；LLM 回复较慢，等待窗口 120s。
 *
 * ⚠️ 输入条选择器依据 = `src/components/chat/MessageInput.tsx`（#2953 单容器双语义，2026-09-06）：
 *   真值类 = `.message-input__container` / `.message-input__textarea` /
 *           `.message-input__icon-btn` / `--voice`（空草稿）/ `--send`（有草稿）/ `--stop`（流式中）
 *   已作废 = `.message-input__hold-btn`、`.message-input__mode-btn`、`.message-input__btn`（源码与产物均为 0）
 */
const {
  capture,
  sleep,
  waitForPageReady,
  waitForElement,
  waitForText,
  waitForBubble,
  waitForBubbleText,
  waitForAssistantReply,
  countBubbles,
  waitForStreamEnd,
  waitForStreamIdle,
  lastBubbleText,
  probeInputBar,
  typeAndSend,
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

  // ── 2. 品牌导航栏（UI-016 副标题租户化 / UI-018 客服名取 botName，未配置兜底「小布」）──
  // 旧断言写死「小布」必红：botName 由企业设置下发（本环境实测「光头强」）。
  const navNameEl = await waitForElement(page, '.chat-page__navbar-name', 15000)
  const navName = navNameEl ? ((await navNameEl.text()) || '').trim() : ''
  rep.step('导航栏客服名已渲染（botName 非空）', navName.length > 0,
    navName ? `name=${navName}` : '未找到 .chat-page__navbar-name 或文本为空')
  const navSub = await waitForText(page, '.chat-page__navbar-sub', '智能购物助手', 8000)
  rep.step('导航栏副标（租户名·智能购物助手）', !!navSub, navSub ? `text=${navSub}` : '未找到')

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
  // UI-018 同源断言：空态问候语 = 「你好，我是{botName}」，与导航名同走 buildBotName。
  // **必须在空态上断言**（进程可能续聊到历史会话，此时空态不渲染）—— 前置条件由上面的
  // 「新对话」步骤确立；断言本身红证见 REPORT.md（空态未渲染时该步确实变红）。
  const sameBot = navName ? await waitForText(page, '.message-list__empty-title', navName, 10000) : null
  rep.step('导航名与空态问候语同源（同一 botName）', !!sameBot,
    `nav=${navName} empty=${sameBot || '(空态未渲染/文案不一致)'}`)
  await capture(mp, SCENARIO, '02-ready.png')

  // ── 5. 快捷操作发消息（真实链路：点卡片 → SSE 回复）──
  if (qa2) {
    const items = await page.$$('.quick-actions__item')
    const label = items && items.length > 0 ? await items[0].text() : ''
    // UI-014（issue #4236 回退）：六格等权（2 列 × 3 行）= 6 格；
    // #4209 的两栏分组（.quick-actions__row）已按用户裁定撤下
    rep.step('快捷入口格存在（算料报价/推荐热门商品/查订单/找产品/售后咨询/查物流）',
      items && items.length >= 6,
      `items=${items ? items.length : 0} first=${label || ''}`)
    await items[0].tap()
    const userBubble = await waitForBubble(page, 'user', 30000)
    rep.step('点击快捷操作后用户消息上屏', !!userBubble, userBubble ? userBubble.slice(0, 50) : '未出现')
    const aiReply = await waitForBubble(page, 'assistant', 120000)
    rep.step('AI 助手回复（SSE 流式）', !!aiReply,
      aiReply ? `${aiReply.replace(/\n/g, ' ').slice(0, 60)}…(len=${aiReply.length})` : '120s 内无回复')
    await waitForStreamEnd(page, 60000) // 等流结束，避免下一次发送被 isStreaming 守卫吞掉
    await capture(mp, SCENARIO, '03-quick-action-reply.png')
  } else {
    rep.step('快捷操作发消息', false, '新对话后快捷操作未出现')
  }

  // ── 6. 单容器输入条 + 键盘输入发送（UI-007 新契约，2026-09-06 重设计）──
  // 契约：textarea 常驻（placeholder「发消息或按住说话」）+ 无模式切换键；右下自适应键：
  //       空草稿=语音键 / 有草稿=发送键 / 流式中=停止键。
  // 先等流式真正结束（DOM 判据：动作键不再是停止键）—— 流式中语音/发送键按设计都不渲染，
  // 不先确立这个前置条件，步骤就变成靠时序碰运气的 flaky 断言。
  await waitForStreamIdle(page, 90000)
  const bar = await probeInputBar(page)
  rep.step('输入条单容器：textarea 常驻且无模式切换键',
    bar.textarea && bar.container && !bar.modeSwitch && !bar.holdBtn,
    `textarea=${bar.textarea} container=${bar.container} modeSwitch=${bar.modeSwitch} holdBtn=${bar.holdBtn}`)
  rep.step('placeholder「发消息或按住说话」（双语义）',
    (bar.placeholder || '').includes('发消息或按住说话'),
    `placeholder=${bar.placeholder}`)
  rep.step('空草稿时右下为「按住说话」语音键', bar.voiceBtn,
    bar.voiceBtn ? 'message-input__icon-btn--voice 存在' : '未找到语音键（语音不支持或已回归）')

  const QUESTION = '你好，有什么热销的窗帘推荐？'
  // **发送前**取基线：新回复可能在我们取基线之前就已开始/完成，「发送后再取」会把自己的回复当旧文本（假红）
  const prevAiText = await lastBubbleText(page, 'assistant')
  // 草稿就绪时（尚未发送）落一张截图：文件名与状态一致才算证据（见 harness.capture 的稳定帧说明）
  const typed = await typeAndSend(page, QUESTION, 10000, async () => {
    await capture(mp, SCENARIO, '04a-draft-send-key.png')
    shot('04a-draft-send-key.png')
  })
  rep.step('有草稿 → 语音键收起 + 发送键出现且激活（自适应动作键）',
    typed.ok && typed.voiceBefore === true && typed.voiceAfter === false,
    typed.reason ||
      `voiceBefore=${typed.voiceBefore} voiceAfter=${typed.voiceAfter} sendClass=${typed.sendClass} streamIdleWait=${typed.idleMs}ms`)
  if (typed.ok) {
    // 精确断言：出现包含输入内容的新用户气泡
    const userBubble2 = await waitForBubbleText(page, 'user', QUESTION, 30000)
    rep.step('键盘输入消息上屏（新气泡+新内容）', !!userBubble2,
      userBubble2 ? `${userBubble2.slice(0, 50)}` : '未出现新用户气泡')
    // 判据 = 发送前基线 → 之后出现「非空且 != 基线」的助手文本（见 harness.waitForAssistantReply 注释：
    // 文本比对取基线太晚、气泡计数在被计数前就已创建，两种写法都会假红 —— 2026-09-14 run5 / cold-run3 实测）
    const aiReply2 = await waitForAssistantReply(page, prevAiText, 120000)
    let failDetail = ''
    if (!aiReply2) {
      // 失败也要留下可归因证据：最终气泡数 / 是否仍在流式 / 末条 AI 文本 / 页面错误横幅
      const postBar = await probeInputBar(page)
      const nowCount = await countBubbles(page, 'assistant')
      const lastText = (await lastBubbleText(page, 'assistant')) || ''
      const errEl = await page.$('.chat-page__error-text')
      const errText = errEl ? (await errEl.text()) || '' : ''
      failDetail =
        `发送前基线(末条AI len=${(prevAiText || '').length}) → 120s 内未出现新回复；` +
        `assistant 气泡数 ${nowCount}；` +
        `流式中(停止键)=${postBar.stopBtn}；末条AI气泡=${JSON.stringify(lastText.replace(/\n/g, ' ').slice(0, 40))}(len=${lastText.length})；` +
        `页面错误横幅=${errText ? JSON.stringify(errText.slice(0, 60)) : '无'}`
    }
    rep.step('AI 回复第二条（SSE 流式，新内容）', !!aiReply2,
      aiReply2 ? `${aiReply2.replace(/\n/g, ' ').slice(0, 60)}…(len=${aiReply2.length})` : failDetail)
    await waitForStreamEnd(page, 60000)
    // ⚠️ 原 `04-typed-reply.png` 已删（#3761 实测 + 验收报告 §5-3 判定）：
    //    · 2026-09-14 21:56 那轮里 `chat/03 == 04 == 05` **逐字节相同**（同一状态三连拍）；
    //    · 更早的验收入库报告（acceptance/2026-09-14/mini-app-e2e/REPORT.md §5-3）已**独立判定**
    //      `chat/04` 画面显示的是**上一轮**（算料报价）内容，与同时刻 DOM 断言不一致，
    //      并明确写下「当前**不得**把 chat/04 当作列表状态的证据引用」⇒ 结论本来就不依赖它。
    //    · 视口是否跟随最新消息是**另一个**未决问题（该报告 §5-3 假设 (b)，需模拟器判决实验），
    //      不由本改动承担，也不因此把这张图改回'证据'。
  } else {
    rep.step('键盘输入消息上屏（新气泡+新内容）', false, `发送未完成：${typed.reason}`)
  }

  // ── 7. 终态截图 ──
  // 终态补拍（#3761）：实测 `05-final.png` 与 `03/04` 同帧 ⇒ 绿路径跳过（0 成本）、失败时补抓。
  await rep.captureFinal(mp, SCENARIO, '05-final.png')
  // 报告登记只在**这里**做一次（原先 `02-ready`/`03-quick-action-reply` 在正文与尾部各登记一次
  // → report.md 的「截图」清单里同一张图出现两遍，读起来像抓了两次）。
  shot('01-entry.png')
  shot('02-ready.png')
  shot('03-quick-action-reply.png')

  return rep.result()
}

module.exports = { run }
