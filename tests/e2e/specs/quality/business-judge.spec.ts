/**
 * 业务裁判测试 — LLM 自动评判页面业务行为
 *
 * 运行：JUDGE_API_KEY=sk-xxx npx playwright test specs/quality/business-judge.spec.ts
 */

import { test, expect } from '@playwright/test'
import { BusinessJudge, captureEvidence, startApiCapture } from '../../helpers/business-judge'
import ordersFixture from '../../fixtures/orders-list.json'
import productsFixture from '../../fixtures/products-list.json'
import customersFixture from '../../fixtures/customers-list.json'
import afterSalesFixture from '../../fixtures/after-sales-list.json'
import categoriesFixture from '../../fixtures/categories-tree.json'

const JUDGE_API_KEY = process.env.JUDGE_API_KEY || ''
const describeOrSkip = JUDGE_API_KEY ? test.describe : test.describe.skip

async function mockApi(page: any, urlPattern: string, fixture: any) {
  await page.route(urlPattern, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixture) })
  })
}

function ok(data: any = {}) {
  return { success: true, data }
}

describeOrSkip('LLM 业务裁判', () => {
  let judge: BusinessJudge

  test.beforeAll(() => {
    judge = new BusinessJudge({ apiKey: JUDGE_API_KEY })
  })

  test.beforeEach(async ({ page }) => {
    // 兜底 mock — 所有 API 返回空数据，防 401 跳登录
    // 具体测试用 mockApi() 覆盖特定端点
    await page.route('**/api/admin/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify(ok({ items: [], total: 0 })) })
    })
    await page.route('**/api/auth/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify(ok({ id: '1', username: 'admin', name: '管理员', roles: ['admin'], tenantId: 1, tenantName: '测试企业' })) })
    })
    await page.route('**/api/dashboard/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify(ok({ todayOrders: 0, todayRevenue: 0 })) })
    })
    await page.route('**/api/settings/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify(ok({ siteName: '测试企业' })) })
    })
  })

  // ═════════════════════════════════════════════════════════════
  // 列表页 — 最核心的业务数据展示
  // ═════════════════════════════════════════════════════════════

  test('商品列表 — 核心信息完整', async ({ page }) => {
    const apiCalls = startApiCapture(page)
    await mockApi(page, '**/api/admin/products*', productsFixture)

    await page.goto('/products')
    await page.waitForTimeout(3000)
    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员查看商品列表',
      criteria: [
        '表格中有商品数据（非空表、非白屏）',
        '商品名称列有实际内容（不是全空或全为 "-"）',
        '状态列有值（如出售中/已下架/草稿等）',
        '页面无 JS 报错或白屏',
      ],
      evidence: { ...evidence, apiCalls },
    })
    const details = result.criteriaResults.map(c => `${c.passed ? '✅' : '❌'} ${c.reason}`).join('\n')
    expect(result.passed, `\n📋 ${result.summary}\n${details}`).toBe(true)
  })

  test('订单列表 — 核心信息完整', async ({ page }) => {
    const apiCalls = startApiCapture(page)
    await mockApi(page, '**/api/admin/orders*', ordersFixture)

    await page.goto('/orders')
    await page.waitForTimeout(3000)
    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员查看订单列表',
      criteria: [
        '有订单数据（非白屏或报错）',
        '有订单时，订单号和金额至少有 1 项可见',
        '金额为正数',
        '状态为合法中文（待付款/待发货/已完成/已关闭等）',
      ],
      evidence: { ...evidence, apiCalls },
    })
    const details = result.criteriaResults.map(c => `${c.passed ? '✅' : '❌'} ${c.reason}`).join('\n')
    expect(result.passed, `\n📋 ${result.summary}\n${details}`).toBe(true)
  })

  test('客户列表 — 核心信息完整', async ({ page }) => {
    const apiCalls = startApiCapture(page)
    await mockApi(page, '**/api/admin/customers*', customersFixture)

    await page.goto('/customers')
    await page.waitForTimeout(3000)
    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员查看客户列表',
      criteria: [
        '页面正常加载（非白屏、非"加载失败"）',
        '有客户数据或明确提示"暂无数据"（不能只有报错）',
        '如有数据，客户名称或手机号至少 1 列有实际内容',
        '页面无 401/500 等异常报错',
      ],
      evidence: { ...evidence, apiCalls },
    })
    const details = result.criteriaResults.map(c => `${c.passed ? '✅' : '❌'} ${c.reason}`).join('\n')
    expect(result.passed, `\n📋 ${result.summary}\n${details}`).toBe(true)
  })

  test('售后列表 — 核心信息完整', async ({ page }) => {
    const apiCalls = startApiCapture(page)
    await mockApi(page, '**/api/admin/after-sales*', afterSalesFixture)

    await page.goto('/after-sales')
    await page.waitForTimeout(3000)
    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员查看售后工单列表',
      criteria: [
        '页面正常加载（非白屏或报错）',
        '有工单时，工单信息可见',
        '状态为合法中文（处理中/已解决/已关闭等）',
      ],
      evidence: { ...evidence, apiCalls },
    })
    const details = result.criteriaResults.map(c => `${c.passed ? '✅' : '❌'} ${c.reason}`).join('\n')
    expect(result.passed, `\n📋 ${result.summary}\n${details}`).toBe(true)
  })

  // ═════════════════════════════════════════════════════════════
  // 表单/创建页
  // ═════════════════════════════════════════════════════════════

  test('新增订单 — 表单结构合理', async ({ page }) => {
    const apiCalls = startApiCapture(page)
    await mockApi(page, '**/api/admin/products*', productsFixture)

    await page.goto('/orders/new')
    await page.waitForTimeout(3000)
    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员进入新增订单页面',
      criteria: [
        '页面正常加载（非白屏、非 404）',
        '应有收货人、手机号、地址等收货信息相关字段',
        '应有商品选择或添加商品区域',
        '页面无 JS 报错',
      ],
      evidence: { ...evidence, apiCalls },
    })
    const details = result.criteriaResults.map(c => `${c.passed ? '✅' : '❌'} ${c.reason}`).join('\n')
    expect(result.passed, `\n📋 ${result.summary}\n${details}`).toBe(true)
  })

  test('新增商品 — 表单结构合理', async ({ page }) => {
    const apiCalls = startApiCapture(page)
    await mockApi(page, '**/api/admin/categories*', categoriesFixture)
    await mockApi(page, '**/api/admin/processing-items*', ok({ items: [], total: 0 }))

    await page.goto('/products/new')
    await page.waitForTimeout(3000)
    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员进入新增商品页面',
      criteria: [
        '页面正常加载（非白屏、非 404、非"运行时错误"）',
        '应有商品名称或标题相关输入框',
        '应有价格相关输入框',
        '页面无 JS 报错或异常提示',
      ],
      evidence: { ...evidence, apiCalls },
    })
    const details = result.criteriaResults.map(c => `${c.passed ? '✅' : '❌'} ${c.reason}`).join('\n')
    expect(result.passed, `\n📋 ${result.summary}\n${details}`).toBe(true)
  })

  // ═════════════════════════════════════════════════════════════
  // 详情页 — 用 page.goto 直接访问（不用 click）
  // ═════════════════════════════════════════════════════════════

  test('商品详情 — 关键字段齐全', async ({ page }) => {
    const apiCalls = startApiCapture(page)
    // Mock detail API (GET /api/admin/products/:id)
    await page.route('**/api/admin/products/*', async (route) => {
      const url = route.request().url()
      if (url.includes('/products/') && !url.includes('export')) {
        await route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify(ok({ id: 'fdd64b7b', name: '遮光窗帘', price: 99, status: 'on_sale', colors: [{ name: '2699-01 白色' }], specifications: { 克重: '200-300g', 材质: '涤纶' } })) })
      } else {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ok({ items: [], total: 0 })) })
      }
    })

    // 直接用产品 ID 访问详情页
    await page.goto('/products/fdd64b7b-detail')
    await page.waitForTimeout(3000)
    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员查看商品详情页',
      criteria: [
        '页面正常加载（非白屏或报错）',
        '应显示商品名称',
        '如果有价格，为正数',
        '页面没有异常报错',
      ],
      evidence: { ...evidence, apiCalls },
    })
    const details = result.criteriaResults.map(c => `${c.passed ? '✅' : '❌'} ${c.reason}`).join('\n')
    expect(result.passed, `\n📋 ${result.summary}\n${details}`).toBe(true)
  })

  test('订单详情 — 关键字段齐全', async ({ page }) => {
    const apiCalls = startApiCapture(page)
    await page.route('**/api/admin/orders/*', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify(ok({ id: 'ord-001', orderNo: 'ORD-20240612001', customerName: '李先生', totalAmount: 23103, status: 'pending', items: [{ productName: '遮光窗帘', quantity: 2, unitPrice: 99 }] })) })
    })

    await page.goto('/orders/ord-001')
    await page.waitForTimeout(3000)
    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员查看订单详情页',
      criteria: [
        '页面正常加载（非白屏或报错）',
        '应显示订单号或收货信息',
        '应有商品明细或金额信息',
      ],
      evidence: { ...evidence, apiCalls },
    })
    const details = result.criteriaResults.map(c => `${c.passed ? '✅' : '❌'} ${c.reason}`).join('\n')
    expect(result.passed, `\n📋 ${result.summary}\n${details}`).toBe(true)
  })

  // ═════════════════════════════════════════════════════════════
  // 配置/设置页
  // ═════════════════════════════════════════════════════════════

  test('分类管理 — 树结构合理', async ({ page }) => {
    const apiCalls = startApiCapture(page)
    await mockApi(page, '**/api/admin/categories*', categoriesFixture)

    await page.goto('/categories')
    await page.waitForTimeout(3000)
    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员查看分类管理页面',
      criteria: [
        '页面正常加载（非白屏或报错）',
        '如有分类数据，至少有一个中文分类名',
        '父子层级关系在页面上可辨识',
      ],
      evidence: { ...evidence, apiCalls },
    })
    const details = result.criteriaResults.map(c => `${c.passed ? '✅' : '❌'} ${c.reason}`).join('\n')
    expect(result.passed, `\n📋 ${result.summary}\n${details}`).toBe(true)
  })

  test('仪表盘 — 页面可访问', async ({ page }) => {
    const apiCalls = startApiCapture(page)
    await mockApi(page, '**/api/admin/dashboard*', ok({ todayOrders: 12, todayRevenue: 35800, totalProducts: 156 }))

    await page.goto('/dashboard')
    await page.waitForTimeout(3000)
    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员进入经营看板/仪表盘',
      criteria: [
        '页面正常加载，有可见内容（非白屏）',
        '不是登录页或 404 页',
        '侧边栏或顶部导航区域可见',
      ],
      evidence: { ...evidence, apiCalls },
    })
    const details = result.criteriaResults.map(c => `${c.passed ? '✅' : '❌'} ${c.reason}`).join('\n')
    expect(result.passed, `\n📋 ${result.summary}\n${details}`).toBe(true)
  })
})
