// UA-2 探针（issue #5255 §A）：商家**手工改** ⇒ 抓「未跟随 / 已人工锁定」类告知的**逐字文案** + 同帧截图
//
// 覆盖路径（全在同一行、按序，避免互相污染）：
//   S0 基线（全自动推导，未手工改任何项）
//   S1 手工改**接高** 0.05 米（加工类型仍自动 ⇒ 定高买宽下才可加接高）
//   S1b 清空接高（回到「由推导决定」）—— 为 S2 换档让路（倒幅下不能接高）
//   S2 手工改**加工类型** → 「定宽买高」（点**真实另一档**，不是「未指定」）
//   S3 手工加**拼次** → 「拼1次」
//   S4 手工改**用料米数** 7.7 → 再改净窗宽（触发「未跟随」告知）
//   S5 点「恢复按公式计算」（告知里的出口）
//
// 用法：
//   PHONE=13600136000 BASE_URL=http://localhost:3001 OUT_DIR=<空目录> \
//     node probe-ua2-manual-override.mjs
//
// 🔴 BASE_URL 必须 http://localhost:3001（127.0.0.1 下 hydration 不接管 ⇒ 永远停在「加载中...」）
// 🔴 PHONE 必须 13600136000（评测管理员）；13800138000 是顾客，/orders/new 会「缺少权限 order:list」
// 🔴 OUT_DIR 每轮必须换（截图名固定 ⇒ 同目录重跑会静默覆盖上一轮证据）
import { createRequire } from 'node:module'
import { writeFileSync, mkdirSync } from 'node:fs'
const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('playwright')

const BASE = process.env.BASE_URL || 'http://localhost:3001'
const OUT = process.env.OUT_DIR || '/tmp/ua2-verify'
const PHONE = process.env.PHONE || '13600136000'
const SMS = process.env.SMS_CODE || '123456'
const W = Number(process.env.WIDTH_M || '6.6')
const H = process.env.HEIGHT_M || '2.6'
const CUT_TO = process.env.CUT_TO || '定宽买高'
mkdirSync(OUT, { recursive: true })

const lines = []
const say = (s) => { lines.push(s); console.log(s) }
let planLog = []

const browser = await chromium.launch({ headless: true, args: ['--no-proxy-server'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } })
page.on('pageerror', (e) => say(`  [pageerror] ${String(e).slice(0, 200)}`))
page.on('response', async (r) => {
  const u = r.url()
  if (u.includes('/craft-calc')) {
    let body = ''
    try { body = await r.text() } catch {}
    say(`  [net] ${r.status()} ${u.replace(/^https?:\/\/[^/]+/, '')} :: ${body.slice(0, 600)}`)
    try {
      const j = JSON.parse(body)
      planLog.push({ status: r.status(), cutting_mode: j?.data?.plan?.cutting_mode, auto: j?.data?.plan?.auto, splice_times: j?.data?.plan?.splice_times, splice_option: j?.data?.plan?.splice_option, join_height_m: j?.data?.plan?.join_height_m, meters: j?.data?.plan?.meters, fabric_meters: j?.data?.fabric_meters, err: j?.error?.message })
    } catch {}
  }
})
const shot = async (name) => {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false })
  say(`  [shot] ${OUT}/${name}.png`)
}

