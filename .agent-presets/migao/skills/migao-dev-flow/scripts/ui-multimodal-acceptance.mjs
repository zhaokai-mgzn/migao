#!/usr/bin/env node
/**
 * Playwright 页面多模态验收 · **证据采集器**（`migao-dev-flow` §15.7 的承载体）
 *
 * 为什么有它：改 web 页面时，「断言绿 + 构建绿」**看不见**用户看到的东西（文案读不读得懂、
 * 控件挤不挤、有没有裸露的 markdown、吸底条挡不挡内容）。§15.7 要求**每轮改 web 页面都跑一轮
 * 真实浏览器的多模态验收** —— 本脚本负责**确定性地**产出那一轮的证据（截图 + DOM 逐字文本 +
 * testid 清单），判定由 AI **读图**完成（读图能力缺失时按 §15.5 用视觉模型开子代理）。
 *
 * 用法（在仓库根执行；`@playwright/test` 从 `<repo>/tests/node_modules` 解析）：
 *
 *   node .agent-presets/migao/skills/migao-dev-flow/scripts/ui-multimodal-acceptance.mjs \
 *     --path /orders/new --shot fee-summary-bar --shot door-width-details \
 *     --fill '如 6.6=3.2' --fill '如 2.6=2.6' --open-details --out /tmp/ui-acceptance
 *
 * 参数：
 *   --site <url>        站点（默认 https://merchant.migaozn.com）
 *   --path <path>       目标路径（必填，如 /orders/new）
 *   --phone/--code      登录（默认 13800138000 / 123456，走**真实 UI 登录**）
 *   --out <dir>         证据目录（默认 /tmp/ui-acceptance-<时间戳>）
 *   --width/--height    视口（默认 1440×980）
 *   --shot <testid>     额外截该元素（可重复；也接受 CSS 选择器）
 *   --fill <ph>=<val>   按 placeholder 子串填值（可重复）
 *   --click <text>      点击文本（可重复，用于展开折叠块等）
 *   --open-details      打开页面上所有 <details>
 *   --allow-login-page  允许停在登录页（**默认禁止** —— 见下）
 *
 * 产出：`01-full.png`（全页）+ `<testid>.png` + `page-text.txt`（body 逐字）+ `testids.txt` + `summary.json`。
 *
 * 🔴 **fail-closed（防假绿）**：登录未生效（仍停在 `/login`）或页面零 `data-testid` ⇒ **非零退出**。
 * 「截了一张登录页/空白页」不是验收证据 —— 它比不跑更危险（看起来做过）。
 */
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

const argv = process.argv.slice(2)
const arg = (name, dflt) => {
  const i = argv.indexOf(`--${name}`)
  return i >= 0 && argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[i + 1] : dflt
}
const argAll = (name) => argv.flatMap((a, i) => (a === `--${name}` && argv[i + 1] && !argv[i + 1].startsWith('--') ? [argv[i + 1]] : []))
const has = (name) => argv.includes(`--${name}`)

const die = (msg) => { console.error(`❌ ${msg}`); process.exit(1) }

const site = arg('site', 'https://merchant.migaozn.com').replace(/\/$/, '')
const target = arg('path')
if (!target) die('缺 `--path`（例：--path /orders/new）')
const phone = arg('phone', '13800138000')
const code = arg('code', '123456')
const width = Number(arg('width', 1440))
const height = Number(arg('height', 980))
const outDir = arg('out', `/tmp/ui-acceptance-${new Date().toISOString().replace(/[:.]/g, '-')}`)
const shots = argAll('shot')
const fills = argAll('fill')
const clicks = argAll('click')

const repoRoot = process.env.MIGAO_REPO_ROOT || process.cwd()
const require = createRequire(path.join(repoRoot, 'tests', 'package.json'))
let chromium
try {
  ;({ chromium } = require('@playwright/test'))
} catch (e) {
  die(`解析不到 @playwright/test（试过 ${path.join(repoRoot, 'tests', 'package.json')}）：先跑 \`npm --prefix tests install\``)
}

fs.mkdirSync(outDir, { recursive: true })
const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 2, locale: 'zh-CN' })
const page = await ctx.newPage()
const http5xx = []
page.on('response', (r) => { if (r.status() >= 500) http5xx.push(`${r.status()} ${r.url()}`) })

