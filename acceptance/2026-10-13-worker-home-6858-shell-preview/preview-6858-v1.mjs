/**
 * 本地预览探针 —— issue #6848（工人工作台补「管理面外壳」：渐变页头 + 灰底 + 白卡）
 *
 * 用**真实 Taro H5 构建产物**（`frontend/bmini-app/dist`）+ 打桩的工人接口截图，
 * 目的 = 在合并前把「改后长什么样」给人看（`migao-dev-flow` §15.7 的读图前置）。
 *
 * 用法：
 *   cd frontend/bmini-app && npm run build:h5
 *   python3 -m http.server 8099 --directory dist &
 *   cd <repo>/tests && PREVIEW_BASE=http://127.0.0.1:8099 node /tmp/mg-probe/preview-6848.mjs
 */
import { chromium } from '../../tests/node_modules/playwright/index.mjs'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))

const BASE = (process.env.PREVIEW_BASE || 'http://127.0.0.1:8099').replace(/\/$/, '')
const OUT = process.env.PREVIEW_OUT || path.join(HERE, 'out')
fs.mkdirSync(OUT, { recursive: true })

const WORKER = {
  session_id: 'preview-session',
  worker_id: 'w-1',
  worker_no: 'cy-1001',
  worker_name: '赵凯',
  idle_minutes: 30,
  idle_expires_at: null,
}

const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 })
const page = await ctx.newPage()
const log = []
page.on('pageerror', (e) => log.push(`pageerror: ${String(e).slice(0, 160)}`))

// 单一日志处理器：按路径分派（避免多条 route 的匹配顺序歧义）
await page.route('**/api/**', async (route) => {
  const url = route.request().url()
  const json = (body) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  if (url.includes('/api/worker/login')) return json({ success: true, data: WORKER })
  if (url.includes('/api/worker/production/current-worker')) return json({ success: true, data: WORKER })
  return json({ success: false, message: 'preview stub' })
})

const result = { base: BASE, at: new Date().toISOString(), login: null, reads: null, shots: [] }
try {
  await page.goto(`${BASE}/#/pages/worker/login/index`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.worker-login__input', { timeout: 30000 })
  const inputs = page.locator('.worker-login__input input')
  await inputs.nth(0).fill('cy-1001')
  await inputs.nth(1).fill('246810')
  await inputs.nth(3).fill('migao')
  await page.locator('.worker-login__submit').click()
  await page.waitForTimeout(2000)
  result.login = { url: page.url() }

  await page.goto(`${BASE}/#/pages/worker/home/index`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.worker-home__primary-title', { timeout: 20000 })
  await page.waitForTimeout(1200)

  result.reads = await page.evaluate(() => {
    const pick = (sel) => {
      const el = document.querySelector(sel)
      if (!el) return null
      const cs = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      return {
        bg: cs.backgroundColor,
        image: cs.backgroundImage.slice(0, 80),
        color: cs.color,
        h: Math.round(r.height * 10) / 10,
        w: Math.round(r.width * 10) / 10,
        text: (el.textContent || '').trim().slice(0, 40),
      }
    }
    return {
      card: pick('.worker-home__card'),
      name: pick('.worker-home__worker-name'),
      no: pick('.worker-home__worker-no'),
      ghost: pick('.worker-home__ghost'),
      primary: pick('.worker-home__primary'),
      primaryTitle: pick('.worker-home__primary-title'),
      section: pick('.worker-home__section'),
      entryCount: document.querySelectorAll('.worker-home__entry').length,
      entryTitles: [...document.querySelectorAll('.worker-home__entry-text')].map((e) => e.textContent.trim()),
    }
  })
  const shot = `${OUT}/worker-home-after-390.png`
  await page.screenshot({ path: shot, fullPage: true })
  result.shots.push(shot)

  // 未登录态（gate）也要看一眼：页头在两种态下都在，引导块不被页头挤坏
  await page.evaluate(() => localStorage.clear())
  await page.goto(`${BASE}/#/pages/worker/home/index`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1200)
  const gateShot = `${OUT}/worker-home-after-gate-390.png`
  await page.screenshot({ path: gateShot, fullPage: true })
  result.shots.push(gateShot)
  result.gate = await page.evaluate(() => ({
    gate: Boolean(document.querySelector('.worker-home__gate')),
    primary: Boolean(document.querySelector('.worker-home__primary')),
  }))
} catch (e) {
  result.fatal = String(e && e.message ? e.message : e)
} finally {
  await browser.close()
}
result.log = log.slice(0, 5)
console.log(JSON.stringify(result, null, 2))
process.exit(result.fatal || !result.reads?.primary ? 1 : 0)
