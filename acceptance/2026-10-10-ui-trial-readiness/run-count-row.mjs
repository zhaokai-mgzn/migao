/**
 * #6703 验收补充：后端整体不可用（/api/admin/** ⇒ 500）时，
 * 六个列表页**不得**再断言「共 0 条」，且必须有**常驻**失败锚点（失败只由瞬时 toast 通报是不够的）。
 * 判定在 **6s 后**复查（避开 toast 存活窗口）。
 */
import { createRequire } from 'node:module'
import { writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('@playwright/test')
const OUT = fileURLToPath(new URL('./evidence/', import.meta.url))
mkdirSync(OUT, { recursive: true })
const PAGES = ['/orders', '/finance', '/customers', '/after-sales', '/knowledge', '/stock-ledger']
const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 980 } })
const page = await ctx.newPage()
await page.goto('http://localhost:3001/login', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('input', { timeout: 90000 })
await page.waitForTimeout(1500)
try { await page.getByRole('tab', { name: /管理员登录/ }).first().click({ timeout: 8000 }) } catch { await page.getByText('管理员登录', { exact: false }).first().click({ timeout: 8000 }).catch(() => {}) }
await page.getByLabel('手机号', { exact: false }).first().fill('13800138000')
await page.getByLabel('验证码', { exact: false }).first().fill('123456')
await page.getByRole('button', { name: /登\s*录/ }).first().click()
await page.waitForURL((u) => !/^\/login\b/.test(u.pathname), { timeout: 40000 })
await page.route('**/api/admin/**', (r) => r.fulfill({ status: 500, contentType: 'application/json', body: '{"success":false,"error":{"code":"INTERNAL_ERROR"}}' }))
const rows = []
for (const p of PAGES) {
  await page.goto('http://localhost:3001' + p, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(6000)   // ≥6s：toast 已过期，剩下的才是"持久面"
  const r = await page.evaluate(() => {
    const t = document.body.innerText || ''
    const tid = Array.from(document.querySelectorAll('[data-testid]')).map((e) => e.getAttribute('data-testid') || '')
    return {
      countZero: (t.match(/共\s?0\s?[条块件]/g) || []).slice(0, 2),
      countDash: (t.match(/共\s?—\s?[条块件]/g) || []).slice(0, 2),
      anchors: tid.filter((x) => /load-error|load-failed|retry/i.test(x)).slice(0, 3),
      permBlame: /没有[^。，；]*权限/.test(t),
    }
  })
  rows.push({ path: p, ...r })
  console.log(`${p.padEnd(18)} 共0条=${r.countZero.length ? '❌' + JSON.stringify(r.countZero) : '无 ✅'} ｜ 计数—=${r.countDash.length ? '✅' : '—'} ｜ 锚点=${r.anchors.join(',') || '无'} ｜ 权限归因=${r.permBlame ? '❌' : '无 ✅'}`)
}
writeFileSync(OUT + 'S7-count-row-read-failure.json', JSON.stringify({ when: new Date().toISOString(), pages: rows }, null, 2))
await browser.close()
// ── 断言 + 退出码（本脚本此前只打印、**永不失败** ⇒ 外壳报"全绿"却可能含着红；2026-10-11 补）
const fails = []
for (const r of rows) {
  if (r.countZero.length) fails.push(`${r.path} 读失败时印了「共 0 条」`)
  if (!r.countDash.length) fails.push(`${r.path} 计数位不是「—」（读不到就该留白，不许编数）`)
  if (r.permBlame) fails.push(`${r.path} 读失败被归因成「没有权限」（#6707 类）`)
}
if (!rows.some((r) => r.anchors.length)) fails.push('没有任何页面出现失败锚点 ⇒ 探针可能没生效（先自证再读数）')
console.log(fails.length ? `\n🔴 红项 ${fails.length} 条：\n  - ` + fails.join('\n  - ') : '\n✅ 全绿')
process.exit(fails.length ? 1 : 0)
