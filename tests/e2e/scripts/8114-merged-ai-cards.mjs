// case_ids: UI-003, UI-004, DA-005, DA-006, DA-007
/**
 * #8114 真机复核脚本：合并后的「黄金策 · 今日经营」卡（速览 + 简报 → 一张卡）。
 *
 * 判据（真机面，与 `tests/unit/pages/dashboard-first-screen.test.tsx` 的机器判据互补）：
 *   ① 看板顶部**只有一张** AI 卡：`daily-business-card` 存在且**唯一**，旧速览条 `today-overview-bar`
 *      与旧简报块 `dashboard-briefing-section` 都**取不到**；
 *   ② 收起态（默认）就能看到速览那一句话；展开态 = 那句话 + 简报（或「未开启 / 未生成」空态，
 *      两者共享 `briefing-collapsed-hint` 语义）；
 *   ③ 简报**关闭**时卡片**仍在**（速览不依赖简报开关）；
 *   ④ 1440×900 首屏不回归：「待处理」区底边 y ≤ 900（量测用 `getBoundingClientRect().bottom`）。
 *
 * 用法（真栈已起，admin-web = http://localhost:3001）：
 *   OUT_DIR=<abs>/acceptance/2026-10-29/8114-merged-ai/out \
 *     node tests/e2e/scripts/8114-merged-ai-cards.mjs
 *
 * ⚠️ 浏览器必须用 http://localhost:3001（不是 127.0.0.1：Next dev 对 127.0.0.1 会拦 `/_next/hmr`，
 *    页面不 hydrate，testid 永远等不到）。
 */
import { chromium } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const BASE = process.env.BASE_URL || 'http://localhost:3001'
const OUT = process.env.OUT_DIR || 'acceptance/2026-10-29/8114-merged-ai/out'
const PHONE = process.env.PHONE || '13600136000'
const SMS_CODE = process.env.SMS_CODE || '123456'
const SHOTS = join(OUT, 'screenshots')
mkdirSync(SHOTS, { recursive: true })

const evidence = { base: BASE, screenshots: {}, consoleErrors: [] }

/** 量测首屏几何 + 结构计数（DOM 现读，不靠推断） */
async function measure(page) {
  return page.evaluate(() => {
    const rect = (sel) => {
      const el = document.querySelector(sel)
      if (!el) return null
      const r = el.getBoundingClientRect()
      return { top: Math.round(r.top), bottom: Math.round(r.bottom), height: Math.round(r.height) }
    }
    const count = (sel) => document.querySelectorAll(sel).length
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      aiCard: rect('[data-testid="daily-business-card"]'),
      aiCardCount: count('[data-testid="daily-business-card"]'),
      legacyOverviewBarCount: count('[data-testid="today-overview-bar"]'),
      legacyBriefingSectionCount: count('[data-testid="dashboard-briefing-section"]'),
      pendingSection: rect('[data-testid="dashboard-pending-section"]'),
      pendingCardCount: count('[data-testid="pending-card"]'),
      sentence: document.querySelector('[data-testid="today-overview-sentence"]')?.textContent || null,
      briefingBody: (() => {
        const el = document.querySelector('[data-testid="daily-business-card-briefing"]')
        return el ? (el.textContent || '').replace(/\s+/g, ' ').trim() : null
      })(),
    }
  })
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })
const page = await ctx.newPage()
page.on('console', (m) => { if (m.type() === 'error') evidence.consoleErrors.push(m.text().slice(0, 300)) })
page.on('pageerror', (e) => evidence.consoleErrors.push(`pageerror: ${e.message}`.slice(0, 300)))

// ── 1. 登录（管理员 = 手机号 + 短信验证码；SMS_BYPASS_CODE 由起栈脚本注入）──
await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
await page.getByRole('tab', { name: /管理员登录/ }).click()
await page.fill('#phone', PHONE)
await page.getByRole('button', { name: '获取验证码' }).click()
await page.fill('#code', SMS_CODE)
await page.getByRole('button', { name: '登 录' }).click()
await page.waitForURL(/\/(dashboard|change-password)/, { timeout: 90000 })
if (page.url().includes('/change-password')) throw new Error('首登强制改密：请换一个已改密的管理员账号')
await page.getByTestId('daily-business-card').waitFor({ timeout: 90000 })

