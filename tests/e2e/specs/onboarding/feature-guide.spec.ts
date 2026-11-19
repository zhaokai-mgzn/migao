// case_ids: UI-153
/**
 * 首次登录功能使用引导（issue #8925）—— 真实浏览器判据 + Before/After 截图入口。
 *
 * 与单测的分工：
 *   · 单测钉存储语义（pending / shown / dismissed 三枚标记）与权限裁剪；
 *   · 本文件钉**真实登录流程**：从 /login 填账号密码 ⇒ 业务页真的弹出引导，
 *     「关闭」后刷新不再弹、退出重登再弹；「不再提醒」后重登也不弹。
 *
 * 环境：本机没有 admin-api 时走 E2E fixture 模式（`E2E_MOCK_AUTH=true` / playwright.config 本地默认），
 * 认证与 dashboard 旁路接口全部 mock；这是本仓既有 UI 证据口径（见
 * tests/e2e/specs/orders/order-detail-regions.spec.ts 头注释），**不是**设计稿。
 *
 * 截图入口（同一脚本可跑改前基线，截图落在断言之前）：
 *   MIGAO_SHOT_DIR=/tmp/feature-guide MIGAO_SHOT_LABEL=before \
 *     npx playwright test e2e/specs/onboarding/feature-guide.spec.ts --project=web
 */
import { test, expect, type Page } from '@playwright/test'

const LOGIN_RESPONSE = {
  success: true,
  data: {
    accessToken: 'e2e-feature-guide-token',
    refreshToken: 'e2e-feature-guide-refresh',
    user: {
      id: 'u-guide-e2e',
      username: 'zhangsan@migao',
      name: '张三',
      mustChangePassword: false,
      tenantId: 1,
      tenantName: '测试布艺',
    },
  },
}

const ADMIN_ME = {
  user: { id: 'u-guide-e2e', username: 'zhangsan@migao', name: '张三', mustChangePassword: false, tenantId: 1, tenantName: '测试布艺' },
  roles: ['admin'],
  permissions: ['*'],
  menus: [],
  capabilities: { mibaoChat: true, aiService: true },
}

const CUSTOMER_SERVICE_ME = {
  user: { id: 'u-guide-kefu', username: 'kefu@migao', name: '客服小王', mustChangePassword: false, tenantId: 1, tenantName: '测试布艺' },
  roles: ['customer_service'],
  permissions: ['agent:session', 'knowledge:view', 'after_sales:view', 'customer:view'],
  menus: [],
  capabilities: { mibaoChat: false },
}

