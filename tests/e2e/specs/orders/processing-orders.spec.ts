// case_ids: PG-005, PG-008, UI-012
import { test, expect } from '../../fixtures'
// auth 由全局 auth-setup 项目提供（fixture 模式 mock /api/auth/me）

// ========== Mock Data ==========
// 状态机语义与后端 ProcessingOrderService.STATUS_TRANSITIONS 对齐：
//   generated → issued → in_processing → completed | cancelled

interface MockPo {
  id: string
  orderId: string
  orderNo: string
  customerName: string
  customerPhone?: string
  processingOrderNo: string
  status: 'generated' | 'issued' | 'in_processing' | 'completed' | 'cancelled'
  processor?: string
  expectedDeliveryDate?: string
  generatedAt: string
  cancelledReason?: string
  items: { productName: string; colorName?: string; quantity: number; unit?: string }[]
}

const MOCK_POS: MockPo[] = [
  {
    id: 'po-001',
    orderId: 'o001',
    orderNo: 'YK20260601001',
    customerName: '张三',
    customerPhone: '13800138001',
    processingOrderNo: 'JG-20260601-0001',
    status: 'generated',
    generatedAt: '2026-06-01T10:30:00Z',
    items: [{ productName: '北欧简约遮光窗帘', colorName: '灰色', quantity: 5, unit: '米' }],
  },
  {
    id: 'po-002',
    orderId: 'o002',
    orderNo: 'YK20260601002',
    customerName: '李四',
    customerPhone: '13900139002',
    processingOrderNo: 'JG-20260602-0002',
    status: 'issued',
    processor: '朝阳加工厂',
    generatedAt: '2026-06-02T09:15:00Z',
    items: [{ productName: '法式蕾丝纱帘', colorName: '白色', quantity: 10, unit: '米' }],
  },
  {
    id: 'po-003',
    orderId: 'o003',
    orderNo: 'YK20260601003',
    customerName: '王五',
    customerPhone: '13700137003',
    processingOrderNo: 'JG-20260603-0003',
    status: 'in_processing',
    processor: '朝阳加工厂',
    generatedAt: '2026-06-03T14:20:00Z',
    items: [
      { productName: '日式棉麻窗帘', colorName: '原木色', quantity: 3, unit: '米' },
      { productName: '酒店工程窗帘', colorName: '米白', quantity: 20, unit: '米' },
    ],
  },
  {
    id: 'po-004',
    orderId: 'o004',
    orderNo: 'YK20260601004',
    customerName: '赵六',
    customerPhone: '13600136004',
    processingOrderNo: 'JG-20260604-0004',
    status: 'completed',
    processor: '城南印染厂',
    generatedAt: '2026-06-04T16:45:00Z',
    items: [{ productName: '儿童房遮光窗帘', colorName: '天蓝', quantity: 8, unit: '米' }],
  },
  {
    id: 'po-005',
    orderId: 'o005',
    orderNo: 'YK20260601005',
    customerName: '孙七',
    customerPhone: '13500135005',
    processingOrderNo: 'JG-20260605-0005',
    status: 'cancelled',
    cancelledReason: '客户取消订单',
    generatedAt: '2026-06-05T11:00:00Z',
    items: [{ productName: '欧式提花窗帘', colorName: '香槟金', quantity: 4, unit: '米' }],
  },
]

/** 与后端 ProcessingOrderService.updateStatus 的 action → 目标状态一致 */
const ACTION_TARGET_STATUS: Record<string, MockPo['status']> = {
  issue: 'issued',
  start: 'in_processing',
  complete: 'completed',
  cancel: 'cancelled',
}

interface PatchCall {
  id: string
  action: string
  processor?: string
  expectedDeliveryDate?: string
  reason?: string
}

