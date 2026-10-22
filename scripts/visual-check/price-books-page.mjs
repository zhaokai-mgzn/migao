// 价格本页的**视觉验收**脚本（issue #7375 段 3）。用法见同目录 README。
//
// 与 `reports-page.mjs` 同款：mock 掉全部 `/api/**`、不需要登录、一次产出「有价 / 无价」两张图。
// 断言靠人看：三层（协议 / 等级 / 阶梯）各自成卡、空层写「未设置」而不是 ¥0.00、删除按钮在位。
import { chromium } from 'playwright'

const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3124'

const filled = {
  skuId: 1024,
  protocol: [{ id: 'p1', customer_id: 'c-9', price: 88 }],
  vipLevels: [{ id: 'v1', vip_level: 'vip2', price: 92 }],
  tiers: [{ id: 't1', min_qty: 50, max_qty: 99, price: 85 }, { id: 't2', min_qty: 100, max_qty: null, price: 78 }],
}
const empty = { skuId: 1024, protocol: [], vipLevels: [], tiers: [] }

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })

async function shoot(book, out) {
  const page = await ctx.newPage()
  await page.route('**/api/**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: [] }) }))
  await page.route('**/api/auth/refresh', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { accessToken: 't', expiresIn: 3600 } }) }))
  await page.route('**/api/auth/me', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { id: 'u1', username: 'admin', name: '管理员', tenantId: 1, roles: ['admin'], permissions: ['*'], menus: [] } }) }))
  await page.route('**/api/admin/pricing/books**', r => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: book }) }))
  await page.goto(BASE + '/price-books', { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('h1', { timeout: 45000 }).catch(() => console.log('!! no h1 within 45s'))
  await page.fill('[data-testid="price-books-sku"]', '1024')
  await page.waitForTimeout(1200)
  await page.screenshot({ path: out, fullPage: true })
  console.log('shot', out)
  await page.close()
}

await shoot(filled, '/tmp/price-books-filled.png')
await shoot(empty, '/tmp/price-books-empty.png')
await browser.close()
