import { test, expect } from '@playwright/test'
import productsListFixture from '../../fixtures/products-list.json'
import productsDetailFixture from '../../fixtures/products-detail.json'

/**
 * 订单创建 E2E 测试 — mock 数据来自 Record-Replay fixtures（真实 API 响应）。
 * 更新 fixtures: cd tests && BASE_URL=http://localhost:8080 npx tsx e2e/scripts/record-fixtures.ts
 */

const P = productsListFixture.data as any
const PD = productsDetailFixture.data as any
const FIRST = P?.items?.[0]
const PROD_NAME = FIRST?.name || 'cessss'
const PROD_ID = FIRST?.id || 'fdd64b7bfe62bd3005f8c7e0a2c7a686'
const COLORS = PD?.colors || []
const C1 = COLORS[0]?.colorName || '白色'
const C2 = COLORS[1]?.colorName || '米白'
const PCS = PD?.processingItemConfigs || []
const PR1 = PCS[0]?.processingItemName || '铅坠安装'
const PR2 = PCS[1]?.processingItemName || '罗马杆环安装'

test.describe('订单创建', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuthMe(page);
    await page.route('**/api/admin/products*', async (route) => {
      const url = route.request().url()
      if (route.request().method() === 'GET' && !url.includes(`/products/${PROD_ID}`))
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200, data: P }) })
      else await route.fallback()
    })
    await page.route(`**/api/admin/products/${PROD_ID}`, async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200, data: PD }) })
    })
    await page.route(`**/api/admin/products/${PROD_ID}/processing-items*`, async (route) => {
      const items = PCS.map((pc: any) => ({ id: pc.processingItemId, name: pc.processingItemName, unitPrice: pc.customPrice || 0, finalPrice: pc.customPrice || 0, unit: '米', pricingMethod: 'per_meter' }))
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ code: 200, data: items }) })
    })
    await page.goto('/orders/new'); await expect(page.getByRole('heading', { name: '新增订单' })).toBeVisible({ timeout: 10_000 })
  })

  test.describe('页面加载', () => {
    test('标题和三个区块', async ({ page }) => {
      await expect(page.getByRole('heading', { name: '新增订单' })).toBeVisible()
      await expect(page.getByText('商品信息')).toBeVisible()
      await expect(page.getByText('收货信息')).toBeVisible()
      await expect(page.getByText('费用明细')).toBeVisible()
    })
    test('提交和取消按钮', async ({ page }) => {
      await expect(page.getByRole('button', { name: '提交订单' })).toBeVisible()
      await expect(page.getByRole('button', { name: '取消' })).toBeVisible()
    })
  })

  test.describe('收货信息', () => {
    test('姓名/手机/地址可输入', async ({ page }) => {
      await page.locator('input[placeholder="请输入收货人姓名"]').fill('张三')
      await page.locator('input[placeholder="请输入 11 位手机号"]').fill('13800138000')
      await page.locator('input[placeholder="请输入详细收货地址"]').fill('杭州')
      await expect(page.locator('input[placeholder="请输入收货人姓名"]')).toHaveValue('张三')
      await expect(page.locator('input[placeholder="请输入 11 位手机号"]')).toHaveValue('13800138000')
    })
  })

  test.describe('商品搜索弹窗', () => {
    test('弹窗显示 fixture 商品', async ({ page }) => {
      await page.getByText('点击搜索并选择商品').click()
      const modal = page.locator('.fixed.inset-0.z-50').last()
      await expect(modal.getByText(PROD_NAME)).toBeVisible()
    })
    test('选择商品后关闭弹窗', async ({ page }) => {
      await page.getByText('点击搜索并选择商品').click()
      const modal = page.locator('.fixed.inset-0.z-50').last()
      await modal.getByText(PROD_NAME).click()
      await expect(modal).toBeHidden()
      await expect(page.getByText(PROD_NAME).first()).toBeVisible()
    })
  })

  test.describe('行项配置', () => {
    test.beforeEach(async ({ page }) => {
    await mockAuthMe(page);
      await page.getByText('点击搜索并选择商品').click()
      await page.locator('.fixed.inset-0.z-50').last().getByText(PROD_NAME).click()
      // 等待产品卡片替换搜索占位按钮（即商品加载成功）
      await expect(page.getByText('点击搜索并选择商品')).not.toBeVisible({ timeout: 10_000 })
      await page.waitForTimeout(500)
    })
    test('颜色选择', async ({ page }) => {
      await expect(page.getByRole('button', { name: C1 })).toBeVisible({ timeout: 10000 })
      await expect(page.getByRole('button', { name: C2 })).toBeVisible({ timeout: 10000 })
    })
    test('加工选项', async ({ page }) => {
      await expect(page.getByText(PR1)).toBeVisible({ timeout: 10000 })
      await expect(page.getByText(PR2)).toBeVisible({ timeout: 10000 })
    })
  })

  test.describe('校验/取消', () => {
    test('未填收货信息提交报错', async ({ page }) => {
      await page.getByRole('button', { name: '提交订单' }).click()
      await expect(page.getByText('请输入收货人姓名')).toBeVisible()
    })
    test('点击取消返回列表', async ({ page }) => {
      await page.getByRole('button', { name: '取消' }).click()
      await page.waitForURL(/\/orders/)
    })
  })
})