/** dashboard 旁路接口（fixture 模式无后端；与 tests/e2e/specs/dashboard/dashboard.spec.ts 同形） */
async function mockDashboard(page: Page) {
  // 兜底：未 mock 的通知 / 企业配置等给空成功，避免 axios 拦截器把「网络连接失败」toast 打进证据
  await page.route('**/api/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: null }),
    })
  })

  await page.route('**/api/auth/employee/login', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LOGIN_RESPONSE) })
  })
  await page.route('**/api/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { accessToken: 'e2e-feature-guide-token' } }),
    })
  })
  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: null }) })
  })

  await page.route('**/api/admin/dashboard/stats', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          todayOrders: 42,
          todayOrdersChange: 12.5,
          todaySales: 8900,
          todaySalesChange: 8.3,
          totalCustomers: 1380,
          newCustomersToday: 8,
          activeSessions: 15,
          aiSessionRate: 73,
          monthRevenue: 256800,
          monthRevenueChange: -3.2,
          totalProducts: 86,
          totalOrders: 521,
          totalTickets: 9,
          pendingShipOrders: 11,
          pendingPaymentOrders: 6,
          overdueTickets: 2,
          processingPendingOrders: 4,
          lowStockItems: 3,
        },
      }),
    })
  })
  await page.route('**/api/admin/dashboard/order-trend*', async (route) => {
    const days = Number(new URL(route.request().url()).searchParams.get('days')) || 7
    const data = Array.from({ length: days }, (_, i) => ({
      date: `11-${String(i + 1).padStart(2, '0')}`,
      orders: 12 + i * 3,
      sessions: 8 + i * 2,
      amount: 2600 + i * 800,
    }))
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data }) })
  })
  await page.route('**/api/admin/dashboard/order-status*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [
          { label: '待付款', count: 6, color: '#f59e0b' },
          { label: '待发货', count: 11, color: '#3b82f6' },
          { label: '已发货', count: 18, color: '#6366f1' },
          { label: '已完成', count: 120, color: '#22c55e' },
          { label: '已关闭', count: 5, color: '#6b7280' },
        ],
      }),
    })
  })
  await page.route('**/api/admin/dashboard/recent-orders*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [
          { id: '1', orderNo: 'MG20261119001', customerName: '张三', totalAmount: 1280.5, status: 'pending_payment', createdAt: '2026-11-19T10:30:00+08:00' },
          { id: '2', orderNo: 'MG20261119002', customerName: '李四', totalAmount: 3560, status: 'completed', createdAt: '2026-11-19T09:15:00+08:00' },
          { id: '3', orderNo: 'MG20261119003', customerName: '王五', totalAmount: 890, status: 'shipped', createdAt: '2026-11-18T14:20:00+08:00' },
        ],
      }),
    })
  })
  await page.route('**/api/admin/dashboard/product-ranking*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: [
          { rank: 1, productId: 'p1', productName: '全遮光雪尼尔', salesQty: 230, salesAmount: 46000, qtyDisplay: '230', amountDisplay: '¥46,000', dailyChange: 12 },
          { rank: 2, productId: 'p2', productName: '亚麻拼接窗帘', salesQty: 185, salesAmount: 37000, qtyDisplay: '185', amountDisplay: '¥37,000', dailyChange: -5 },
          { rank: 3, productId: 'p3', productName: '纱帘B款', salesQty: 120, salesAmount: 24000, qtyDisplay: '120', amountDisplay: '¥24,000', dailyChange: 8 },
        ],
      }),
    })
  })

  const emptyReports: Record<string, unknown> = {
    'order-margins': { hasData: false, rows: [], totals: null, unknownCostOrders: 0 },
    'inventory-aging': { slowMovingDays: 90, hasData: false, rows: [], totals: null, undeterminedRows: 0 },
    'staff-performance': { hasData: false, rows: [], totals: null, unattributedOrders: 0 },
    'quality-cost': { components: [], total: null, complete: true, unknownComponents: [] },
    'receivable-aging': { asOf: '2026-11-19', hasData: false, customerCount: 0, buckets: [], customers: [], totals: null },
  }
  for (const [key, data] of Object.entries(emptyReports)) {
    await page.route(`**/api/admin/reports/${key}*`, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data }) })
    })
  }
  await page.route('**/api/admin/reports/quality-cost/breakdown*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          dimension: 'customer', scope: 'x', startDate: null, endDate: null, hasData: false, rows: [], totals: null,
          unattributed: { rework: 0, reworkLines: 0, compensation: 0, compensationCount: 0, total: 0, reason: '' },
          notes: [],
        },
      }),
    })
  })
  await page.route('**/api/admin/warehouses*', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: [] }) })
  })
  await page.route('**/api/admin/briefing/config', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { enabled: false } }) })
  })
  await page.route('**/api/admin/notifications/unread-count', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: { count: 2 } }) })
  })
}

async function mockMe(page: Page, me: typeof ADMIN_ME | typeof CUSTOMER_SERVICE_ME) {
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: me }) })
  })
}

async function loginFromUi(page: Page, expectedUrl = '**/dashboard*') {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 300_000 })
  // Next dev 首屏水合前 fill 会被受控输入的重渲染清空（实测账号框被清掉、密码框留下）⇒
  // 等 load + 一小段水合窗口后再填，并逐字断言值真的进去了。
  await page.waitForLoadState('load')
  await page.waitForTimeout(1_500)
  const identifier = page.getByLabel('账号')
  const password = page.getByLabel('密码')
  await identifier.fill('zhangsan@migao')
  await password.fill('Init#12345')
  await expect(identifier).toHaveValue('zhangsan@migao')
  await expect(password).toHaveValue('Init#12345')
  await page.locator('button[type="submit"]').click()
  // 登录落点按权限算（landingPath）：管理员 = /dashboard；客服岗位首项 = 在线接待。
  await page.waitForURL(expectedUrl, { timeout: 120_000 })
}

async function logoutFromUi(page: Page) {
  await page.getByRole('button', { name: '用户菜单' }).click()
  await page.getByRole('button', { name: '退出登录' }).click()
  await page.waitForURL('**/login*', { timeout: 120_000 })
}

