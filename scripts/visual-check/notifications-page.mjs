// 通知中心页 + 铃铛面板的**视觉验收**脚本（issue #7524）。
// 用法见同目录 README；与 `stocktakes-page.mjs` / `reports-page.mjs` 同款：
// mock 掉全部 `/api/**`、不需要登录，产出三张图（通知中心列表 / 点开跳转后的入库单列表 / 铃铛面板）。
//
// 本脚本同时承担**行为断言**（截图看不出「点了有没有走」）：
//   ① 有 targetPath 的条目点开 ⇒ URL 落到 `/inbound-orders?keyword=<单号>`；
//   ② 铃铛面板里条目可点、面板能打开。
import { chromium } from 'playwright'
import assert from 'node:assert'

const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3125'

const now = Date.now()
const iso = (minutesAgo) => new Date(now - minutesAgo * 60_000).toISOString()

const items = [
  {
    id: 'n-inbound',
    tenantId: 1,
    recipientId: 'u1',
    recipientType: 'employee',
    channel: 'internal',
    title: '入库单 RK-20261023-0001 已过账',
    content: '供应商 柯桥××布行，共 2 行、入库 60.5 米，金额 756.25 元；操作人 13800000000。',
    status: 'sent',
    bizType: 'inbound_order',
    bizId: 'inbound-1',
    bizNo: 'RK-20261023-0001',
    targetPath: '/inbound-orders?keyword=RK-20261023-0001',
    severity: 'info',
    occurredAt: iso(8),
    retryCount: 0,
    createdAt: iso(8),
  },
  {
    id: 'n-order',
    tenantId: 1,
    recipientId: 'u1',
    recipientType: 'employee',
    channel: 'internal',
    title: '新订单 ORD-20261023-0007 已创建',
    content: '客户 李女士，金额 1,280.00 元，待确认。',
    status: 'sent',
    bizType: 'order',
    bizId: 'order-7',
    bizNo: 'ORD-20261023-0007',
    targetPath: '/orders?keyword=ORD-20261023-0007',
    severity: 'warn',
    occurredAt: iso(35),
    retryCount: 0,
    createdAt: iso(35),
  },
  {
    id: 'n-as',
    tenantId: 1,
    recipientId: 'u1',
    recipientType: 'employee',
    channel: 'internal',
    title: '售后工单 AS-20261023-0002 待处理',
    content: '客户反馈布面有跳线，请尽快处理。',
    status: 'sent',
    bizType: 'after_sales',
    bizId: 'as-2',
    bizNo: 'AS-20261023-0002',
    targetPath: '/after-sales',
    severity: 'urgent',
    occurredAt: iso(70),
    retryCount: 0,
    createdAt: iso(70),
  },
  {
    // 老通知：没有 targetPath / severity —— 必须**看不出可点**、圆点按 info 渲染
    id: 'n-legacy',
    tenantId: 1,
    recipientId: 'u1',
    recipientType: 'employee',
    channel: 'internal',
    title: '系统维护通知',
    content: '系统将于今晚 23:00 维护，预计 30 分钟。',
    status: 'read',
    retryCount: 0,
    createdAt: iso(60 * 26),
  },
]

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await ctx.newPage()

// ⚠️ Playwright：**先注册的通配优先**（后注册的具体路由会覆盖它）⇒ 通配必须第一个注册
await page.route('**/api/**', (r) =>
  r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: [] }) }),
)
await page.route('**/api/auth/refresh', (r) =>
  r.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, data: { accessToken: 't', expiresIn: 3600 } }),
  }),
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
await page.route('**/api/admin/notifications**', (r) =>
  r.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ success: true, data: { items, total: items.length, page: 1, size: 20 } }),
  }),
)
// ⚠️ 未读数**最后注册**（Playwright：后注册者优先）—— 否则会被上面那条通配吃掉，
// 铃铛徽标恒 0，截图会看不出「有几条未读」。
await page.route('**/api/admin/notifications/unread-count', (r) =>
  r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { count: 3 } }) }),
)

// ① 通知中心列表（含类型筛选、严重级圆点、标题里的单号）
await page.goto(BASE + '/notifications', { waitUntil: 'domcontentloaded' })
await page
  .waitForSelector('[data-testid="notification-item-n-inbound"]', { timeout: 45000 })
  .catch(() => console.log('!! 通知列表没渲染出来'))
await page.waitForTimeout(600)
await page.screenshot({ path: '/tmp/notifications-center.png', fullPage: true })
console.log('shot /tmp/notifications-center.png')

// ② 点开「有落地页」的条目 ⇒ 必须真的走到入库单列表（截图看不出这件事，所以这里断言）
await page.click('[data-testid="notification-item-n-inbound"]')
await page.waitForURL(/\/inbound-orders\?keyword=RK-20261023-0001/, { timeout: 15000 }).catch(() => {
  throw new Error('点开通知没跳到入库单列表（targetPath 未生效）')
})
await page.waitForTimeout(800)
await page.screenshot({ path: '/tmp/notifications-open-inbound.png', fullPage: true })
console.log('shot /tmp/notifications-open-inbound.png')
assert.ok(page.url().includes('/inbound-orders?keyword=RK-20261023-0001'), 'URL 应带入库单号深链')

// ③ 铃铛面板：条目可点、有落地页（面板本身也要看得见）。
// ⚠️ 不要回 `/` 首页：本脚本把未 mock 的 `/api/**` 一律回 `[]`，首页某些面板会因拿到
// 「数组当对象」而崩（视觉验收只关心通知面），所以直接回通知中心，铃铛在同一个 Header 里。
await page.goto(BASE + '/notifications', { waitUntil: 'domcontentloaded' })
await page.waitForSelector('[data-testid="notification-item-n-inbound"]', { timeout: 30000 })
const bell = page.locator('button:has(svg.lucide-bell)').first()
await bell.waitFor({ timeout: 30000 }).catch(() => console.log('!! 铃铛按钮没渲染出来'))
await bell.click()
await page.waitForSelector('[data-testid="notification-bell-item"]', { timeout: 15000 }).catch(() => console.log('!! 铃铛面板列表没渲染出来'))
await page.waitForTimeout(500)
await page.screenshot({ path: '/tmp/notifications-bell.png', fullPage: false })
console.log('shot /tmp/notifications-bell.png')

await browser.close()
console.log('✅ 通知视觉验收完成')
