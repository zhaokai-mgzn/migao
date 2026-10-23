import { chromium } from 'playwright'

// 「被闸门拦下时就地申请审批」的视觉验收（issue #7374 段 3）。
//
// 用法（frontend/admin-web 先 `npm run build`）：
//   1) `npx next start -p 3133`
//   2) `node scripts/visual-check/approval-entry.mjs`
// 产物：`/tmp/approval-entry.png`（盘点单完成被拒 → 自动弹出申请，对象与金额已预填）
const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3133'

const HEAD = { id: 'st1', stocktakeNo: 'PD202610220001', warehouseId: 1, warehouseCode: 'WH01',
  status: 'counting', note: '月末全仓盘点', completedAt: null, items: [] }
const DETAIL = { ...HEAD, items: [
  { batchId: 11, batchNo: 'PC-20261022-0001', skuCode: 'SKU-A', bookQty: 10, countedQty: 8, diffQty: -2 },
  { batchId: 12, batchNo: 'PC-20261022-0002', skuCode: 'SKU-B', bookQty: 5, countedQty: 5, diffQty: 0 },
] }

const browser = await chromium.launch()
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage()
page.on('console', (m) => { if (m.type() === 'error') console.log('[console]', m.text().slice(0, 160)) })

await page.route('**/api/**', (r) => r.fulfill({ status: 200, contentType: 'application/json',
  body: JSON.stringify({ success: true, data: [] }) }))
await page.route('**/api/auth/refresh', (r) => r.fulfill({ status: 200, contentType: 'application/json',
  body: JSON.stringify({ success: true, data: { accessToken: 'dev-token', expiresIn: 3600 } }) }))
await page.route('**/api/auth/me', (r) => r.fulfill({ status: 200, contentType: 'application/json',
  body: JSON.stringify({ success: true, data: { id: 'u1', username: 'admin', name: '管理员', tenantId: 1,
    roles: ['admin'], permissions: ['*'], menus: [] } }) }))
await page.route('**/api/admin/user/info', (r) => r.fulfill({ status: 200, contentType: 'application/json',
  body: JSON.stringify({ success: true, data: { id: 'u1', username: 'admin', name: '管理员', tenantId: 1,
    roles: ['admin'], permissions: ['*'], menus: [] } }) }))
await page.route('**/api/admin/warehouses', (r) => r.fulfill({ status: 200, contentType: 'application/json',
  body: JSON.stringify({ success: true, data: [{ id: 1, code: 'WH01', name: '主仓' }] }) }))
await page.route('**/api/admin/stocktakes/st1/complete', (r) => r.fulfill({ status: 400,
  contentType: 'application/json',
  body: JSON.stringify({ success: false, message: '盘点有差异（合计 2），必须先有已通过的「盘点差异」审批：objectType=stocktake_diff，objectRef=PD202610220001，金额 ≥ 2' }) }))
await page.route('**/api/admin/stocktakes/st1', (r) => r.fulfill({ status: 200, contentType: 'application/json',
  body: JSON.stringify({ success: true, data: DETAIL }) }))
await page.route('**/api/admin/stocktakes', (r) => r.fulfill({ status: 200, contentType: 'application/json',
  body: JSON.stringify({ success: true, data: [HEAD] }) }))

await page.goto(`${BASE}/stocktakes`, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('h1', { timeout: 45000 }).catch(() => {})
await page.waitForTimeout(1200)
await page.getByTestId('stocktake-open-detail-st1').click()
await page.waitForTimeout(600)
await page.getByTestId('stocktake-complete').click()
await page.waitForTimeout(400)
await page.getByTestId('stocktake-confirm-submit').click()
await page.waitForTimeout(1200)
await page.screenshot({ path: '/tmp/approval-entry.png', fullPage: true })
console.log('shot | body len:', (await page.textContent('body'))?.length)
await browser.close()
