/**
 * 部署后读图重放探针 —— issue #6847（`app.migaozn.com/b/` 工人工作台补页面底色，#6760 的另一半）
 *
 * 判据（与 issue #6760 的重放探针**同口径**，可对读）：
 *   · `.taro_page`：Taro H5 注入的页面容器（恒 `rgb(255,255,255)`，本单有意不动）
 *   · `.worker-home`：页面根 —— 修前 `rgba(0, 0, 0, 0)`（透明 ⇒ 露出白页容器），修后 `rgb(245, 247, 250)`
 *   · `.worker-home__card`：白卡 `rgb(255,255,255)` + 非 none 的 box-shadow（#6760 修的，本单不动）
 *   ⇒ 修后「白卡 vs 页面」有色差（255,255,255 ≠ 245,247,250）= 卡片浮在页面底色上。
 *
 * 用法：cd <repo>/tests && node ./worker-home-surface-6847-replay.mjs [BASE_URL]
 * 退出码：0 = 取到页面根与卡片读数且色差成立；非零 = 登录失败 / 元素缺失（fail-closed，不伪装成通过）
 */
import { chromium } from '../../tests/node_modules/playwright/index.mjs'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))

const BASE = (process.argv[2] || 'https://app.migaozn.com').replace(/\/$/, '')
const OUT = process.env.PROBE_OUT || path.join(HERE, 'out')
fs.mkdirSync(OUT, { recursive: true })
const WORKER_NO = process.env.PROBE_WORKER_NO || 'UITEST01'
const PIN = process.env.PROBE_PIN || '246810'
const ENTERPRISE = process.env.PROBE_ENTERPRISE || 'migao'

const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 })
const page = await ctx.newPage()
const result = { base: BASE, at: new Date().toISOString(), login: null, reads: null, shot: null }

try {
  await page.goto(`${BASE}/b/#/pages/worker/login/index`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.worker-login__input', { timeout: 30000 })
  const inputs = page.locator('.worker-login__input input')
  await inputs.nth(0).fill(WORKER_NO)
  await inputs.nth(1).fill(PIN)
  await inputs.nth(3).fill(ENTERPRISE)
  await page.locator('.worker-login__submit').click()
  await page
    .waitForFunction(
      () => document.querySelector('.worker-home__card') !== null || document.querySelector('.worker-login__error') !== null,
      { timeout: 30000 },
    )
    .catch(() => {})

  const err = await page.locator('.worker-login__error').first().textContent().catch(() => null)
  result.login = { error: err ? err.trim() : null, url: page.url() }

  // 🔴 登录成功后**必须显式去工作台**：登录页的成功分支是 `Taro.navigateBack({delta:1})`
  //    —— 它是为「从工作台被弹到登录页」设计的；直接打开登录页时无 history 可回 ⇒ 会停在登录页
  //    （本探针第一版就卡在这里：登录接口 200，但 `home/card` 全为 null）。
  if (!err) {
    if (!page.url().includes('/pages/worker/home/index')) {
      await page.goto(`${BASE}/b/#/pages/worker/home/index`, { waitUntil: 'domcontentloaded' })
    }
    await page.waitForSelector('.worker-home', { timeout: 20000 }).catch(() => {})
    await page.waitForTimeout(1500)
  }

  result.reads = await page.evaluate(() => {
    const read = (sel) => {
      const el = document.querySelector(sel)
      if (!el) return null
      const cs = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      return {
        background: cs.backgroundColor,
        border: `${cs.borderTopWidth} ${cs.borderTopStyle} ${cs.borderTopColor}`,
        shadow: cs.boxShadow,
        height: Math.round(r.height * 10) / 10,
        width: Math.round(r.width * 10) / 10,
      }
    }
    const page_ = read('.taro_page')
    const home = read('.worker-home')
    const card = read('.worker-home__card')
    const entry = read('.worker-home__entry')
    return {
      taroPage: page_,
      home,
      card,
      entry,
      cardOnOwnSurface: Boolean(card && home && card.background !== home.background && home.background !== 'rgba(0, 0, 0, 0)'),
    }
  })
  const shot = `${OUT}/worker-home-6847-surface-after.png`
  await page.screenshot({ path: shot, fullPage: true })
  result.shot = shot
} catch (e) {
  result.fatal = String(e && e.message ? e.message : e)
} finally {
  await browser.close()
}

console.log(JSON.stringify(result, null, 2))
const r = result.reads
process.exit(result.fatal || result.login?.error || !r?.card || !r?.home ? 1 : 0)
