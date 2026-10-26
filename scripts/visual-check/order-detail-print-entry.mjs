import { chromium } from 'playwright'

// 订单详情页「**唯一打印入口**」的视觉验收脚本（issue #7544）。
//
// 用法（在 `frontend/admin-web` 先 `npm run build`）：
//   1) `npx next start -p 3129`
//   2) `node scripts/visual-check/order-detail-print-entry.mjs`（BASE 默认 3129）
// 产物（4 张）：
//   `/tmp/order-detail-print-entry.png`      已发货订单首屏 —— 标题右侧**只有一个**「打印」
//   `/tmp/order-detail-print-center-sales.png` 点「打印」后的打印层（默认销售单 + **三张**单据标签）
//   `/tmp/order-detail-print-center-quotation.png` 换到「报价单」（纸型跟着变 A4）
//   ⚠️ 加工单（A4）自 issue #7870 起**不在本页**（它随「加工单生产明细」页的「打印」走，
//   与洗水唛同层）⇒ 本脚本只覆盖订单详情页的三份纸
//   `/tmp/order-detail-closed.png`           已关闭订单首屏 —— 同样有「打印」（改前这里一张都打不出来）
//
// 为什么要有它：单测断言的是「按钮/标签在不在、纸型读数对不对」，
// **看不出**「唯一入口是否被挤到汉堡里、状态卡操作行是否终于不再铺满、打印层的标签行会不会换行错位」。
// 只读、mock 全部 API（免登录、不碰真库）。
const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3129'
const ORDER_ID = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'

const ME = {
  id: 'u1',
  username: 'admin',
  name: '管理员',
  tenantId: 1,
  roles: ['admin'],
  permissions: ['*'],
  menus: [],
}

const buildItems = (count) =>
  Array.from({ length: count }, (_, i) => ({
    id: `item-${i + 1}`,
    productId: `p-${i + 1}`,
    productName: `奶油风纯色遮光窗帘 桂月白露系列`,
    skuCode: `2659-0${i + 1}`,
    quantity: 6,
    unitPrice: 37.8,
    amount: 226.8,
    subtotal: 226.8,
    processingInfo: { colorName: '桂月白露', doorWidth: '2.8', sellingMethod: 'bulk_cut' },
  }))

const baseOrder = (overrides = {}) => ({
  id: ORDER_ID,
  orderNo: '202610233318010002',
  customerName: '张记布艺',
  customerPhone: '13800138000',
  customerAddress: '浙江省杭州市余杭区某某路 1 号 3 幢',
  totalAmount: 226.8,
  actualAmount: 226.8,
  discountAmount: 0,
  refundAmount: 0,
  status: 'producing',
  createdAt: '2026-10-23T11:04:00+08:00',
  paidAt: '2026-10-23T11:04:00+08:00',
  shippedAt: null,
  receivedAt: null,
  remark: '客户要求工作日送达，走北门卸货',
  items: buildItems(2),
  processingItems: [{ id: 'pi-1', name: '打孔', quantity: 2 }],
  workOrderKind: 'processing',
  logistics: { logisticsCompany: '顺丰速运', trackingNo: 'SF1234567890', shipperName: '王小美' },
  ...overrides,
})

async function newPage(ctx, order) {
  const page = await ctx.newPage()
  page.on('console', (m) => {
    if (m.type() === 'error') console.log('[console]', m.text().slice(0, 160))
  })

  // 默认把任何未显式 mock 的接口喂成「空列表」，避免红屏把页面布局挡住
  await page.route('**/api/**', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: [] }),
    })
  )
  const json = (route, data) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data }) })

  await page.route('**/api/auth/refresh', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { accessToken: 'dev-token', expiresIn: 3600 } }),
    })
  )
  await page.route('**/api/auth/me', (r) => json(r, ME))
  await page.route('**/api/admin/user/info', (r) => json(r, ME))
  await page.route('**/api/admin/notifications**', (r) =>
    json(r, { items: [], total: 0, unreadCount: 0 })
  )
  await page.route('**/api/admin/settings/payment-qrcodes**', (r) => json(r, {}))
  await page.route('**/api/admin/orders/*/shipments', (r) =>
    json(r, { order_id: ORDER_ID, order_no: order.orderNo, status: order.status, shipments: [] })
  )
  await page.route('**/api/admin/production/orders/*/operations', (r) => json(r, { positions: [] }))
  // 加工单块：本页要验的是「页头只有一个打印入口」，作业块内容为空即可（避免造第二张单）
  await page.route('**/api/admin/processing-orders/**', (r) => json(r, null))
  await page.route('**/api/admin/orders/*', (r) => json(r, order))

  await page.goto(`${BASE}/orders/${ORDER_ID}`, { waitUntil: 'domcontentloaded' })
  try {
    await page.waitForSelector('h1', { timeout: 45000 })
  } catch {
    console.log('!! no h1 within 45s')
  }
  await page.waitForTimeout(1200)
  return page
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 980 }, deviceScaleFactor: 1 })

// ① 生产中（= 用户截图里的那一单）：页面级唯一「打印」入口 + 状态卡不再铺四个打印按钮
const page = await newPage(ctx, baseOrder())
await page.screenshot({ path: '/tmp/order-detail-print-entry.png' })
const printButtons = await page.getByRole('button', { name: /^打印/ }).count()
console.log('首屏「打印」开头的按钮数 =', printButtons, '（应为 1）')

// ② 点「打印」⇒ 打印层：默认销售单 + 三张单据标签（先预览再出纸；加工单已迁出本页，#7870）
await page.getByTestId('order-print-entry').click()
await page.waitForSelector('[data-testid="print-preview"]')
await page.waitForTimeout(800)
await page.screenshot({ path: '/tmp/order-detail-print-center-sales.png' })
console.log('单据标签数 =', await page.locator('[data-testid^="print-preview-doc-"]').count(), '（应为 3）')
console.log('加工单标签在本页应为 0 =', await page.getByTestId('print-preview-doc-processing').count())

// ③ 换到「报价单」：纸型读数应从三联纸 241×140 变成 A4 210×297
const before = await page.getByTestId('print-preview-media').textContent()
await page.getByTestId('print-preview-doc-quotation').click()
await page.waitForTimeout(800)
const after = await page.getByTestId('print-preview-media').textContent()
console.log('换单据前后纸型：', before?.slice(0, 24), '→', after?.slice(0, 24))
await page.screenshot({ path: '/tmp/order-detail-print-center-quotation.png' })
await page.close()

// ④ 已关闭订单：改前这里**一张单据都打不出来**（入口被状态吃掉）
const closed = await newPage(ctx, baseOrder({ status: 'closed', closeReason: '客户取消' }))
await closed.screenshot({ path: '/tmp/order-detail-closed.png' })
console.log(
  '已关闭订单「打印」入口可见 =',
  await closed.getByTestId('order-print-entry').isVisible()
)
await closed.close()

await browser.close()
