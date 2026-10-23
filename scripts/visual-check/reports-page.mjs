import { chromium } from 'playwright'

const filled = {
  'order-margins': { hasData: true, rows: [], totals: { revenue: 128600, refunded: 3200, fabricCost: 74200, laborCost: 18600, grossMargin: 32600 }, unknownCostOrders: 3 },
  'inventory-aging': { slowMovingDays: 90, hasData: true, rows: [], totals: { onHand: 8420.5, slowMovingOnHand: 2310.4, slowMovingBatches: 7 }, undeterminedRows: 2 },
  'staff-performance': { hasData: true, rows: [ { staffId: 'u1', staffName: '王小美', orderCount: 42, revenue: 86500, avgOrderValue: 2059.52 }, { staffId: 'u2', staffName: '李建国', orderCount: 31, revenue: 42100, avgOrderValue: 1358.06 } ], totals: { orderCount: 73, revenue: 128600 }, unattributedOrders: 18 },
  'quality-cost': { components: [ { code: 'rework_labor', label: '返工工时', amount: 4820, known: true, note: '', unknownItems: 0 }, { code: 'scrap_material', label: '报废料', amount: null, known: false, note: '本仓未采集', unknownItems: 0 }, { code: 'compensation', label: '赔付（退款口径）', amount: 3200, known: true, note: '', unknownItems: 0 } ], total: 8020, complete: false, unknownComponents: ['scrap_material'] },
  'receivable-aging': { asOf: '2026-10-23', hasData: true, customerCount: 6, buckets: [ { bucket: 'NOT_DUE', label: '未到期', amount: 61200, orderCount: 22 }, { bucket: 'DAYS_1_30', label: '逾期 1-30 天', amount: 8400, orderCount: 7 }, { bucket: 'DAYS_31_60', label: '逾期 31-60 天', amount: 5200, orderCount: 5 }, { bucket: 'DAYS_61_90', label: '逾期 61-90 天', amount: 1000, orderCount: 1 }, { bucket: 'DAYS_90_PLUS', label: '逾期 90 天以上', amount: 1400, orderCount: 2 } ], customers: [{ customerName: '张记布艺', customerPhone: '13800000001', paymentTermsDays: 30, total: 42600, overdue: 8600, buckets: [] }, { customerName: '李家窗帘', customerPhone: '13800000002', paymentTermsDays: 45, total: 31800, overdue: 0, buckets: [] }, { customerName: '王家软装', customerPhone: '13800000003', paymentTermsDays: null, total: 12400, overdue: 2400, buckets: [] } ], totals: { outstanding: 86200, overdue: 11000, orderCount: 37 } },
}

// 质量成本维度汇总（issue #7377 段 5）：含「无法归属」的样本 —— 它必须单独露出来
const breakdown = (dim) => ({
  dimension: dim,
  scope: dim === 'customer' ? 'rework_and_compensation_by_customer' : 'rework_by_processing_operation',
  startDate: null, endDate: null, hasData: true,
  rows: dim === 'product'
    ? [
        { key: 'prod:sku-1', label: '遮光布 米白 2.8m', rework: 620, reworkLines: 4, compensation: 900, compensationCount: 2, total: 1520 },
        { key: 'prod:sku-2', label: '纱帘 象牙白 2.8m', rework: 480, reworkLines: 3, compensation: 300, compensationCount: 1, total: 780 },
      ]
    : dim === 'customer'
    ? [
        { key: 'cus:13800000001', label: '张记布艺', rework: 860, reworkLines: 6, compensation: 1200, compensationCount: 2, total: 2060 },
        { key: 'cus:13800000002', label: '李家窗帘', rework: 420, reworkLines: 3, compensation: 0, compensationCount: 0, total: 420 },
      ]
    : [
        { key: 'op:缝制', label: '缝制', rework: 980, reworkLines: 7, compensation: 0, compensationCount: 0, total: 980 },
        { key: 'op:定型', label: '定型', rework: 300, reworkLines: 2, compensation: 0, compensationCount: 0, total: 300 },
      ],
  totals: { rework: 1280, reworkLines: 9, compensation: 1200, compensationCount: 2, total: 2480 },
  unattributed: {
    rework: 0, reworkLines: 0,
    compensation: dim === 'process' ? 1200 : 0,
    compensationCount: dim === 'process' ? 2 : 0,
    total: dim === 'process' ? 1200 : 0,
    reason: dim === 'process'
      ? '赔付（退款口径）没有工序信息 ⇒ 全部计入「无法归属」（不是「赔付为 0」）'
      : '这些返工报工关联不到加工单/订单，或退款流水关联不到订单',
  },
  notes: dim === 'process'
    ? ['报废料不在本视图：本仓未采集（质检只到成品帘级），摊到任何维度都是编数',
       '赔付（退款口径）没有工序信息 ⇒ 全部计入「无法归属」（不是「赔付为 0」）']
    : ['报废料不在本视图：本仓未采集（质检只到成品帘级），摊到任何维度都是编数',
       '返工经「报工 → 加工单 → 订单 → 客户」归属；赔付经「退款流水 → 订单 → 客户」归属'],
})

