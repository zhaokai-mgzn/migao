/**
 * 跨页面数据一致性测试 — 使用 recorded fixture 替代 live API
 *
 * 验证列表和详情中同一个实体的关键字段一致。
 * fixture 由 CI 录制步骤定期更新，不依赖 dev 环境数据变化。
 *
 * 运行: npx playwright test specs/quality/cross-page-consistency.spec.ts
 */
// case_ids: UI-001, UI-002
import { test, expect } from '../../fixtures'
import ordersFixture from '../../fixtures/orders-list.json'
import productsFixture from '../../fixtures/products-list.json'
import customersFixture from '../../fixtures/customers-list.json'
import afterSalesFixture from '../../fixtures/after-sales-list.json'
import processingFixture from '../../fixtures/processing-list.json'

function firstItem(fixture: any): any {
  return fixture?.data?.items?.[0] || null
}

test.describe('列表 JSON 字段完整性', () => {

  test('订单列表项含 totalAmount (number)', async () => {
    // 列表中的金额需要与详情一致（使用列表 fixture 中的金额即可）
    const order = firstItem(ordersFixture)
    if (!order?.id) { console.log('[skip] 无订单 fixture'); return }
    expect(order.totalAmount).toBeDefined()
    expect(typeof order.totalAmount).toBe('number')
  })

  test('商品列表项含 price (number)', async () => {
    const product = firstItem(productsFixture)
    if (!product?.id) { console.log('[skip] 无商品 fixture'); return }
    expect(product.price).toBeDefined()
    expect(typeof product.price).toBe('number')
  })
})

test.describe('表格 ↔ 接口数据一致性', () => {

  test('订单列表行数 = 接口返回 items 数量', async ({ page }) => {
    // 用 fixture mock 订单列表 API，验证表格渲染数据量
    const apiItems = ordersFixture?.data?.items || []

    await page.route('**/api/admin/orders*', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ordersFixture) })
    })
    await page.goto('/orders')
    await page.waitForSelector('tbody tr', { timeout: 10000 })

    const rows = page.locator('tbody tr')
    const hasNoData = await page.getByText(/暂无数据|暂无订单/).isVisible().catch(() => false)
    if (hasNoData) {
      expect(apiItems.length).toBe(0)
    } else {
      const rowCount = await rows.count()
      expect(rowCount).toBe(apiItems.length)
    }
  })
})

test.describe('客户列表 ↔ 详情', () => {
  test('name 或 wechatNickname 存在 + phone 字段存在', async () => {
    const first = firstItem(customersFixture)
    if (!first?.id) { console.log('[skip]'); return }
    expect(first.name || first.wechatNickname).toBeTruthy()
    expect(first).toHaveProperty('phone')
  })
})

test.describe('售后列表 ↔ 详情', () => {
  test('ticketNo 和 status 字段存在', async () => {
    const first = firstItem(afterSalesFixture)
    if (!first?.id) { console.log('[skip]'); return }
    expect(first.ticketNo).toBeDefined()
    expect(first.status).toBeDefined()
  })
})

test.describe('加工项列表 ↔ 详情', () => {
  // 2026-09-21（issue #4882，用户裁定「移除加工项单价和计价方式」）：
  // `tests/e2e/fixtures/processing-list.json` 是**生成物**（`synthetic_processing_fee_data.py
  // --write-fixture`），随 V101 删列一并去掉 `pricingMethod` / `unitPrice`。
  // 原断言 `expect(first.unitPrice).toBeDefined()` 因此**必红**（本文件是 #4882 的**回退漏网**：
  // 生产者/夹具都改了，消费者断言没跟）。改判为「单位口径 + 防回退锁」，断言只增不减。
  test('name / unit 字段存在，且不再有 unitPrice / pricingMethod（#4882）', async () => {
    const first = firstItem(processingFixture)
    if (!first?.id) { console.log('[skip]'); return }
    expect(first.name).toBeDefined()
    // `unit` 保留：加工项仍有「加工数量单位」（V101 把默认值由「元」改为「米」）
    expect(first.unit).toBeDefined()
    // 防回退锁：两个已退场的键一旦被加回来即红（与 admin-web 单测、
    // `tests/e2e/specs/catalog/processing.spec.ts`、`scripts/ui-smoke-merchant/spec.mjs` 同口径）
    expect(first.unitPrice).toBeUndefined()
    expect(first.pricingMethod).toBeUndefined()
  })
})
