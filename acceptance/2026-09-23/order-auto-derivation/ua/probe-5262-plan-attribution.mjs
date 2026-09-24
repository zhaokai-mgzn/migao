// #5262 取证探针（只取证，不改实现）：两条观察项的**缺失读数**
//
// 观察项①：只改「接高」时，引擎**实际收到**的 `cutting_mode` / `auto` 是什么？与 S0 逐字段对照。
//   缺口（#5255 归档里没有的）：归档只记了 **响应**，没记 **请求载荷**；
//   且归档的 S0 快照是**面板收起**时抓的（`OrderCraftFields` 未渲染 ⇒ `cutting_mode_checked=[]`）
//   ⇒ 本探针先展开「改工艺参数」再抓 S0，使 S0/S1 在**同一 DOM 条件下**可比（S0c 保留收起态作对照）。
//
// 观察项②：`定高买宽 + 拼2次` 引擎 422 时，**上屏文本**是什么？同帧还写「已并入特殊选项」吗？
//   ⚠️ 实测（本探针 r1）：**光有**「人工加工类型=定高买宽 + 拼2次」**不**触发 422 ——
//   引擎 `_implied_mode()` 把「人工拼次 ≥ 1」判为**蕴含倒幅**（先于显式加工类型）⇒ 200 `定宽买高`。
//   ⇒ 422 的真实前置 = **人工接高 + 拼次 ≥ 1 同时存在**（此时 `effective_mode` 被接高钉死在定高买宽）。
//   故本版按 r1 的实测前置重排步骤（S2 = 接高 0.05 + 拼2次 ⇒ 422）。
//
// 覆盖路径：
//   S0c 面板**收起**态（复现归档 `cutting_mode_checked=[]` 的抓取条件）
//   S0  展开「改工艺参数」后的全自动基线
//   S1  **只**手工改接高 = 0.05（加工类型一个键都没点过）  ← 观察项①的决定性帧
//   S1b 清空接高 ⇒ 回到全自动（确认可逆）
//   S2  接高 0.05 **+** 拼2次 ⇒ 预期引擎 422        ← 观察项②的决定性帧
//   S3  清空接高（拼2次保留）⇒ 预期 200 定宽买高     ← ② 的对照：同一面板文案、引擎同意
//   S4  显式点加工类型「定高买宽」（拼2次保留）⇒ 200 但 `plan.cutting_mode` 被蕴含口径改写
//   S5  拼次回「由推导决定」⇒ 恢复
//
// 用法：
//   PHONE=13600136000 BASE_URL=http://localhost:3001 OUT_DIR=<空目录> \
//     node acceptance/2026-09-23/order-auto-derivation/ua/probe-5262-plan-attribution.mjs
//
// 🔴 BASE_URL 必须 http://localhost:3001（127.0.0.1 下 hydration 不接管 ⇒ 永远停在「加载中...」）
// 🔴 PHONE 必须 13600136000（评测管理员）；13800138000 是顾客，/orders/new 会「缺少权限 order:list」
// 🔴 OUT_DIR 每轮必须换（截图名固定 ⇒ 同目录重跑会静默覆盖上一轮证据）
import { createRequire } from 'node:module'
import { writeFileSync, mkdirSync } from 'node:fs'
const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('playwright')

const BASE = process.env.BASE_URL || 'http://localhost:3001'
const OUT = process.env.OUT_DIR || '/tmp/ua5262'
const PHONE = process.env.PHONE || '13600136000'
const SMS = process.env.SMS_CODE || '123456'
const W = Number(process.env.WIDTH_M || '6.6')
const H = Number(process.env.HEIGHT_M || '2.6')
mkdirSync(OUT, { recursive: true })

const lines = []
const say = (s) => { lines.push(s); console.log(s) }
let planLog = []
let reqLog = []
const marks = []

