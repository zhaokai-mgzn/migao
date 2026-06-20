 * 反占位符巡检 — 所有数据页面不应全列显示 '-'
 *
 * 使用 recorded fixture mock API 路由，不依赖 live dev 数据。
 * fixture 由 CI 录制步骤定期更新。Auth 由 project storageState 提供。
 *
 * 如果某列所有行都是 '-'，说明后端未返回该字段或前端未渲染。
 */
import { test } from '@playwright/test'
import { assertNoPlaceholderFallback } from '../../helpers/assertions.helper'
import ordersFixture from '../../fixtures/orders-list.json'
import productsFixture from '../../fixtures/products-list.json'
import customersFixture from '../../fixtures/customers-list.json'
import afterSalesFixture from '../../fixtures/after-sales-list.json'
import employeesFixture from '../../fixtures/employees-list.json'
import categoriesFixture from '../../fixtures/categories-tree.json'
import processingFixture from '../../fixtures/processing-list.json'
import knowledgeFixture from '../../fixtures/knowledge-list.json'

/** Mock API 路由返回 fixture 数据 */
async function mockWithFixture(page: any, urlPattern: string, fixture: any) {
  await page.route(urlPattern, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixture) })
  })
}

/** 所有需要检查的页面 — fixture 直接从 import 获取 */
const PAGES = [
  { name: '订单列表', path: '/orders', rowSelector: 'tbody tr', columns: { '采购明细': 'td:nth-child(4)' }, fixture: ordersFixture, api: '**/api/admin/orders*' },
  { name: '商品列表', path: '/products', rowSelector: 'tbody tr, [data-testid="product-table"] > div', columns: { '商品名称': 'td:nth-child(2), [data-testid^="product-"] span:first-child' }, fixture: productsFixture, api: '**/api/admin/products*' },
  { name: '客户列表', path: '/customers', rowSelector: 'tbody tr, [data-testid="data-table"] > div', columns: { '客户名称': 'td:nth-child(2), [data-testid^="customer-"] span:first-child' }, fixture: customersFixture, api: '**/api/admin/customers*' },
  { name: '售后列表', path: '/after-sales', rowSelector: 'tbody tr', columns: { '工单信息': 'td:nth-child(2)' }, fixture: afterSalesFixture, api: '**/api/admin/after-sales*' },
  { name: '员工列表', path: '/employees', rowSelector: 'tbody tr, [data-testid="data-table"] > div', columns: { '员工名称': 'td:nth-child(2)' }, fixture: employeesFixture, api: '**/api/admin/users*' },
  { name: '分类列表', path: '/categories', rowSelector: 'tbody tr', columns: { '分类名称': 'td:nth-child(2)' }, fixture: categoriesFixture, api: '**/api/admin/categories*' },
  { name: '加工项列表', path: '/processing', rowSelector: 'tbody tr', columns: { '加工项名称': 'td:nth-child(2)' }, fixture: processingFixture, api: '**/api/admin/processing-items*' },
  { name: '知识库列表', path: '/knowledge', rowSelector: 'tbody tr', columns: { '文档名称': 'td:nth-child(2)' }, fixture: knowledgeFixture, api: '**/api/admin/knowledge/documents*' },
]

for (const { name, path, rowSelector, columns, fixture, api } of PAGES) {
  test(`反占位符检查 — ${name}`, async ({ page }) => {
    await mockWithFixture(page, api, fixture)

    await page.goto(path)
    await page.waitForTimeout(2000) // 等待 mock 数据渲染
    const hasRows = await page.locator(rowSelector).count()
    if (hasRows === 0) {
      console.log(`[skip] ${name}: 无数据行`)
      return
    }

    await assertNoPlaceholderFallback(page, { rowSelector, columns: columns as unknown as Record<string, string>, minRows: 1 })
  })
}
