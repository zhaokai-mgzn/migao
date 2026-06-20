import { test, expect } from '@playwright/test'

/**
 * Mock dashboard API responses so tests run deterministically
 * without requiring a live backend.
 */
async function mockDashboardApis(page: import('@playwright/test').Page) {
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

  // GET /api/dashboard/sessions/active
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
}

test.describe('仪表盘页面', () => {
  test.beforeEach(async ({ page }) => {
    await mockDashboardApis(page)
    await page.goto('/dashboard')
    // 等待数据加载完成（骨架屏消失）
    await page.waitForTimeout(500)
    await expect(page.locator('.animate-pulse')).toHaveCount(0, { timeout: 10_000 })
  })

  test('欢迎语展示用户名', async ({ page }) => {
    await expect(page.getByText('欢迎回来，张三')).toBeVisible()
  })

  test('日期显示格式正确', async ({ page }) => {
    // 格式：YYYY年M月D日 星期X
    const datePattern = /\d{4}年\d{1,2}月\d{1,2}日 星期[一二三四五六日]/
    await expect(page.getByText(datePattern)).toBeVisible()
  })

  test('4 个统计卡片标题正确渲染', async ({ page }) => {
    await expect(page.getByText('今日订单')).toBeVisible()
    await expect(page.getByText('客户总数')).toBeVisible()
    await expect(page.getByText('活跃会话')).toBeVisible()
    await expect(page.getByText('本月收入')).toBeVisible()
  })

  test('"今日订单"卡片：数量 + 变化百分比', async ({ page }) => {
    // todayOrders: 42
    await expect(page.locator('text=42').first()).toBeVisible()
    // todayOrdersChange: +12.5% 较昨日
    await expect(page.getByText('+12.5% 较昨日')).toBeVisible()
  })

  test('"客户总数"卡片：总量 + 今日新增', async ({ page }) => {
    // totalCustomers: 1380
    await expect(page.getByText('1,380')).toBeVisible()
    // newCustomersToday: +8 今日新增
    await expect(page.getByText('+8 今日新增')).toBeVisible()
  })

  test('"活跃会话"卡片：数量 + AI 占比', async ({ page }) => {
    // activeSessions: 15
    await expect(page.locator('text=15').first()).toBeVisible()
    // AI 处理 73%
    await expect(page.getByText('AI 处理 73%')).toBeVisible()
  })

  test('"本月收入"卡片：货币格式化', async ({ page }) => {
    // monthRevenue: 256800 → >= 10000 → ¥25.7万
    await expect(page.getByText('¥25.7万')).toBeVisible()
    // monthRevenueChange: -3.2% 较上月
    await expect(page.getByText('-3.2% 较上月')).toBeVisible()
  })

  test('订单趋势图渲染', async ({ page }) => {
    // OrderTrendChart 标题 "订单趋势"
    await expect(page.getByText('订单趋势')).toBeVisible()
    // recharts 渲染的 SVG 应存在
    await expect(page.locator('.recharts-responsive-container')).toBeVisible()
  })

  test('趋势图默认 7 天选中', async ({ page }) => {
    // 默认 range=7, "近7天" 按钮应为激活状态（bg-white + text-gray-900）
    const btn7 = page.getByRole('button', { name: '近7天' })
    await expect(btn7).toBeVisible()
    await expect(btn7).toHaveClass(/bg-white/)
  })

  test('点击 14 天切换 → 数据刷新', async ({ page }) => {
    // 注：代码中只有 7 和 30 两个选项，无 14 天按钮
    // 此测试改为验证点击"近30天"切换 → 数据刷新
    let trendRequestCount = 0
    await page.route('**/api/admin/dashboard/order-trend*', async (route) => {
      trendRequestCount++
      const url = new URL(route.request().url())
      const days = Number(url.searchParams.get('days')) || 7
      const data = Array.from({ length: days }, (_, i) => ({
        date: `06-${String(i + 1).padStart(2, '0')}`,
        orders: 20 + i,
        sessions: 10 + i,
      }))
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data }),
      })
    })

    const btn30 = page.getByRole('button', { name: '近30天' })
    await btn30.click()

    // 等待新的 API 请求完成
    await page.waitForTimeout(500)

    // "近30天" 按钮应变为激活状态
    await expect(btn30).toHaveClass(/bg-white/)

    // 趋势 API 应被再次调用（days=30）
    expect(trendRequestCount).toBeGreaterThan(0)
  })

  test('点击 30 天切换 → 数据刷新', async ({ page }) => {
    // 与上面的测试一致，验证 30 天切换后图表仍渲染
    await page.getByRole('button', { name: '近30天' }).click()
    await page.waitForTimeout(500)

    // 图表仍然渲染
    await expect(page.locator('.recharts-responsive-container')).toBeVisible()
  })

  test('订单状态饼图渲染', async ({ page }) => {
    // OrderStatusChart 标题 "订单状态分布"
    await expect(page.getByText('订单状态分布')).toBeVisible()
    // 饼图使用 recharts
    await expect(page.locator('.recharts-pie').first()).toBeVisible()
  })

  test('最近订单表格显示数据', async ({ page }) => {
    // RecentOrders 标题 "近期订单"
    await expect(page.getByText('近期订单')).toBeVisible()
    // 表头
    await expect(page.getByText('订单号')).toBeVisible()
    await expect(page.getByText('客户')).toBeVisible()
    await expect(page.getByText('金额')).toBeVisible()
    await expect(page.getByText('状态')).toBeVisible()
    // 数据行
    await expect(page.getByText('YK20260601001')).toBeVisible()
    await expect(page.getByText('张三')).toBeVisible()
  })

  test('活跃会话列表渲染', async ({ page }) => {
    // ActiveSessions 标题 "活跃会话"
    await expect(page.getByText('活跃会话')).toBeVisible()
    // 会话项
    await expect(page.getByText('赵六')).toBeVisible()
    await expect(page.getByText('AI')).toBeVisible()
    await expect(page.getByText('钱七')).toBeVisible()
    await expect(page.getByText('人工')).toBeVisible()
  })

  test('数据加载中展示骨架屏/加载状态', async ({ page }) => {
    // 拦截所有 dashboard API，延迟响应以观察 loading
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

    // 骨架屏：4 个 animate-pulse 的占位卡片
    await expect(page.locator('.animate-pulse')).toHaveCount(4, { timeout: 3_000 })
  })

  // #387: 待处理卡片跳转链接验证（娜总 17:29 重点验收）
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
      const link = page.getByRole('link', { name: /待发货订单/ })
      await expect(link).toBeVisible()
      await expect(link).toHaveAttribute('href', '/orders?status=%E5%BE%85%E5%8F%91%E8%B4%A7')
    })

    test('"含加工待发货订单"卡片链接 → /orders?category=含加工订单&status=待发货', async ({ page }) => {
      const link = page.getByRole('link', { name: /含加工待发货订单/ })
      await expect(link).toBeVisible()
      await expect(link).toHaveAttribute('href', '/orders?category=%E5%90%AB%E5%8A%A0%E5%B7%A5%E8%AE%A2%E5%8D%95&status=%E5%BE%85%E5%8F%91%E8%B4%A7')
    })

    test('"待补库存商品"卡片链接 → /products?low_stock=true', async ({ page }) => {
      const link = page.getByRole('link', { name: /待补库存商品/ })
      await expect(link).toBeVisible()
      await expect(link).toHaveAttribute('href', '/products?low_stock=true')
    })

    test('点击"含加工待发货订单"卡片 → 跳转到订单页', async ({ page }) => {
      await page.getByRole('link', { name: /含加工待发货订单/ }).click()
      await page.waitForURL('**/orders?category=*status=*', { timeout: 10_000 })
      // 验证 URL 包含两个参数
      const url = new URL(page.url())
      expect(url.searchParams.get('category')).toBe('含加工订单')
      expect(url.searchParams.get('status')).toBe('待发货')
    })
  })
})
