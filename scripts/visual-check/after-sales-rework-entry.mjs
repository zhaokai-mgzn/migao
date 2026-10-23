import { chromium } from 'playwright'

// 售后详情页「发起返工」入口的**视觉验收**脚本（issue #7377 段 4）。
//
// 用法（在 `frontend/admin-web` 先 `npm run build`）：
//   1) `npx next start -p 3129`
//   2) `node scripts/visual-check/after-sales-rework-entry.mjs`（BASE 默认 3129）
// 产物：`/tmp/as-rework-detail.png`（详情页带入口 + 返工区块）/ `/tmp/as-rework-modal.png`（开单弹窗）。
//
// 为什么要有它：入口的**显隐与置灰**、返工区块的排版只能"看"出来 —— 单测断言 testid 与文本，
// 看不出按钮是否被挤到第二行、提示是否与按钮错位。只读、mock 全部 API（免登录）。
const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3129'

const TICKET = {
  id: 'ticket-001',
  ticketNo: 'AS202610230001',
  ticketType: 'refund',
  status: 'processing',
  priority: 'normal',
  description: '客户反馈帘头褶皱不齐，要求重做帘头。',
  orderId: 'order-001',
  orderNo: 'MG202610230001',
  customerName: '张记布艺',
  customerPhone: '13800000001',
  source: 'customer',
  createdAt: '2026-10-23T09:12:00+08:00',
  updatedAt: '2026-10-23T09:40:00+08:00',
  statusHistory: [
    { status: 'pending', time: '2026-10-23T09:12:00+08:00', operator: '系统', remark: '客户提交售后申请' },
    { status: 'processing', time: '2026-10-23T09:40:00+08:00', operator: '王小美', remark: '已联系客户，安排返工' },
  ],
}

// 已有未完结返工单的形态：入口**变灰**并点明是哪一张（判据 2 的视觉面）
const REWORK = [{
  id: 'rw9', reworkNo: 'FG202610230009', afterSalesTicketId: 'ticket-001', orderId: 'order-001',
  processingOrderId: 'JG-20261023-0008', status: 'in_progress', reason: '帘头褶皱不齐，重做帘头',
  createdByName: '王小美', startedAt: '2026-10-23T10:00:00+08:00', completedAt: null,
}]

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 })

async function open(reworkRows) {
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
  await page.route('**/api/admin/after-sales/ticket-001', (r) => r.fulfill({ status: 200,
    contentType: 'application/json', body: JSON.stringify({ success: true, data: TICKET }) }))
  await page.route('**/api/admin/rework-orders**', (r) => r.fulfill({ status: 200,
    contentType: 'application/json', body: JSON.stringify({ success: true, data: reworkRows }) }))

  await page.goto(`${BASE}/after-sales/ticket-001`, { waitUntil: 'domcontentloaded' })
  try { await page.waitForSelector('h1', { timeout: 45000 }) } catch { console.log('!! no h1 within 45s') }
  await page.waitForTimeout(1500)
  return page
}

const page = await open(REWORK)
await page.screenshot({ path: '/tmp/as-rework-detail.png', fullPage: true })
console.log('shot detail | body len:', (await page.textContent('body'))?.length)

// 弹窗形态：把已有关联返工单清掉再看开单弹窗（否则按钮是灰的，点不开）
await page.close()
const page2 = await open([])
await page2.getByTestId('after-sales-rework-create').click()
await page2.waitForTimeout(600)
await page2.screenshot({ path: '/tmp/as-rework-modal.png', fullPage: true })
console.log('shot modal | body len:', (await page2.textContent('body'))?.length)

await browser.close()
