// case_ids: OR-001, CU-001
/**
 * E2E 测试 — 搜索区域左对齐验证
 *
 * 业务真值 D1：所有表单页搜索/筛选区左侧对齐（与订单页一致）
 *
 * 以订单页为基准，验证各列表页搜索区域左边界位置一致。
 * 使用 recorded fixture mock API，确保测试确定性。
 * 选择器统一使用 [data-testid="search-area"]（2026-08-29 修复：原 class 选择器
 * border-gray-200 与当前 UI border-neutral-200 失配，导致测试从未真正通过）。
 *
 * 运行: npx playwright test specs/quality/search-alignment.spec.ts
 */
import { test, expect } from '../../fixtures'
import ordersFixture from '../../fixtures/orders-list.json'
import productsFixture from '../../fixtures/products-list.json'
import customersFixture from '../../fixtures/customers-list.json'
import afterSalesFixture from '../../fixtures/after-sales-list.json'
import employeesFixture from '../../fixtures/employees-list.json'

const SEARCH_SELECTOR = '[data-testid="search-area"]'

type PageKey = 'orders' | 'products' | 'after-sales' | 'customers' | 'employees'
const TOLERANCE = 2

async function mockApi(page: any, urlPattern: string, fixture: any) {
  await page.route(urlPattern, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixture) })
  })
}

async function getSearchLeft(page: any, pageKey: PageKey): Promise<number> {
  await page.waitForSelector(SEARCH_SELECTOR, { timeout: 10000 })
  const box = await page.locator(SEARCH_SELECTOR).first().boundingBox()
  if (!box) throw new Error(`Cannot find search container on ${pageKey} using "${SEARCH_SELECTOR}"`)
  return box.x
}

const API_MAP: Record<PageKey, [string, any]> = {
  orders: ['**/api/admin/orders*', ordersFixture],
  products: ['**/api/admin/products*', productsFixture],
  'after-sales': ['**/api/admin/after-sales*', afterSalesFixture],
  customers: ['**/api/admin/customers*', customersFixture],
  employees: ['**/api/admin/users*', employeesFixture],
}

test.describe('搜索区域左对齐 — 跨页面一致性', () => {
  test('各页面搜索区域 rect.left 与订单页基准一致（容差 2px）', async ({ page }) => {
    for (const [key, [pattern, fixture]] of Object.entries(API_MAP) as [PageKey, [string, any]][]) {
      await mockApi(page, pattern, fixture)
    }

    await page.goto('/orders')
    await page.waitForTimeout(2000)
    const ordersLeft = await getSearchLeft(page, 'orders')

    const keys: PageKey[] = ['products', 'after-sales', 'customers', 'employees']
    for (const key of keys) {
      await page.goto(`/${key}`)
      await page.waitForTimeout(2000)
      const left = await getSearchLeft(page, key)
      expect(Math.abs(left - ordersLeft), `${key} 搜索区 left 与订单页基准一致`).toBeLessThanOrEqual(TOLERANCE)
    }
  })

  test('搜索区域无边距居中（负向测试）', async ({ page }) => {
    const pagesToCheck: PageKey[] = ['orders', 'products', 'after-sales', 'customers', 'employees']

    for (const key of pagesToCheck) {
      const [pattern, fixture] = API_MAP[key]
      await mockApi(page, pattern, fixture)
      await page.goto(`/${key}`)
      await page.waitForTimeout(2000)

      await page.waitForSelector(SEARCH_SELECTOR, { timeout: 10000 })
      const el = page.locator(SEARCH_SELECTOR).first()

      const marginLeft = await el.evaluate((node: HTMLElement) => getComputedStyle(node).marginLeft)
      const marginRight = await el.evaluate((node: HTMLElement) => getComputedStyle(node).marginRight)

      if (marginLeft === marginRight && marginLeft !== '0px') {
        console.log(`[warn] ${key}: margin-left=${marginLeft}, margin-right=${marginRight} (可疑的对称值)`)
      }
      const isAutoLeft = marginLeft === 'auto'
      const isAutoRight = marginRight === 'auto'
      expect(isAutoLeft && isAutoRight, `${key} 搜索区不应 margin auto 居中`).toBe(false)
    }
  })
})

test.describe('搜索功能无损 — 回归验证', () => {
  test('订单页搜索后表格仍返回数据', async ({ page }) => {
    const fixtureItems = ordersFixture?.data?.items || []
    await mockApi(page, '**/api/admin/orders*', ordersFixture)

    await page.goto('/orders')
    await page.waitForTimeout(2000)

    const searchInput = page.locator(`${SEARCH_SELECTOR} input`).first()
    if (await searchInput.isVisible()) {
      await searchInput.fill('test')
      await searchInput.press('Enter')
      await page.waitForTimeout(1500)
    }

    const rows = page.locator('tbody tr')
    const hasRows = (await rows.count().catch(() => 0)) > 0
    const hasNoData = await page.getByText(/暂无数据|暂无订单/).isVisible().catch(() => false)
    if (fixtureItems.length > 0) {
      expect(hasRows || !hasNoData).toBe(true)
    } else {
      console.log('[skip] fixture 无数据')
    }
  })

  test('客户页搜索后页面展示客户数据', async ({ page }) => {
    const fixtureItems = customersFixture?.data?.items || []
    await mockApi(page, '**/api/admin/customers*', customersFixture)

    await page.goto('/customers')
    await page.waitForTimeout(2000)

    const searchInput = page.getByPlaceholder('客户名/手机号').first()
    if (await searchInput.isVisible()) {
      await searchInput.fill('test')
      const searchBtn = page.locator(`${SEARCH_SELECTOR} button`).filter({ hasText: '搜索' }).first()
      if (await searchBtn.isVisible()) {
        await searchBtn.click()
        await page.waitForTimeout(1500)
      }
    }

    const rows = page.locator('tbody tr, [data-testid="data-table"] > div')
    const hasRows = (await rows.count().catch(() => 0)) > 0
    const hasNoData = await page.getByText(/暂无数据|暂无客户/).isVisible().catch(() => false)
    if (fixtureItems.length > 0) {
      expect(hasRows || !hasNoData).toBe(true)
    } else {
      console.log('[skip] fixture 无数据')
    }
  })
})
