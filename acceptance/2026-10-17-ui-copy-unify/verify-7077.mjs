// 临时验收脚本（issue #7077 的多模态读图轮，跑完即删）
import { createRequire } from 'node:module'
import { mkdirSync } from 'node:fs'

const REPO_ROOT = '/Users/guangzhen.zk/ai native/migao'
const { chromium } = createRequire(`${REPO_ROOT}/tests/package.json`)('playwright')
const OUT = '/tmp/shots-7077'
mkdirSync(OUT, { recursive: true })
const BASE = 'http://localhost:3001'

const browser = await chromium.launch({ headless: true })
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
const page = await ctx.newPage()
page.on('console', (m) => {
  if (m.type() === 'error') console.log('[console.error]', m.text().slice(0, 160))
})

await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
const phone = page.locator('#phone')
if (!(await phone.isVisible().catch(() => false))) {
  await page.getByRole('tab', { name: /管理员|手机/ }).first().click()
  await page.waitForTimeout(400)
}
await page.fill('#phone', '13800138000')
await page.fill('#code', '123456')
const btns = await page.locator('button:visible').allInnerTexts()
console.log('可见按钮:', JSON.stringify(btns).slice(0, 300))
await page.locator('button[type="submit"]:visible').last().click()
await page.waitForURL(/dashboard|\/settings|\/orders/, { timeout: 30000 }).catch(() => {})
await page.waitForTimeout(2500)
console.log('登录后 URL:', page.url())

async function domainShot(name) {
  await page.goto(`${BASE}/settings`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2000)
  const nav = page.getByRole('button', { name: new RegExp(name) })
  if (await nav.count()) {
    await nav.first().click()
  } else {
    await page.getByText(name, { exact: false }).first().click()
  }
  await page.waitForTimeout(1800)
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true })
  console.log('已截图', name)
}

await domainShot('算料口径')
await domainShot('余料尺寸')

await page.goto(`${BASE}/production`, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(3000)
await page.screenshot({ path: `${OUT}/生产看板.png`, fullPage: true })
console.log('已截图 生产看板')

await page.goto(`${BASE}/production/pool`, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(3500)
const boxes = page.locator('input[type="checkbox"]')
const n = Math.min(await boxes.count(), 12)
for (let i = 0; i < n; i++) await boxes.nth(i).check().catch(() => {})
await page.waitForTimeout(4000)
await page.screenshot({ path: `${OUT}/智能派单.png`, fullPage: true })
console.log('已截图 智能派单（勾了', n, '行）')

await browser.close()
