/**
 * 登录页 / 首次改密页「产品定位文案」截图取证（issue #6463）。
 *
 * 用法（在**本仓根**执行，dev server 已起在 :3001）：
 *   node acceptance/2026-10-07-positioning-copy/shot-login-copy.mjs "$PWD" "$PWD/acceptance/2026-10-07-positioning-copy/out" http://localhost:3001
 *
 * 为什么不用 mock：页面来自 `npm run dev` 起的**本分支真实构建**，不注入 token、不替换接口。
 * …@playwright/test 从 `<repo>/tests/node_modules` 解析（与官方载体同一处，不跨工作区共享依赖）。
 */
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

const repoRoot = process.argv[2]
const outDir = process.argv[3]
const site = process.argv[4] || 'http://localhost:3001'
const require = createRequire(path.join(repoRoot, 'tests', 'package.json'))
const { chromium } = require('@playwright/test')
fs.mkdirSync(outDir, { recursive: true })

const pickSubtitle = (texts) => texts.find((t) => t.includes('经营管理') || t.includes('电商')) || null
const result = {}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 980 } })
const page = await ctx.newPage()

await page.goto(`${site}/login`, { waitUntil: 'domcontentloaded' })
await page.getByText('米高', { exact: true }).first().waitFor({ timeout: 30000 })
await page.locator('input').first().waitFor({ state: 'visible', timeout: 30000 })
result.loginUrl = page.url()
result.loginTitle = await page.title()
result.loginSubtitle = pickSubtitle(await page.locator('p').allInnerTexts())
await page.screenshot({ path: path.join(outDir, '01-login-full.png'), fullPage: true })
fs.writeFileSync(path.join(outDir, 'page-text-login.txt'), await page.innerText('body'), 'utf8')
fs.writeFileSync(
  path.join(outDir, 'testids-login.txt'),
  (await page.$$eval('[data-testid]', (els) => els.map((e) => e.getAttribute('data-testid')))).join('\n'),
  'utf8',
)

await page.goto(`${site}/change-password`, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(3000)
result.changePasswordUrl = page.url()
result.changePasswordTitle = await page.title()
result.changePasswordSubtitle = pickSubtitle(await page.locator('p').allInnerTexts())
await page.screenshot({ path: path.join(outDir, '02-change-password.png'), fullPage: true })
fs.writeFileSync(path.join(outDir, 'page-text-change-password.txt'), await page.innerText('body'), 'utf8')

fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(result, null, 2), 'utf8')
await browser.close()
console.log(JSON.stringify(result, null, 2))
