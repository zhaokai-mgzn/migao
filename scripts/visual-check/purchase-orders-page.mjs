// 采购单页的**视觉验收**脚本（issue #7567：明细分只从公共选品器来；收货面认商品不印雪花号）。
//
// 用法见同目录 README（先在 `frontend/admin-web` 跑 `npm run build`，再 `npx next start -p 3124`）。
// mock 掉全部 `/api/**`、不需要登录、不碰真库 ⇒ 任何机器都能跑。
//
// 产出三张图（人看）：
//   /tmp/purchase-orders-list.png      列表（状态 / 收货进度 / 金额 / 操作列不换行）
//   /tmp/purchase-orders-create.png    新建弹窗（两栏选品器 + 勾出来的明细行）
//   /tmp/purchase-orders-receive.png   收货弹窗（**商品名 / 颜色 / 门幅**，不是雪花号）
import { chromium } from 'playwright'

const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3124'

/** 线上真实量级（> 2^53）：明细里存的是这种雪花号，页面上**不许**出现 */
const SKU_ID = '2097126615461462018'
const PRODUCT = { id: 'prod-1', name: '奶油风纯色遮光窗帘', skuCode: '2659' }
const SKUS = [
  { id: SKU_ID, colorName: '桂月白露', doorWidth: '2.8', stock: 86, price: 30, status: 'active' },
  { id: '2097126615461462019', colorName: '桂月白露', doorWidth: '3.2', stock: 101, price: 30, status: 'active' },
]

const ORDERS = [
  {
    id: 'po-1',
    poNo: 'CG-20261023-0001',
    supplierId: 'sup-1',
    supplierName: '绍兴柯桥××布行',
    orderDate: '2026-10-23',
    expectedDate: '2026-10-28',
    status: 'partially_received',
    totalAmount: 3720,
    remark: null,
    closedAt: null,
    closedReason: null,
    items: [
      {
        id: 'it-1',
        skuId: SKU_ID,
        productId: 'prod-1',
        quantity: 100,
        unitPrice: 30,
        amount: 3000,
        receivedQuantity: 40,
        remainingQuantity: 60,
        productName: '奶油风纯色遮光窗帘',
        skuCode: '2659',
        colorName: '桂月白露',
        doorWidth: '2.8',
      },
      {
        id: 'it-2',
        skuId: '2097126615461462019',
        productId: 'prod-1',
        quantity: 24,
        unitPrice: 30,
        amount: 720,
        receivedQuantity: 0,
        remainingQuantity: 24,
        productName: '奶油风纯色遮光窗帘',
        skuCode: '2659',
        colorName: '桂月白露',
        doorWidth: '3.2',
      },
    ],
    receipts: [],
  },
  {
    id: 'po-2',
    poNo: 'CG-20261021-0002',
    supplierId: 'sup-1',
    supplierName: '绍兴柯桥××布行',
    orderDate: '2026-10-21',
    expectedDate: '2026-10-25',
    status: 'closed',
    totalAmount: 1200,
    remark: null,
    closedAt: '2026-10-22T10:00:00+08:00',
    closedReason: '供应商断货',
    items: [
      {
        id: 'it-3',
        skuId: '2097126615461462020',
        productId: 'prod-1',
        quantity: 40,
        unitPrice: 30,
        amount: 1200,
        receivedQuantity: 0,
        remainingQuantity: 40,
        productName: '奶油风纯色遮光窗帘',
        skuCode: '2659',
        colorName: '奶咖',
        doorWidth: '2.8',
      },
    ],
    receipts: [],
  },
]

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })

const page = await ctx.newPage()
page.on('console', m => { if (m.type() === 'error') console.log('[console]', m.text().slice(0, 160)) })

await page.route('**/api/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: [] }) }))
await page.route('**/api/auth/refresh', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { accessToken: 'dev-token', expiresIn: 3600 } }) }))
await page.route('**/api/auth/me', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { id: 'u1', username: 'admin', name: '管理员', tenantId: 1, roles: ['admin'], permissions: ['*'], menus: [] } }) }))
await page.route('**/api/admin/user/info', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { id: 'u1', username: 'admin', name: '管理员', tenantId: 1, roles: ['admin'], permissions: ['*'], menus: [] } }) }))
await page.route('**/api/admin/purchase-orders**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: ORDERS }) }))
await page.route('**/api/admin/suppliers**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: [{ id: 'sup-1', name: '绍兴柯桥××布行', status: 'active' }] }) }))
// 选品器（issue #7567）：⚠️ Playwright 后注册优先 ⇒ 详情路由写在列表之后
await page.route('**/api/admin/products**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { items: [PRODUCT], total: 1 } }) }))
await page.route('**/api/admin/products/*', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { ...PRODUCT, skus: SKUS } }) }))

await page.goto(`${BASE}/purchase-orders`, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('h1', { timeout: 45000 }).catch(() => console.log('!! no h1 within 45s'))
await page.waitForTimeout(1500)
await page.screenshot({ path: '/tmp/purchase-orders-list.png', fullPage: true })
console.log('shot /tmp/purchase-orders-list.png')

// 新建采购单：勾一个 SKU ⇒ 明细成行（页面上**没有**手打 SKU 的输入框）
await page.getByTestId('purchase-create').click()
await page.waitForTimeout(800)
const legacyInput = page.locator('input[placeholder="SKU"]')
console.log('legacy SKU input count（必须是 0）:', await legacyInput.count())
await page.getByLabel('搜索商品').fill('遮光')
await page.getByRole('button', { name: /奶油风纯色遮光窗帘/ }).first().click()
await page.getByRole('checkbox').first().click()
await page.getByTestId('purchase-form-qty-0').fill('100')
await page.getByTestId('purchase-form-price-0').fill('30')
await page.waitForTimeout(600)
await page.screenshot({ path: '/tmp/purchase-orders-create.png', fullPage: true })
console.log('shot /tmp/purchase-orders-create.png')

// 关上建单弹窗，看收货弹窗（展示名，不印雪花号）
await page.getByRole('button', { name: '取消' }).first().click()
await page.waitForTimeout(500)
await page.getByTestId('purchase-receive-CG-20261023-0001').click()
await page.waitForTimeout(800)
const bodyText = await page.textContent('body')
console.log('雪花号上屏了吗（必须是 false）:', bodyText?.includes(SKU_ID))
await page.screenshot({ path: '/tmp/purchase-orders-receive.png', fullPage: true })
console.log('shot /tmp/purchase-orders-receive.png')

await browser.close()
