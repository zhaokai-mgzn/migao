/**
 * 试用前 UI 金路径 · 多模态验收运行器（admin-web 面）
 * 一次跑完，产出：逐场景截图（viewport，不用 fullPage：fixed 元素会被挪动）+ readings.json（断言读数）
 *
 * 场景：
 *  S1 登录（**不点发送验证码**，零额度）→ 落到非 /login
 *  S2 工作台：金额/订单读数形态（不得出现 NaN/undefined/[object Object]）
 *  S3 商品列表：表格渲染 + 浮球几何判定（该点归属浮球 ∧ 摘掉浮球后属于该元素本身）
 *  S4 余料台账：分页控件在场 + 翻页真发 page=2 + 行集合真换（#6697）
 *  S5 读失败注入：失败锚点 + 可行动文案 + 重试出口（#6691 口径），并核对**不得**把失败画成 0
 *  S6 屏面卫生：UUID/24位ObjectId/snake_case 内部键/机翻值/残留加载态（§31 不摆内部标识）
 */
import { createRequire } from 'node:module'
import { mkdirSync, writeFileSync } from 'node:fs'
const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('@playwright/test')
const BASE = process.env.ADMIN_WEB_BASE || 'http://localhost:3001'
const OUT = new URL('./evidence', import.meta.url).pathname
mkdirSync(OUT, { recursive: true })
const R = { when: new Date().toISOString(), base: BASE, sections: {} }

const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 980 } })
const page = await ctx.newPage()
const apiSeen = []
page.on('response', (r) => { if (r.url().includes('/api/')) apiSeen.push(r.status() + ' ' + r.url().replace(/^https?:\/\/[^/]+/, '')) })

// ── S1 登录
await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('input', { timeout: 60000 })
await page.waitForTimeout(1200)
try { await page.getByRole('tab', { name: /管理员登录/ }).first().click({ timeout: 8000 }) } catch { await page.getByText('管理员登录', { exact: false }).first().click({ timeout: 8000 }).catch(() => {}) }
await page.getByLabel('手机号', { exact: false }).first().fill('13800138000')
await page.getByLabel('验证码', { exact: false }).first().fill('123456')
await page.screenshot({ path: `${OUT}/S1-login-form.png` })
await page.getByRole('button', { name: /登\s*录/ }).first().click()
await page.waitForURL((u) => !/^\/login\b/.test(u.pathname), { timeout: 30000 })
await page.waitForTimeout(3000)
await page.screenshot({ path: `${OUT}/S1-after-login.png` })
R.sections.S1_login = { landedOn: new URL(page.url()).pathname, smsSendCalled: apiSeen.some((a) => /sms\/send/.test(a)) }

