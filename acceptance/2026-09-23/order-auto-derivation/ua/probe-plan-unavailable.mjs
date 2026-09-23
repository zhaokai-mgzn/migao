// 降级提示探针（issue #5255 §A 判据 3 的对照件）：
//   让 `data.plan` **真的缺席** ⇒ 抓「推导服务未就绪」那条降级提示的**逐字文案** + 截图，
//   与「未跟随 / 已人工锁定」告知并列对照（判据 3：两者必须能区分、不得同形）。
//
// 触发方式（**不用桩、不改任何仓库代码**）：`plan` 的开关在 ai-agent 侧是
//   `derive_plan_config = request.fabric_width is not None`（`app/api/internal.py` 的 craft-calc 端点——
//   按 `fabric_width is not None` 检索）；前端只在**能解析出门幅**时才发该键
//   （`lib/craft-calc-request.ts` 的 `params.fabric_width = fabricWidth`，解析不到 ⇒ 不发、不猜）。
//   ⇒ 把某个 SKU 的 `door_width` 置空（**本地一次性库的数据改动**，非代码改动），
//     选中它即成「门幅未维护」真实现场 ⇒ `plan` 缺席 ⇒ 降级提示上屏。
//
// 前置（本探针**不代跑**，由 README §2 ⑩ 给出）：
//   UPDATE product_skus SET door_width = NULL WHERE product_id = 'prod_eval_summer';
//
// 用法：
//   PHONE=13600136000 BASE_URL=http://localhost:3001 OUT_DIR=<空目录> \
//     PRODUCT=夏日清风窗帘 COLOR=米白色 node probe-plan-unavailable.mjs
import { createRequire } from 'node:module'
import { writeFileSync, mkdirSync } from 'node:fs'
const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('playwright')

const BASE = process.env.BASE_URL || 'http://localhost:3001'
const OUT = process.env.OUT_DIR || '/tmp/ua-plan-unavailable'
const PHONE = process.env.PHONE || '13600136000'
const PRODUCT = process.env.PRODUCT || '夏日清风窗帘'
const COLOR = process.env.COLOR || '米白色'
mkdirSync(OUT, { recursive: true })

const lines = []
const say = (s) => { lines.push(s); console.log(s) }

const browser = await chromium.launch({ headless: true, args: ['--no-proxy-server'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } })
page.on('response', async (r) => {
  const u = r.url()
  if (u.includes('/craft-calc')) {
    let body = ''
    try { body = await r.text() } catch {}
    say(`  [net] ${r.status()} ${u.replace(/^https?:\/\/[^/]+/, '')} :: ${body.slice(0, 500)}`)
  }
})
const shot = async (name) => { await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false }); say(`  [shot] ${OUT}/${name}.png`) }

try {
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForSelector('#phone', { timeout: 60000 })
  await page.fill('#phone', PHONE)
  await page.getByRole('button', { name: /获取验证码/ }).click()
  await page.waitForTimeout(1200)
  await page.fill('#code', '123456')
  await page.getByRole('button', { name: /登\s*录|登录/ }).last().click()
  await page.waitForURL('**/dashboard**', { timeout: 30000 })
  say('✅ 登录成功')

  await page.goto(`${BASE}/orders/new`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(2000)
  await page.fill('input[placeholder*="收货人姓名"]', '降级探针')
  await page.fill('input[placeholder*="手机号"]', '13900004444')
  await page.fill('input[placeholder*="收货地址"]', '杭州市西湖区探针路 3 号')
  await page.getByRole('button', { name: /选择商品/ }).first().click()
  await page.waitForTimeout(800)
  const search = page.locator('[role="dialog"] input[placeholder*="搜索商品"]').first()
  await search.waitFor({ state: 'visible', timeout: 10000 })
  await search.fill(PRODUCT)
  await page.locator('[role="dialog"] button:has-text("搜索")').first().click()
  await page.waitForTimeout(1500)
  await page.locator('[role="dialog"] button').filter({ hasText: new RegExp(PRODUCT) }).first().click()
  await page.waitForTimeout(2000)
  const chips = page.getByText(COLOR, { exact: true })
  if (await chips.count()) { await chips.first().click(); await page.waitForTimeout(1500) }
  await page.getByLabel('窗宽 (米)').first().fill('6.6')
  await page.getByLabel('窗高 (米)').first().fill('2.6')
  await page.waitForTimeout(4000)
  say(`✅ 已建行：${PRODUCT} / ${COLOR} / 6.6×2.6（该 SKU 门幅已置空 ⇒ 不发 fabric_width）`)

  const dom = await page.evaluate(() => {
    const grab = (sel) => {
      const el = document.querySelector(sel)
      return el ? (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim() : null
    }
    const panelEl = document.querySelector('[data-testid="craft-plan"]')
    return {
      panel_text: panelEl ? (panelEl.innerText || '').replace(/[ \t]+/g, ' ').trim() : null,
      craft_plan_unavailable: grab('[data-testid="craft-plan-unavailable"]'),
      craft_plan_source: grab('[data-testid="craft-plan-source"]'),
      craft_plan_mode: grab('[data-testid="craft-plan-mode"]'),
      meters_manual_stale: grab('[data-testid="meters-manual-stale"]'),
      door_width_missing_badge: grab('[data-testid="size-door-width-missing"]'),
      craft_plan_edit_label: grab('[data-testid="craft-plan-edit"]'),
    }
  })
  say(`  [DOM] craft-plan 面板逐字：${JSON.stringify(dom.panel_text)}`)
  for (const [k, v] of Object.entries(dom)) if (k !== 'panel_text') say(`  [DOM] ${k} = ${JSON.stringify(v)}`)
  await page.locator('[data-testid="craft-plan"]').first().scrollIntoViewIfNeeded().catch(() => {})
  await page.waitForTimeout(400)
  await shot('20-推导服务未就绪-降级提示')

  writeFileSync(`${OUT}/plan-unavailable-readings.txt`, lines.join('\n') + '\n')
  say(`\n[saved] ${OUT}/plan-unavailable-readings.txt`)
  say('PROBE_DONE_OK')
} catch (e) {
  say(`PROBE_FAILED: ${String(e).slice(0, 600)}`)
  await shot('99-失败现场').catch(() => {})
  writeFileSync(`${OUT}/plan-unavailable-readings.txt`, lines.join('\n') + '\n')
} finally {
  await browser.close()
}
