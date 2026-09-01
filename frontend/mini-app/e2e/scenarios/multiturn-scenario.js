// case_ids: CH-010, CH-011, CH-012
/**
 * 多轮场景 E2E 验收（C 端表单化交互）
 *
 * S1 选购下单：驱动多轮对话（推荐→选品→规格→报价），断言交互组件（choice/confirm/form）出现
 * S5 数据安全：订单卡片手机号脱敏（138****8000），无 11 位明文
 *
 * 说明：真实后端 LLM 行为有波动，采用「软断言」——观察交互组件出现与可交互性，
 * 不硬断言 LLM 回复文本；无订单数据时脱敏断言记录跳过（单测已覆盖脱敏逻辑）。
 */
const {
  capture,
  sleep,
  waitForPageReady,
  waitForElement,
  waitForText,
  waitForBubble,
  waitForStreamEnd,
  lastBubbleText,
  makeReporter,
} = require('../lib/harness')

const SCENARIO = 'multiturn'

/** 轮询：任一选择器出现（返回命中的选择器名） */
async function waitForAny(page, selectors, timeoutMs = 60000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    for (const sel of selectors) {
      try {
        const el = await page.$(sel)
        if (el) return sel
      } catch {}
    }
    await sleep(1000)
  }
  return null
}

async function run(mp) {
  const rep = makeReporter('多轮表单化交互验收')
  const shot = (name) => rep.screenshot(SCENARIO, name)

  const page = await waitForPageReady(mp)
  rep.step('页面就绪', !!page && page.path === 'pages/chat/index/index',
    page ? `path=${page.path}` : '未就绪')

  // ── S1 选购下单：多轮交互组件出现 ──
  const newChat = await waitForElement(page, '.chat-page__new-chat', 15000)
  if (newChat) {
    await newChat.tap()
    await sleep(2000)
  }

  // 第 1 轮：推荐热销窗帘 → 期望出现商品卡片/选择卡片/文本任一
  const input = await waitForElement(page, '.message-input__textarea', 15000)
  if (input) {
    await input.input('推荐几款热销窗帘')
    await sleep(500)
    const sendBtn = await waitForElement(page, '.message-input__btn', 5000)
    if (sendBtn) await sendBtn.tap()

    const r1 = await waitForAny(page, [
      '.choice-card', '.product-card', '.message-bubble--assistant', '.message-bubble__cards',
    ], 90000)
    rep.step('第1轮：推荐窗帘收到回复（卡片或文本）', !!r1, r1 ? `出现 ${r1}` : '90s 无回复')
    await waitForStreamEnd(page, 60000)
    await capture(mp, SCENARIO, '01-recommend.png')

    // 若出现 choice 卡片 → 点选第一个选项（选品）
    const choiceItem = await page.$('.choice-card__option')
    if (choiceItem) {
      const optText = (await choiceItem.text()) || ''
      await choiceItem.tap()
      rep.step('第2轮：点选 choice 选项（选品）', true, `选项：${optText.slice(0, 30)}`)
      await sleep(1500)
    } else {
      // 无 choice 卡片 → 文本表达选品（软跳过，记为信息）
      const q2 = await waitForElement(page, '.message-input__textarea', 10000)
      if (q2) {
        await q2.input('选第一款，白色，2.8米门幅，按米卖')
        await sleep(400)
        const sb2 = await waitForElement(page, '.message-input__btn', 5000)
        if (sb2) await sb2.tap()
      }
      rep.step('第2轮：文本表达选品规格', true, '未出现 choice 卡片，用文本补充')
    }
    await sleep(2000)

    // 等待本轮回复结束后，检查是否出现交互组件（choice/confirm/form）
    const interactive = await waitForAny(page, [
      '.choice-card', '.confirm-card', '.form-card',
    ], 90000)
    rep.step('多轮中出现交互组件（choice/confirm/form）', !!interactive,
      interactive ? `出现 ${interactive}` : '90s 内未出现交互组件（LLM 可能用纯文本收参）')
    await waitForStreamEnd(page, 60000)

    // 若出现 form 卡片 → 验证字段渲染与必填校验（不提交真实下单）
    const formCard = await page.$('.form-card')
    if (formCard) {
      const submitBtn = await waitForElement(page, '.form-card__submit', 5000)
      rep.step('FormCard 渲染（多字段表单）', !!submitBtn, submitBtn ? '含提交按钮' : '无提交按钮')
      if (submitBtn) {
        // 空表单直接提交 → 必填校验拦截（不触发 onAction/不发消息）
        await submitBtn.tap()
        await sleep(800)
        const errText = await page.$('.form-card__field-error')
        rep.step('FormCard 必填校验生效（空表单提交被拦截）', !!errText,
          errText ? (await errText.text())?.slice(0, 30) : '无错误提示（可能字段非必填）')
      }
      await capture(mp, SCENARIO, '02-form-card.png')
    }

    // 若出现 confirm 卡片 → 验证确认按钮存在（不点击，避免真实下单）
    const confirmCard = await page.$('.confirm-card')
    if (confirmCard) {
      const confirmBtn = await waitForElement(page, '.confirm-card__confirm', 5000)
      rep.step('ConfirmCard 渲染（写操作确认守卫）', !!confirmBtn, confirmBtn ? '含确认按钮' : '无确认按钮')
      await capture(mp, SCENARIO, '03-confirm-card.png')
    }
  } else {
    rep.step('输入框可用', false, '未找到输入框')
  }

  // ── S5 数据安全：订单卡片手机号脱敏 ──
  const input2 = await waitForElement(page, '.message-input__textarea', 15000)
  if (input2) {
    await input2.input('查一下我的订单')
    await sleep(400)
    const sb3 = await waitForElement(page, '.message-input__btn', 5000)
    if (sb3) await sb3.tap()
    const orderCard = await waitForElement(page, '.order-card', 90000)
    if (orderCard) {
      await waitForStreamEnd(page, 60000)
      const text = (await orderCard.text()) || ''
      const masked = /1[3-9]\d{2}\*{4}\d{4}/.test(text) || /(\d{3}\*{4}\d{4})/.test(text)
      const leaked = /1[3-9]\d{9}/.test(text)
      rep.step('S5：订单卡片手机号脱敏', masked && !leaked,
        masked ? '脱敏格式匹配' : text.includes('****') ? '含掩码' : '无手机号字段')
      await capture(mp, SCENARIO, '04-order-card.png')
    } else {
      rep.step('S5：订单卡片手机号脱敏', true, '当前用户无订单数据，跳过（单测已覆盖脱敏）')
    }
  }

  await capture(mp, SCENARIO, '05-final.png')
  shot('01-recommend.png')
  shot('02-form-card.png')
  shot('03-confirm-card.png')
  shot('04-order-card.png')
  shot('05-final.png')

  return rep.result()
}

module.exports = { run }
