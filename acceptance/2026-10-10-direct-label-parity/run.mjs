// 复跑：node acceptance/2026-10-10-direct-label-parity/run.mjs
// 前置：① 先在 frontend/admin-web 下把 render-bitmap.tsx 拷进去并打包（命令见 README 的「怎么采的」）
//       ② Playwright 从主仓 tests/package.json 解析（本 worktree 不装）
import fs from 'node:fs'
import { createRequire } from 'node:module'
const MAIN_REPO = process.env.MIGAO_MAIN_REPO || '/Users/guangzhen.zk/ai native/migao'
const require = createRequire(`${MAIN_REPO}/tests/package.json`)
const { chromium } = require('@playwright/test')
const OUT = new URL('./out', import.meta.url).pathname
const bundle = fs.readFileSync('/tmp/wl-accept/bundle.js', 'utf8')
const browser = await chromium.launch()
const page = await browser.newPage()
const errors = []
page.on('pageerror', (e) => errors.push(String(e).split('\n')[0]))
await page.setContent('<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>')
await page.addScriptTag({ content: bundle })
await page.waitForFunction('window.__PNG', null, { timeout: 30000 })
const png = await page.evaluate('window.__PNG')
const rows = await page.evaluate('window.__ROWS')
const geometry = await page.evaluate('window.__GEOMETRY')
fs.writeFileSync(`${OUT}/01-direct-print-bitmap.png`, Buffer.from(String(png).split(',')[1], 'base64'))
fs.writeFileSync(`${OUT}/rows.json`, JSON.stringify({ geometry, rows, pageerrors: errors }, null, 2))
console.log('geometry =', JSON.stringify(geometry))
console.log('rows =', JSON.stringify(rows, null, 1))
console.log('pageerrors =', JSON.stringify(errors))
await browser.close()
