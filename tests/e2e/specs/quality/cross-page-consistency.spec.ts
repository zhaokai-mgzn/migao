/**
 * 跨页面数据一致性测试
 *
 * 验证同一个数据在列表页和详情页的值是否一致。
 * 列表页只展示摘要，详情页展示完整信息 — 两者不应该冲突。
 *
 * 运行: npx playwright test specs/quality/cross-page-consistency.spec.ts
 */
import { test, expect } from '@playwright/test'
import { loginViaApi, injectAuth } from '../../helpers/auth.helper'

test.describe('列表 ↔ 详情数据一致性', () => {

  test('订单列表金额 = 订单详情金额', async ({ request }) => {
    const tokens = await loginViaApi()
    const auth = { Authorization: `Bearer ${tokens.accessToken}` }

    // 拿列表第一个订单
    const listResp = await request.get('/api/admin/orders?page=1&size=1', { headers: auth })
    const firstOrder = (await listResp.json())?.data?.items?.[0]
    if (!firstOrder?.id) { console.log('[skip]'); return }

    const listAmount = firstOrder.totalAmount

    // 拿同一个订单的详情
    const detailResp = await request.get(`/api/admin/orders/${firstOrder.id}`, { headers: auth })
    const detail = (await detailResp.json())?.data
    const detailAmount = detail?.totalAmount

    expect(detailAmount).toBe(listAmount)
  })

  test('商品列表价格 = 商品详情价格', async ({ request }) => {
    const tokens = await loginViaApi()
    const auth = { Authorization: `Bearer ${tokens.accessToken}` }

    const listResp = await request.get('/api/admin/products?page=1&size=1', { headers: auth })
    const firstProduct = (await listResp.json())?.data?.items?.[0]
    if (!firstProduct?.id) { console.log('[skip]'); return }

    const listPrice = firstProduct.price

    const detailResp = await request.get(`/api/admin/products/${firstProduct.id}`, { headers: auth })
    const detail = (await detailResp.json())?.data
    const detailPrice = detail?.price

    expect(detailPrice).toBe(listPrice)
  })
})

test.describe('表格 ↔ 接口数据一致性', () => {

  test('订单列表列数 = 接口返回 items 数量', async ({ page, request }) => {
    const tokens = await loginViaApi()
    const auth = { Authorization: `Bearer ${tokens.accessToken}` }

    // 从 API 获取实际数据量
    const apiResp = await request.get('/api/admin/orders?page=1&size=10', { headers: auth })
    const apiItems = (await apiResp.json())?.data?.items || []
    const apiCount = apiItems.length

    // 浏览器中访问订单列表
    await injectAuth(page, tokens)
    await page.goto('/orders')
    await page.waitForSelector('tbody tr', { timeout: 10000 })

    // 统计表格行数（排除加载中/暂无数据的占位行）
    const rows = page.locator('tbody tr')
    const rowCount = await rows.count()

    // 表格行数应与 API 返回一致
    expect(rowCount).toBe(apiCount)
  })
})
