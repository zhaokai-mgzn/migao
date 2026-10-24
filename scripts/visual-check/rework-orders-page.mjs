import { chromium } from 'playwright'

// 返工单页 `/rework-orders` 的**视觉验收**脚本（issue #7377）。
//
// 用法（在 `frontend/admin-web` 先 `npm run build`）：
//   1) `npx next start -p 3127`
//   2) `node scripts/visual-check/rework-orders-page.mjs`（PORT 默认 3127）
// 产物：`/tmp/rework-filled.png`（三种状态都在）/ `/tmp/rework-empty.png`（空态）。
//
// 为什么要有它：状态机纪律（已闭环**不给**动作按钮）与「本页不出现 ¥0.00」只能"看"出来 ——
// 单测断言的是 testid 与文本，看不出按钮是否挤在一格、金额列是否错位。
// 只读、mock 掉全部 API（不碰真库、免登录），任何机器可跑。
const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3127'

const ROWS = [
  { id: 'rw1', reworkNo: 'FG202610230001', afterSalesTicketId: 'SH-20261023-0001', orderId: 'o1',
    processingOrderId: 'JG-20261023-0008', status: 'draft', reason: '帘头褶皱不齐', createdByName: '王小美',
    startedAt: null, completedAt: null },
  { id: 'rw2', reworkNo: 'FG202610230002', afterSalesTicketId: 'SH-20261021-0007', orderId: 'o2',
    processingOrderId: null, status: 'in_progress', reason: '轨道卡顿异响', createdByName: '李建国',
    startedAt: '2026-10-23T09:10:00+08:00', completedAt: null },
  { id: 'rw3', reworkNo: 'FG202610230003', afterSalesTicketId: 'SH-20261019-0003', orderId: 'o3',
    processingOrderId: 'JG-20261019-0011', status: 'done', reason: '尺寸超差 15mm', createdByName: '王小美',
    startedAt: '2026-10-21T08:00:00+08:00', completedAt: '2026-10-21T17:30:00+08:00' },
  { id: 'rw4', reworkNo: 'FG202610230004', afterSalesTicketId: 'SH-20261018-0012', orderId: 'o4',
    processingOrderId: null, status: 'cancelled', reason: '客户改主意不修了', createdByName: '李建国',
    startedAt: null, completedAt: null },
]

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })

async function shoot(rows, out, path = '/rework-orders') {
  const page = await ctx.newPage()
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
  await page.route('**/api/admin/rework-orders**', (r) => r.fulfill({ status: 200,
    contentType: 'application/json', body: JSON.stringify({ success: true, data: rows }) }))

  await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' })
  try {
    await page.waitForSelector('h1', { timeout: 45000 })
  } catch { console.log('!! no h1 within 45s') }
  await page.waitForTimeout(1500)
  await page.screenshot({ path: out, fullPage: true })
  console.log('shot', out, '| title:', await page.title(), '| body len:', (await page.textContent('body'))?.length)
  await page.close()
}

await shoot(ROWS, '/tmp/rework-filled.png')
await shoot([], '/tmp/rework-empty.png')
await browser.close()
