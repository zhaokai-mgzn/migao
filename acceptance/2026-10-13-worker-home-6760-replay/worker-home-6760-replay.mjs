/**
 * 工人工作台样式修复的部署后重放探针 —— issue #6760（`app.migaozn.com/b/`）
 *
 * 目的：把「登录后像没样式」变成**可复算的机器读数**，与 issue #6760 正文/评论里的修前读数**同口径**：
 *   · `.taro_page`（Taro H5 注入的页面容器，恒白底）
 *   · `.worker-home__card` / `.worker-home__entry` 的 backgroundColor / border / boxShadow
 *   · 修前：card bg=rgb(255,255,255)、border=0px none、shadow=none（与 .taro_page 逐值同色 ⇒ 屏上无卡片）
 *   · 修后：card 有非 none 的 box-shadow；entry 有 1px border + shadow
 *   · 入口条数：修前 3；#6761 上线后 4（「拍照发货」）
 *
 * 用法：
 *   cd <repo>/tests
 *   node ../acceptance/2026-10-13-worker-home-6760-replay/worker-home-6760-replay.mjs [BASE_URL]
 *   环境变量：PROBE_OUT（截图目录，默认 = 本脚本同目录的 out/）
 *             PROBE_WORKER_NO / PROBE_PIN / PROBE_ENTERPRISE（默认 = issue #6760 用的验收工人身份）
 *
 * 退出码：0 = 登录成功且取到 `.worker-home__card`；非零 = 登录失败 / 页面没渲染出该卡片（fail-closed，不伪装成通过）。
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
const result = { base: BASE, viewport: '390x844', at: new Date().toISOString(), login: null, reads: null, shot: null }

try {
  await page.goto(`${BASE}/b/#/pages/worker/login/index`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.worker-login__input', { timeout: 30000 })

  // 输入面顺序（见 frontend/bmini-app/src/pages/worker/login/index.tsx）：工号 / PIN / 设备标签 / 企业编码
  const inputs = page.locator('.worker-login__input input')
  await inputs.nth(0).fill(WORKER_NO)
  await inputs.nth(1).fill(PIN)
  await inputs.nth(3).fill(ENTERPRISE)
  await page.locator('.worker-login__submit').click()

  // 结果只有两种：落到工人工作台，或出现 `.worker-login__error`
  await page
    .waitForFunction(
      () =>
        document.querySelector('.worker-home__card') !== null ||
        document.querySelector('.worker-login__error') !== null,
      { timeout: 30000 },
    )
    .catch(() => {})

  const err = await page.locator('.worker-login__error').first().textContent().catch(() => null)
  result.login = {
    error: err,
    hasWorkerSession: Boolean(await page.evaluate(() => localStorage.getItem('worker_session_id'))),
  }

  if (!err) {
    if (!page.url().includes('/pages/worker/home/index')) {
      await page.goto(`${BASE}/b/#/pages/worker/home/index`, { waitUntil: 'domcontentloaded' })
    }
    await page.waitForSelector('.worker-home', { timeout: 20000 }).catch(() => {})
    await page.waitForTimeout(1500)
  }

  result.reads = await page.evaluate(() => {
    const pick = (sel) => {
      const el = document.querySelector(sel)
      if (!el) return null
      const cs = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      return {
        sel,
        bg: cs.backgroundColor,
        borderTop: `${cs.borderTopWidth} ${cs.borderTopStyle} ${cs.borderTopColor}`,
        shadow: cs.boxShadow,
        h: +r.height.toFixed(1),
        w: +r.width.toFixed(1),
      }
    }
    return {
      hash: location.hash,
      taro_page: pick('.taro_page'),
      body: pick('body'),
      home: pick('.worker-home'),
      card: pick('.worker-home__card'),
      entry: pick('.worker-home__entry'),
      gate: pick('.worker-home__gate'),
      entries: document.querySelectorAll('.worker-home__entry').length,
      icons: document.querySelectorAll('.worker-home svg, .worker-home img').length,
      cardText: (document.querySelector('.worker-home__card') || {}).innerText || null,
    }
  })

  result.shot = path.join(OUT, 'worker-home-6760-live.png')
  await page.screenshot({ path: result.shot, fullPage: true })
} catch (e) {
  result.fatal = String(e && e.message ? e.message : e)
} finally {
  await browser.close()
}

console.log(JSON.stringify(result))
process.exit(result.fatal || result.login?.error || !result.reads?.card ? 1 : 0)
