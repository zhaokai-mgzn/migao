import { createRequire } from 'node:module'
import { writeFileSync } from 'node:fs'
const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('@playwright/test')
const b = await chromium.launch({ channel: 'chrome' })
const out = {}
const targets = [
  ['migaozn-home', 'https://migaozn.com/', 1440, 900],
  ['migaozn-about', 'https://migaozn.com/about', 1440, 900],
  ['migaozn-services', 'https://migaozn.com/services', 1440, 900],
  ['migaozn-contact', 'https://migaozn.com/contact', 1440, 900],
  ['bmini', 'https://app.migaozn.com/b/', 390, 844],
  ['worker-h5', 'https://app.migaozn.com/w/', 390, 844],
  ['merchant-root', 'https://merchant.migaozn.com/', 1440, 900],
]
try {
  for (const [name, url, w, h] of targets) {
    const ctx = await b.newContext({ viewport: { width: w, height: h }, isMobile: w < 500, hasTouch: w < 500 })
    const page = await ctx.newPage()
    const errs = []
    page.on('pageerror', (e) => errs.push(String(e).slice(0, 80)))
    try {
      const r = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 })
      await page.waitForTimeout(6000)
      const m = await page.evaluate(() => {
        const t = document.body.innerText || ''
        return {
          h1: document.querySelectorAll('h1').length,
          textLen: t.replace(/\s+/g, '').length,
          spinner: /加载中|Loading\.\.\./i.test(t),
          overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          md: (t.match(/\*\*|__|#{1,3}\s/g) || []).length,
          head: t.replace(/\s+/g, ' ').slice(0, 90),
        }
      })
      out[name] = { url, status: r ? r.status() : null, finalUrl: page.url(), ...m, errors: errs.slice(0, 2) }
      await page.screenshot({ path: new URL(`./evidence/S31-live-${name}.png`, import.meta.url).pathname })
      console.log(`${name.padEnd(16)} ${out[name].status} h1=${m.h1} 字数=${String(m.textLen).padStart(4)} 转圈=${m.spinner ? '❌有' : '✓无'} 溢出=${m.overflow}px md记号=${m.md}`)
    } catch (e) {
      out[name] = { url, error: String(e).slice(0, 100) }
      console.log(`${name.padEnd(16)} ❌ ${String(e).slice(0, 70)}`)
    }
    await ctx.close()
  }
} finally { await b.close() }
writeFileSync(new URL('./evidence/S31-live-reprobe.json', import.meta.url), JSON.stringify(out, null, 2))
// ── 断言 + 退出码（同上：此前只打印读数）
const CORPORATE = ['migaozn-home', 'migaozn-about', 'migaozn-services', 'migaozn-contact']
const fails = []
for (const [name, r] of Object.entries(out)) {
  if (r.error) { fails.push(`${name} 打开失败：${r.error}`); continue }
  if (r.status !== 200) fails.push(`${name} 状态码 ${r.status}`)
  if (CORPORATE.includes(name) && r.h1 !== 1) fails.push(`${name} h1=${r.h1}（官网页应恰好 1 个）`)
  if (r.spinner) fails.push(`${name} 仍在「加载中」`)
  if (r.overflow > 0) fails.push(`${name} 横向溢出 ${r.overflow}px`)
  if (r.md > 0) fails.push(`${name} 出现 ${r.md} 处 Markdown 记号（P10 类）`)
}
console.log(fails.length ? `\n🔴 红项 ${fails.length} 条：\n  - ` + fails.join('\n  - ') : '\n✅ 全绿')
process.exit(fails.length ? 1 : 0)
