import { chromium } from 'playwright'

// 订单详情「打印报价单」预览层的**视觉验收**脚本（issue #7527）。
//
// 用法（在 `frontend/admin-web` 先 `npm run build`）：
//   1) `npx next start -p 3127`
//   2) `node scripts/visual-check/quotation-print-preview.mjs`（BASE 默认 3127）
// 产物：`/tmp/quotation-print-preview.png`（预览层整帧）/ `/tmp/quotation-print-paper.png`（纸框）。
//
// 为什么要有它：**列的多少、列宽是否错列、行高是否被长文案撑歪**只能「看」出来 ——
// 单测断言文本与 `th` 计数，看不出「去掉品名列后金额列有没有错位」「工艺行撤掉后
// 表格下半截是否留白」。只读、mock 全部 API（免登录）。
//
// 判据（人 / AI 读图）：① 表头**没有**「品名」；② 表头与数据列逐列对齐（小计在最后一列）；
// ③ 明细**没有**「工艺」行；④ 不用横向滚动就能看全 8 列。
const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3127'

const ORDER = {
  id: 'order_quotation',
  orderNo: 'CSO202610230001',
  customerName: '回归客户-01',
  customerPhone: '13900003001',
  customerAddress: '杭州',
  totalAmount: 268.8,
  actualAmount: 268.8,
  discountAmount: 0,
  status: 'shipped',
  hasProcessing: false,
  remark: '客户要求工作日送达',
  logisticsType: 'logistics',
  logisticsCompany: '顺丰速运',
  createdAt: '2026-10-23T09:00:00+08:00',
  items: [
    {
      id: 'item_001',
      productId: 'prod_001',
      // 品名只用于「不得上纸」的负向核对（issue #7527）—— 纸面不该出现这串
      productName: '奶油风纯色遮光窗帘 桂月白露系列',
      skuCode: '2659',
      quantity: 6,
      unitPrice: 30.8,
      amount: 184.8,
      subtotal: 184.8,
      width: 3,
      height: 2.6,
      processingInfo: {
        colorName: '2659-01 桂月白露',
        doorWidth: '2.8米',
        componentRole: '主布',
        craft: '韩褶',
        cuttingMode: '定高买宽',
        openCount: 2,
        isShaped: true,
        formula: 'pleat',
        pleatCount: 2,
        perPanelPleats: 1,
      },
      processingFee: 42,
    },
  ],
}

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 })
const page = await ctx.newPage()
page.on('console', (m) => { if (m.type() === 'error') console.log('[console]', m.text().slice(0, 160)) })

const json = (data) => ({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, code: 200, data }) })

await page.route('**/api/**', (r) => r.fulfill(json([])))
await page.route('**/api/auth/refresh', (r) => r.fulfill(json({ accessToken: 'dev-token', expiresIn: 3600 })))
await page.route('**/api/auth/me', (r) => r.fulfill(json({
  id: 'u1', username: 'admin', name: '管理员', tenantId: 1,
  roles: ['admin'], permissions: ['*'], menus: [],
})))
await page.route('**/api/admin/user/info', (r) => r.fulfill(json({
  id: 'u1', username: 'admin', name: '管理员', tenantId: 1,
  roles: ['admin'], permissions: ['*'], menus: [],
})))
await page.route('**/api/admin/orders/order_quotation', (r) => r.fulfill(json(ORDER)))
// 无收款码（与用户截图同形态）—— 页头不出现二维码块
await page.route('**/api/admin/settings/payment-qrcodes', (r) => r.fulfill(json({})))

await page.goto(`${BASE}/orders/order_quotation`, { waitUntil: 'domcontentloaded' })
await page.getByRole('button', { name: '打印报价单' }).click({ timeout: 45000 })
await page.waitForSelector('[data-testid="print-preview-paper"]', { timeout: 45000 })
await page.waitForTimeout(800)

// 机器读数（与读图互相印证）：列数 / 是否含「品名」「工艺」/ 是否出现商品名
const probe = await page.evaluate(() => {
  const paper = document.querySelector('[data-testid="print-preview-paper"]')
  const area = paper?.querySelector('.quotation-print-area')
  const heads = Array.from(area?.querySelectorAll('thead th') ?? []).map((el) => el.textContent?.trim() ?? '')
  const rows = Array.from(area?.querySelectorAll('tbody tr') ?? []).map((tr) =>
    Array.from(tr.querySelectorAll('td')).map((td) => td.textContent?.trim() ?? '')
  )
  const text = area?.textContent ?? ''
  // 表头是否被挤压/溢出（`whitespace-nowrap` 下溢出会压到相邻列的边框上）
  const headOverflow = Array.from(area?.querySelectorAll('thead th') ?? []).map((el) => ({
    text: el.textContent?.trim() ?? '',
    overflowPx: Math.round(el.scrollWidth - el.clientWidth),
    widthPx: Math.round(el.getBoundingClientRect().width),
  }))
  return {
    headOverflow,
    heads,
    rowCells: rows.map((r) => r.length),
    hasNameColumn: heads.includes('品名'),
    hasProductName: text.includes('奶油风纯色遮光窗帘'),
    hasCraftRow: rows.some((r) => r[0] === '工艺'),
    scrollWidth: area?.scrollWidth ?? 0,
    clientWidth: area?.clientWidth ?? 0,
    paperHeightMm: paper?.getBoundingClientRect().height ?? 0,
  }
})
console.log('probe:', JSON.stringify(probe))

await page.screenshot({ path: '/tmp/quotation-print-preview.png', fullPage: true })
await page.locator('[data-testid="print-preview-paper"]').screenshot({ path: '/tmp/quotation-print-paper.png' })
console.log('shot: /tmp/quotation-print-preview.png + /tmp/quotation-print-paper.png')

await browser.close()
