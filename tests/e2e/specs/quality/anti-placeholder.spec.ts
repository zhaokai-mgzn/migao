/**
 * 反占位符巡检 — 所有数据页面不应全列显示 '-'
 *
 * 如果某列所有行都是 '-'，说明后端未返回该字段或前端未渲染。
 * 本 spec 在每次 E2E 全量跑时自动检测，CI 中失败即阻塞。
 */
import { test } from '@playwright/test'
import { loginViaApi, injectAuth } from '../../helpers/auth.helper'
import { assertNoPlaceholderFallback } from '../../helpers/assertions.helper'

/** 所有需要检查的页面 */
const PAGES = [
  {
    name: '订单列表',
    path: '/orders',
    rowSelector: 'tbody tr',
    columns: { '采购明细': 'td:nth-child(4)' },
  },
  {
    name: '商品列表',
    path: '/products',
    rowSelector: 'tbody tr, [data-testid="product-table"] > div',
    columns: { '商品名称': 'td:nth-child(2), [data-testid^="product-"] span:first-child' },
  },
  {
    name: '客户列表',
    path: '/customers',
    rowSelector: 'tbody tr, [data-testid="data-table"] > div',
    columns: { '客户名称': 'td:nth-child(2), [data-testid^="customer-"] span:first-child' },
  },
  {
    name: '售后列表',
    path: '/after-sales',
    rowSelector: 'tbody tr',
    columns: { '工单信息': 'td:nth-child(2)' },
  },
  {
    name: '员工列表',
    path: '/employees',
    rowSelector: 'tbody tr, [data-testid="data-table"] > div',
    columns: { '员工名称': 'td:nth-child(2)' },
  },
  {
    name: '分类列表',
    path: '/categories',
    rowSelector: 'tbody tr',
    columns: { '分类名称': 'td:nth-child(2)' },
  },
  {
    name: '加工项列表',
    path: '/processing',
    rowSelector: 'tbody tr',
    columns: { '加工项名称': 'td:nth-child(2)' },
  },
  {
    name: '知识库列表',
    path: '/knowledge',
    rowSelector: 'tbody tr',
    columns: { '文档名称': 'td:nth-child(2)' },
  },
]

for (const { name, path, rowSelector, columns } of PAGES) {
  test(`反占位符检查 — ${name}`, async ({ page }) => {
    const tokens = await loginViaApi()
    await injectAuth(page, tokens)
    await page.goto(path)

    // 等待数据加载
    await page.waitForTimeout(3000)
    const hasRows = await page.locator(rowSelector).count()
    if (hasRows === 0) {
      console.log(`[skip] ${name}: 无数据行`)
      return
    }

    await assertNoPlaceholderFallback(page, { rowSelector, columns: columns as Record<string, string>, minRows: 1 })
  })
}