async function mockProcessingOrderApis(page: import('@playwright/test').Page) {
  // 可变状态：PATCH 成功后列表 GET 需返回新状态（断言"结果可见"的前提）
  const state: MockPo[] = MOCK_POS.map((p) => ({ ...p, items: p.items.map((i) => ({ ...i })) }))
  const patchBodies: PatchCall[] = []

  // fixture 模式下前端 baseURL 指向 127.0.0.1:8080（跨域）：
  // 非 GET（JSON body）会触发 CORS 预检 OPTIONS —— 不处理则预检失败、PATCH 根本不发出
  // （既有 order-create.spec 的「form submit 未触发 POST」就是同一现象，见其 TODO）。
  const corsHeaders = {
    'Access-Control-Allow-Origin': 'http://localhost:3001',
    'Access-Control-Allow-Credentials': 'true',
    'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  }
  const json = (status: number, data: unknown) =>
    route.fulfill({ status, contentType: 'application/json', headers: corsHeaders, body: JSON.stringify(data) })

  // ⚠️ glob 语义：`*` 不匹配 `/` —— 尾缀必须用 `**`，否则 `.../processing-orders/po-001`
  // 这种带 id 的 PATCH 路径不会被拦截（GET 列表无尾缀所以一直"看起来正常"）。
  await page.route('**/api/admin/processing-orders**', async (route) => {
    const method = route.request().method()
    const url = new URL(route.request().url())
    // 携带 CORS 头的 JSON 响应（route 作用域内定义）
    const json = (status: number, data: unknown) =>
      route.fulfill({ status, contentType: 'application/json', headers: corsHeaders, body: JSON.stringify(data) })

    // CORS 预检
    if (method === 'OPTIONS') {
      await route.fulfill({ status: 204, headers: corsHeaders })
      return
    }

    if (method === 'GET') {
      // 列表：/api/admin/processing-orders（keyword/status）
      const rest = url.pathname.replace('/api/admin/processing-orders', '')
      if (rest) {
        // 加工单详情（issue #4345）：加工单块按 **orderId** 取详情 —— 与后端
        // `resolveProcessingOrder` 的三形态同口径（内部 id / 加工单号 / 订单号）。
        // 旧实现对该子路径一律 404 ⇒ 订单详情页永远看不到加工单块，
        // 「状态流转唯一入口 = 订单详情页」这条旅程在 e2e 里**不可达**。
        const key = decodeURIComponent(rest.replace(/^\//, ''))
        const hit = state.find(
          (p) => p.id === key || p.processingOrderNo === key || p.orderId === key,
        )
        await json(hit ? 200 : 404, { code: hit ? 200 : 404, data: hit ?? null })
        return
      }
      let filtered = [...state]
      const keyword = url.searchParams.get('keyword')
      const status = url.searchParams.get('status')
      // 与后端 selectByKeyword 一致：keyword 精确匹配加工单号/订单号（此时 status 被忽略）
      if (keyword) {
        filtered = filtered.filter((p) => p.processingOrderNo === keyword || p.orderNo === keyword)
      } else if (status) {
        filtered = filtered.filter((p) => p.status === status)
      }
      await json(200, { code: 200, data: filtered })
      return
    }

    if (method === 'PATCH') {
      const id = decodeURIComponent(url.pathname.split('/').pop() ?? '')
      const body = route.request().postDataJSON() as { action: string; processor?: string; expectedDeliveryDate?: string; reason?: string }
      patchBodies.push({ id, ...body })
      const target = state.find((p) => p.id === id)
      if (!target) {
        await json(404, { code: 404, data: null })
        return
      }
      target.status = ACTION_TARGET_STATUS[body.action] ?? target.status
      if (body.action === 'issue') {
        target.processor = body.processor
        target.expectedDeliveryDate = body.expectedDeliveryDate
      }
      if (body.action === 'cancel') target.cancelledReason = body.reason
      await json(200, { code: 200, data: { ...target } })
      return
    }

    // 其它方法（本 spec 不会出现）：交给更早注册的 handler / 网络
    await route.fallback()
  })

  // 生产看板每行的「工序进度 + 计件合计」（issue #4357：加工单唯一入口 = /production，
  // 它逐行调这两个端点）。未 mock ⇒ 落到真实网络（fixture 模式无后端）⇒ 行内进度/计件显示「—」
  // 且请求悬挂拖慢旅程。给确定性响应，让「合并后看板仍渲染真实数据行」可断言。
  await page.route('**/api/admin/production/orders/**', async (route) => {
    const json = (status: number, data: unknown) =>
      route.fulfill({ status, contentType: 'application/json', headers: corsHeaders, body: JSON.stringify(data) })
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith('/operations')) {
      await json(200, { code: 200, data: { positions: [], progress: { total: 11, done: 4, percent: 36 } } })
      return
    }
    if (pathname.endsWith('/piecework')) {
      await json(200, { code: 200, data: { total: 17, per_worker: {}, per_operation: [] } })
      return
    }
    await route.fallback()
  })

  return { patchBodies }
}

/**
 * 订单详情页 mock（issue #4345）：加工单块的**父页面**（唯一入口所在页）。
 * 块本身经 orderId 取加工单详情，由上面的 `mockProcessingOrderApis` 一并覆盖。
 */
async function mockOrderDetailApi(page: import('@playwright/test').Page, orderId: string) {
  const corsHeaders = {
    'Access-Control-Allow-Origin': 'http://localhost:3001',
    'Access-Control-Allow-Credentials': 'true',
    'Access-Control-Allow-Methods': 'GET,POST,PATCH,PUT,DELETE,OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
  }
  await page.route(`**/api/admin/orders/${orderId}`, async (route) => {
    if (route.request().method() !== 'GET') {
      await route.fallback()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers: corsHeaders,
      body: JSON.stringify({
        code: 200,
        data: {
          id: orderId,
          orderNo: 'YK20260601001',
          customerName: '张三',
          customerPhone: '13800138001',
          customerAddress: '浙江省杭州市西湖区文三路1号1幢101室',
          totalAmount: 536.0,
          actualAmount: 536.0,
          status: 'producing',
          hasProcessing: true,
          items: [
            {
              id: 'item_001',
              productId: 'prod_001',
              productName: '北欧简约遮光窗帘',
              color: '灰色',
              specification: '门幅2.8米',
              quantity: 5,
              unitPrice: 23.8,
              amount: 119.0,
            },
          ],
          processingItems: [
            { id: 'pi_001', name: '韩式打褶定型', unitPrice: 25.0, quantity: 2, amount: 50.0 },
          ],
          logistics: null,
          createdAt: '2026-06-01T10:30:00Z',
        },
      }),
    })
  })
}

/** 按加工单号定位表格行（行内断言用，避免跨行歧义） */
function rowBy(page: import('@playwright/test').Page, processingOrderNo: string) {
  return page.locator('tbody tr', { hasText: processingOrderNo })
}

test.describe('生产看板 /production（加工单唯一入口）', () => {
  // 共享 mock 捕获（beforeEach 注册一次，测试内只读）
  let api: { patchBodies: PatchCall[] }

  test.describe.configure({ timeout: 240_000 })

  // 预热 Next dev on-demand 编译：新路由（/production 及跳转目标 /orders/[id]）
  // 在冷启动/机器负载下首访可达数十秒。预热页自带 auth mock，避免未登录跳 /login
  // 导致页面未完整渲染（编译仍触发，但带 mock 更稳）。预热失败不阻断：beforeEach 兜底。
  test.beforeAll(async ({ browser }) => {
    const warm = await browser.newPage()
    await warm.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: { id: '1', username: '13800138000', name: '管理员', roles: ['admin'], tenantId: 1, tenantName: '测试企业' },
        }),
      })
    })
    try {
      await warm.goto('http://localhost:3001/production', { timeout: 120_000 })
      await warm.goto('http://localhost:3001/processing-orders', { timeout: 120_000 })
      await warm.goto('http://localhost:3001/orders/o001', { timeout: 120_000 })
    } catch {
      // best-effort：编译没完成也不阻断，由 beforeEach 的正信号等待兜底
    } finally {
      await warm.close()
    }
  })

  test.beforeEach(async ({ page }) => {
    api = await mockProcessingOrderApis(page)
    // issue #4357：原加工单列表页 /processing-orders 已并入本页并改为重定向 ⇒ 旅程入口 = /production
    await page.goto('/production')
    // 正信号等待（防竞态：'加载中… not visible' 可能在首次渲染前就通过）：
    // 标题出现 = 页面挂载；首行加工单号可见 = 列表数据已渲染。
    // 60s 容忍 Next dev on-demand 编译（冷启动/负载下可达数十秒）
    await expect(page.getByRole('heading', { name: '生产看板' })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('JG-20260601-0001')).toBeVisible({ timeout: 60_000 })
  })

  test('列表渲染：加工单号/订单号/客户/商品摘要/状态徽章齐全', async ({ page }) => {
    // 页面标题 + 面包屑（§15.2「面包屑与侧边栏菜单名一致」）：
    // #4357 前 /production 没有任何面包屑条目 ⇒ 曾回落成「工作台 > 经营看板」。
    // 侧边栏 IA（加工单不再作为独立菜单项）由 vitest 单测断言 —— e2e 的 auth fixture
    // 不带 permissions ⇒ 侧边栏里所有带权限码的项都被过滤掉，此处断言不了菜单项。
    await expect(page.getByRole('heading', { name: '生产看板' })).toBeVisible()
    const breadcrumb = page.getByRole('banner').getByRole('navigation')
    await expect(breadcrumb).toContainText('生产管理')
    await expect(breadcrumb).toContainText('生产看板')

    for (const po of MOCK_POS) {
      await expect(page.getByText(po.processingOrderNo)).toBeVisible()
      await expect(page.getByText(po.orderNo)).toBeVisible()
      await expect(page.getByText(po.customerName)).toBeVisible()
    }
    // 状态徽章（5 种状态文本）—— 必须按行定位：状态下拉的 <option> 同文且 DOM 更靠前（hidden）
    const badgeCases: Array<[string, string]> = [
      ['JG-20260601-0001', '已生成'],
      ['JG-20260602-0002', '已发加工'],
      ['JG-20260603-0003', '加工中'],
      ['JG-20260604-0004', '加工完成'],
      ['JG-20260605-0005', '已取消'],
    ]
    for (const [no, label] of badgeCases) {
      await expect(rowBy(page, no).getByText(label, { exact: true })).toBeVisible()
    }
    // 商品与数量摘要
    await expect(page.getByText(/北欧简约遮光窗帘（灰色）× 5米/)).toBeVisible()
    // 多明细行：po-003 有 2 项 → 显示 2 行商品
    await expect(rowBy(page, 'JG-20260603-0003').getByText('日式棉麻窗帘（原木色）× 3米')).toBeVisible()
    await expect(rowBy(page, 'JG-20260603-0003').getByText('酒店工程窗帘（米白）× 20米')).toBeVisible()
  })

  test('状态筛选：选「已发加工」只显示 issued 行（结果可见）', async ({ page }) => {
    await page.getByLabel('状态筛选').selectOption('issued')
    await page.getByRole('button', { name: '查询' }).click()
    await page.waitForTimeout(300)

    await expect(page.getByText('JG-20260602-0002')).toBeVisible()
    await expect(page.getByText('JG-20260601-0001')).not.toBeVisible()
    await expect(page.getByText('JG-20260603-0003')).not.toBeVisible()

    // 再筛「已生成」→ 只显示 generated 行
    await page.getByLabel('状态筛选').selectOption('generated')
    await page.getByRole('button', { name: '查询' }).click()
    await page.waitForTimeout(300)
    await expect(page.getByText('JG-20260601-0001')).toBeVisible()
    await expect(page.getByText('JG-20260602-0002')).not.toBeVisible()
  })

  test('关键词搜索：按加工单号/订单号精确匹配（结果可见）', async ({ page }) => {
    // 按加工单号
    await page.getByPlaceholder('请输入加工单号或订单号').fill('JG-20260602-0002')
    await page.getByRole('button', { name: '查询' }).click()
    await page.waitForTimeout(300)
    await expect(page.getByText('JG-20260602-0002')).toBeVisible()
    await expect(page.getByText('JG-20260601-0001')).not.toBeVisible()

    // 按订单号
    await page.getByPlaceholder('请输入加工单号或订单号').fill('YK20260601003')
    await page.getByRole('button', { name: '查询' }).click()
    await page.waitForTimeout(300)
    await expect(page.getByText('JG-20260603-0003')).toBeVisible()
    await expect(page.getByText('JG-20260602-0002')).not.toBeVisible()

    // 空结果 → 空态
    await page.getByPlaceholder('请输入加工单号或订单号').fill('不存在的单号')
    await page.getByRole('button', { name: '查询' }).click()
    await page.waitForTimeout(300)
    await expect(page.getByText(/暂无加工单/)).toBeVisible()
  })

  test('重置按钮清空筛选并恢复全量列表', async ({ page }) => {
    // 关键词精确命中 issued 行（keyword 命中时后端忽略 status，等价于单条件筛选）
    await page.getByPlaceholder('请输入加工单号或订单号').fill('JG-20260602-0002')
    await page.getByRole('button', { name: '查询' }).click()
    await page.waitForTimeout(300)
    await expect(page.getByText('JG-20260602-0002')).toBeVisible()
    await expect(page.getByText('JG-20260601-0001')).not.toBeVisible()

    await page.getByRole('button', { name: '重置' }).click()
    await page.waitForTimeout(300)
    await expect(page.getByPlaceholder('请输入加工单号或订单号')).toHaveValue('')
    await expect(page.getByLabel('状态筛选')).toHaveValue('')
    await expect(page.getByText('JG-20260601-0001')).toBeVisible()
  })

  test('唯一入口不再提供状态流转入口（唯一入口 = 订单详情页，issue #4305）', async ({ page }) => {
    // #4305 用户裁定：状态流转入口**收敛到订单详情页加工单块**，加工单侧四个动作按钮全部移除。
    // 本条改判自原「状态机按钮随状态渲染」——五种状态逐一负向断言（含终态），
    // 并断言跳转类入口与引导文案仍在（避免「移除了动作」被误读成「移除了操作区」）。
    // #4357 后本页（/production）承接原列表页，负向断言**一条不放宽**。
    for (const no of [
      'JG-20260601-0001',
      'JG-20260602-0002',
      'JG-20260603-0003',
      'JG-20260604-0004',
      'JG-20260605-0005',
    ]) {
      const row = rowBy(page, no)
      await expect(row.getByRole('button', { name: '查看' })).toBeVisible()
      await expect(row.getByRole('button', { name: '生产明细' })).toBeVisible()
      for (const label of ['发加工', '开始加工', '加工完成', '取消加工单']) {
        await expect(row.getByRole('button', { name: label })).not.toBeVisible()
      }
      await expect(row.getByText('状态流转请在订单详情操作')).toBeVisible()
    }
  })

  test('查看按钮跳转对应订单详情（订单详情已含加工单块）', async ({ page }) => {
    await rowBy(page, 'JG-20260601-0001').getByRole('button', { name: '查看' }).click()
    await page.waitForURL(/\/orders\/o001/, { timeout: 15_000 })
    expect(page.url()).toContain('/orders/o001')
  })

  test('刷新按钮重新拉取列表', async ({ page }) => {
    let listRequests = 0
    await page.route('**/api/admin/processing-orders*', async (route) => {
      if (route.request().method() !== 'GET') {
        await route.fallback()
        return
      }
      const url = new URL(route.request().url())
      const rest = url.pathname.replace('/api/admin/processing-orders', '')
      if (rest) {
        await route.fallback()
        return
      }
      listRequests += 1
      // fallback 交给更早注册的 mock handler（continue 会直连网络，fixture 模式无后端）
      await route.fallback()
    })
    const before = listRequests
    await page.getByRole('button', { name: '刷新' }).click()
    await page.waitForTimeout(500)
    expect(listRequests).toBeGreaterThan(before)
    await expect(page.getByText('JG-20260601-0001')).toBeVisible()
  })

  test('旧入口 /processing-orders 重定向到 /production（旧深链不 404，issue #4357）', async ({ page }) => {
    await page.goto('/processing-orders')
    // 重定向后落到唯一入口：URL 与页面标题都是 /production 的生产看板
    await page.waitForURL(/\/production$/, { timeout: 30_000 })
    await expect(page.getByRole('heading', { name: '生产看板' })).toBeVisible({ timeout: 60_000 })
    await expect(page.getByText('JG-20260601-0001')).toBeVisible({ timeout: 60_000 })
  })
})

