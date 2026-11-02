// 探针：浏览器里到底有没有装上 `performance.measure` 区间守卫（issue #6946 的根因判别）。
// 用法：node acceptance/2026-10-14/tools/probe-timing-guard.mjs [url...]
// 读数：`installed` = 守卫自己打的标记；`negativeMeasureThrows` = 直接构造负区间看浏览器抛不抛。
import { createRequire } from 'node:module'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
// playwright 挂在仓库 tests/node_modules（与 scripts/ui-smoke-merchant/spec.mjs 同口径）
const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
const { chromium } = createRequire(join(REPO_ROOT, 'tests', 'package.json'))('playwright')

const urls = process.argv.slice(2)
const targets = urls.length ? urls : ['http://localhost:3001/login', 'http://localhost:3001/processing']

const browser = await chromium.launch()
const page = await browser.newPage()
const pageErrors = []
page.on('pageerror', (e) => pageErrors.push(String(e).slice(0, 160)))

for (const url of targets) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 25000 }).catch(() => {})
  await page.waitForTimeout(3500)
  const r = await page.evaluate(() => {
    // ⚠️ 标记打在 **window.performance** 上（不是 measure 函数上）—— 探针自己踩过一次假阴性
    const perf = window.performance
    const installed = !!perf.__userTimingGuardInstalled
    const patched = !!perf.measure && !String(perf.measure).includes('[native code]')
    let throws = 'n/a'
    try {
      // 真栈同款负区间：start=100, end=50
      // 真触发形态 = **负时间戳**（Chromium 实测：负时长 100→50 不抛，负时间戳才抛）
      window.performance.measure('\u200bProbeNegative', { start: -1, end: 10 })
      throws = false
    } catch (e) {
      throws = String(e && e.message ? e.message : e).slice(0, 80)
    }
    // 合法埋点必须**照旧透传**（否则就是"靠不记录换不报错"）
    window.performance.measure('\u200bProbeLegit', { start: 10, end: 20 })
    const passedThrough = window.performance.getEntriesByName('\u200bProbeLegit').length > 0
    return { installed, patched, throws, passedThrough, url: location.pathname }
  })
  console.log(`[probe] ${url} -> path=${r.url} installed=${r.installed} patched=${r.patched} negativeTimestampThrows=${r.throws} legitPassedThrough=${r.passedThrough}`)
}
console.log(`[probe] pageerrors=${pageErrors.length}`, pageErrors.slice(0, 3))
await browser.close()
