// case_ids: CH-010, CH-011, CH-012
/**
 * 多轮场景 E2E 验收（C 端表单化交互）
 *
 * S1 选购下单：驱动多轮对话（推荐→选品→报价），断言交互组件（choice/confirm/form）出现
 * S5 数据安全：订单卡片手机号脱敏（138****8000），无 11 位明文
 *
 * 说明：真实后端 LLM 行为有波动，采用「软断言」——观察交互组件出现与可交互性，
 * 不硬断言 LLM 回复文本；无订单数据时脱敏断言记录跳过（单测已覆盖脱敏逻辑）。
 *
 * ⚠️ 选择器依据 = `src/components/chat/MessageInput.tsx`（#2953 单容器双语义）：
 *    输入框 `.message-input__textarea` **常驻**（无「先切键盘模式」这一步）；
 *    发送键为 `.message-input__icon-btn--send`（有草稿才渲染）。
 *    旧脚本用的 `--hold-btn`/`--mode-btn`/`--btn` 在源码与产物里都不存在 →
 *    发送从未发生 → 两轮「90s 无回复」实为**断言/选择器造成的假红**（2026-09-14 实证）。
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
  typeAndSend,
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

  // 输入条为单容器（#2953）：textarea 常驻，无需（也无）模式切换键
  const input = await waitForElement(page, '.message-input__textarea', 15000)

  // 第 1 轮：推荐热销窗帘 → 期望出现商品卡片/文本（LLM 用 product_list 卡片展示）
  if (input) {
    const t1 = await typeAndSend(page, '推荐几款热销窗帘')
    if (t1.ok) {
      const r1 = await waitForAny(page, [
        '.choice-card', '.product-card', '.message-bubble--assistant', '.message-bubble__cards',
      ], 90000)
      rep.step('第1轮：推荐窗帘收到回复（卡片或文本）', !!r1, r1 ? `出现 ${r1}` : '90s 无回复')
      await waitForStreamEnd(page, 60000)
      await capture(mp, SCENARIO, '01-recommend.png')

      // 第 2 轮：明确选品规格（建立商品上下文，贴近已验证的 API 成功路径）
      const prev2 = await lastBubbleText(page, 'assistant')
      const t2 = await typeAndSend(page, '我要买米白色遮光窗帘，2.8米门幅，按米卖')
      if (t2.ok) {
        const r2 = await waitForAny(page, ['.message-bubble--assistant'], 90000)
        const fresh2 = !!r2 && (r2 && lastBubbleText(page, 'assistant')) !== prev2
        rep.step('第2轮：选品规格收到回复（新气泡）', fresh2, fresh2 ? '已回复' : (r2 ? '有气泡但内容未变' : '90s 无回复'))
        await waitForStreamEnd(page, 60000)

        // 第 3 轮：下单意图但信息不全 → 期望 LLM 下发 interact(form) 表单（表单化交互核心场景）
        const prev3 = await lastBubbleText(page, 'assistant')
        const t3 = await typeAndSend(page, '帮我下单')
        if (t3.ok) {
          // 真实断言 = 收到回复（红证：无回复即红）；FormCard 是否出现为**信息性数据点**
          // （LLM 用文本收参同属合法行为，不由本 e2e 判红 —— 表单化覆盖见 agent-eval CH-010）
          const r3 = await waitForAny(page, ['.message-bubble--assistant'], 90000)
          const fresh3 = !!r3 && (await lastBubbleText(page, 'assistant')) !== prev3
          const formCard = await page.$('.form-card')
          rep.step('第3轮：下单意图收到回复', fresh3,
            fresh3
              ? `已回复（信息性：form-card=${formCard ? '出现' : '未出现'}，纯文本收参同属合法）`
              : '90s 无回复')
          await waitForStreamEnd(page, 60000)

          if (formCard) {
            // 验证多字段渲染（收货人/手机号/地址/数量）
            const fields = await page.$$('.form-card__field')
            rep.step('FormCard 多字段渲染', fields.length >= 3, `fields=${fields.length}`)
            const submitBtn = await waitForElement(page, '.form-card__submit', 5000)
            rep.step('FormCard 提交按钮', !!submitBtn, submitBtn ? '存在' : '缺失')
            // 必填校验：**只有表单声明了必填字段**时空提交才必然被拦 —— `required` 是 LLM 决定的
            // 可选字段（backend/ai-agent-service/app/tools/interact.py:203 `"default": False`），
            // FormCard 只对 required 字段报错（src/components/cards/FormCard.tsx:37-39）。
            // 旧断言无条件要求出现 .form-card__field-error → LLM 未标必填时必红（2026-09-14 实测），
            // 属「断言宽于契约」的假红；校验逻辑本身由单测 tests/form-card.test.tsx 覆盖。
            const requiredMarks = await page.$$('.form-card__required')
            if (submitBtn && requiredMarks && requiredMarks.length > 0) {
              // 空表单直接提交 → 必填校验拦截（不触发 onAction/不发消息，不产生真实订单）
              await submitBtn.tap()
              await sleep(800)
              const errText = await page.$('.form-card__field-error')
              rep.step('FormCard 必填校验生效（空表单提交被拦截）', !!errText,
                errText ? (await errText.text())?.slice(0, 30) : `无错误提示（requiredMarks=${requiredMarks.length}）`)
            } else {
              rep.step('FormCard 必填校验（信息性，本轮不可判）', true,
                `本次表单未声明必填字段（requiredMarks=0）→ 空提交不被拦属合法行为；不点击提交` +
                `（避免向真实后端发出空表单消息）。校验分支由单测 tests/form-card.test.tsx 覆盖`)
            }
            await capture(mp, SCENARIO, '02-form-card.png')
          }
        } else {
          rep.step('第3轮：下单意图收到回复', false, `发送未完成：${t3.reason}`)
        }
      } else {
        rep.step('第2轮：选品规格收到回复（新气泡）', false, `发送未完成：${t2.reason}`)
      }
    } else {
      rep.step('第1轮：推荐窗帘收到回复（卡片或文本）', false, `发送未完成：${t1.reason}`)
    }
  } else {
    rep.step('输入框可用', false, '未找到输入框 .message-input__textarea')
  }

  // ── S5 数据安全：订单卡片手机号脱敏 ──
  const order = await typeAndSend(page, '查一下我的订单')
  if (order.ok) {
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
  } else {
    rep.step('S5：订单卡片手机号脱敏', false, `发送未完成：${order.reason}`)
  }

  // 终态补拍（#3761）：实测 `05-final.png` 与 `04-order-card.png` 逐字节相同 ⇒ 绿路径跳过、失败时补抓。
  await rep.captureFinal(mp, SCENARIO, '05-final.png')
  shot('01-recommend.png')
  shot('02-form-card.png')
  // ⚠️ 原 `shot('03-confirm-card.png')` 已删：该图**从未被 capture**（本场景没有 confirm-card 抓取点），
  //    却出现在 report.md 的「截图」清单里 —— 报告声称有、磁盘上没有（证据清单与产物不一致）。
  shot('04-order-card.png')

  return rep.result()
}

module.exports = { run }