const empty = {
  'order-margins': { hasData: false, rows: [], totals: null, unknownCostOrders: 0 },
  'inventory-aging': { slowMovingDays: 90, hasData: false, rows: [], totals: null, undeterminedRows: 0 },
  'staff-performance': { hasData: false, rows: [], totals: null, unattributedOrders: 0 },
  'quality-cost': { components: [], total: null, complete: true, unknownComponents: [] },
  'receivable-aging': { asOf: '2026-10-23', hasData: false, customerCount: 0, buckets: [], customers: [], totals: null },
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
  // ⚠️ Playwright 的 route 是**后注册优先**（LIFO）⇒ 具体路由必须写在通用路由**之后**，
  //    否则 `quality-cost` 这条通用匹配会把 `quality-cost/breakdown` 吃掉（实测：页面显示「暂无数据」）
  await page.route('**/api/admin/reports/quality-cost/breakdown**', r => {
    const dim = new URL(r.request().url()).searchParams.get('dimension') || 'customer'
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, data: breakdown(dim) }) })
  })

  await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded' })
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

// 第三张：切到「按工序」维度（issue #7377 段 5）—— 这张能看到「无法归属」那一行（赔付无工序信息）
{
  const page = await ctx.newPage()
  await page.route('**/api/**', (r) => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, data: [] }) }))
  await page.route('**/api/auth/refresh', (r) => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, data: { accessToken: 'dev-token', expiresIn: 3600 } }) }))
  await page.route('**/api/auth/me', (r) => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ success: true, data: { id: 'u1', username: 'admin', name: '管理员', tenantId: 1,
      roles: ['admin'], permissions: ['*'], menus: [] } }) }))
  await page.route('**/api/admin/reports/**', (r) => {
    const url = r.request().url()
    const key = Object.keys(filled).find((k) => url.includes(k))
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, data: filled[key] }) })
  })
  await page.route('**/api/admin/reports/quality-cost/breakdown**', (r) => {
    const dim = new URL(r.request().url()).searchParams.get('dimension') || 'customer'
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, data: breakdown(dim) }) })
  })
  await page.goto(`${BASE}/reports`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('h1', { timeout: 45000 }).catch(() => {})
  await page.waitForTimeout(1200)
  await page.getByTestId('reports-quality-dim-process').click()
  await page.waitForTimeout(600)
  await page.screenshot({ path: '/tmp/reports-breakdown-process.png', fullPage: true })
  console.log('shot process-dim | body len:', (await page.textContent('body'))?.length)
  await page.getByTestId('reports-quality-dim-product').click()
  await page.waitForTimeout(800)
  await page.waitForTimeout(800)
  await page.screenshot({ path: '/tmp/reports-breakdown-product.png', fullPage: true })
  console.log('shot product-dim | body len:', (await page.textContent('body'))?.length)
  await page.close()
}
await browser.close()
