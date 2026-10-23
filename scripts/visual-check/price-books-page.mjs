// 价格本页的**视觉验收**脚本（issue #7375 段 3；issue #7567 起 SKU 用公共选品器选）。
// 用法见同目录 README。
//
// 与 `reports-page.mjs` 同款：mock 掉全部 `/api/**`、不需要登录、一次产出三张图：
//   ① 未选 SKU（引导态）；② 有价（选中 SKU 后）；③ 无价（三层都空）。
// 断言靠人看：三层（协议 / 等级 / 阶梯）各自成卡、空层写「未设置」而不是 ¥0.00、删除按钮在位；
// 选品器两栏（左搜商品 / 右选 SKU）与入库单同形，且**页面上没有**手打 SKU 编号的输入框。
import { chromium } from 'playwright'

const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3124'

const SKU_ID = '2097126615461462018'
const PRODUCT = { id: 'prod-1', name: '遮光窗帘布', skuCode: 'HUOHAO-01' }
const SKUS = [
  { id: SKU_ID, colorName: '米白', doorWidth: '3.2', stock: 86, price: 30, status: 'active' },
  { id: '2097126615461462019', colorName: '米白', doorWidth: '2.8', stock: 101, price: 30, status: 'active' },
]

const filled = {
  skuId: SKU_ID,
  protocol: [{ id: 'p1', customer_id: 'c-9', price: 88 }],
  vipLevels: [{ id: 'v1', vip_level: 'vip2', price: 92 }],
  tiers: [{ id: 't1', min_qty: 50, max_qty: 99, price: 85 }, { id: 't2', min_qty: 100, max_qty: null, price: 78 }],
}
const empty = { skuId: SKU_ID, protocol: [], vipLevels: [], tiers: [] }

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })

async function openPage(book) {
  const page = await ctx.newPage()
  page.on('console', m => { if (m.type() === 'error') console.log('[console]', m.text().slice(0, 160)) })
  await page.route('**/api/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: [] }) }))
  await page.route('**/api/auth/refresh', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { accessToken: 't', expiresIn: 3600 } }) }))
  await page.route('**/api/auth/me', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { id: 'u1', username: 'admin', name: '管理员', tenantId: 1, roles: ['admin'], permissions: ['*'], menus: [] } }) }))
  await page.route('**/api/admin/pricing/books**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: book }) }))
  // 选品器（issue #7567）：商品搜索 + 规格详情。（⚠️ 后注册优先 ⇒ 详情路由写在列表之后）
  await page.route('**/api/admin/products**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { items: [PRODUCT], total: 1 } }) }))
  await page.route('**/api/admin/products/*', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { ...PRODUCT, skus: SKUS } }) }))
  await page.goto(BASE + '/price-books', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('h1', { timeout: 45000 }).catch(() => console.log('!! no h1 within 45s'))
  await page.waitForTimeout(1200)
  return page
}

// ① 未选 SKU：只有引导（且**没有**手打编号的输入框）
{
  const page = await openPage(filled)
  const legacyInput = await page.locator('[data-testid="price-books-sku"]').count()
  console.log('legacy sku input count（必须是 0）:', legacyInput)
  await page.screenshot({ path: '/tmp/price-books-hint.png', fullPage: true })
  console.log('shot /tmp/price-books-hint.png')
  await page.close()
}

async function shootSelected(book, out) {
  const page = await openPage(book)
  // 走公共选品器：搜商品 → 点商品 → 单选第一个 SKU
  await page.getByLabel('搜索商品').fill('遮光')
  await page.getByRole('button', { name: /遮光窗帘布/ }).first().click()
  await page.getByRole('radio').first().click()
  await page.waitForTimeout(1200)
  await page.screenshot({ path: out, fullPage: true })
  console.log('shot', out)
  await page.close()
}

await shootSelected(filled, '/tmp/price-books-filled.png')
await shootSelected(empty, '/tmp/price-books-empty.png')
await browser.close()
