// case_ids: OR-008, OR-009, OR-010
import { test, expect } from '../../fixtures'
import productsListFixture from '../../fixtures/products-list.json'
import productsDetailFixture from '../../fixtures/products-detail.json'

/**
 * 订单创建 E2E 测试 — mock 数据来自 Record-Replay fixtures（真实 API 响应）。
 * 更新 fixtures: cd tests && BASE_URL=http://localhost:8080 npx tsx e2e/scripts/record-fixtures.ts
 *
 * issue #673: createOrder payload 加入 actualAmount — 验证前端正确传递实收款字段
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
    // Mock /api/auth/me — AuthProvider.initialize() 验证 token
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ code: 200, data: { id: '1', username: 'admin', name: '管理员', roles: ['admin'], tenantId: 1, tenantName: '测试企业' } }) })
    })
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
      await expect(modal.getByText(PROD_NAME).first()).toBeVisible()
    })
    test('选择商品后关闭弹窗', async ({ page }) => {
      await page.getByText('点击搜索并选择商品').click()
      const modal = page.locator('.fixed.inset-0.z-50').last()
      await modal.getByText(PROD_NAME).first().click()
      await expect(modal).toBeHidden()
      await expect(page.getByText(PROD_NAME).first()).toBeVisible()
    })
  })

  test.describe('行项配置', () => {
    test.beforeEach(async ({ page }) => {
      await page.getByText('点击搜索并选择商品').click()
      await page.locator('.fixed.inset-0.z-50').last().getByText(PROD_NAME).first().click()
      // 等待产品数据加载和颜色/加工选项渲染
      await page.waitForTimeout(1500)
    })
    // TODO: fixture 商品缺 colors 字段（products-list.json 无 colors/sellingMethods），
    // 且当前商品选择弹窗未渲染颜色区。补 fixture 数据 + 对齐弹窗 UI 后可放开。
    test.skip('颜色选择', async ({ page }) => {
      await expect(page.getByRole('button', { name: C1 })).toBeVisible({ timeout: 10000 })
      await expect(page.getByRole('button', { name: C2 })).toBeVisible({ timeout: 10000 })
    })
    // TODO: fixture 商品缺 processingItems 数据（同上），放开前需补录 fixture 并确认弹窗渲染。
    test.skip('加工选项', async ({ page }) => {
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

  test.describe('实收款 (issue #673)', () => {
    // TODO: CI mock 环境下 form submit 未触发 POST，暂时 skip。
    // 本地 dev 服务器可正常验证，后续排查 CI mock 链路后放开。
    test.skip('createOrder payload 包含 actualAmount', async ({ page }) => {
      // 填写收货信息
      await page.locator('input[placeholder="请输入收货人姓名"]').fill('测试客户')
      await page.locator('input[placeholder="请输入 11 位手机号"]').fill('13900139000')
      await page.locator('input[placeholder="请输入详细收货地址"]').fill('杭州市西湖区')

      // 选择商品
      await page.getByText('点击搜索并选择商品').click()
      const modal = page.locator('.fixed.inset-0.z-50').last()
      await expect(modal).toBeVisible({ timeout: 5000 })
      await modal.getByText(PROD_NAME).first().click()
      await page.waitForTimeout(500)

      // 设置实收款为 100
      await expect(page.getByLabel('实收款 (¥)')).toBeVisible({ timeout: 5000 })
      await page.getByLabel('实收款 (¥)').fill('100')

      // 提交同时拦截 createOrder 请求，验证 payload 包含 actualAmount
      const [request] = await Promise.all([
        page.waitForRequest(req =>
          req.url().includes('/api/admin/orders') && req.method() === 'POST',
          { timeout: 10000 },
        ),
        page.getByRole('button', { name: '提交订单' }).click(),
      ])
      const payload = JSON.parse(request.postData() || '{}')
      expect(payload.actualAmount).toBe(100)
    })
  })

  /**
   * 下单页重构的真浏览器走查（issue #4874 / #4875；migao-dev-flow §15.2「真实浏览器旅程验证」）。
   *
   * 为什么必须有这一层：§15 的三条纪律里，**页面结构/信息层次**类判据在 vitest/jsdom 里只能验「组件树
   * 渲染了什么」，验不了「用户在真页面上看到的是这一个」（#3070 的 5 个 UI 问题全是这么漏过去的）。
   * 本组断言只依赖**结构**（标题/档位/控件名与几何），不依赖任何未 mock 的后端端点 ⇒ 在无 Java 后端的
   * E2E 栈里同样稳定。
   */
  test.describe('两步化 + 帘体档位 + 用料公式 + 收货物流控件（issue #4874/#4875）', () => {
    test.beforeEach(async ({ page }) => {
      await page.getByText('点击搜索并选择商品').click()
      await page.locator('.fixed.inset-0.z-50').last().getByText(PROD_NAME).first().click()
      await expect(page.getByTestId('wizard-step-1')).toBeVisible({ timeout: 10_000 })
    })

    test('订单项录入只有两个步骤区块（原四段手风琴已合并）', async ({ page }) => {
      await expect(page.getByTestId('wizard-step-1')).toBeVisible()
      await expect(page.getByTestId('wizard-step-2')).toBeVisible()
      // 反向断言：原 ③④ 两个步骤号**不得**再出现（合并 = 真的合并，不是并存）
      await expect(page.getByTestId('wizard-step-3')).toHaveCount(0)
      await expect(page.getByTestId('wizard-step-4')).toHaveCount(0)
      await expect(page.getByTestId('wizard-step-1')).toContainText('尺寸与数量 · 工艺规格')
      await expect(page.getByTestId('wizard-step-2')).toContainText('加工项 · 特殊选项')
    })

    test('帘体只剩「布帘 / 纱帘」两档（「布帘+纱帘」已移除）', async ({ page }) => {
      const body = page.getByRole('radiogroup', { name: '帘体' })
      await expect(body.getByRole('radio', { name: '布帘', exact: true })).toBeVisible()
      await expect(body.getByRole('radio', { name: '纱帘', exact: true })).toBeVisible()
      await expect(page.getByRole('radio', { name: '布帘+纱帘' })).toHaveCount(0)
    })

    test('工艺规格：用料公式在、褶距已移除（步骤 1 默认展开）', async ({ page }) => {
      await expect(page.getByRole('radio', { name: '韩折公式（折数法）' })).toBeVisible()
      await expect(page.getByRole('radio', { name: '褶倍数公式（倍数法）' })).toBeVisible()
      // 反向断言：褶距控件与文案都不得再出现（#4874 第 7 条）
      await expect(page.getByLabel('褶距')).toHaveCount(0)
      await expect(page.getByText('褶距', { exact: true })).toHaveCount(0)
    })

    test('收货信息含「常用物流/快递」与「常用物流公司」两个控件', async ({ page }) => {
      await expect(page.getByLabel('常用物流/快递')).toBeVisible()
      await expect(page.getByLabel('常用物流公司')).toBeVisible()
      // 「未指定」是真值：客户档案没录时不编造「快递」（#4419 口径）
      await expect(page.getByTestId('order-logistics-type')).toHaveValue('')
    })

    test('布局遮挡探针：米宝 FAB 与「提交订单」无重叠（§15.3）', async ({ page }) => {
      // 场景 B：内容不足一屏 —— 展开两个步骤后仍不得让 FAB 压住主操作
      await page.getByTestId('wizard-step-2').getByRole('button').first().click()
      await expect(page.getByRole('button', { name: '提交订单' })).toBeVisible()

      const overlap = await page.evaluate(() => {
        const pick = (sel: string) => document.querySelector(sel)?.getBoundingClientRect() ?? null
        const fab = pick('button[title="打开米宝"]')
        const submit = [...document.querySelectorAll('button')].find(
          (b) => (b.textContent || '').trim() === '提交订单',
        )
        const box = submit?.getBoundingClientRect() ?? null
        if (!fab || !box) return null
        const x = Math.max(0, Math.min(fab.right, box.right) - Math.max(fab.left, box.left))
        const y = Math.max(0, Math.min(fab.bottom, box.bottom) - Math.max(fab.top, box.top))
        return { x, y }
      })
      // 无 FAB（如该构建未挂载）⇒ `null`：**不假装通过**，显式跳过并留下痕迹
      test.skip(overlap === null, '本页未挂载米宝 FAB（title="打开米宝" 找不到）⇒ 无遮挡面可判')
      expect(overlap).not.toBeNull()
      expect(overlap!.x === 0 || overlap!.y === 0).toBe(true)
    })
  })
})