test.describe('首次登录功能使用引导（issue #8925）', () => {
  // 本用例自己走 UI 登录 ⇒ 不加载 auth-setup 的 storageState
  test.use({ storageState: { cookies: [], origins: [] }, viewport: { width: 1440, height: 980 } })

  test('登录后弹出；关闭仅本次、退出重登再弹；不再提醒后重登不弹', async ({ page }) => {
    test.setTimeout(600_000)
    await mockDashboard(page)
    await mockMe(page, ADMIN_ME)

    await loginFromUi(page)

    // 截图落在「引导是否出现」断言之前：同一脚本跑改前基线时也能留下 Before 证据。
    // 等「登录成功」toast 消失，并只在截图时隐藏 Next dev 指示器（不改业务 DOM）。
    const shotDir = process.env.MIGAO_SHOT_DIR
    if (shotDir) {
      await page.waitForTimeout(4_000)
      await page.addStyleTag({ content: 'nextjs-portal { display: none !important; }' })
      await page.screenshot({
        path: `${shotDir}/${process.env.MIGAO_SHOT_LABEL || 'feature-guide'}.png`,
        fullPage: false,
      })
    }

    const dialog = page.getByRole('dialog', { name: '功能使用引导' })
    await expect(dialog).toBeVisible({ timeout: 10_000 })
    await expect(dialog.getByRole('button', { name: '关闭' })).toBeVisible()
    await expect(dialog.getByRole('button', { name: '不再提醒' })).toBeVisible()
    await expect(dialog.getByText('「关闭」仅本次，下次登录仍会提示')).toBeVisible()
    // 功能地图真的渲染（不是空弹窗）
    await expect(dialog.getByTestId('feature-guide-module-customer-service')).toContainText('在线接待')

    // ① 关闭 ⇒ 本次会话不再弹（刷新同一 tab，sessionStorage 仍在）
    await dialog.getByRole('button', { name: '关闭' }).click()
    await expect(dialog).toHaveCount(0)
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { level: 1, name: '经营报表' })).toBeVisible({ timeout: 120_000 })
    await expect(page.getByRole('dialog', { name: '功能使用引导' })).toHaveCount(0)

    // ② 退出重登 ⇒ pending 重新落下，再次弹出
    await logoutFromUi(page)
    await loginFromUi(page)
    await expect(page.getByRole('dialog', { name: '功能使用引导' })).toBeVisible({ timeout: 10_000 })

    // ③ 不再提醒 ⇒ 重登 / 刷新都不弹
    await page.getByTestId('feature-guide-never').click()
    await expect(page.getByRole('dialog', { name: '功能使用引导' })).toHaveCount(0)
    const dismissed = await page.evaluate(() =>
      Object.keys(localStorage).filter((k) => k.startsWith('migao.feature-guide.dismissed.v1.')),
    )
    expect(dismissed.length, '「不再提醒」应写按用户隔离的 localStorage 标记').toBeGreaterThan(0)

    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { level: 1, name: '经营报表' })).toBeVisible({ timeout: 120_000 })
    await expect(page.getByRole('dialog', { name: '功能使用引导' })).toHaveCount(0)

    await logoutFromUi(page)
    await loginFromUi(page)
    await expect(page.getByRole('dialog', { name: '功能使用引导' })).toHaveCount(0)
  })

  test('功能地图按岗位权限裁剪：客服看不到财务 / 销售订单，也不教无权限的经营报表 / 米宝', async ({ page }) => {
    test.setTimeout(600_000)
    await mockDashboard(page)
    await mockMe(page, CUSTOMER_SERVICE_ME)

    await loginFromUi(page, '**/agent-workspace/human-sessions*')
    const dialog = page.getByRole('dialog', { name: '功能使用引导' })
    await expect(dialog).toBeVisible({ timeout: 10_000 })

    await expect(dialog.getByTestId('feature-guide-module-customer-service')).toContainText('在线接待')
    await expect(dialog.getByTestId('feature-guide-module-orders-products')).toContainText('客户列表')
    await expect(dialog.getByTestId('feature-guide-module-finance-center')).toHaveCount(0)
    await expect(dialog.getByText('销售订单')).toHaveCount(0)
    await expect(dialog.getByText('先看经营报表')).toHaveCount(0)
    await expect(dialog.getByText('不会操作就问米宝')).toHaveCount(0)
  })
})