// ── 真实用户路径登录（手机验证码）───────────────────────────────────────────
await page.goto(`${site}/login`, { waitUntil: 'domcontentloaded', timeout: 60000 })
await page.waitForTimeout(1200)
await page.getByText('手机验证码', { exact: false }).first().click({ timeout: 5000 }).catch(() => {})
await page.waitForTimeout(600)
await page.locator('input[placeholder*="手机号"]').first().fill(phone)
await page.getByText('获取验证码', { exact: false }).first().click({ timeout: 5000 }).catch(() => {})
await page.waitForTimeout(1500)
await page.locator('input[placeholder*="验证码"]').first().fill(code)
await page.getByRole('button', { name: /登\s*录/ }).first().click().catch(() => {})
await page.waitForTimeout(5000)
const afterLogin = page.url()
const loginOk = !/\/login\b/.test(afterLogin)

await page.goto(`${site}${target}`, { waitUntil: 'networkidle', timeout: 90000 })
await page.waitForTimeout(2500)

for (const spec of fills) {
  const [ph, value] = spec.split('=')
  const input = page.locator(`input[placeholder*="${ph}"]`).first()
  if ((await input.count()) === 0) { console.error(`⚠️ 未找到 placeholder 含「${ph}」的输入框（跳过）`); continue }
  await input.click(); await input.fill(''); await input.type(value, { delay: 60 })
  await page.waitForTimeout(400)
}
for (const text of clicks) {
  await page.getByText(text, { exact: false }).first().click({ timeout: 5000 }).catch(() => console.error(`⚠️ 点不到「${text}」（跳过）`))
  await page.waitForTimeout(800)
}
if (has('open-details')) {
  await page.evaluate(() => { document.querySelectorAll('details:not([open])').forEach((d) => d.setAttribute('open', '')) })
  await page.waitForTimeout(800)
}

const url = page.url()
const testids = await page.evaluate(() => Array.from(document.querySelectorAll('[data-testid]')).map((e) => e.getAttribute('data-testid')))
const text = await page.evaluate(() => document.body.innerText)
await page.screenshot({ path: path.join(outDir, '01-full.png'), fullPage: true })
fs.writeFileSync(path.join(outDir, 'page-text.txt'), text)
fs.writeFileSync(path.join(outDir, 'testids.txt'), testids.join('\n'))

const shotFiles = []
for (const sel of shots) {
  const locator = sel.startsWith('[') || sel.startsWith('.') || sel.startsWith('#') ? page.locator(sel).first() : page.locator(`[data-testid="${sel}"]`).first()
  const name = sel.replace(/[^A-Za-z0-9_-]/g, '_')
  if ((await locator.count()) === 0) { console.error(`⚠️ MISSING ${sel}（元素不在 DOM ⇒ 记入 summary.missing）`); continue }
  try {
    await locator.scrollIntoViewIfNeeded(); await page.waitForTimeout(300)
    await locator.screenshot({ path: path.join(outDir, `${name}.png`) })
    shotFiles.push(`${name}.png`)
  } catch (e) { console.error(`⚠️ 截图失败 ${sel}: ${String(e).slice(0, 120)}`) }
}

const summary = { site, target, url, loginOk, afterLogin, testids: testids.length, http5xx, files: ['01-full.png', ...shotFiles, 'page-text.txt', 'testids.txt'], missingShots: shots.filter((s) => !shotFiles.includes(s.replace(/[^A-Za-z0-9_-]/g, '_'))) }
fs.writeFileSync(path.join(outDir, 'summary.json'), JSON.stringify(summary, null, 2))
await browser.close()

console.log(`\n证据目录: ${outDir}`)
console.log(`URL: ${url} ｜ testid: ${testids.length} ｜ 5xx: ${http5xx.length}`)
console.log(`截图: ${summary.files.filter((f) => f.endsWith('.png')).join(', ')}`)
if (!loginOk && !has('allow-login-page')) die(`登录未生效（停在 ${afterLogin}）—— **拒绝把登录页当验收证据**（§15.7 假绿形态①）`)
if (testids.length === 0 && !has('allow-login-page')) die('页面零 data-testid —— 疑似未渲染/被重定向，**不作为验收证据**')
console.log('✅ 证据采集完成 —— 下一步：AI **读图**逐条判定（读图能力缺失时按 §15.5 用视觉模型开子代理）')
