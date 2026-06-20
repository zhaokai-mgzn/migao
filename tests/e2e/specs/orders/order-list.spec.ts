import { test, expect } from '@playwright/test'
// auth 由全局 auth-setup 项目提供

// ========== Mock Data ==========

const MOCK_ORDERS = [
  {
    id: 'o001',
    orderNo: 'YK20260601001',
    customerName: '张三',
    customerPhone: '13800138001',
    customerAddress: '浙江省杭州市西湖区文三路 100 号',
    totalAmount: 1280.5,
    actualAmount: 1280.5,
    status: 'pending_payment',
    createdAt: '2026-06-01T10:30:00Z',
    items: [
      {
        id: 'i1',
        productId: 'p001',
        productName: '北欧简约遮光窗帘',
        productCode: 'CL-GY-001',
        color: '灰色',
        specification: '门幅2.8米',
        quantity: 5,
        unitPrice: 256.1,
        amount: 1280.5,
        subtotal: 1280.5,
      },
    ],
    processingItems: [],
  },
  {
    id: 'o002',
    orderNo: 'YK20260601002',
    customerName: '李四',
    customerPhone: '13900139002',
    customerAddress: '江苏省南京市玄武区中山路 200 号',
    totalAmount: 3560.0,
    actualAmount: 3560.0,
    status: 'pending_shipment',
    createdAt: '2026-06-01T09:15:00Z',
    items: [
      {
        id: 'i2',
        productId: 'p002',
        productName: '法式蕾丝纱帘',
        productCode: 'CL-WH-002',
        color: '白色',
        specification: '门幅3.0米',
        quantity: 10,
        unitPrice: 356,
        amount: 3560,
        subtotal: 3560,
      },
    ],
    processingItems: [
      {
        id: 'pr1',
        name: '韩式打褶定型',
        unitPrice: 30,
        quantity: 10,
        amount: 300,
      },
    ],
  },
  {
    id: 'o003',
    orderNo: 'YK20260531003',
    customerName: '王五',
    customerPhone: '13700137003',
    customerAddress: '上海市浦东新区陆家嘴金融中心',
    totalAmount: 890.0,
    actualAmount: 890.0,
    status: 'shipped',
    createdAt: '2026-05-31T14:20:00Z',
    items: [
      {
        id: 'i3',
        productId: 'p003',
        productName: '日式棉麻窗帘',
        productCode: 'CL-BG-003',
        color: '原木色',
        specification: '门幅2.5米',
        quantity: 3,
        unitPrice: 296.67,
        amount: 890,
        subtotal: 890,
      },
    ],
    processingItems: [],
  },
  {
    id: 'o004',
    orderNo: 'YK20260530004',
    customerName: '赵六',
    customerPhone: '13600136004',
    customerAddress: '北京市朝阳区建国路 88 号',
    totalAmount: 5600.0,
    actualAmount: 5600.0,
    status: 'completed',
    createdAt: '2026-05-30T16:45:00Z',
    items: [
      {
        id: 'i4',
        productId: 'p005',
        productName: '酒店工程窗帘',
        productCode: 'CL-HT-005',
        color: '米白',
        specification: '门幅3.2米',
        quantity: 20,
        unitPrice: 280,
        amount: 5600,
        subtotal: 5600,
      },
    ],
    processingItems: [],
  },
]

