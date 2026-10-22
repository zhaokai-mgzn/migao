// 盘点单页的**视觉验收**脚本（issue #7373，P1-1 段 2 的商家面）。
// 用法见同目录 README；与 `reports-page.mjs` / `price-books-page.mjs` 同款：
// mock 掉全部 `/api/**`、不需要登录、一次产出两张图（列表+明细 / 出任务弹窗）。
import { chromium } from 'playwright'

const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3125'

const warehouses = [
  { id: 7, code: 'WH01', name: '主仓', isDefault: true },
  { id: 9, code: 'WH02', name: '加工仓', isDefault: false },
]

const list = [
  {
    id: 'st1', stocktakeNo: 'PD202610220001', warehouseId: 7, warehouseCode: null,
    status: 'counting', note: '月末全仓盘点', completedAt: null, items: [],
  },
  {
    id: 'st0', stocktakeNo: 'PD202610150002', warehouseId: 9, warehouseCode: null,
    status: 'completed', note: null, completedAt: '2026-10-15T09:12:00+08:00', items: [],
  },
]

const detail = {
  ...list[0],
  items: [
    { batchId: 11, batchNo: 'PC-20261022-0001', skuCode: 'SKU-BL-001', bookQty: 12.5, countedQty: 11, diffQty: -1.5 },
    { batchId: 12, batchNo: 'PC-20261022-0002', skuCode: 'SKU-BL-002', bookQty: 8, countedQty: 8, diffQty: 0 },
    { batchId: 13, batchNo: 'PC-20261022-0003', skuCode: 'SKU-BL-003', bookQty: 3.5, countedQty: null, diffQty: null },
  ],
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()

// ⚠️ Playwright：**先注册的通配优先**（后注册的具体路由会覆盖它）⇒ 通配必须第一个注册
await page.route('**/api/**', (r) =>
  r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: [] }) }),
)
await page.route('**/api/auth/refresh', (r) =>
  r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { accessToken: 't', expiresIn: 3600 } }) }),
)
await page.route('**/api/auth/me', (r) =>
  r.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      success: true,
      data: { id: 'u1', username: 'admin', name: '管理员', tenantId: 1, roles: ['admin'], permissions: ['*'], menus: [] },
    }),
  }),
)
await page.route('**/api/admin/warehouses', (r) =>
  r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: warehouses }) }),
)
await page.route('**/api/admin/stocktakes/st1', (r) =>
  r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: detail }) }),
)
await page.route('**/api/admin/stocktakes', (r) =>
  r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: list }) }),
)

await page.goto(BASE + '/stocktakes', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('[data-testid="stocktakes-table"]', { timeout: 45000 }).catch(() => console.log('!! 列表没渲染出来'))
await page.click('[data-testid="stocktake-open-detail-st1"]')
await page.waitForSelector('[data-testid="stocktake-lines"]', { timeout: 15000 }).catch(() => console.log('!! 明细没渲染出来'))
await page.waitForTimeout(600)
await page.screenshot({ path: '/tmp/stocktakes-detail.png', fullPage: true })
console.log('shot /tmp/stocktakes-detail.png')

await page.click('[data-testid="stocktake-open"]')
await page.waitForTimeout(500)
await page.screenshot({ path: '/tmp/stocktakes-open.png', fullPage: true })
console.log('shot /tmp/stocktakes-open.png')

await browser.close()
