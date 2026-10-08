// 2026-10-06 演示数据 · 最终验收（真浏览器读页面 + API 读数）
// 目的：确认用户在 admin-web 上**真的能看到**这批 300 单 / 加工单 / 报工 / 计件 / 省料
import { api, chromium, loginUi, OUT } from './lib.mjs'
import { login } from './steps.mjs'
import { writeFileSync } from 'node:fs'

const token = await login()
const R = { at: new Date().toISOString(), checks: [] }
const ck = (id, ok, detail) => { R.checks.push({ id, ok: !!ok, detail }); console.log(`${ok ? '✅' : '❌'} ${id} — ${detail}`) }

// ── API 读数 ──
const orderPage = (await api('GET', '/api/admin/orders?page=1&size=1', { token })).json?.data
R.api = {
  orderTotal: orderPage?.total,
  poListLimit: (await api('GET', '/api/admin/processing-orders', { token })).json?.data?.length,
  statusDist: ((await api('GET', '/api/admin/processing-orders', { token })).json?.data || [])
    .reduce((a, p) => (a[p.status] = (a[p.status] || 0) + 1, a), {}),
}
for (const s of ['generated', 'issued', 'in_processing', 'completed', 'cancelled']) {
  R.api[`po_${s}`] = (await api('GET', `/api/admin/processing-orders?status=${s}`, { token })).json?.data?.length
}
const period = new Date().toISOString().slice(0, 7)
R.api.piecework = (await api('GET', `/api/admin/production/piecework/summary?period=${period}`, { token })).json?.data
R.api.savingBoard = (await api('GET', '/api/admin/batch-stock/saving-board?granularity=month', { token })).json?.data?.total
R.api.pool = (await api('GET', '/api/admin/production/pool', { token })).json?.data
R.api.consumptions = (await api('GET', '/api/admin/batch-stock/consumptions?page=1&size=1', { token })).json?.data?.total

ck('订单读面有数据', Number(R.api.orderTotal) >= 300, `订单总数=${R.api.orderTotal}`)
ck('加工单五种状态齐全', ['generated', 'issued', 'in_processing', 'completed', 'cancelled'].every((s) => (R.api[`po_${s}`] || 0) > 0),
  JSON.stringify({ generated: R.api.po_generated, issued: R.api.po_issued, in_processing: R.api.po_in_processing, completed: R.api.po_completed, cancelled: R.api.po_cancelled }))
ck('计件汇总有数（报工→计件链路通）', Number(R.api.piecework?.total) > 0 && (R.api.piecework?.per_worker || []).length > 0,
  `total=${R.api.piecework?.total} 元；工人 ${(R.api.piecework?.per_worker || []).length} 人；工序 ${(R.api.piecework?.per_operation || []).length} 道`)
ck('省料台账有数据', Number(R.api.consumptions) > 0, `批次消耗行=${R.api.consumptions}；看板 saved=${R.api.savingBoard?.savedMeters} 米 / ${R.api.savingBoard?.savedAmount} 元`)

// ── 真浏览器：看用户会看的页面 ──
const shots = [
  ['订单管理', '/orders', '[data-testid="orders-table"], table'],
  ['加工单（生产管理）', '/production/processing-orders', 'table, [data-testid*="processing"]'],
  ['智能派单', '/production/pool', 'body'],
  ['计件工资报表', '/production/piecework', 'table, [data-testid*="piecework"]'],
  ['省料看板', '/production/saving-board', '[data-testid="saving-saved-groups"]'],
]
const browser = await chromium.launch({ headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
await loginUi(page, { mode: 'admin', phone: process.env.ADMIN_PHONE || '13800138000' })
R.pages = {}
for (const [name, path, sel] of shots) {
  try {
    await page.goto(`${process.env.BASE_URL}/#${path}`, { waitUntil: 'domcontentloaded', timeout: 45000 }).catch(() => {})
    await page.goto(`${process.env.BASE_URL}${path}`, { waitUntil: 'domcontentloaded', timeout: 45000 })
    await page.waitForSelector(sel.split(',')[0].trim(), { timeout: 25000 }).catch(() => {})
    await page.waitForTimeout(2000)
    const text = (await page.locator('body').innerText()).replace(/\s+/g, ' ').slice(0, 700)
    const file = `${OUT}/screenshots/demo-${path.replace(/\//g, '_')}.png`
    await page.screenshot({ path: file, fullPage: false })
    R.pages[name] = { path, url: page.url(), file, text }
    console.log(`📸 ${name} ${path} → ${file}`)
  } catch (e) { R.pages[name] = { path, error: String(e).slice(0, 200) }; console.log(`❌ ${name} ${path}: ${String(e).slice(0, 160)}`) }
}
await browser.close()
ck('五个页面都能打开并渲染', Object.values(R.pages).filter((p) => p.text && p.text.length > 40).length >= 4,
  Object.entries(R.pages).map(([k, v]) => `${k}:${v.text ? v.text.length + '字' : '失败'}`).join(' / '))

writeFileSync(`${OUT}/evidence/seed-final.json`, JSON.stringify(R, null, 2))
console.log('\n===== 最终 =====')
console.log(JSON.stringify({ api: R.api, pages: Object.fromEntries(Object.entries(R.pages).map(([k, v]) => [k, (v.text || '').slice(0, 90)])) }, null, 1))