/** 抓「商家此刻看得见的告知」—— testid 逐条 + craft-plan 面板整体 innerText（原样） */
const snapshot = async (label) => {
  say(`\n===== ${label} =====`)
  const notice = await page.evaluate(() => {
    const grab = (sel) => {
      const el = document.querySelector(sel)
      return el ? (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : null
    }
    const panelEl = document.querySelector('[data-testid="craft-plan"]')
    return {
      panel_text: panelEl ? (panelEl.innerText || '').replace(/[ \t]+/g, ' ').trim() : null,
      notice_craft_plan_source: grab('[data-testid="craft-plan-source"]'),
      notice_craft_plan_mode: grab('[data-testid="craft-plan-mode"]'),
      notice_craft_plan_splice: grab('[data-testid="craft-plan-splice"]'),
      notice_craft_plan_join_height: grab('[data-testid="craft-plan-join-height"]'),
      notice_craft_plan_derived_options: grab('[data-testid="craft-plan-derived-options"]'),
      notice_craft_plan_reason: grab('[data-testid="craft-plan-reason"]'),
      notice_meters_manual_stale: grab('[data-testid="meters-manual-stale"]'),
      notice_meters_source_line: grab('[data-testid="craft-plan"]')
        ? null : null,
      notice_craft_plan_unavailable: grab('[data-testid="craft-plan-unavailable"]'),
      notice_craft_plan_meters_mismatch: grab('[data-testid="craft-plan-meters-mismatch"]'),
      notice_craft_plan_join_error: grab('[data-testid="craft-plan-join-error"]'),
      // 「未跟随 / 人工」相关**所有**可见文本（不预设 testid；叶子节点）
      texts_with_manual_wording: Array.from(document.querySelectorAll('p,div,span,strong'))
        .filter((e) => e.children.length === 0)
        .map((e) => (e.innerText || '').replace(/\s+/g, ' ').trim())
        .filter((t) => t && /未跟随|人工指定|人工锁定|不再被自动|人工优先|已修改|恢复按公式|人工加/.test(t)),
      // 用料米数框旁那条「人工指定 / 恢复按公式计算」行（没有 testid，按文本抓）
      meters_manual_line: (() => {
        const el = Array.from(document.querySelectorAll('p')).find((p) => /人工指定/.test(p.innerText || '') && /恢复按公式计算/.test(p.innerText || ''))
        return el ? (el.innerText || '').replace(/\s+/g, ' ').trim() : null
      })(),
      cutting_mode_checked: Array.from(document.querySelectorAll('[role="radiogroup"][aria-label="加工类型"] [role="radio"]'))
        .filter((e) => e.getAttribute('aria-checked') === 'true').map((e) => e.innerText.trim()),
      plan_override_splice_checked: Array.from(document.querySelectorAll('[role="radiogroup"][aria-label="拼接（人工加）"] [role="radio"]'))
        .filter((e) => e.getAttribute('aria-checked') === 'true').map((e) => e.innerText.trim()),
    }
  })
  say(`  [DOM] craft-plan 面板逐字：${JSON.stringify(notice.panel_text)}`)
  for (const [k, v] of Object.entries(notice)) {
    if (k === 'panel_text') continue
    say(`  [DOM] ${k} = ${JSON.stringify(v)}`)
  }
  say(`  [server] 末次 craft-calc 读数 = ${JSON.stringify(planLog.at(-1) ?? null)}`)
  return notice
}

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
  await page.fill('input[placeholder*="收货人姓名"]', 'UA2探针')
  await page.fill('input[placeholder*="手机号"]', '13900003333')
  await page.fill('input[placeholder*="收货地址"]', '杭州市西湖区探针路 2 号')
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
  await shot('10-baseline-推导面板')
  await snapshot('S0 基线（全自动推导，未手工改任何项）')

  // 3) 展开「改工艺参数 / 人工加接高接宽拼接」
  await page.locator('[data-testid="craft-plan-edit"]').first().click()
  await page.waitForTimeout(600)
  say('✅ 已展开「改工艺参数 / 人工加接高接宽拼接」')

  // ── S1：手工改接高（此刻加工类型仍自动选中 定高买宽 ⇒ 可加接高）
  const joinInput = page.locator('[data-testid="craft-plan-join-height-input"]').first()
  if (await joinInput.count()) {
    await joinInput.click()
    await joinInput.fill('')
    await joinInput.type('0.05', { delay: 80 })
    await joinInput.press('Enter')
    await page.waitForTimeout(3000)
    await shot('11-手工改接高')
    await snapshot('S1 手工改接高 = 0.05 米（加工类型此时仍是自动推导值）')
    // ── S1b：清空接高（回到由推导决定）—— 倒幅下不能接高，为 S2 让路
    await joinInput.click()
    await joinInput.fill('')
    await joinInput.press('Enter')
    await joinInput.blur()
    await page.waitForTimeout(3000)
    say('  ✅ 已清空接高（回到「由推导决定」）')
  } else {
    say('⚠️ 未找到 接高 人工输入（此刻加工类型可能不是定高买宽）')
  }

  // ── S2：手工改加工类型 → 点**真实另一档**（跳过「未指定」）
  const modeGroup = page.locator('[role="radiogroup"][aria-label="加工类型"] [role="radio"]')
  const modes = await modeGroup.allInnerTexts()
  say(`  加工类型档位 = ${JSON.stringify(modes)}`)
  const activeLabel = await page.evaluate(() => {
    const rs = Array.from(document.querySelectorAll('[role="radiogroup"][aria-label="加工类型"] [role="radio"]'))
    const hit = rs.find((e) => e.getAttribute('aria-checked') === 'true')
    return hit ? hit.innerText.trim() : null
  })
  say(`  当前选中档 = ${JSON.stringify(activeLabel)}`)
  let targetIdx = -1
  for (let i = 0; i < modes.length; i++) {
    if (modes[i].trim() === CUT_TO) { targetIdx = i; break }
  }
  if (targetIdx < 0) say(`⚠️ 档位里没有「${CUT_TO}」`)
  if (targetIdx >= 0) {
    await modeGroup.nth(targetIdx).click()
    await page.waitForTimeout(3500)
    await shot('12-手工改加工类型')
    await snapshot(`S2 手工改加工类型：${JSON.stringify(activeLabel)} → ${JSON.stringify(CUT_TO)}`)
  }

  // ── S3：手工加拼次 = 拼1次（倒幅下拼接是合法组合）
  const spliceRadio = page.locator('[role="radiogroup"][aria-label="拼接（人工加）"] [role="radio"]').filter({ hasText: '拼1次' }).first()
  if (await spliceRadio.count()) {
    await spliceRadio.click()
    await page.waitForTimeout(3500)
    await shot('13-手工加拼次')
    await snapshot('S3 手工加拼次 = 拼1次')
  } else {
    say('⚠️ 未找到「拼1次」人工加档位')
  }

  // ── S4：手工改用料米数 7.7 → 再改净窗宽 ⇒ 「未跟随」告知
  const qty = page.getByLabel('用料米数').first()
  await qty.click()
  await qty.fill('')
  await qty.type('7.7', { delay: 80 })
  await qty.press('Enter')
  await qty.blur()
  await page.waitForTimeout(3000)
  await shot('14a-手工改用料米数')
  await snapshot('S4a 手工改用料米数 = 7.7（尚未改宽高 ⇒ 签名未变）')
  const wInput = page.getByLabel('窗宽 (米)').first()
  await wInput.fill(String(W + 0.4))
  await wInput.press('Enter')
  await page.waitForTimeout(4000)
  await shot('14b-未跟随告知')
  await snapshot(`S4b 手工改用料后再改净窗宽 → ${W + 0.4}（触发「未跟随」告知）`)

  // ── S5：点告知里的出口「恢复按公式计算」
  const restore = page.getByRole('button', { name: /恢复按公式计算/ }).first()
  if (await restore.count()) {
    await restore.click()
    await page.waitForTimeout(4000)
    await shot('15-恢复按公式计算')
    await snapshot('S5 点「恢复按公式计算」（告知里的出口）之后')
  } else {
    say('⚠️ 未找到「恢复按公式计算」按钮')
  }

  writeFileSync(`${OUT}/ua2-readings.txt`, lines.join('\n') + '\n')
  say(`\n[saved] ${OUT}/ua2-readings.txt`)
  say('PROBE_DONE_OK')
} catch (e) {
  say(`PROBE_FAILED: ${String(e).slice(0, 600)}`)
  await shot('99-失败现场').catch(() => {})
  writeFileSync(`${OUT}/ua2-readings.txt`, lines.join('\n') + '\n')
} finally {
  await browser.close()
}
