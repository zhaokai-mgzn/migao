/**
 * 业务裁判测试 — LLM 自动评判页面业务行为
 *
 * 不判 UI 好不好看，只判：页面内容在业务上对不对。
 *
 * 运行：
 *   JUDGE_API_KEY=sk-xxx npx playwright test specs/quality/business-judge.spec.ts
 */

import { test, expect } from '@playwright/test'
import { BusinessJudge, captureEvidence, startApiCapture } from '../../helpers/business-judge'
import ordersFixture from '../../fixtures/orders-list.json'
import productsFixture from '../../fixtures/products-list.json'
import customersFixture from '../../fixtures/customers-list.json'

const JUDGE_API_KEY = process.env.JUDGE_API_KEY || ''
const describeOrSkip = JUDGE_API_KEY ? test.describe : test.describe.skip

async function mockApi(page: any, urlPattern: string, fixture: any) {
  await page.route(urlPattern, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixture) })
  })
}

// ═══════════════════════════════════════════════════════════════

describeOrSkip('LLM 业务裁判', () => {
  let judge: BusinessJudge

  test.beforeAll(() => {
    judge = new BusinessJudge({ apiKey: JUDGE_API_KEY })
  })

  test.beforeEach(async ({ page }) => {
    // Mock auth — 防止 AuthProvider.initialize() 调 /api/auth/me 失败 → 清空认证 → 跳登录
    // 格式必须与 request.ts response interceptor 一致：{success: true, data: ...}
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: { id: '1', username: 'admin', name: '管理员', roles: ['admin'], tenantId: 1, tenantName: '测试企业' },
        }),
      })
    })
  })

  test('商品列表 — 数据业务合理', async ({ page }) => {
    const apiCalls = startApiCapture(page)
    await mockApi(page, '**/api/admin/products*', productsFixture)

    await page.goto('/products')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000) // 等渲染完成

    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员查看商品列表，应看到商品的名称、价格、状态等核心信息',
      criteria: [
        '页面中有商品名称（不是空值或纯占位符）',
        '价格数值正常（正整数或正小数，非 0 或负）',
        '状态列的值为合法中文（如上架/下架/草稿）',
        '页面没有明显的 JS 错误提示或异常状态',
      ],
      evidence: { ...evidence, apiCalls },
    })

    console.log(`\n📋 ${result.passed ? '✅' : '❌'} 商品列表: ${result.summary}`)
    for (const c of result.criteriaResults) {
      console.log(`   ${c.passed ? '✅' : '❌'} ${c.reason}`)
    }
    expect(result.passed).toBe(true)
  })

  test('订单列表 — 数据业务合理', async ({ page }) => {
    const apiCalls = startApiCapture(page)
    await mockApi(page, '**/api/admin/orders*', ordersFixture)

    await page.goto('/orders')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000)

    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员查看订单列表，应看到订单号、客户名、金额、状态等核心信息',
      criteria: [
        '页面中有订单数据或明确提示"暂无订单"（不能白屏或报错）',
        '如有订单，订单号和金额格式正常（不是纯数字序号或 0）',
        '订单状态为合法中文（如待发货/已发货/已完成/已取消）',
        '页面没有 JS 报错或数据加载失败提示',
      ],
      evidence: { ...evidence, apiCalls },
    })

    console.log(`\n📋 ${result.passed ? '✅' : '❌'} 订单列表: ${result.summary}`)
    for (const c of result.criteriaResults) {
      console.log(`   ${c.passed ? '✅' : '❌'} ${c.reason}`)
    }
    expect(result.passed).toBe(true)
  })

  test('客户列表 — 数据业务合理', async ({ page }) => {
    const apiCalls = startApiCapture(page)
    await mockApi(page, '**/api/admin/customers*', customersFixture)

    await page.goto('/customers')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000)

    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员查看客户列表，应看到客户名称、手机号、标签等核心信息',
      criteria: [
        '页面中有客户数据或明确提示无数据（不能白屏或报错）',
        '如有客户数据，客户名称不是纯数字或占位符',
        '手机号格式应为 11 位数字或脱敏格式（如 138****0001）',
      ],
      evidence: { ...evidence, apiCalls },
    })

    console.log(`\n📋 ${result.passed ? '✅' : '❌'} 客户列表: ${result.summary}`)
    for (const c of result.criteriaResults) {
      console.log(`   ${c.passed ? '✅' : '❌'} ${c.reason}`)
    }
    expect(result.passed).toBe(true)
  })

  test('仪表盘 — 统计数据业务合理', async ({ page }) => {
    const apiCalls = startApiCapture(page)

    await page.goto('/')
    await page.waitForLoadState('networkidle')
    await page.waitForTimeout(2000)

    const evidence = await captureEvidence(page)

    const result = await judge.evaluate({
      scenario: '管理员登录后进入首页/仪表盘，应看到业务概览数据',
      criteria: [
        '页面正常加载，有可见内容（非白屏）',
        '如果有数字统计，数值不是负数或离谱的大数',
        '页面结构包含导航区或仪表盘区域，不是空白或错误页',
        '导航菜单可识别（有中文菜单项）',
      ],
      evidence: { ...evidence, apiCalls },
    })

    console.log(`\n📋 ${result.passed ? '✅' : '❌'} 仪表盘: ${result.summary}`)
    for (const c of result.criteriaResults) {
      console.log(`   ${c.passed ? '✅' : '❌'} ${c.reason}`)
    }
    expect(result.passed).toBe(true)
  })
})
