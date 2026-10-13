/**
 * 部署后读图重放探针 —— issue #6763（`app.migaozn.com/w/` 报工页页头按钮折行）
 *
 * 判据（与 issue #6763 的修前读数**同口径**）：360 / 390 / 430 三视口下，页头两个按钮的文字
 *   **行盒数 == 1**（`Range.getClientRects()`；折行 ⇒ 2）+ 无横向溢出 + 触控目标仍 ≥44px。
 *
 * 🔴 **为什么不能判高度 / `scrollWidth`**（本包实测踩过）：
 *   `.wh5-ghost` 有 `min-height: 44px`，折成两行仍被 44px 包住 ⇒ 高度不是判别量；
 *   而「折行」也没有横向溢出（修前 `scrollWidth <= clientWidth` 照样成立）⇒ 它也不是。
 *   唯一判别量 = **文字节点的行盒数**。
 *
 * 用法：
 *   cd <repo>/tests
 *   node ../acceptance/2026-10-13-worker-h5-header-6763-replay/worker-h5-header-6763-replay.mjs [BASE_URL]
 *   环境变量：PROBE_OUT（截图目录，默认 = 本脚本同目录的 out/）
 *             PROBE_WORKER_NO / PROBE_PIN / PROBE_ENTERPRISE（默认 = issue #6763 现场用的验收工人身份）
 *
 * 退出码：0 = 三个视口下两个按钮都是单行且不溢出；非零 = 有视口不达标或登录失败（fail-closed）。
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
const VIEWPORTS = [360, 390, 430]

const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 })
const page = await ctx.newPage()
const result = { base: BASE, at: new Date().toISOString(), login: null, viewports: {}, shots: [] }

try {
  await page.goto(`${BASE}/w/`, { waitUntil: 'domcontentloaded' })

  // 未登录 ⇒ 先登录（真工人身份；输入面 id 见 frontend/worker-h5/src/render.mjs 的 loginView）
  if (await page.locator('#wh5-login').count()) {
    await page.fill('#wh5-enterprise-code', ENTERPRISE)
    await page.fill('#wh5-worker-no', WORKER_NO)
    await page.fill('#wh5-pin', PIN)
    await page.click('#wh5-login')
  }
  await page.waitForSelector('#wh5-switch', { timeout: 30000 })
  result.login = { headerText: ((await page.locator('#wh5-current-worker').textContent().catch(() => '')) || '').trim() }

  for (const width of VIEWPORTS) {
    await page.setViewportSize({ width, height: 844 })
    await page.waitForTimeout(300)
    result.viewports[width] = await page.evaluate(() => {
      const read = (sel) => {
        const el = document.querySelector(sel)
        if (!el) return null
        const range = document.createRange()
        range.selectNodeContents(el)
        const r = el.getBoundingClientRect()
        return {
          text: (el.textContent || '').trim(),
          lines: [...range.getClientRects()].length,
          scrollWidth: el.scrollWidth,
          clientWidth: el.clientWidth,
          height: Math.round(r.height * 10) / 10,
          width: Math.round(r.width * 10) / 10,
        }
      }
      const worker = document.querySelector('#wh5-current-worker')
      let workerReading = null
      if (worker) {
        const range = document.createRange()
        range.selectNodeContents(worker)
        workerReading = {
          width: Math.round(worker.getBoundingClientRect().width * 10) / 10,
          lines: [...range.getClientRects()].length,
        }
      }
      return { worker: workerReading, switch: read('#wh5-switch'), logout: read('#wh5-logout') }
    })
    const shot = path.join(OUT, `worker-h5-header-${width}.png`)
    await page.screenshot({ path: shot, fullPage: false })
    result.shots.push(shot)
  }
} catch (e) {
  result.fatal = String(e && e.message ? e.message : e)
} finally {
  await browser.close()
}

console.log(JSON.stringify(result))
const bad = VIEWPORTS.filter((w) => {
  const v = result.viewports[w]
  return !v || v.switch?.lines !== 1 || v.logout?.lines !== 1 || v.switch?.scrollWidth > v.switch?.clientWidth
})
process.exit(result.fatal || bad.length ? 1 : 0)