// ────────────────────────── 订单详情页加工单块（状态流转唯一入口） ──────────────────────────
//
// issue #4305 用户裁定「从订单作为发加工的唯一入口」⇒ 原列表页弹窗/按钮驱动的四条流转旅程
// **改判到订单详情页的加工单块**（issue #4345：本 spec 是 #4305 的漏改点，main 曾因此 5 failed）。
// 断言只增不减：PATCH body 逐字段、状态徽标、按钮切换三件效果层判据全部保留。
test.describe('订单详情页加工单块（唯一入口）', () => {
  let api: { patchBodies: PatchCall[] }

  test.describe.configure({ timeout: 240_000 })

  test.beforeEach(async ({ page }) => {
    api = await mockProcessingOrderApis(page)
    await mockOrderDetailApi(page, 'o001')
    await page.goto('/orders/o001')
    // 正信号等待：加工单块（唯一入口）与加工单号出现
    const block = page.locator('.po-print-area')
    await expect(block).toBeVisible({ timeout: 60_000 })
    await expect(block.getByText('JG-20260601-0001')).toBeVisible({ timeout: 60_000 })
  })

  test('发加工：内联表单填加工方/交期 → PATCH(issue) → 徽标「已发加工」+ 按钮切换', async ({ page }) => {
    const block = page.locator('.po-print-area')
    await block.getByRole('button', { name: '发加工' }).click()
    await page.locator('input[placeholder*="加工方"]').first().fill('城东印染厂')
    // 交期必须 ≥ 今天（加工单块 date 控件 min=今天，且 handleAction 有同一口径的防御校验）
    const future = new Date(Date.now() + 30 * 24 * 3600 * 1000).toISOString().slice(0, 10)
    await block.locator('input[type="date"]').first().fill(future)
    await block.getByRole('button', { name: '确认发加工' }).click()
    await page.waitForTimeout(500)

    const patch = api.patchBodies.find((b) => b.action === 'issue' && b.id === 'po-001')
    expect(patch).toBeTruthy()
    expect(patch?.processor).toBe('城东印染厂')
    expect(patch?.expectedDeliveryDate).toBe(future)
    // 效果层：状态徽标逐字（块内唯一的 span.bg-primary-50）+ 按钮切换
    // （块的状态时间线**恒含**四个步骤文案 ⇒ 全页文本断言是空判据，不用）
    await expect(block.locator('span.bg-primary-50').first()).toHaveText('已发加工', { timeout: 5_000 })
    await expect(block.getByRole('button', { name: '开始加工' })).toBeVisible()
    await expect(block.getByRole('button', { name: '发加工' })).not.toBeVisible()
  })

  test('开始加工：confirm → PATCH(start) → 徽标「加工中」+「加工完成」按钮出现', async ({ page }) => {
    const block = page.locator('.po-print-area')
    // 先发加工（块上 generated 态只有「发加工/取消加工单」）
    page.on('dialog', async (dialog) => {
      await dialog.accept()
    })
    await block.getByRole('button', { name: '发加工' }).click()
    await block.getByRole('button', { name: '确认发加工' }).click()
    await expect(block.locator('span.bg-primary-50').first()).toHaveText('已发加工', { timeout: 5_000 })

    await block.getByRole('button', { name: '开始加工' }).click()
    await page.waitForTimeout(500)

    const patch = api.patchBodies.find((b) => b.action === 'start' && b.id === 'po-001')
    expect(patch).toBeTruthy()
    await expect(block.locator('span.bg-primary-50').first()).toHaveText('加工中', { timeout: 5_000 })
    await expect(block.getByRole('button', { name: '加工完成' })).toBeVisible()
    await expect(block.getByRole('button', { name: '开始加工' })).not.toBeVisible()
  })

  test('加工完成：confirm → PATCH(complete) → 徽标「加工完成」+ 发货提示', async ({ page }) => {
    const block = page.locator('.po-print-area')
    page.on('dialog', async (dialog) => {
      await dialog.accept()
    })
    // generated → issued → in_processing → completed（状态机主链逐级走，非法迁移会被后端拒绝）
    await block.getByRole('button', { name: '发加工' }).click()
    await block.getByRole('button', { name: '确认发加工' }).click()
    await expect(block.locator('span.bg-primary-50').first()).toHaveText('已发加工', { timeout: 5_000 })
    await block.getByRole('button', { name: '开始加工' }).click()
    await expect(block.locator('span.bg-primary-50').first()).toHaveText('加工中', { timeout: 5_000 })

    await block.getByRole('button', { name: '加工完成' }).click()
    await page.waitForTimeout(500)

    const patch = api.patchBodies.find((b) => b.action === 'complete' && b.id === 'po-001')
    expect(patch).toBeTruthy()
    await expect(block.locator('span.bg-primary-50').first()).toHaveText('加工完成', { timeout: 5_000 })
    await expect(block.getByText('加工已完成，可发货')).toBeVisible()
  })

  test('取消加工单：原因必填 → PATCH(cancel, reason) → 徽标「已取消」+ 原因可见', async ({ page }) => {
    const block = page.locator('.po-print-area')
    await block.getByRole('button', { name: '取消加工单' }).click()
    // 原因为空时确认按钮禁用（后端同样要求取消必填原因）
    const confirmBtn = block.getByRole('button', { name: '确认取消' })
    await expect(confirmBtn).toBeDisabled()
    await block.getByPlaceholder('取消原因（必填，涉及订单状态联动）').fill('客户不要了')
    await expect(confirmBtn).toBeEnabled()
    await confirmBtn.click()
    await page.waitForTimeout(500)

    const patch = api.patchBodies.find((b) => b.action === 'cancel' && b.id === 'po-001')
    expect(patch).toBeTruthy()
    expect(patch?.reason).toBe('客户不要了')
    await expect(block.locator('span.bg-primary-50').first()).toHaveText('已取消', { timeout: 5_000 })
    await expect(block.getByText('取消原因：客户不要了')).toBeVisible()
  })
})
