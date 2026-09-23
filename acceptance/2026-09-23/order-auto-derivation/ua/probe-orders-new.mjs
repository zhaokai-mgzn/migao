// 下单页 UA 探针（真浏览器）：登录 → /orders/new → 选商品 → 填净窗宽/高 → 抓推导面板
// 用法：node probe-orders-new.mjs
import { createRequire } from 'node:module'
const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('playwright')

const BASE = process.env.BASE_URL || 'http://localhost:3001'
const OUT = process.env.OUT_DIR || '/tmp/ua-verify'
const W = process.env.WIDTH_M || '6.6'
const H = process.env.HEIGHT_M || '2.6'
const PHONE = process.env.PHONE || '13800138000'
const SMS = process.env.SMS_CODE || '123456'

const browser = await chromium.launch({ headless: true, args: ['--no-proxy-server'] })
const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } })
page.on('console', (m) => { if (m.type() === 'error') console.log(`  [console.error] ${m.text().slice(0, 250)}`) })
page.on('pageerror', (e) => console.log(`  [pageerror] ${String(e).slice(0, 250)}`))
page.on('response', async (r) => {
  const u = r.url()
  if (u.includes('craft-calc') || u.includes('auto-features')) {
    let body = ''
    try { body = (await r.text()).slice(0, 400) } catch {}
    console.log(`  [net] ${r.status()} ${u.replace('http://localhost:8090', '')} :: ${body}`)
  }
})
page.on('requestfailed', (r) => console.log(`  [reqfail] ${r.url().slice(0, 120)} :: ${r.failure()?.errorText}`))
const shot = async (name) => { await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false }); console.log(`  [shot] ${OUT}/${name}.png`) }
const dumpTestIds = async (label) => {
  const ids = await page.evaluate(() => Array.from(document.querySelectorAll('[data-testid]')).map((e) => e.getAttribute('data-testid')))
  const labels = await page.evaluate(() => Array.from(document.querySelectorAll('[aria-label]')).map((e) => e.getAttribute('aria-label')))
  console.log(`  [${label}] testids(${ids.length}) = ${JSON.stringify(ids.slice(0, 60))}`)
  console.log(`  [${label}] aria-labels(${labels.length}) = ${JSON.stringify(labels.slice(0, 40))}`)
}

try {
  // 1) 登录
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 })
  await page.waitForTimeout(8000)
  await shot('00-登录页')
  console.log(`  登录页 title=${JSON.stringify(await page.title())} bodyLen=${(await page.evaluate(() => document.body.innerText)).length}`)
  await page.waitForSelector('#phone', { timeout: 60000 })
  await page.fill('#phone', PHONE)
  await page.getByRole('button', { name: /获取验证码/ }).click()
  await page.waitForTimeout(1500)
  await page.fill('#code', SMS)
  await page.getByRole('button', { name: /登\s*录|登录/ }).last().click()
  await page.waitForURL('**/dashboard**', { timeout: 25000 })
  console.log('✅ 登录成功')

  // 2) 下单页
  await page.goto(`${BASE}/orders/new`, { waitUntil: 'domcontentloaded', timeout: 30000 })
  await page.waitForTimeout(2500)
  await dumpTestIds('初次进入 /orders/new')
  await shot('01-orders-new-初始')

  // 3) 客户信息
  await page.fill('input[placeholder*="收货人姓名"]', 'UA探针')
  await page.fill('input[placeholder*="手机号"]', '13900002222')
  await page.fill('input[placeholder*="收货地址"]', '杭州市西湖区探针路 1 号')

  // 4) 选商品
  await page.getByRole('button', { name: /选择商品/ }).first().click()
  await page.waitForTimeout(1000)
  const search = page.locator('[role="dialog"] input[placeholder*="搜索商品"]').first()
  await search.waitFor({ state: 'visible', timeout: 10000 })
  await search.fill('遮光窗帘')
  await page.locator('[role="dialog"] button:has-text("搜索")').first().click()
  await page.waitForTimeout(2000)
  const result = page.locator('[role="dialog"] button').filter({ hasText: /遮光窗帘/ }).first()
  await result.click()
  await page.waitForTimeout(2500)
  console.log('✅ 已选商品')
  await dumpTestIds('选完商品')
  await shot('02-选完商品')

  // 4.5) 选颜色（页面要求「颜色 + 净窗宽 + 净窗高」三项都由商家给）
  for (const name of ['浅灰', '米白']) {
    const chip = page.getByText(name, { exact: true }).first()
    if (await chip.count()) { await chip.click(); console.log(`✅ 已选颜色「${name}」`); await page.waitForTimeout(2000); break }
  }
  await dumpTestIds('选完颜色')
  await shot('02b-选完颜色')

  // 5) 填净窗宽 / 净窗高
  const w = page.getByLabel('窗宽 (米)').first()
  const hgt = page.getByLabel('窗高 (米)').first()
  if (await w.count()) { await w.fill(W); console.log(`✅ 已填 窗宽 ${W}`) } else { console.log('⚠️ 未找到 窗宽 (米) 输入框') }
  if (await hgt.count()) { await hgt.fill(H); console.log(`✅ 已填 窗高 ${H}`) } else { console.log('⚠️ 未找到 窗高 (米) 输入框') }
  await page.waitForTimeout(3500)
  await dumpTestIds('填完宽高')
  await shot('03-填完宽高')

  // 6) 抓推导面板读数
  const panel = page.locator('[data-testid="craft-plan"]')
  if (await panel.count()) {
    console.log('✅ craft-plan 面板已渲染')
    for (const id of ['craft-plan-mode', 'craft-plan-source', 'craft-plan-craft', 'craft-plan-door-width', 'craft-plan-panels', 'craft-plan-splice', 'craft-plan-join-height', 'craft-plan-join-width', 'craft-plan-meters', 'craft-plan-reason']) {
      const t = await page.locator(`[data-testid="${id}"]`).first().textContent().catch(() => null)
      if (t !== null) console.log(`    ${id} = ${JSON.stringify(t.trim())}`)
    }
    const cands = await page.locator('[data-testid^="craft-plan-candidate-"]').allTextContents()
    console.log(`    candidates(${cands.length}) = ${JSON.stringify(cands.map((s) => s.replace(/\s+/g, ' ').trim()))}`)
    const feats = await page.locator('[data-testid="auto-detected-features"]').first().textContent().catch(() => null)
    if (feats) console.log(`    auto-detected-features = ${JSON.stringify(feats.replace(/\s+/g, ' ').trim())}`)
  } else {
    console.log('❌ craft-plan 面板未出现')
  }
  await page.locator('[data-testid="craft-plan"]').first().scrollIntoViewIfNeeded().catch(() => {})
  await page.waitForTimeout(500)
  await shot('04-推导面板')
  console.log('PROBE_DONE_OK')
} catch (e) {
  console.log(`PROBE_FAILED: ${String(e).slice(0, 500)}`)
  await shot('99-失败现场')
} finally {
  await browser.close()
}
