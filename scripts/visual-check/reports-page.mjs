import { chromium } from 'playwright'

const filled = {
  'order-margins': { hasData: true, rows: [], totals: { revenue: 128600, refunded: 3200, fabricCost: 74200, laborCost: 18600, grossMargin: 32600 }, unknownCostOrders: 3 },
  'inventory-aging': { slowMovingDays: 90, hasData: true, rows: [], totals: { onHand: 8420.5, slowMovingOnHand: 2310.4, slowMovingBatches: 7 }, undeterminedRows: 2 },
  'staff-performance': { hasData: true, rows: [ { staffId: 'u1', staffName: '王小美', orderCount: 42, revenue: 86500, avgOrderValue: 2059.52 }, { staffId: 'u2', staffName: '李建国', orderCount: 31, revenue: 42100, avgOrderValue: 1358.06 } ], totals: { orderCount: 73, revenue: 128600 }, unattributedOrders: 18 },
  'quality-cost': { components: [ { code: 'rework_labor', label: '返工工时', amount: 4820, known: true, note: '', unknownItems: 0 }, { code: 'scrap_material', label: '报废料', amount: null, known: false, note: '本仓未采集', unknownItems: 0 }, { code: 'compensation', label: '赔付（退款口径）', amount: 3200, known: true, note: '', unknownItems: 0 } ], total: 8020, complete: false, unknownComponents: ['scrap_material'] },
}

const empty = {
  'order-margins': { hasData: false, rows: [], totals: null, unknownCostOrders: 0 },
  'inventory-aging': { slowMovingDays: 90, hasData: false, rows: [], totals: null, undeterminedRows: 0 },
  'staff-performance': { hasData: false, rows: [], totals: null, unattributedOrders: 0 },
  'quality-cost': { components: [], total: null, complete: true, unknownComponents: [] },
}

// 报表中心页的**视觉验收**脚本（issue #7376 复盘：界面改动必须先在本地看一眼再合）。
//
// 用法（在 `frontend/admin-web` 目录先 `npm run build`）：
//   1) `npx next start -p 3124`
//   2) `npm --prefix /tmp i playwright && npx playwright install chromium`（仅首次）
//   3) `node scripts/visual-check/reports-page.mjs`（在**仓库根**跑；PORT 默认 3124）
// 产物：`/tmp/reports-filled.png`（有数据）与 `/tmp/reports-empty.png`（空数据）。
//
// 为什么要有它：四张报表的**展示纪律**（空数据不写 ¥0.00 / 未知不填 0 / 内部分项不摆中文码）
// 只能"看"出来 —— 单测断言的是文本，看不出「整页留白是否对齐、金额是否错列」。
// 只读、mock 掉全部 API（不碰真库），所以可以在任何机器上跑。
const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3124'

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })

async function shoot(payload, out, path = '/reports') {
  const page = await ctx.newPage()
  page.on('console', m => { if (m.type() === 'error') console.log('[console]', m.text().slice(0, 160)) })

  await page.route('**/api/**', r => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, data: [] }) }))
  await page.route('**/api/auth/refresh', r => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, data: { accessToken: 'dev-token', expiresIn: 3600 } }) }))
  await page.route('**/api/auth/me', r => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, data: { id: 'u1', username: 'admin', name: '管理员', tenantId: 1, roles: ['admin'], permissions: ['*'], menus: [] } }) }))
  await page.route('**/api/admin/user/info', r => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, data: { id: 'u1', username: 'admin', name: '管理员', tenantId: 1, roles: ['admin'], permissions: ['*'], menus: [] } }) }))
  await page.route('**/api/admin/reports/**', r => {
    const url = r.request().url()
    const key = Object.keys(payload).find(k => url.includes(k))
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: payload[key] }) })
  })

  await page.goto('BASE + path, { waitUntil: 'domcontentloaded' })
  try {
    await page.waitForSelector('h1', { timeout: 45000 })
  } catch { console.log('!! no h1 within 45s') }
  await page.waitForTimeout(1500)
  await page.screenshot({ path: out, fullPage: true })
  console.log('shot', out, '| title:', await page.title(), '| body len:', (await page.textContent('body'))?.length)
  await page.close()
}

await shoot(filled, '/tmp/reports-filled.png')
await shoot(empty, '/tmp/reports-empty.png')
await browser.close()
