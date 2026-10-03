// 07-chat 空白页专项探针：s4 同款登录 → /chat → 抓 console/pageerror/HTTP≥400
import { createRequire } from 'module'
const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('playwright')

const BASE = 'http://localhost:3001'

const browser = await chromium.launch({ headless: true })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()

const logs = []
page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) logs.push(`[console.${m.type()}] ${m.text().slice(0, 300)}`) })
page.on('pageerror', (e) => logs.push(`[pageerror] ${String(e).slice(0, 400)}`))
page.on('response', (r) => { if (r.status() >= 400) logs.push(`[HTTP ${r.status()}] ${r.url().slice(0, 160)}`) })

// s4 同款登录
await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 25000 })
await page.getByRole('tab', { name: /管理员登录/ }).click()
await page.waitForSelector('#phone', { timeout: 45000 })
await page.fill('#phone', '13870217889')
await page.getByRole('button', { name: /获取验证码/ }).click()
await page.waitForTimeout(1200)
await page.fill('#code', '123456')
await page.getByRole('button', { name: /登\s*录|登录/ }).last().click()
await page.waitForURL('**/dashboard**', { timeout: 20000 })
console.log('login ok →', page.url())

logs.length = 0 // 登录期噪音不混入
await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded', timeout: 20000 })
await page.waitForTimeout(4000)
const info = await page.evaluate(() => ({
  bodyLen: document.body.innerText.length,
  bodyHead: document.body.innerText.slice(0, 200),
  textareas: document.querySelectorAll('textarea, input[type="text"]').length,
  gateDenied: !!document.querySelector('[data-testid="mibao-gate-denied"]'),
}))
console.log('chat =', JSON.stringify(info))
console.log('---- /chat console/pageerror/HTTP≥400 ----')
logs.slice(0, 40).forEach((l) => console.log(l))
await page.screenshot({ path: '/tmp/probe-chat.png' })
await browser.close()
