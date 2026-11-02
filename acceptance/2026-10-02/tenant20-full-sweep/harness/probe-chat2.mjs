// 07-chat 深挖：SessionList 是否挂载 / 折叠态 / 面板宽度 / sessions API 是否发起
import { createRequire } from 'module'
const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('playwright')

const BASE = 'http://localhost:3001'
const browser = await chromium.launch({ headless: true })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()

const reqs = []
page.on('request', (r) => { if (/agent|session|chat/i.test(r.url())) reqs.push(`${r.method()} ${r.url().replace(BASE, '')}`) })
page.on('response', (r) => { if (/agent|session|chat/i.test(r.url()) && r.status() >= 400) reqs.push(`→ ${r.status()} ${r.url().replace(BASE, '')}`) })

await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded', timeout: 25000 })
await page.getByRole('tab', { name: /管理员登录/ }).click()
await page.waitForSelector('#phone', { timeout: 45000 })
await page.fill('#phone', '13870217889')
await page.getByRole('button', { name: /获取验证码/ }).click()
await page.waitForTimeout(1200)
await page.fill('#code', '123456')
await page.getByRole('button', { name: /登\s*录|登录/ }).last().click()
await page.waitForURL('**/dashboard**', { timeout: 20000 })

reqs.length = 0
await page.goto(`${BASE}/chat`, { waitUntil: 'domcontentloaded', timeout: 20000 })
await page.waitForTimeout(4000)

const dump = await page.evaluate(() => {
  const q = (sel) => document.querySelector(sel)
  const all = (sel) => [...document.querySelectorAll(sel)].map((el) => ({
    text: (el.textContent || '').slice(0, 60),
    cls: (el.className || '').toString().slice(0, 80),
    w: el.getBoundingClientRect().width, h: el.getBoundingClientRect().height,
  }))
  return {
    bodyLen: document.body.innerText.length,
    buttons: all('button').slice(0, 10),
    textareas: document.querySelectorAll('textarea').length,
    lsKeys: Object.keys(localStorage),
    mibaoPanel: q('[class*="mibao"]') ? { w: q('[class*="mibao"]').getBoundingClientRect().width } : null,
    collapsedRail: !!q('[aria-label*="展开"], [title*="展开"]'),
  }
})
console.log(JSON.stringify(dump, null, 1))
console.log('---- chat 相关请求 ----')
reqs.slice(0, 20).forEach((r) => console.log(r))
await page.screenshot({ path: '/tmp/probe-chat2.png' })
await browser.close()