const browser = await chromium.launch({ headless: true, args: ['--no-proxy-server'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } })
page.on('pageerror', (e) => say(`  [pageerror] ${String(e).slice(0, 200)}`))
// ── **请求载荷**（#5262 的关键缺失读数）：引擎**实际收到**的人工面 ──
page.on('request', (r) => {
  const u = r.url()
  if (!u.includes('/orders/craft-calc') || r.method() !== 'POST') return
  let body = ''
  try { body = r.postData() || '' } catch {}
  let keys = null
  try {
    const j = JSON.parse(body)
    const has = (k) => Object.prototype.hasOwnProperty.call(j, k)
    keys = {
      width: j.width, height: j.height, fabric_width: j.fabric_width ?? null,
      craft: j.craft ?? null, craft_tier: j.craft_tier ?? null, formula: j.formula ?? null,
      // 人工面四键：`null` + `sent:false` = **请求里根本没有这个键**
      cutting_mode: has('cutting_mode') ? j.cutting_mode : null, cutting_mode_sent: has('cutting_mode'),
      splice_times: has('splice_times') ? j.splice_times : null, splice_times_sent: has('splice_times'),
      join_height_m: has('join_height_m') ? j.join_height_m : null, join_height_m_sent: has('join_height_m'),
      join_width_m: has('join_width_m') ? j.join_width_m : null, join_width_m_sent: has('join_width_m'),
    }
  } catch {}
  reqLog.push(keys)
  say(`  [req] craft-calc 请求（人工面）= ${JSON.stringify(keys)}`)
})
page.on('response', async (r) => {
  const u = r.url()
  if (!u.includes('/orders/craft-calc')) return
  let body = ''
  try { body = await r.text() } catch {}
  say(`  [net] ${r.status()} ${u.replace(/^https?:\/\/[^/]+/, '')} :: ${body.replace(/\s+/g, ' ').slice(0, 700)}`)
  try {
    const j = JSON.parse(body)
    planLog.push({
      status: r.status(),
      cutting_mode: j?.data?.plan?.cutting_mode ?? null,
      auto: j?.data?.plan?.auto ?? null,
      splice_times: j?.data?.plan?.splice_times ?? null,
      splice_option: j?.data?.plan?.splice_option ?? null,
      join_height_m: j?.data?.plan?.join_height_m ?? null,
      meters: j?.data?.plan?.meters ?? null,
      fabric_meters: j?.data?.fabric_meters ?? null,
      // 失败报文：admin-api 包装形状与引擎形状都收（两种形态都出现过）
      err_code: j?.error?.code ?? j?.detail?.error?.code ?? null,
      err: j?.error?.message ?? j?.detail?.error?.message ?? j?.detail?.message ?? null,
    })
  } catch {}
})
const shot = async (name) => {
  // 截图必须**真的拍到被断言的那块**（证据层纪律）：先把推导面板滚进视口再拍
  await page.locator('[data-testid="craft-plan"]').first().scrollIntoViewIfNeeded().catch(() => {})
  await page.waitForTimeout(250)
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false })
  say(`  [shot] ${OUT}/${name}.png`)
}

