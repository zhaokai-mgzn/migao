/**
 * 工人工作台「菜单重排」的部署后重放探针 —— issue #6858（`app.migaozn.com/b/`）
 *
 * 目的：把用户那句「不太符合我们整体样式设计 / 为什么搞成纯白色背景」变成**可复算的机器读数**：
 *   · 身份条 `.worker-home__card`（姓名 / 工号 / 「退出」按钮的宽高）
 *   · 常驻主按钮 `.worker-home__primary`（`#1a73e8` 实心 + 标题「扫码领活」）
 *   · 分组小标题 `.worker-home__section`（「其他功能」）
 *   · 三张行卡 `.worker-home__entry`（标题 + 一句副标 + 左色彩条底色）
 *   · 未登录态：`gate` 在、主按钮不在（不渲染写入口）
 *
 * 同口径的**修前**读数（#6847 部署后实测，本单是它的下一刀）：
 *   页面只有「当前工人」三行白卡 + 四条等权入口，**没有主按钮、没有身份条、没有副标** —— 见
 *   `acceptance/2026-10-13-worker-home-6760-replay/out/worker-home-6847-surface-after.png` 与 README §7。
 *
 * 用法：
 *   cd <repo>/tests
 *   node ../acceptance/2026-10-13-worker-home-6858-shell-preview/worker-home-6858-replay.mjs [BASE_URL]
 *   环境变量：PROBE_OUT（截图目录，默认 = 本脚本同目录的 out/）
 *             PROBE_WORKER_NO / PROBE_PIN / PROBE_ENTERPRISE（默认 = 验收工人身份）
 *
 * 退出码：0 = 登录成功且取到身份条 + 主按钮 + 3 张行卡；非零 = 任一缺失（fail-closed，不伪装成通过）。
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
const result = { base: BASE, viewport: '390x844', at: new Date().toISOString(), login: null, reads: null, shots: [] }

try {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 })
  const page = await ctx.newPage()
  await page.goto(`${BASE}/b/#/pages/worker/login/index`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.worker-login__input', { timeout: 30000 })

  // 输入面顺序（见 frontend/bmini-app/src/pages/worker/login/index.tsx）：工号 / PIN / 设备标签 / 企业编码
  const inputs = page.locator('.worker-login__input input')
  await inputs.nth(0).fill(WORKER_NO)
  await inputs.nth(1).fill(PIN)
  await inputs.nth(3).fill(ENTERPRISE)
  await page.locator('.worker-login__submit').click()
  await page
    .waitForFunction(
      () =>
        document.querySelector('.worker-home__card') !== null ||
        document.querySelector('.worker-login__error') !== null,
      { timeout: 30000 },
    )
    .catch(() => {})
  const err = await page.locator('.worker-login__error').first().textContent().catch(() => null)
  result.login = { error: err || null }

  // 登录成功走 navigateBack，首个历史项时是空操作 ⇒ 显式落到工作台
  await page.goto(`${BASE}/b/#/pages/worker/home/index`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.worker-home__card', { timeout: 20000 })
  await page.waitForTimeout(1200)

  result.reads = await page.evaluate(() => {
    const pick = (sel) => {
      const el = document.querySelector(sel)
      if (!el) return null
      const cs = getComputedStyle(el)
      const r = el.getBoundingClientRect()
      return {
        text: (el.textContent || '').trim().slice(0, 60),
        bg: cs.backgroundColor,
        color: cs.color,
        border: `${cs.borderTopWidth} ${cs.borderTopStyle} ${cs.borderTopColor}`,
        shadow: cs.boxShadow,
        h: Math.round(r.height * 10) / 10,
        w: Math.round(r.width * 10) / 10,
      }
    }
    return {
      taroPageBg: pick('.taro_page')?.bg ?? null,
      pageBg: pick('.worker-home')?.bg ?? null,
      identity: pick('.worker-home__card'),
      name: pick('.worker-home__worker-name'),
      no: pick('.worker-home__worker-no'),
      status: pick('.worker-home__worker-status'),
      exit: pick('.worker-home__ghost'),
      primary: pick('.worker-home__primary'),
      primaryTitle: pick('.worker-home__primary-title'),
      primarySub: pick('.worker-home__primary-sub'),
      section: pick('.worker-home__section'),
      entries: [...document.querySelectorAll('.worker-home__entry')].map((el) => ({
        title: el.querySelector('.worker-home__entry-text')?.textContent?.trim() ?? null,
        sub: el.querySelector('.worker-home__entry-sub')?.textContent?.trim() ?? null,
        bar: el.querySelector('.worker-home__entry-bar')
          ? getComputedStyle(el.querySelector('.worker-home__entry-bar')).backgroundColor
          : null,
        h: Math.round(el.getBoundingClientRect().height * 10) / 10,
      })),
    }
  })

  const shot = path.join(OUT, 'worker-home-6858-live-390.png')
  await page.screenshot({ path: shot, fullPage: true })
  result.shots.push(shot)

  // 未登录态：主按钮不该在（不渲染写入口）
  await page.evaluate(() => localStorage.clear())
  await page.goto(`${BASE}/b/#/pages/worker/home/index`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1200)
  result.gate = await page.evaluate(() => ({
    gate: Boolean(document.querySelector('.worker-home__gate')),
    primary: Boolean(document.querySelector('.worker-home__primary')),
  }))
  const gateShot = path.join(OUT, 'worker-home-6858-live-gate-390.png')
  await page.screenshot({ path: gateShot, fullPage: true })
  result.shots.push(gateShot)
  await ctx.close()
} catch (e) {
  result.fatal = String(e && e.message ? e.message : e)
} finally {
  await browser.close()
}
console.log(JSON.stringify(result, null, 2))

const r = result.reads
const ok =
  !result.fatal &&
  Boolean(r?.identity) &&
  r?.primary?.bg === 'rgb(26, 115, 232)' &&
  (r?.entries?.length ?? 0) === 3 &&
  result.gate?.gate === true &&
  result.gate?.primary === false
process.exit(ok ? 0 : 1)
