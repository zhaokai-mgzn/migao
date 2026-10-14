// 一次性诊断：admin-web /agent-workspace/sessions 与 /chat 打 ai-agent 为何 401（issue 现场见本轮 REPORT）
// 用法：node acceptance/2026-10-14/tools/probe-chat-auth.mjs
import { createRequire } from 'node:module'
import { join } from 'node:path'
const REPO = '/Users/guangzhen.zk/ai native/migao'
const { chromium } = createRequire(join(REPO, 'tests', 'package.json'))('playwright')

const BASE = 'http://localhost:3001'
const b = await chromium.launch()
const ctx = await b.newContext()
const page = await ctx.newPage()

const seen = []
page.on('request', (r) => { if (r.url().includes(':8001') || r.url().includes('/api/auth/me') || r.url().includes('/api/auth/refresh')) seen.push({ phase: 'req', url: r.url(), method: r.method(), auth: (r.headers()['authorization'] || '').slice(0, 20) || '(无)', cookie: (r.headers()['cookie'] || '') ? 'HAS' : '(无)' }) })
page.on('response', async (r) => { if (r.url().includes(':8001') || r.url().includes('/api/auth/')) seen.push({ phase: 'res', url: r.url(), status: r.status() }) })
const bad = []
page.on('response', (r) => { if (r.status() >= 400) bad.push(`${r.status()} ${r.request().method()} ${r.url().slice(0, 120)}`) })

await page.goto(BASE + '/login', { waitUntil: 'domcontentloaded', timeout: 30000 })
await page.getByText('管理员登录').first().click().catch(() => {})
await page.waitForTimeout(500)
await page.fill('#phone', '13800138000')
await page.getByRole('button', { name: /获取验证码/ }).click().catch(() => {})
await page.waitForTimeout(800)
await page.fill('#code', '123456')
await page.getByRole('button', { name: /登\s*录|登录/ }).last().click()
await page.waitForURL('**/dashboard**', { timeout: 25000 })

const cookies = (await ctx.cookies()).map((c) => `${c.name} domain=${c.domain} secure=${c.secure} sameSite=${c.sameSite} path=${c.path}`)
const ls = await page.evaluate(() => Object.fromEntries(Object.entries(localStorage).map(([k, v]) => [k, String(v).slice(0, 24)])))
const docCookie = await page.evaluate(() => document.cookie.slice(0, 120))

await page.goto(BASE + '/agent-workspace/sessions', { waitUntil: 'domcontentloaded', timeout: 30000 })
await page.waitForTimeout(3000)
await page.goto(BASE + '/chat', { waitUntil: 'domcontentloaded', timeout: 30000 })
await page.waitForTimeout(3000)

// 从页面上下文里直发一次（带 credentials），看 agent 怎么答
const direct = await page.evaluate(async () => {
  const out = {}
  for (const u of ['http://localhost:8001/api/chat/sessions', 'http://localhost:8080/api/auth/me']) {
    const r = await fetch(u, { credentials: 'include' })
    out[u] = r.status
  }
  return out
})

console.log(JSON.stringify({ cookies, ls, docCookie, direct, bad: [...new Set(bad)], seen: seen.slice(-14) }, null, 2))
await b.close()
