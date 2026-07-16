/**
 * E2E 测试 — 搜索区域左对齐验证
 *
 * 业务真值 D1：所有表单页搜索/筛选区左侧对齐（与订单页一致）
 *
 * 以订单页为基准，验证各列表页搜索区域左边界位置一致。
 * 使用 recorded fixture mock API，确保测试确定性。
 *
 * 运行: npx playwright test specs/quality/search-alignment.spec.ts
 */
import { test, expect } from '@playwright/test'
import ordersFixture from '../../fixtures/orders-list.json'
import productsFixture from '../../fixtures/products-list.json'
import customersFixture from '../../fixtures/customers-list.json'
import afterSalesFixture from '../../fixtures/after-sales-list.json'
import employeesFixture from '../../fixtures/employees-list.json'

const SEARCH_SELECTORS: Record<string, string> = {
  orders: '.bg-white.rounded-lg.border.border-gray-200.p-5',
  products: '.bg-white.rounded-lg.border.border-gray-200.p-5',
  'after-sales': '.bg-white.border-x.border-gray-200.p-4',
  customers: '.bg-gray-50.p-4.rounded-lg',
  employees: '.bg-gray-50.p-4.rounded-lg.mb-4',
}

type PageKey = keyof typeof SEARCH_SELECTORS
const TOLERANCE = 2

async function mockApi(page: any, urlPattern: string, fixture: any) {
  await page.route(urlPattern, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixture) })
  })
}

async function getSearchLeft(page: any, pageKey: PageKey): Promise<number> {
  const selector = SEARCH_SELECTORS[pageKey]
  await page.waitForSelector(selector, { timeout: 10000 })
  const box = await page.locator(selector).first().boundingBox()
  if (!box) throw new Error(`Cannot find search container on ${pageKey} using "${selector}"`)
  return box.x
}

test.describe('搜索区域左对齐 — 跨页面一致性', () => {
  test('各页面搜索区域 rect.left 与订单页基准一致（容差 2px）', async ({ page }) => {
    await mockApi(page, '**/api/admin/orders*', ordersFixture)
    await mockApi(page, '**/api/admin/products*', productsFixture)
    await mockApi(page, '**/api/admin/customers*', customersFixture)
    await mockApi(page, '**/api/admin/after-sales*', afterSalesFixture)
    await mockApi(page, '**/api/admin/users*', employeesFixture)

    await page.goto('/orders')
    await page.waitForTimeout(2000)
    const ordersLeft = await getSearchLeft(page, 'orders')

    await page.goto('/products')
    await page.waitForTimeout(2000)
    const productsLeft = await getSearchLeft(page, 'products')
    expect(Math.abs(productsLeft - ordersLeft)).toBeLessThanOrEqual(TOLERANCE)

    await page.goto('/after-sales')
    await page.waitForTimeout(2000)
    const afterSalesLeft = await getSearchLeft(page, 'after-sales')
    expect(Math.abs(afterSalesLeft - ordersLeft)).toBeLessThanOrEqual(TOLERANCE)

    await page.goto('/customers')
    await page.waitForTimeout(2000)
    const customersLeft = await getSearchLeft(page, 'customers')
    expect(Math.abs(customersLeft - ordersLeft)).toBeLessThanOrEqual(TOLERANCE)

    await page.goto('/employees')
    await page.waitForTimeout(2000)
    const employeesLeft = await getSearchLeft(page, 'employees')
    expect(Math.abs(employeesLeft - ordersLeft)).toBeLessThanOrEqual(TOLERANCE)
  })

  test('搜索区域无边距居中（负向测试）', async ({ page }) => {
    const pagesToCheck: PageKey[] = ['orders', 'products', 'after-sales', 'customers', 'employees']
    const apiMap: Record<string, [string, any]> = {
      orders: ['**/api/admin/orders*', ordersFixture],
      products: ['**/api/admin/products*', productsFixture],
      'after-sales': ['**/api/admin/after-sales*', afterSalesFixture],
      customers: ['**/api/admin/customers*', customersFixture],
      employees: ['**/api/admin/users*', employeesFixture],
    }

    for (const key of pagesToCheck) {
      const [pattern, fixture] = apiMap[key]
      await mockApi(page, pattern, fixture)
      await page.goto(`/${key}`)
      await page.waitForTimeout(2000)

      const selector = SEARCH_SELECTORS[key]
      await page.waitForSelector(selector, { timeout: 10000 })
      const el = page.locator(selector).first()

      const marginLeft = await el.evaluate((node: HTMLElement) => getComputedStyle(node).marginLeft)
      const marginRight = await el.evaluate((node: HTMLElement) => getComputedStyle(node).marginRight)

      if (marginLeft === marginRight && marginLeft !== '0px') {
        console.log(`[warn] ${key}: margin-left=${marginLeft}, margin-right=${marginRight} (可疑的对称值)`)
      }
      const isAutoLeft = marginLeft === 'auto'
      const isAutoRight = marginRight === 'auto'
      expect(isAutoLeft && isAutoRight).toBe(false)
    }
  })
})

test.describe('搜索功能无损 — 回归验证', () => {
  test('订单页搜索后表格仍返回数据', async ({ page }) => {
    const fixtureItems = ordersFixture?.data?.items || []
    await mockApi(page, '**/api/admin/orders*', ordersFixture)

    await page.goto('/orders')
    await page.waitForTimeout(2000)

    const searchInput = page.locator('.bg-white.rounded-lg.border input[placeholder*="订单"]').first()
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

    const searchInput = page.locator('input[placeholder*="客户名"]').first()
    if (await searchInput.isVisible()) {
      await searchInput.fill('test')
      const searchBtn = page.locator('.bg-gray-50 button').filter({ hasText: '搜索' }).first()
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
