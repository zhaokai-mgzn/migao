// 客户详情「标签」空态的视觉验收（issue #7526）。
//
// 用法（在 `frontend/admin-web` 先 `npm run build`）：
//   1) `npx next start -p 3126`
//   2) `npm --prefix /tmp i playwright && npx playwright install chromium`（仅首次）
//   3) `node scripts/visual-check/customer-detail-tags-empty.mjs`（在**仓库根**跑）
// 产物：
//   /tmp/customer-tags-empty-before.png    系统无标签，未点「+」
//   /tmp/customer-tags-empty-popover.png   系统无标签，点「+」后的空态 + 去处（本单的靶心）
//   /tmp/customer-tags-picker.png          有可加标签时的正常选择器（负控：空态不得掩盖它）
//   /tmp/customer-tags-manage-modal.png    深链 `/customers?manageTags=1` 直接打开标签管理
//
// 为什么要有它：本单是**交互反馈**问题（「点了没反应」）—— 单测能断言 DOM，但看不出
// 「浮层位置是否压住别的卡片 / 文案是否挤成两行 / 按钮是否像能点的」。只读、mock 全部 API。
import { chromium } from 'playwright'

const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3126'

const PROFILE = {
  id: 'cus-001',
  wechatNickname: '张三',
  phone: '13800138000',
  sourceChannel: 'wechat_mini',
  vipLevel: 'vip1',
  agentNotes: '老客户，偏好遮光窗帘',
  lastActiveAt: '2026-10-20T14:30:00',
  registeredAt: '2026-01-15T10:00:00',
  defaultReceiverName: '张三',
  defaultReceiverPhone: '13800138000',
  defaultReceiverAddress: '浙江省杭州市西湖区文三路1号1幢101室',
  defaultLogisticsType: 'logistics',
  defaultLogisticsCompany: '四季安物流',
}

const ORDER = {
  id: 'o1', orderNo: 'ORD20261015001', totalAmount: 2680, status: 'completed', createdAt: '2026-10-15T10:00:00',
}

const detail = (tags) => ({
  success: true,
  data: { id: 'cus-001', profile: PROFILE, tags, orders: [ORDER], sessions: [] },
})

const TAG = { id: 't1', name: '优质', color: '#48618f' }
const TAG2 = { id: 't2', name: '待跟进', color: '#F59E0B' }

const CREDIT = {
  success: true,
  data: { customerId: 'cus-001', creditLimit: 10000, paymentTermsDays: 30, outstanding: 6000, available: 4000 },
}

const json = (data) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(data) })

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 980 }, deviceScaleFactor: 1 })

/** 一套 API 桩：`systemTags` = 系统里定义的标签，`customerTags` = 该客户已关联的标签 */
async function newPage({ systemTags, customerTags }) {
  const page = await ctx.newPage()
  page.on('console', (m) => { if (m.type() === 'error') console.log('[console]', m.text().slice(0, 160)) })

  // 通用兜底先注册（Playwright route 后注册优先）
  await page.route('**/api/**', (r) => r.fulfill(json({ success: true, data: [] })))
  await page.route('**/api/auth/refresh', (r) => r.fulfill(json({ success: true, data: { accessToken: 'dev-token', expiresIn: 3600 } })))
  await page.route('**/api/auth/me', (r) => r.fulfill(json({
    success: true,
    data: { id: 'u1', username: 'admin', name: '管理员', tenantId: 1, roles: ['admin'], permissions: ['*'], menus: [] },
  })))
  await page.route('**/api/admin/user/info', (r) => r.fulfill(json({
    success: true,
    data: { id: 'u1', username: 'admin', name: '管理员', tenantId: 1, roles: ['admin'], permissions: ['*'], menus: [] },
  })))

  await page.route('**/api/admin/customer-tags**', (r) => r.fulfill(json({ success: true, data: systemTags })))
  await page.route('**/api/admin/customers/cus-001/credit**', (r) => r.fulfill(json(CREDIT)))
  await page.route('**/api/admin/customers/cus-001', (r) => r.fulfill(json(detail(customerTags))))
  await page.route('**/api/admin/customers?**', (r) => r.fulfill(json({
    success: true,
    data: { items: [{ id: 'cus-001', name: '张三', phone: '138****8000', sourceChannel: 'wechat_mini', vipLevel: 'vip1', tags: [], totalOrders: 1, totalSpent: 2680, createdAt: '2026-01-15T10:00:00', lastActiveAt: '2026-10-20T14:30:00' }], total: 1, page: 1, pageSize: 10 },
  })))
  return page
}

// ① 系统还没有任何标签：未点「+」 vs 点「+」后（本单的靶心）
{
  const page = await newPage({ systemTags: [], customerTags: [] })
  await page.goto(`${BASE}/customers/cus-001`, { waitUntil: 'domcontentloaded' })
  await page.getByText('张三').first().waitFor({ timeout: 45000 })
  const trigger = page.getByRole('button', { name: '添加标签' })
  await trigger.scrollIntoViewIfNeeded()
  await page.waitForTimeout(600)
  await page.screenshot({ path: '/tmp/customer-tags-empty-before.png' })

  await trigger.click()
  await page.waitForTimeout(500)
  await page.screenshot({ path: '/tmp/customer-tags-empty-popover.png' })
  const empty = page.getByTestId('customer-tag-empty')
  console.log('空态面板在场:', await empty.count(), '| 文案:', ((await empty.innerText()) || '').replace(/\s+/g, ' '))
  await page.close()
}

// ② 负控：有可加标签 ⇒ 选择器照常列出（空态不得掩盖正常选择器）
{
  const page = await newPage({ systemTags: [TAG, TAG2], customerTags: [TAG] })
  await page.goto(`${BASE}/customers/cus-001`, { waitUntil: 'domcontentloaded' })
  await page.getByText('张三').first().waitFor({ timeout: 45000 })
  const trigger = page.getByRole('button', { name: '添加标签' })
  await trigger.scrollIntoViewIfNeeded()
  await page.waitForTimeout(600)
  await trigger.click()
  await page.waitForTimeout(500)
  await page.screenshot({ path: '/tmp/customer-tags-picker.png' })
  console.log('可加标签「待跟进」可见:', await page.getByText('待跟进').count(),
    '| 空态面板数:', await page.getByTestId('customer-tag-empty').count())
  await page.close()
}

// ③ 深链：/customers?manageTags=1 直接打开标签管理（空态里那个按钮真正落到哪）
{
  const page = await newPage({ systemTags: [], customerTags: [] })
  await page.goto(`${BASE}/customers?manageTags=1`, { waitUntil: 'domcontentloaded' })
  await page.getByText('新建标签').first().waitFor({ timeout: 45000 })
  await page.waitForTimeout(500)
  await page.screenshot({ path: '/tmp/customer-tags-manage-modal.png' })
  console.log('标签管理模态在场（「新建标签」）:', await page.getByText('新建标签').count())
  await page.close()
}

await browser.close()
