// case_ids: AS-001, CH-010
/**
 * 售后链路 E2E 验收（POC 收尾 E 项）
 * 覆盖：售后咨询快捷操作 → 用户消息上屏 → AI 售后回复（真实后端 SSE）
 * 说明：转人工端到端（人工客服实时接待）需真人客服在线配合，本场景覆盖
 *      售后咨询真实回复链路；转人工判定/服务层已由单测覆盖（test_handoff_judge 等）。
 */
const {
  capture,
  sleep,
  waitForPageReady,
  waitForElement,
  waitForBubble,
  waitForBubbleText,
  waitForStreamEnd,
  makeReporter,
} = require('../lib/harness')

const SCENARIO = 'aftersales'
const ENTRY_PAGE = 'pages/chat/index/index'

async function run(mp) {
  const rep = makeReporter('售后咨询链路验收')
  const shot = (name) => rep.screenshot(SCENARIO, name)

  // ── 1. 入口 ──
  const page = await waitForPageReady(mp)
  rep.step('入口页面为对话页', !!page && page.path === ENTRY_PAGE,
    page ? `path=${page.path}` : '无法获取当前页面')

  // ── 2. 新对话回到空态（确定性起点；已在空态则跳过）──
  const qa0 = await page.$('.quick-actions')
  if (!qa0) {
    const newChat = await waitForElement(page, '.chat-page__new-chat', 10000)
    if (newChat) {
      try { await newChat.tap() } catch (e) { console.log('  [aftersales] 新对话 tap 重试'); await sleep(1000); try { await newChat.tap() } catch (e2) {} }
      await sleep(4000)
    }
  } else {
    await sleep(1000)
  }
  const qa = await waitForElement(page, '.quick-actions', 15000)
  rep.step('新对话后快捷操作重现', !!qa, qa ? '快捷操作已出现' : '未出现')

  // ── 3. 定位「售后咨询」卡片并点击 ──
  if (qa) {
    const items = await page.$$('.quick-actions__item')
    let target = null
    let label = ''
    if (items && items.length > 0) {
      for (let i = 0; i < items.length; i++) {
        const t = (await items[i].text()) || ''
        if (t.includes('售后')) { target = items[i]; label = t; break }
      }
    }
    rep.step('售后咨询快捷卡片存在', !!target, target ? `label=${label || '(含售后)'}` : '未找到售后卡片')
    if (target) {
      await target.tap()
      const userBubble = await waitForBubble(page, 'user', 30000)
      rep.step('点击后用户消息上屏（售后意图）', !!userBubble,
        userBubble ? userBubble.slice(0, 60) : '未出现')
      const aiReply = await waitForBubble(page, 'assistant', 120000)
      rep.step('AI 售后回复（SSE 流式）', !!aiReply,
        aiReply ? `${aiReply.replace(/\n/g, ' ').slice(0, 80)}…(len=${aiReply.length})` : '120s 内无回复')
      // 售后回复应体现售后语义（引导描述问题/查工单/转人工任一）
      const text = (aiReply || '').toLowerCase()
      const sem = ['售后', '工单', '问题', '转人工', '退货', '退款', '客服'].some(w => text.includes(w))
      rep.step('回复语义与售后相关', !!aiReply && sem,
        aiReply ? (sem ? '含售后语义' : `回复=${text.slice(0, 60)}`) : '无回复可判')
      await waitForStreamEnd(page, 60000)
      await capture(mp, SCENARIO, '01-aftersales-reply.png')
      shot('01-aftersales-reply.png')
    }
  } else {
    rep.step('售后咨询快捷卡片', false, '快捷操作未出现')
  }

  await capture(mp, SCENARIO, '02-final.png')
  shot('02-final.png')
  return rep.result()
}

module.exports = { run }
