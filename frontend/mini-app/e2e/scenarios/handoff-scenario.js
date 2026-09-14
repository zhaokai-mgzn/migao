// case_ids: CH-013, CH-014
/**
 * 转人工链路 E2E 验收（POC 收尾 I 项）
 * 覆盖：输入「我要转人工」→ SSE 触发 human_handoff → C 端 handedOff 横幅出现
 * 说明：转人工后 agent-session 的 B 端可见性由配套脚本（B 端 API/页面）验证。
 *
 * ⚠️ 选择器依据 = `src/components/chat/MessageInput.tsx`（#2953 单容器双语义）：
 *    textarea 常驻（无模式切换键）；发送键 `.message-input__icon-btn--send`（有草稿才渲染）。
 *    旧脚本的 `--hold-btn`/`--mode-btn`/`--btn` 已作废 → 发送从未发生（2026-09-14 实证假红）。
 */
const {
  capture,
  sleep,
  waitForPageReady,
  waitForElement,
  waitForBubble,
  waitForBubbleText,
  waitForStreamEnd,
  typeAndSend,
  makeReporter,
} = require('../lib/harness')

const SCENARIO = 'handoff'

async function run(mp) {
  const rep = makeReporter('转人工链路验收')
  const shot = (name) => rep.screenshot(SCENARIO, name)

  const page = await waitForPageReady(mp)
  rep.step('入口页面为对话页', !!page && page.path === 'pages/chat/index/index',
    page ? `path=${page.path}` : '无法获取当前页面')

  // 新对话回空态（起点）
  const qa0 = await page.$('.quick-actions')
  if (!qa0) {
    const newChat = await waitForElement(page, '.chat-page__new-chat', 10000)
    if (newChat) {
      try { await newChat.tap() } catch (e) { await sleep(1000); try { await newChat.tap() } catch (e2) {} }
      await sleep(4000)
    }
  } else {
    await sleep(1000)
  }
  await waitForElement(page, '.quick-actions', 15000)

  // 单容器输入条：textarea 常驻（无需切模式）
  const textarea = await waitForElement(page, '.message-input__textarea', 15000)
  rep.step('输入框可用（单容器 textarea 常驻）', !!textarea, textarea ? 'textarea 可见' : '未找到 .message-input__textarea')

  // 输入「我要转人工」
  const QUESTION = '我要转人工'
  const typed = await typeAndSend(page, QUESTION)
  if (typed.ok) {
    const userBubble = await waitForBubbleText(page, 'user', QUESTION, 30000)
    rep.step('用户消息上屏（转人工意图）', !!userBubble, userBubble ? userBubble.slice(0, 40) : '未出现')
    // 等待 AI 回复（human_handoff 后应有安抚话术/转人工提示）
    const aiReply = await waitForBubble(page, 'assistant', 120000)
    rep.step('AI 回复（转人工处理话术）', !!aiReply,
      aiReply ? `${aiReply.replace(/\n/g, ' ').slice(0, 80)}…` : '120s 内无回复')
    await waitForStreamEnd(page, 60000)
    // 检查 handedOff 横幅
    await sleep(2500)
    const handoff = await page.$('.chat-page__handoff')
    rep.step('C 端「已转人工」横幅出现', !!handoff,
      handoff ? 'handoff 横幅存在' : '未出现（可能未触发或延迟）')
    await capture(mp, SCENARIO, '01-handoff.png')
    shot('01-handoff.png')
  } else {
    rep.step('用户消息上屏（转人工意图）', false, `发送未完成：${typed.reason}`)
  }

  await capture(mp, SCENARIO, '02-final.png')
  shot('02-final.png')
  return rep.result()
}

module.exports = { run }
