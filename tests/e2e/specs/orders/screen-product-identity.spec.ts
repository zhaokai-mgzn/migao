// case_ids: OR-006, OR-034
import { test, expect } from '../../fixtures'

/**
 * issue #6882 屏幕面「商品身份」列的**真浏览器**判据（已进 `demo-path-specs.txt` ⇒ CI 每 PR 跑）。
 *
 * 目的：改前发货页「商品货号 / 颜色 / 规格尺寸」三列恒 `-`（读的是响应里没有的键）；
 * 这里用真 wire 形态的夹具，逐格判**看得见的真值**，并留下截图供读图判定。
 */
const SHOT = process.env.MIGAO_SHOT_DIR

const SHIP_ORDER = {
  id: 'order_ship_001',
  orderNo: 'ORD-20250115-0001',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '浙江省杭州市西湖区文三路100号',
  totalAmount: 536.0,
  actualAmount: 536.0,
  status: 'pending_shipment',
  hasProcessing: false,
  items: [
    {
      id: 'item_001',
      productId: 'prod_001',
      productName: '天鹅绒遮光窗帘',
      skuCode: 'SKU-001',
      quantity: 2,
      unitPrice: 168.0,
      amount: 336.0,
      subtotal: 336.0,
      processingInfo: { colorName: '灰色', doorWidth: '2.8米' },
    },
  ],
  processingItems: [],
  paidAt: '2025-01-15T11:00:00Z',
  createdAt: '2025-01-15T10:30:00Z',
}

const DETAIL_ORDER = {
  ...SHIP_ORDER,
  id: 'order_001',
  orderNo: 'ORD-20250101-0001',
  status: 'pending_payment',
}

test.setTimeout(240_000)

test.describe('issue #6882 发货页商品表身份列（真浏览器）', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/admin/orders/order_ship_001', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: SHIP_ORDER }),
      })
    })
    await page.goto('/orders/order_ship_001/ship', { timeout: 180_000 })
    await expect(page.getByRole('heading', { name: '商品发货' })).toBeVisible({ timeout: 120_000 })
  })

  test('三列印真值 + 表头是「门幅」（改前：三列恒 -、表头是「规格尺寸」）', async ({ page }) => {
    const row = page.locator('tr', { hasText: '天鹅绒遮光窗帘' }).first()
    await expect(row.getByText('SKU-001')).toBeVisible()
    await expect(row.getByText('灰色')).toBeVisible()
    await expect(row.getByText('2.8米')).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '门幅' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '规格尺寸' })).toHaveCount(0)
    if (SHOT) await row.screenshot({ path: `${SHOT}/ship-product-row.png` })
    if (SHOT) await page.screenshot({ path: `${SHOT}/ship-page.png`, fullPage: true })
  })
})

test.describe('issue #6882 订单详情商品表「货号」列（真浏览器）', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/admin/orders/order_001', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: DETAIL_ORDER }),
      })
    })
    await page.goto('/orders/order_001', { timeout: 180_000 })
    await expect(page.getByText('商品信息').first()).toBeVisible({ timeout: 120_000 })
  })

  test('屏幕表格「货号」列印 skuCode（改前读 row.sku ⇒ 恒 -）', async ({ page }) => {
    await expect(page.getByText('SKU-001').first()).toBeVisible()
    await expect(page.getByRole('columnheader', { name: '货号' })).toBeVisible()
    if (SHOT) await page.screenshot({ path: `${SHOT}/order-detail-page.png`, fullPage: true })
  })
})
