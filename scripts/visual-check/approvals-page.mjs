import { chromium } from 'playwright'

// 审批中心页 `/approvals` 的**视觉验收**脚本（issue #7374）。
//
// 用法（在 `frontend/admin-web` 先 `npm run build`）：
//   1) `npx next start -p 3131`
//   2) `node scripts/visual-check/approvals-page.mjs`（BASE 默认 3131）
// 产物：`/tmp/approvals-filled.png`（四态同屏）/ `/tmp/approvals-empty.png`（空态）。
//
// 为什么要有它：「只对待审给动作」「已使用不打折」这些纪律只能"看"出来 ——
// 单测断言 testid，看不出按钮列是否挤成一团、状态徽与「已使用」是否分得清。
const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3131'

const ROWS = [
  { id: 'ap1', objectType: 'price_change', objectRef: 'sku-1', objectLabel: '遮光布 米白 2.8m',
    amount: 1200, payload: null, reason: '客户要 3% 折扣', status: 'pending',
    requestedBy: 'u-x', requestedByName: '王小美', requestedAt: '2026-10-23T10:00:00+08:00',
    decidedBy: null, decidedByName: null, decidedAt: null, decisionNote: null, consumedAt: null, consumedRef: null },
  { id: 'ap2', objectType: 'credit_override', objectRef: 'cus-9', objectLabel: '张记布艺',
    amount: 8600, payload: null, reason: '本月额度已用满，需超 2000 放单', status: 'pending',
    requestedBy: 'u-me', requestedByName: '李建国', requestedAt: '2026-10-23T09:20:00+08:00',
    decidedBy: null, decidedByName: null, decidedAt: null, decisionNote: null, consumedAt: null, consumedRef: null },
  { id: 'ap3', objectType: 'refund', objectRef: 'o-77', objectLabel: 'SO-20261023-0007',
    amount: 320, payload: null, reason: '帘头褶皱，客户要求退款', status: 'approved',
    requestedBy: 'u-x', requestedByName: '王小美', requestedAt: '2026-10-22T15:00:00+08:00',
    decidedBy: 'u-boss', decidedByName: '李经理', decidedAt: '2026-10-22T16:10:00+08:00',
    decisionNote: '已核实', consumedAt: null, consumedRef: null },
  { id: 'ap4', objectType: 'stocktake_diff', objectRef: 'st-12', objectLabel: 'PD202610220001',
    amount: null, payload: null, reason: '盘亏 3 米', status: 'approved',
    requestedBy: 'u-x', requestedByName: '王小美', requestedAt: '2026-10-21T18:00:00+08:00',
    decidedBy: 'u-boss', decidedByName: '李经理', decidedAt: '2026-10-21T19:00:00+08:00',
    decisionNote: null, consumedAt: '2026-10-21T19:30:00+08:00', consumedRef: 'PD202610220001' },
  { id: 'ap5', objectType: 'purchase_over', objectRef: 'po-3', objectLabel: 'CG-20261020-0003',
    amount: 5200, payload: null, reason: '急单加采', status: 'rejected',
    requestedBy: 'u-x', requestedByName: '王小美', requestedAt: '2026-10-20T11:00:00+08:00',
    decidedBy: 'u-boss', decidedByName: '李经理', decidedAt: '2026-10-20T12:00:00+08:00',
    decisionNote: '本月采购额度已满', consumedAt: null, consumedRef: null },
]

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })

async function shoot(rows, out) {
  const page = await ctx.newPage()
  page.on('console', (m) => { if (m.type() === 'error') console.log('[console]', m.text().slice(0, 160)) })

  await page.route('**/api/**', (r) => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, data: [] }) }))
  await page.route('**/api/auth/refresh', (r) => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, data: { accessToken: 'dev-token', expiresIn: 3600 } }) }))
  await page.route('**/api/auth/me', (r) => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, data: { id: 'u-me', username: 'admin', name: '管理员', tenantId: 1,
      roles: ['admin'], permissions: ['*'], menus: [] } }) }))
  await page.route('**/api/admin/user/info', (r) => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, data: { id: 'u-me', username: 'admin', name: '管理员', tenantId: 1,
      roles: ['admin'], permissions: ['*'], menus: [] } }) }))
  await page.route('**/api/admin/approvals**', (r) => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, data: rows }) }))

  await page.goto(`${BASE}/approvals`, { waitUntil: 'domcontentloaded' })
  try { await page.waitForSelector('h1', { timeout: 45000 }) } catch { console.log('!! no h1 within 45s') }
  await page.waitForTimeout(1500)
  await page.screenshot({ path: out, fullPage: true })
  console.log('shot', out, '| body len:', (await page.textContent('body'))?.length)
  await page.close()
}

await shoot(ROWS, '/tmp/approvals-filled.png')
await shoot([], '/tmp/approvals-empty.png')
await browser.close()