// ── S2 工作台
await page.goto(BASE + '/dashboard', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(4500)
await page.screenshot({ path: `${OUT}/S2-dashboard.png` })
R.sections.S2_dashboard = await page.evaluate(() => {
  const t = document.body.innerText || ''
  return {
    badValues: (t.match(/undefined|NaN|\[object Object\]|Infinity/g) || []).slice(0, 4),
    moneySamples: (t.match(/[¥￥]\s?[\d,.]+/g) || []).slice(0, 6),
    failBanner: !!document.querySelector('[data-testid="dashboard-load-failed"]'),
    loadingLeft: (t.match(/加载中/g) || []).length,
  }
})

// ── S3 商品列表 + 浮球几何
await page.goto(BASE + '/products', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(4000)
await page.screenshot({ path: `${OUT}/S3-products.png` })
R.sections.S3_products_fab = await page.evaluate(() => {
  const fab = document.querySelector('button.fixed.bottom-6.right-6') || document.querySelector('button.fixed')
  const rows = document.querySelectorAll('table tbody tr').length
  if (!fab) return { rows, fab: null }
  const f = fab.getBoundingClientRect()
  const main = document.querySelector('main') || document.body
  const out = []
  for (const e of Array.from(main.querySelectorAll('a, button'))) {
    const b = e.getBoundingClientRect()
    if (!(b.width > 0 && b.height > 0 && b.top < f.bottom + 6 && b.bottom > f.top - 6)) continue
    const cx = Math.round(b.left + b.width / 2), cy = Math.round(b.top + b.height / 2)
    if (cx < 0 || cy < 0 || cx > innerWidth || cy > innerHeight) continue
    const el = document.elementFromPoint(cx, cy)
    if (!el || !fab.contains(el)) continue
    const parent = fab.parentElement, next = fab.nextSibling
    fab.remove()
    const el2 = document.elementFromPoint(cx, cy)
    const stolen = !!el2 && (el2 === e || e.contains(el2))
    parent.insertBefore(fab, next)
    if (stolen) out.push({ t: (e.textContent || '').trim().slice(0, 8), x: Math.round(b.left), y: Math.round(b.top) })
  }
  return { rows, fab: { l: Math.round(f.left), t: Math.round(f.top) }, stolen: out.length, details: out }
})

// ── S4 余料台账分页
const api4 = []
page.on('response', (r) => { if (r.url().includes('/production/remnants')) api4.push(r.url().replace(/^https?:\/\/[^/]+/, '')) })
await page.goto(BASE + '/production/remnants', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(5000)
const readRows = () => page.evaluate(() => {
  const ids = Array.from(document.querySelectorAll('[data-testid^="remnant-row-"]')).map((e) => e.getAttribute('data-testid'))
  const pager = document.querySelector('[data-testid="remnant-pagination"]')
  return { rows: ids.length, first: ids[0] || null, last: ids[ids.length - 1] || null, pager: !!pager, pagerText: (pager?.textContent || '').trim().slice(0, 46), totalLine: (document.body.innerText.match(/共\s?\d+\s?块/) || [])[0] || null }
})
const p1 = await readRows()
await page.screenshot({ path: `${OUT}/S4-remnants-page1.png` })
const clicked = await page.getByRole('button', { name: '2', exact: true }).first().click({ timeout: 8000 }).then(() => true).catch(() => false)
await page.waitForTimeout(4500)
const p2 = await readRows()
await page.screenshot({ path: `${OUT}/S4-remnants-page2.png` })
R.sections.S4_remnants_paging = { page1: p1, page2: p2, clickedPage2: clicked, page2Requested: api4.some((u) => /page=2/.test(u)), rowsChanged: p1.first !== p2.first }

// ── S5 读失败注入（余料台账读面 500）
await page.route('**/api/admin/production/remnants**', (route) => route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ success: false, error: { code: 'INTERNAL_ERROR', message: '验收注入' } }) }))
await page.goto(BASE + '/production/remnants', { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(2200)
const earlyToast = await page.evaluate(() => Array.from(document.querySelectorAll('[data-sonner-toast],[role=alert]')).map((e) => (e.textContent || '').trim().slice(0, 40)).filter(Boolean).slice(0, 4))
await page.waitForTimeout(3000)
await page.screenshot({ path: `${OUT}/S5-remnants-read-failure.png` })
R.sections.S5_read_failure = await page.evaluate(() => {
  const t = document.body.innerText || ''
  const tid = Array.from(document.querySelectorAll('[data-testid]')).map((e) => e.getAttribute('data-testid'))
  return {
    failAnchors: tid.filter((x) => /error|fail|retry/i.test(x || '')).slice(0, 6),
    actionable: (t.match(/[^\n]*(稍后重试|重试|失败|读不到|不可用)[^\n]*/g) || []).slice(0, 4),
    rows: document.querySelectorAll('[data-testid^="remnant-row-"]').length,
    fakeZero: (t.match(/共\s?0\s?块/g) || []).slice(0, 2),
  }
})
R.sections.S5_read_failure.earlyToast = earlyToast
await page.unroute('**/api/admin/production/remnants**')

// ── S6 屏面卫生（多页）
const hygiene = []
for (const p of ['/products', '/orders', '/inbound-orders', '/customers', '/finance', '/production/remnants', '/stock-ledger', '/notifications']) {
  await page.goto(BASE + p, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(2600)
  const r = await page.evaluate(() => {
    const t = document.body.innerText || ''
    return {
      uuid: (t.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/gi) || []).length,
      objectId: (t.match(/\b[0-9a-f]{24}\b/gi) || []).length,
      snake: [...new Set(t.match(/\b[a-z][a-z0-9]*_[a-z0-9_]+\b/g) || [])].slice(0, 3),
      bad: [...new Set(t.match(/undefined|NaN|\[object Object\]/g) || [])].slice(0, 3),
      loading: (t.match(/加载中/g) || []).length,
    }
  })
  hygiene.push({ path: p, ...r })
}
R.sections.S6_hygiene = hygiene

R.apiSeenSample = [...new Set(apiSeen)].slice(0, 12)
writeFileSync(`${OUT}/readings.json`, JSON.stringify(R, null, 2))
console.log(JSON.stringify(R, null, 1))
await browser.close()