// ── 2. 简报开关：记录当前状态；本轮验收要覆盖「未开启」⇒ 若开着就关掉 ──
await page.goto(`${BASE}/settings?tab=basic`, { waitUntil: 'domcontentloaded' })
const toggle = page.getByRole('button', { name: '启用智能每日经营简报开关' })
await toggle.waitFor({ timeout: 90000 })
const enabledBefore = ((await toggle.getAttribute('class')) || '').includes('bg-primary-600')
evidence.briefingEnabledBefore = enabledBefore
if (enabledBefore) {
  await toggle.click()
  // 即时保存（PUT /api/admin/briefing/config）+ toast；等它落库再回看板
  await page.waitForFunction(() => {
    const el = document.querySelector('[aria-label="启用智能每日经营简报开关"]')
    return el && !(el.className || '').includes('bg-primary-600')
  }, null, { timeout: 30000 })
  await page.waitForTimeout(800)
}

// ── 3. 看板：合并卡（默认收起态）= 首屏截图 + 几何量测 ──
await page.goto(`${BASE}/dashboard`, { waitUntil: 'domcontentloaded' })
await page.getByTestId('daily-business-card').waitFor({ timeout: 90000 })
await page.getByTestId('today-overview-sentence').waitFor({ timeout: 90000 })
// 等真实读数落定（不是加载中的占位）
await page.waitForFunction(() => {
  const el = document.querySelector('[data-testid="today-overview-sentence"]')
  return !!el && /今日订单|今日暂无新订单/.test(el.textContent || '')
}, null, { timeout: 90000 })
await page.waitForTimeout(800) // 让统计卡 finish（避免首屏截图卡在骨架）
const collapsed = await measure(page)
evidence.collapsed = collapsed
evidence.screenshots.collapsed = join(SHOTS, 'merged-ai-1440x900.png')
await page.screenshot({ path: evidence.screenshots.collapsed })

// ── 4. 展开态（简报未开启）—— 证明「不开启」也覆盖，且卡片没消失 ──
await page.getByTestId('briefing-toggle').click()
await page.getByTestId('daily-business-card-briefing').waitFor({ timeout: 30000 })
await page.waitForTimeout(500)
const expanded = await measure(page)
evidence.expanded = expanded
evidence.screenshots.disabledExpanded = join(SHOTS, 'merged-ai-disabled.png')
await page.screenshot({ path: evidence.screenshots.disabledExpanded })

// ── 5. 判据（任何一条不成立 ⇒ 非零退出，不产出「看着正常」的结论）──
const failures = []
if (collapsed.aiCardCount !== 1) failures.push(`合并卡应唯一，实际 ${collapsed.aiCardCount}`)
if (collapsed.legacyOverviewBarCount !== 0) failures.push('旧速览条 today-overview-bar 仍在')
if (collapsed.legacyBriefingSectionCount !== 0) failures.push('旧简报块 dashboard-briefing-section 仍在')
if (!collapsed.sentence) failures.push('收起态没看到速览那一句话')
if (collapsed.pendingCardCount !== 5) failures.push(`待处理卡应为 5 张，实际 ${collapsed.pendingCardCount}`)
if (collapsed.pendingSection === null) failures.push('待处理区取不到几何读数')
else if (collapsed.pendingSection.bottom > 900) failures.push(`待处理区底边 ${collapsed.pendingSection.bottom} > 900（首屏回归）`)
if (!expanded.briefingBody || !expanded.briefingBody.includes('每日经营简报未开启')) {
  failures.push(`简报关闭时展开态应说「每日经营简报未开启」，实际：${expanded.briefingBody}`)
}
if (expanded.aiCard && expanded.aiCard.top !== collapsed.aiCard?.top) failures.push('展开后合并卡位置变化（首屏结构回归）')

evidence.pass = failures.length === 0
evidence.failures = failures
writeFileSync(join(OUT, 'merged-ai-evidence.json'), JSON.stringify(evidence, null, 2))

console.log(JSON.stringify({
  pass: evidence.pass,
  failures,
  collapsed: {
    aiCard: collapsed.aiCard,
    pendingSection: collapsed.pendingSection,
    pendingCardCount: collapsed.pendingCardCount,
    legacy: { overviewBar: collapsed.legacyOverviewBarCount, briefingSection: collapsed.legacyBriefingSectionCount },
    sentence: collapsed.sentence,
  },
  expanded: { briefingBody: expanded.briefingBody },
  screenshots: evidence.screenshots,
}, null, 2))

await browser.close()
process.exit(evidence.pass ? 0 : 1)