/** 抓「商家此刻看得见的告知」+ 加工类型**选中态** + 错误文本的**同帧可见性**（逐字、原样） */
const snapshot = async (label) => {
  say(`\n===== ${label} =====`)
  const notice = await page.evaluate(() => {
    const grab = (sel) => {
      const el = document.querySelector(sel)
      return el ? (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : null
    }
    const rectOf = (el) => {
      const r = el.getBoundingClientRect()
      return {
        in_viewport: r.top < window.innerHeight && r.bottom > 0 && r.left < window.innerWidth && r.right > 0,
        top: Math.round(r.top), bottom: Math.round(r.bottom),
      }
    }
    // 试算失败那条 `<p class="text-red-600">`（**没有 testid**）⇒ 按类名 + 文本抓，并给出**同帧可见性**
    const calcErrors = Array.from(document.querySelectorAll('p,div,span'))
      .filter((e) => e.children.length === 0 && /text-red-600/.test(e.className || ''))
      .map((e) => (e.innerText || '').replace(/\s+/g, ' ').trim())
      .filter(Boolean)
    const errEls = Array.from(document.querySelectorAll('p,div,span')).filter(
      (e) => e.children.length === 0 && /算料试算失败/.test(e.innerText || '')
    )
    return {
      panel_text: (() => {
        const el = document.querySelector('[data-testid="craft-plan"]')
        return el ? (el.innerText || '').replace(/[ \t]+/g, ' ').trim() : null
      })(),
      panel_in_viewport: (() => {
        const el = document.querySelector('[data-testid="craft-plan"]')
        return el ? rectOf(el).in_viewport : null
      })(),
      notice_craft_plan_source: grab('[data-testid="craft-plan-source"]'),
      notice_craft_plan_mode: grab('[data-testid="craft-plan-mode"]'),
      notice_craft_plan_splice: grab('[data-testid="craft-plan-splice"]'),
      notice_craft_plan_join_height: grab('[data-testid="craft-plan-join-height"]'),
      notice_craft_plan_derived_options: grab('[data-testid="craft-plan-derived-options"]'),
      notice_craft_plan_reason: grab('[data-testid="craft-plan-reason"]'),
      notice_craft_plan_meters: grab('[data-testid="craft-plan-meters"]'),
      // 观察项①：加工类型的**选中态** + 「自动」标记（#5020 的 `cutting-mode-auto`）
      cutting_mode_auto_badge: grab('[data-testid="cutting-mode-auto"]'),
      radiogroups: Array.from(document.querySelectorAll('[role="radiogroup"]')).map((g) => ({
        label: g.getAttribute('aria-label'),
        options: Array.from(g.querySelectorAll('[role="radio"]')).map((e) => (e.innerText || '').trim()),
        checked: Array.from(g.querySelectorAll('[role="radio"]'))
          .filter((e) => e.getAttribute('aria-checked') === 'true')
          .map((e) => (e.innerText || '').trim()),
      })),
      // 观察项②：**上屏的试算失败文本** + 它此刻**在不在视口内**
      calc_error_red_texts: calcErrors,
      calc_error_in_viewport: errEls.length ? errEls.map((e) => rectOf(e).in_viewport) : [],
      calc_error_rects: errEls.map((e) => rectOf(e)),
      unpriced_fee_alert: grab('[data-testid="unpriced-fee-alert"]'),
      craft_plan_unavailable: grab('[data-testid="craft-plan-unavailable"]'),
      craft_plan_meters_mismatch: grab('[data-testid="craft-plan-meters-mismatch"]'),
      craft_plan_join_error: grab('[data-testid="craft-plan-join-error"]'),
      craft_plan_style_conflict: grab('[data-testid="craft-plan-style-conflict"]'),
      craft_plan_splice_manual: grab('[data-testid="craft-plan-splice-manual"]'),
      craft_plan_edit_expanded: (() => {
        const el = document.querySelector('[data-testid="craft-plan-edit"]')
        return el ? el.getAttribute('aria-expanded') : null
      })(),
    }
  })
  say(`  [DOM] craft-plan 面板逐字：${JSON.stringify(notice.panel_text)}`)
  for (const [k, v] of Object.entries(notice)) {
    if (k === 'panel_text') continue
    say(`  [DOM] ${k} = ${JSON.stringify(v)}`)
  }
  say(`  [req ] 末次 craft-calc **请求**（人工面）= ${JSON.stringify(reqLog.at(-1) ?? null)}`)
  say(`  [server] 末次 craft-calc **响应**读数 = ${JSON.stringify(planLog.at(-1) ?? null)}`)
  // 有试算失败文本时，**另拍一张**把错误行滚进视口的截图（面板那张拍不到它）
  const slug = (label.match(/^S[0-9a-z]*/) || ['S'])[0]
  if (notice.calc_error_red_texts.length > 0) {
    await page.evaluate(() => {
      const el = Array.from(document.querySelectorAll('p,div,span')).find(
        (e) => e.children.length === 0 && /算料试算失败/.test(e.innerText || '')
      )
      if (el) el.scrollIntoView({ block: 'center' })
    })
    await page.waitForTimeout(250)
    await page.screenshot({ path: `${OUT}/${slug}-错误行.png`, fullPage: false })
    say(`  [shot] ${OUT}/${slug}-错误行.png （错误行滚入视口后的同帧截图）`)
  }
  marks.push({ label, at: lines.length, req: reqLog.at(-1) ?? null, resp: planLog.at(-1) ?? null })
  return notice
}
const sect = (from, prefix) =>
  lines.slice(from).find((l) => l.trim().startsWith(prefix))?.trim() ?? '(未抓到)'

try {
  // 1) 登录
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('#phone', { timeout: 60000 })
  await page.fill('#phone', PHONE)
  await page.getByRole('button', { name: /获取验证码/ }).click()
  await page.waitForTimeout(1200)
  await page.fill('#code', SMS)
  await page.getByRole('button', { name: /登\s*录|登录/ }).last().click()
  await page.waitForURL('**/dashboard**', { timeout: 30000 })
  say('✅ 登录成功')

  // 2) 下单页 + 三项输入
  await page.goto(`${BASE}/orders/new`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(2000)
  await page.fill('input[placeholder*="收货人姓名"]', '5262探针')
  await page.fill('input[placeholder*="手机号"]', '13900005262')
  await page.fill('input[placeholder*="收货地址"]', '杭州市西湖区取证路 5262 号')
  await page.getByRole('button', { name: /选择商品/ }).first().click()
  await page.waitForTimeout(800)
  const search = page.locator('[role="dialog"] input[placeholder*="搜索商品"]').first()
  await search.waitFor({ state: 'visible', timeout: 10000 })
  await search.fill('遮光窗帘')
  await page.locator('[role="dialog"] button:has-text("搜索")').first().click()
  await page.waitForTimeout(1500)
  await page.locator('[role="dialog"] button').filter({ hasText: /遮光窗帘/ }).first().click()
  await page.waitForTimeout(2000)
  const colorChip = page.getByText('浅灰', { exact: true }).first()
  if (await colorChip.count()) { await colorChip.click(); await page.waitForTimeout(1200) }
  await page.getByLabel('窗宽 (米)').first().fill(String(W))
  await page.getByLabel('窗高 (米)').first().fill(String(H))
  await page.waitForTimeout(3500)
  say(`✅ 已建行：遮光窗帘 / 浅灰 / ${W}×${H}`)
  await page.locator('[data-testid="craft-plan"]').first().scrollIntoViewIfNeeded().catch(() => {})
  await page.waitForTimeout(400)

  // ── S0c：**面板收起**态（复现归档 `cutting_mode_checked=[]` 的抓取条件）──
  await shot('5262-a1-S0c-面板收起')
  await snapshot('S0c 面板**收起**（`craft-plan-edit` 未展开 ⇒ `OrderCraftFields` 不在 DOM）')

  // ── 展开「改工艺参数 / 人工加接高接宽拼接」——**必须早于 S0**，否则 S0/S1 不可比 ──
  await page.locator('[data-testid="craft-plan-edit"]').first().click()
  await page.waitForTimeout(900)
  say('✅ 已展开「改工艺参数 / 人工加接高接宽拼接」')
  await shot('5262-a2-S0-展开后基线')
  await snapshot('S0 展开后的全自动基线（未手工改任何项）')

  const joinInput = page.locator('[data-testid="craft-plan-join-height-input"]').first()
  const setJoin = async (value) => {
    await joinInput.click()
    await joinInput.fill('')
    if (value !== '') await joinInput.type(value, { delay: 80 })
    await joinInput.press('Enter')
    await joinInput.blur().catch(() => {})
    await page.waitForTimeout(3200)
  }
  const setSplice = async (text, wait = 3600) => {
    const radio = page
      .locator('[role="radiogroup"][aria-label="拼接（人工加）"] [role="radio"]')
      .filter({ hasText: text })
      .first()
    if (!(await radio.count())) { say(`⚠️ 未找到「${text}」拼接档位`); return false }
    await radio.click()
    await page.waitForTimeout(wait)
    return true
  }
  const clickMode = async (text, wait = 3600) => {
    const radio = page
      .locator('[role="radiogroup"][aria-label="加工类型"] [role="radio"]')
      .filter({ hasText: new RegExp(`^${text}$`) })
      .first()
    if (!(await radio.count())) { say(`⚠️ 未找到加工类型「${text}」档位`); return false }
    await radio.click()
    await page.waitForTimeout(wait)
    return true
  }

  if (!(await joinInput.count())) {
    say('⚠️ 未找到 接高 人工输入（此刻加工类型可能不是定高买宽）—— 后续步骤跳过')
  } else {
    // ── S1：**只**手工改接高 = 0.05（加工类型**不点**）── 观察项①的决定性帧
    await setJoin('0.05')
    await shot('5262-a3-S1-只改接高0.05')
    await snapshot('S1 **只**手工改接高 = 0.05 米（加工类型一个键都没点过）')

    // ── S1b：清空接高 ⇒ 回到全自动（确认可逆）──
    await setJoin('')
    await shot('5262-a4-S1b-清空接高')
    await snapshot('S1b 清空接高 ⇒ 回到「由推导决定」（可逆性）')

    // ── S2：接高 0.05 **+** 拼2次 ⇒ 预期 422（观察项②的决定性帧）──
    await setJoin('0.05')
    if (await setSplice('拼2次', 4200)) {
      await shot('5262-b1-S2-接高0.05+拼2次-422')
      await snapshot('S2 人工接高 0.05 **+** 人工拼2次 ⇒ 预期引擎 422（面板同帧文案？）')
    }

    // ── S3：清空接高（拼2次保留）⇒ 预期 200 定宽买高（② 的对照：同一面板文案、引擎同意）──
    await setJoin('')
    await shot('5262-b2-S3-拼2次-合法对照')
    await snapshot('S3 清空接高（拼2次保留）⇒ 预期 200「定宽买高 + 拼2次」（② 的对照）')

    // ── S4：显式点加工类型「定高买宽」（拼2次保留）⇒ 200 但加工类型被蕴含口径改写？──
    if (await clickMode('定高买宽', 4200)) {
      await shot('5262-b3-S4-显式定高买宽+拼2次')
      await snapshot('S4 **正对照**：显式点加工类型「定高买宽」（拼2次保留）')
    }

    // ── S5：拼次回「由推导决定」+ 加工类型回「未指定」⇒ 恢复 ──
    await setSplice('由推导决定')
    await clickMode('未指定')
    await shot('5262-b4-S5-恢复')
    await snapshot('S5 拼次回「由推导决定」+ 加工类型回「未指定」⇒ 恢复')
  }

  // ── 逐字段对照（观察项①的定性依据）：每帧的**请求/响应**并排 ──
  say('\n===== [diff] 逐帧「请求人工面 vs 引擎响应」对照 =====')
  for (const m of marks) {
    say(`  ${m.label}`)
    say(`    [req ] ${JSON.stringify(m.req)}`)
    say(`    [resp] ${JSON.stringify(m.resp)}`)
  }
  const S0 = marks.find((m) => m.label.startsWith('S0 展开后'))
  const S1 = marks.find((m) => m.label.startsWith('S1 **只**'))
  if (S0 && S1) {
    say('\n  ── 观察项① 决定性对照（S0 全自动 vs S1 只改接高）──')
    for (const k of ['cutting_mode', 'cutting_mode_sent', 'join_height_m', 'splice_times']) {
      say(`    req.${k}: S0=${JSON.stringify(S0.req?.[k])} vs S1=${JSON.stringify(S1.req?.[k])}`)
    }
    for (const k of ['status', 'cutting_mode', 'auto', 'splice_times', 'join_height_m', 'meters']) {
      say(`    resp.${k}: S0=${JSON.stringify(S0.resp?.[k])} vs S1=${JSON.stringify(S1.resp?.[k])}`)
    }
  } else {
    say('  ⚠️ 未定位到 S0/S1 帧')
  }
  say(`\n  [req] 全部请求人工面序列 = ${JSON.stringify(reqLog)}`)
  say(`  [server] 全部响应读数序列 = ${JSON.stringify(planLog)}`)

  writeFileSync(`${OUT}/readings.txt`, lines.join('\n') + '\n')
  say(`\n[saved] ${OUT}/readings.txt`)
  say('PROBE_DONE_OK')
} catch (e) {
  say(`PROBE_FAILED: ${String(e).slice(0, 600)}`)
  await shot('5262-99-失败现场').catch(() => {})
  writeFileSync(`${OUT}/readings.txt`, lines.join('\n') + '\n')
} finally {
  await browser.close()
}