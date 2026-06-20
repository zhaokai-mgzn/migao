import { test, expect } from '@playwright/test'
// auth 由全局 auth-setup 项目提供

/**
 * Mock dashboard API responses so tests run deterministically
 * without requiring a live backend.
 */
async function mockDashboardApis(page: import('@playwright/test').Page) {
  // GET /api/auth/me — AuthProvider.initialize() 验证 token 有效性
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ code: 200, data: { id: '1', username: '13800138000', name: '管理员', roles: ['admin'], tenantId: 1, tenantName: '测试企业' } }),
    })
  })

  // GET /api/admin/notifications/unread-count (NotificationBell in Header)
  await page.route('**/api/admin/notifications/unread-count', async (route) => {
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ code: 200, data: { count: 0 } }),
    })
  })

  // GET /api/dashboard/stats
  await page.route('**/api/admin/dashboard/stats', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
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
        },
      }),
    })
  })

  // GET /api/dashboard/orders/trend?days=7 or days=30
  await page.route('**/api/admin/dashboard/order-trend*', async (route) => {
    const url = new URL(route.request().url())
    const days = Number(url.searchParams.get('days')) || 7
    const data = Array.from({ length: days }, (_, i) => ({
      date: `06-${String(i + 1).padStart(2, '0')}`,
      orders: Math.floor(Math.random() * 50) + 10,
      sessions: Math.floor(Math.random() * 30) + 5,
      totalAmount: (Math.floor(Math.random() * 50) + 10) * 23.8,
    }))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 200, data }),
    })
  })

  // GET /api/dashboard/orders/status
  await page.route('**/api/admin/dashboard/order-status*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        data: [
          { label: '待付款', count: 12, color: '#f59e0b' },
          { label: '待发货', count: 25, color: '#3b82f6' },
          { label: '已发货', count: 18, color: '#6366f1' },
          { label: '已完成', count: 120, color: '#22c55e' },
          { label: '已关闭', count: 5, color: '#6b7280' },
        ],
      }),
    })
  })

  // GET /api/dashboard/orders/recent
  await page.route('**/api/admin/dashboard/recent-orders*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        data: [
          {
            id: '1',
            orderNo: 'YK20260601001',
            customerName: '张三',
            totalAmount: 1280.50,
            status: 'pending_payment',
            createdAt: '2026-06-01T10:30:00Z',
          },
          {
            id: '2',
            orderNo: 'YK20260601002',
            customerName: '李四',
            totalAmount: 3560.00,
            status: 'completed',
            createdAt: '2026-06-01T09:15:00Z',
          },
          {
            id: '3',
            orderNo: 'YK20260601003',
            customerName: '王五',
            totalAmount: 890.00,
            status: 'shipped',
            createdAt: '2026-05-31T14:20:00Z',
          },
        ],
      }),
    })
  })

  // GET /api/dashboard/sessions/active (not used by current dashboard but mock for safety)
  await page.route('**/api/admin/dashboard/active-sessions*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        data: [
          {
            id: 's1',
            customerName: '赵六',
            isAI: true,
            lastMessage: '请问这款窗帘有遮光效果吗？',
            channel: 'wechat_mini',
            duration: '5分钟',
          },
          {
            id: 's2',
            customerName: '钱七',
            isAI: false,
            lastMessage: '我需要定制3米宽的',
            channel: 'h5',
            duration: '12分钟',
          },
        ],
      }),
    })
  })

  // GET /api/dashboard/product-ranking
  await page.route('**/api/admin/dashboard/product-ranking*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        data: [
          { rank: 1, productId: 'p1', productName: '遮光窗帘A款', salesQty: 230, salesAmount: 46000, qtyDisplay: '230', amountDisplay: '¥46,000', dailyChange: 12 },
          { rank: 2, productId: 'p2', productName: '纱帘B款', salesQty: 185, salesAmount: 37000, qtyDisplay: '185', amountDisplay: '¥37,000', dailyChange: -5 },
          { rank: 3, productId: 'p3', productName: '百叶窗C款', salesQty: 120, salesAmount: 24000, qtyDisplay: '120', amountDisplay: '¥24,000', dailyChange: 8 },
        ],
      }),
    })
  })
}