async function mockOrderApis(page: import('@playwright/test').Page) {
  // GET /api/orders (list)
  await page.route('**/api/admin/orders*', async (route) => {
    if (route.request().method() !== 'GET') return
    const url = new URL(route.request().url())

    let filtered = [...MOCK_ORDERS]

    // 状态过滤
    const statusParam = url.searchParams.get('status')
    if (statusParam) {
      filtered = filtered.filter((o) => o.status === statusParam)
    }

    // 加工订单过滤
    const hasProcessing = url.searchParams.get('hasProcessing')
    if (hasProcessing === 'true') {
      filtered = filtered.filter((o) => o.processingItems && o.processingItems.length > 0)
    }

    // 日期过滤
    const startDate = url.searchParams.get('startDate')
    if (startDate) {
      filtered = filtered.filter((o) => o.createdAt >= startDate)
    }
    const endDate = url.searchParams.get('endDate')
    if (endDate) {
      filtered = filtered.filter((o) => o.createdAt <= endDate + 'T23:59:59Z')
    }

    // keyword 模糊搜索
    const keyword = url.searchParams.get('keyword')
    if (keyword) {
      filtered = filtered.filter(
        (o) =>
          o.orderNo.includes(keyword) ||
          o.customerName.includes(keyword) ||
          o.items?.some((item) => item.productCode?.includes(keyword) || item.productName.includes(keyword)),
      )
    }

    const pg = Number(url.searchParams.get('page')) || 1
    const size = Number(url.searchParams.get('size')) || 20
    const start = (pg - 1) * size
    const items = filtered.slice(start, start + size)

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        code: 200,
        data: { items, total: filtered.length, page: pg, size },
      }),
    })
  })

  // PUT /api/orders/*/payment (确认付款)
  await page.route('**/api/admin/orders/*/payment', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 200, data: null }),
    })
  })

  // PUT /api/orders/*/status (更新状态)
  await page.route('**/api/admin/orders/*/status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 200, data: null }),
    })
  })

  // PUT /api/orders/*/cancel (关闭订单)
  await page.route('**/api/admin/orders/*/cancel', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 200, data: null }),
    })
  })

  // POST /api/orders/*/remark (添加备注)
  await page.route('**/api/admin/orders/*/remark', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ code: 200, data: null }),
    })
  })
}

test.describe('订单列表页面', () => {
  test.beforeEach(async ({ page }) => {
    await mockOrderApis(page)
    await page.goto('/orders')
    // 等待表格数据加载完成（"加载中…" 消失）
    await expect(page.getByText('加载中…')).not.toBeVisible({ timeout: 10_000 })
    await page.waitForTimeout(300)
  })

  // ========== 搜索 (1-9) ==========

  test('默认日期范围为最近一个月', async ({ page }) => {
    // 下单时间输入框应有默认值
    const dateInputs = page.locator('input[type="date"]')
    const startDate = await dateInputs.first().inputValue()
    const endDate = await dateInputs.last().inputValue()

    // 开始日期和结束日期应有值
    expect(startDate).toBeTruthy()
    expect(endDate).toBeTruthy()

    // 结束日期应为今天
    const today = new Date()
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
    expect(endDate).toBe(todayStr)
  })

  test('按订单号搜索', async ({ page }) => {
    await page.locator('input[placeholder="请输入订单ID"]').fill('YK20260601001')
    await page.getByRole('button', { name: '查询' }).click()
    await page.waitForTimeout(500)

    await expect(page.getByText('YK20260601001')).toBeVisible()
    await expect(page.getByText('YK20260530004')).not.toBeVisible()
  })

  test('按收货人搜索', async ({ page }) => {
    await page.locator('input[placeholder="请输入收货人姓名或手机号"]').fill('李四')
    await page.getByRole('button', { name: '查询' }).click()
    await page.waitForTimeout(500)

    await expect(page.getByText('YK20260601002')).toBeVisible()
  })

  test('按下单日期搜索 — 应筛选出指定日期的订单', async ({ page }) => {
    const dateInputs = page.locator('input[type="date"]')
    await dateInputs.first().fill('2026-06-01')
    await dateInputs.last().fill('2026-06-01')

    await page.getByRole('button', { name: '查询' }).click()
    await page.waitForTimeout(500)

    // 应只显示 6/1 的订单，不应显示其他日期的
    await expect(page.getByText('YK20260601001')).toBeVisible()
    await expect(page.getByText('YK20260530004')).not.toBeVisible()
  })

  test('按商品编码搜索 — 搜索后应显示匹配的订单', async ({ page }) => {
    await page.locator('input[placeholder="请输入商品货号"]').fill('CL-GY-001')
    await page.getByRole('button', { name: '查询' }).click()
    await page.waitForTimeout(500)

    // 应显示包含该商品编码的订单
    await expect(page.getByText('YK20260601001')).toBeVisible()
    // 确认搜索结果不是空列表
    await expect(page.getByText('暂无数据')).not.toBeVisible()
  })

  test('按商品标题搜索 — 搜索后应显示匹配的订单', async ({ page }) => {
    await page.locator('input[placeholder="请输入商品标题"]').fill('遮光')
    await page.getByRole('button', { name: '查询' }).click()
    await page.waitForTimeout(500)

    // 搜索结果中应出现包含"遮光"的订单
    await expect(page.getByText('YK20260601001')).toBeVisible()
    // 确认搜索结果不是空列表
    await expect(page.getByText('暂无数据')).not.toBeVisible()
  })

  test('按加工订单筛选', async ({ page }) => {
    const select = page.locator('select').last()
    await select.selectOption('true')
    await page.getByRole('button', { name: '查询' }).click()
    await page.waitForTimeout(500)

    // 只有 o002 有加工项
    await expect(page.getByText('YK20260601002')).toBeVisible()
  })

  test('重置按钮恢复默认搜索条件', async ({ page }) => {
    // 填入搜索条件
    await page.locator('input[placeholder="请输入订单ID"]').fill('YK20260601001')
    await page.locator('input[placeholder="请输入收货人姓名或手机号"]').fill('张三')

    // 点击重置
    await page.getByRole('button', { name: /重置/ }).click()
    await page.waitForTimeout(500)

    // 搜索条件应被清空
    await expect(page.locator('input[placeholder="请输入订单ID"]')).toHaveValue('')
    await expect(page.locator('input[placeholder="请输入收货人姓名或手机号"]')).toHaveValue('')
    await expect(page.locator('input[placeholder="请输入商品货号"]')).toHaveValue('')
    await expect(page.locator('input[placeholder="请输入商品标题"]')).toHaveValue('')
  })

  test('回车键触发搜索', async ({ page }) => {
    const orderIdInput = page.locator('input[placeholder="请输入订单ID"]')
    await orderIdInput.fill('YK20260601002')
    await orderIdInput.press('Enter')
    await page.waitForTimeout(500)

    await expect(page.getByText('YK20260601002')).toBeVisible()
  })

  // ========== Tab 切换 (10-14) ==========

  test('默认选中"全部" Tab', async ({ page }) => {
    // "全部" Tab 应为激活状态
    const allTab = page.getByRole('button', { name: '全部' })
    await expect(allTab).toHaveClass(/text-primary-600/)
  })

  test('切换到"待付款" Tab', async ({ page }) => {
    await page.getByRole('button', { name: '待付款' }).click()
    await page.waitForTimeout(500)

    // 应只显示 pending_payment 状态的订单
    await expect(page.getByText('YK20260601001')).toBeVisible()
    await expect(page.getByText('YK20260601002')).not.toBeVisible()
  })

  test('切换到"待发货" Tab', async ({ page }) => {
    await page.getByRole('button', { name: '待发货' }).click()
    await page.waitForTimeout(500)

    await expect(page.getByText('YK20260601002')).toBeVisible()
    await expect(page.getByText('YK20260601001')).not.toBeVisible()
  })

  test('切换到"含加工订单" Tab', async ({ page }) => {
    await page.getByRole('button', { name: '含加工订单' }).click()
    await page.waitForTimeout(500)

    // o002 有加工项
    await expect(page.getByText('YK20260601002')).toBeVisible()
  })

  test('8 个 Tab 全部渲染', async ({ page }) => {
    const tabLabels = ['全部', '待付款', '待发货', '已发货', '已完成', '含加工订单', '已关闭', '退款/售后']
    for (const label of tabLabels) {
      await expect(page.getByRole('button', { name: label })).toBeVisible()
    }
  })

  // ========== 分页 (15) ==========

  test('分页器展示及翻页', async ({ page }) => {
    // Mock 大量订单以触发分页
    await page.route('**/api/admin/orders*', async (route) => {
      if (route.request().method() !== 'GET') return
      const url = new URL(route.request().url())
      const pg = Number(url.searchParams.get('page')) || 1
      const size = Number(url.searchParams.get('size')) || 20
      const allOrders = Array.from({ length: 45 }, (_, i) => ({
        ...MOCK_ORDERS[i % MOCK_ORDERS.length],
        id: `o${String(i + 1).padStart(3, '0')}`,
        orderNo: `YK2026060${String(i + 1).padStart(3, '0')}`,
      }))
      const start = (pg - 1) * size
      const items = allOrders.slice(start, start + size)
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          code: 200,
          data: { items, total: 45, page: pg, size },
        }),
      })
    })

    await page.reload()
    await page.waitForTimeout(500)

    // 应展示总数
    await expect(page.getByText('共 45 条')).toBeVisible()

    // 点击下一页按钮 (›)
    await page.getByRole('button', { name: '›' }).click()
    await page.waitForTimeout(500)

    // 应显示第二页数据
    await expect(page.getByText('YK2026060021')).toBeVisible()
  })

  // ========== 行操作 (16-21) ==========

  test('查看按钮跳转订单详情', async ({ page }) => {
    const viewBtn = page.locator('tbody button').filter({ hasText: '查看' }).first()
    await viewBtn.click()

    await page.waitForURL(/\/orders\/o/, { timeout: 5_000 })
    expect(page.url()).toContain('/orders/o')
  })

  test('确认付款操作', async ({ page }) => {
    // pending_payment 订单有 "确认付款" 按钮
    const confirmBtn = page.locator('tbody button').filter({ hasText: '确认付款' }).first()
    if (await confirmBtn.isVisible()) {
      // window.confirm 需要处理
      page.on('dialog', async (dialog) => {
        await dialog.accept()
      })

      await confirmBtn.click()
      await page.waitForTimeout(500)

      // 应显示成功提示
      await expect(page.getByText('付款已确认')).toBeVisible({ timeout: 5_000 })
    }
  })

  test('发货按钮跳转发货页', async ({ page }) => {
    // 切换到待发货 Tab 以看到发货按钮
    await page.getByRole('button', { name: '待发货' }).click()
    await page.waitForTimeout(500)

    const shipBtn = page.locator('tbody button').filter({ hasText: '发货' }).first()
    if (await shipBtn.isVisible()) {
      await shipBtn.click()

      // 应跳转到 /orders/{id}?action=ship
      await page.waitForURL(/\/orders\/.*action=ship/, { timeout: 5_000 })
      expect(page.url()).toContain('action=ship')
    }
  })

  test('关闭订单操作', async ({ page }) => {
    // pending_payment 订单有 "关闭" 按钮
    const closeBtn = page.locator('tbody button').filter({ hasText: '关闭' }).first()
    if (await closeBtn.isVisible()) {
      await closeBtn.click()

      // 应弹出关闭订单弹窗
      const closeModal = page.locator('.fixed.inset-0')
      await expect(closeModal.getByRole('heading', { name: '关闭订单' })).toBeVisible()
      await expect(closeModal.getByText('确定关闭当前订单吗？')).toBeVisible()

      // 关闭弹窗
      await closeModal.getByRole('button', { name: '取消' }).click()
    }
  })

  test('备注操作', async ({ page }) => {
    const remarkBtn = page.locator('tbody button').filter({ hasText: '备注' }).first()
    if (await remarkBtn.isVisible()) {
      await remarkBtn.click()

      // 应弹出备注弹窗
      const remarkModal = page.locator('.fixed.inset-0')
      await expect(remarkModal.getByRole('heading', { name: '添加备注' })).toBeVisible()
      await expect(remarkModal.locator('textarea[placeholder="请输入备注内容"]')).toBeVisible()

      // 关闭弹窗
      await remarkModal.getByRole('button', { name: '取消' }).click()
    }
  })

  test('确认收货操作', async ({ page }) => {
    // 切换到已发货 Tab 以看到确认收货按钮
    await page.getByRole('button', { name: '已发货' }).click()
    await page.waitForTimeout(500)

    const confirmReceiveBtn = page.locator('tbody button').filter({ hasText: '确认收货' }).first()
    if (await confirmReceiveBtn.isVisible()) {
      page.on('dialog', async (dialog) => {
        await dialog.accept()
      })

      await confirmReceiveBtn.click()
      await page.waitForTimeout(500)

      await expect(page.getByText('订单已完成')).toBeVisible({ timeout: 5_000 })
    }
  })

  // ========== 弹窗 (22-23) ==========

  test('关闭订单弹窗：预设原因及自定义输入', async ({ page }) => {
    const closeBtn = page.locator('tbody button').filter({ hasText: '关闭' }).first()
    if (await closeBtn.isVisible()) {
      await closeBtn.click()

      const modal = page.locator('.fixed.inset-0')

      // 弹窗标题
      await expect(modal.getByRole('heading', { name: '关闭订单' })).toBeVisible()

      // 预设原因
      await expect(modal.getByText('缺货')).toBeVisible()
      await expect(modal.getByText('过期未付款')).toBeVisible()
      await expect(modal.getByText('协商一致')).toBeVisible()
      await expect(modal.getByText('备注其它原因')).toBeVisible()

      // 默认选中 "缺货"
      const radio = modal.locator('input[type="radio"][name="close-reason"]').first()
      await expect(radio).toBeChecked()

      // 选择 "备注其它原因"
      await modal.getByText('备注其它原因').click()
      // 应出现 textarea
      await expect(modal.locator('textarea[placeholder="请输入关闭原因"]')).toBeVisible()

      // 确定按钮应禁用（因为自定义原因为空）
      const confirmBtn = modal.getByRole('button', { name: '确定' })
      await expect(confirmBtn).toBeDisabled()

      // 输入原因后可提交
      await modal.locator('textarea[placeholder="请输入关闭原因"]').fill('客户取消')
      await confirmBtn.click()
      await page.waitForTimeout(500)

      await expect(page.getByText('订单已关闭')).toBeVisible({ timeout: 5_000 })
    }
  })

  test('备注弹窗：输入内容并提交', async ({ page }) => {
    const remarkBtn = page.locator('tbody button').filter({ hasText: '备注' }).first()
    if (await remarkBtn.isVisible()) {
      await remarkBtn.click()

      const modal = page.locator('.fixed.inset-0')

      // 弹窗标题
      await expect(modal.getByRole('heading', { name: '添加备注' })).toBeVisible()

      // textarea
      const textarea = modal.locator('textarea[placeholder="请输入备注内容"]')
      await expect(textarea).toBeVisible()

      // 确认按钮初始禁用（内容为空）
      const confirmBtn = modal.getByRole('button', { name: '确认' })
      await expect(confirmBtn).toBeDisabled()

      // 输入备注
      await textarea.fill('客户备注：请尽快发货')

      // 确认按钮启用
      await expect(confirmBtn).toBeEnabled()

      // 提交
      await confirmBtn.click()
      await page.waitForTimeout(500)

      await expect(page.getByText('备注添加成功')).toBeVisible({ timeout: 5_000 })
    }
  })

  // ========== 新增订单 (24) ==========

  test('新增订单按钮跳转', async ({ page }) => {
    const newBtn = page.getByRole('button', { name: /新增订单/ })
    await expect(newBtn).toBeVisible()
    await newBtn.click()

    await page.waitForURL(/\/orders\/new/, { timeout: 5_000 })
    expect(page.url()).toContain('/orders/new')
  })
})