test.describe('仪表盘页面', () => {
  test.beforeEach(async ({ page }) => {
    await mockDashboardApis(page)
    await page.goto('/dashboard')
    // 等待数据加载完成（骨架屏消失）
    await page.waitForTimeout(500)
    await expect(page.locator('.animate-pulse')).toHaveCount(0, { timeout: 10_000 })
  })

  test('页面标题展示"数据看板"', async ({ page }) => {
    await expect(page.getByText('数据看板')).toBeVisible()
  })

  test('日期显示格式正确 — 数据更新时间', async ({ page }) => {
    // formatFullDateTime 输出格式：YYYY年M月D日 HH:mm（无星期）
    // 显示为：数据更新时间：2026年6月20日 14:30
    const datePattern = /\d{4}年\d{1,2}月\d{1,2}日 \d{2}:\d{2}/
    await expect(page.getByText(datePattern)).toBeVisible()
  })

  test('3 个经营数据卡片标题正确渲染', async ({ page }) => {
    await expect(page.getByText('今日订单数')).toBeVisible()
    await expect(page.getByText('今日销售额')).toBeVisible()
    await expect(page.getByText('本月销售额')).toBeVisible()
  })

  test('"今日订单数"卡片：数量 + 变化', async ({ page }) => {
    // todayOrders: 42 — toLocaleString() → "42"
    await expect(page.locator('text=42').first()).toBeVisible()
    // change 格式：较昨天 {val}（无 % 前缀，BizStatCard 模板硬编码）
    await expect(page.getByText('较昨天 12.5')).toBeVisible()
  })

  test('"今日销售额"卡片：货币格式化 + 变化', async ({ page }) => {
    // todaySales: 8900 → fmtCurrency → "¥8,900"
    await expect(page.getByText('¥8,900')).toBeVisible()
    // todaySalesChange: 8.3 → 较昨天 8.3
    await expect(page.getByText('较昨天 8.3')).toBeVisible()
  })

  test('"本月销售额"卡片：货币格式化', async ({ page }) => {
    // monthRevenue: 256800 → fmtCurrency → "¥25.7万"
    await expect(page.getByText('¥25.7万')).toBeVisible()
    // monthRevenueChange: -3.2 → val 字符串为 "-3.2% 较上月"，BizStatCard 前缀 "较昨天 "
    // 实际渲染：较昨天 -3.2% 较上月；getByText 使用子串匹配
    await expect(page.getByText('-3.2% 较上月')).toBeVisible()
  })

  test('订单趋势图渲染（内联 SVG）', async ({ page }) => {
    // 标题 "订单趋势"
    await expect(page.getByText('订单趋势')).toBeVisible()
    // 趋势图使用内联 SVG（非 recharts），svg > polyline 存在即可
    await expect(page.locator('svg polyline').first()).toBeVisible()
  })

  test('趋势图默认 7 天选中', async ({ page }) => {
    // 默认 range=7, "近7天" 按钮应为激活状态（bg-white + text-gray-900）
    const btn7 = page.getByRole('button', { name: '近7天' })
    await expect(btn7).toBeVisible()
    await expect(btn7).toHaveClass(/bg-white/)
  })

  test('点击"近30天"切换 → 数据刷新', async ({ page }) => {
    // 点击后等待趋势 API 带 days=30 的请求完成
    const btn30 = page.getByRole('button', { name: '近30天' })
    const respPromise = page.waitForResponse(
      (resp) => resp.url().includes('/dashboard/order-trend') && resp.url().includes('days=30'),
      { timeout: 10_000 },
    )
    await btn30.click()
    // 等待 API 响应
    await respPromise
    // "近30天" 按钮应变为激活状态
    await expect(btn30).toHaveClass(/bg-white/)
  })

  test('点击"近30天"切换后图表仍渲染', async ({ page }) => {
    await page.getByRole('button', { name: '近30天' }).click()
    await page.waitForTimeout(500)

    // 图表仍然渲染（内联 SVG）
    await expect(page.locator('svg polyline').first()).toBeVisible()
  })

  test('销售额趋势图渲染', async ({ page }) => {
    // 第二个图表标题 "销售额数据"（替代了原来的订单状态饼图）
    await expect(page.getByText('销售额数据')).toBeVisible()
    // 面积图使用 SVG path + polyline
    await expect(page.locator('svg path').first()).toBeVisible()
  })

  test('近期订单表格显示数据', async ({ page }) => {
    // 标题 "近期订单"
    await expect(page.getByText('近期订单')).toBeVisible()
    // 表头（新增 "时间" 列，共 5 列）
    await expect(page.getByText('订单号')).toBeVisible()
    await expect(page.getByText('客户')).toBeVisible()
    await expect(page.getByText('金额')).toBeVisible()
    await expect(page.getByText('状态')).toBeVisible()
    await expect(page.getByText('时间')).toBeVisible()
    // 数据行
    await expect(page.getByText('YK20260601001')).toBeVisible()
    await expect(page.getByText('张三')).toBeVisible()
  })

  test('商品销量排行渲染', async ({ page }) => {
    // 替代了原来的活跃会话列表
    await expect(page.getByText('商品销量排行')).toBeVisible()
    // 表头
    await expect(page.getByText('成交量')).toBeVisible()
    // 数据行
    await expect(page.getByText('遮光窗帘A款')).toBeVisible()
    await expect(page.getByText('230')).toBeVisible()
  })

  test('数据加载中展示骨架屏/加载状态', async ({ page }) => {
    // 拦截 stats API，延迟响应以观察 loading
    await page.route('**/api/admin/dashboard/stats', async (route) => {
      await new Promise((r) => setTimeout(r, 5000))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: {} }),
      })
    })

    // 重新导航触发 loading
    await page.goto('/dashboard')

    // 骨架屏：3 个经营数据卡片 + 5 个排行骨架行 = 8 个 animate-pulse
    await expect(page.locator('.animate-pulse')).toHaveCount(8, { timeout: 3_000 })
  })

  // #387: 待处理卡片跳转链接验证
  test.describe('待处理区 3 个卡片 — 跳转链接 (#387)', () => {
    test.beforeEach(async ({ page }) => {
      // 待发货订单数
      await page.route('**/api/admin/dashboard/pending-shipment-count', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200, data: 15 }) })
      })
      // 含加工待发货订单数
      await page.route('**/api/admin/dashboard/processing-shipment-count', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200, data: 8 }) })
      })
      // 待补库存 SKU
      await page.route('**/api/admin/products/low-stock-by-color*', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200, data: Array.from({ length: 12 }) }) })
      })
      await page.goto('/dashboard')
      await page.waitForTimeout(500)
      await expect(page.locator('.animate-pulse')).toHaveCount(0, { timeout: 10_000 })
    })

    test('"待发货订单"卡片链接 → /orders?status=待发货', async ({ page }) => {
      // anchor at start to avoid matching "含加工待发货订单" (which contains the substring)
      const link = page.getByRole('link', { name: /^待发货订单/ })
      await expect(link).toBeVisible()
      await expect(link).toHaveAttribute('href', /\/orders\?.*status=/)
    })

    test('"含加工待发货订单"卡片链接 → /orders?category=含加工订单&status=待发货', async ({ page }) => {
      const link = page.getByRole('link', { name: /含加工待发货订单/ })
      await expect(link).toBeVisible()
      await expect(link).toHaveAttribute('href', /\/orders\?.*category=.*status=/)
    })

    test('"待补库存商品"卡片链接 → /products?low_stock=true', async ({ page }) => {
      const link = page.getByRole('link', { name: /待补库存商品/ })
      await expect(link).toBeVisible()
      await expect(link).toHaveAttribute('href', '/products?low_stock=true')
    })

    test('点击"含加工待发货订单"卡片 → 跳转到订单页', async ({ page }) => {
      await page.getByRole('link', { name: /含加工待发货订单/ }).click()
      await page.waitForURL(/\/orders\?.*category=.*status=/, { timeout: 10_000 })
      // 验证 URL 包含两个参数
      const url = new URL(page.url())
      expect(url.searchParams.get('category')).toBe('含加工订单')
      expect(url.searchParams.get('status')).toBe('待发货')
    })
  })
})
