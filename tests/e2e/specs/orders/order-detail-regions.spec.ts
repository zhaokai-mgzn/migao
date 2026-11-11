// case_ids: UI-149, UI-151, UI-152
/**
 * 订单详情三区与操作层级（issue #8838）—— 真实浏览器判据。
 *
 * 用户 2026-11-07 口径：订单详情页按「商品信息 / 作业单 / 可操作」三区展示；整体操作
 *（打印 / 退款 / 发货 / 确认收货…）在页面顶部，局部操作贴对应信息
 *（编辑物流 → 收货信息）。
 * 用户 2026-11-09 追加口径：加急/到货日从基础信息上收页面顶部，与「订单操作」同一区域卡。
 *
 * 这层要回答的是单测答不了的两件事：
 * ① **真实渲染位置** —— 区域在 DOM 里谁先谁后、是否真的上下分区（jsdom 不做布局，y 坐标只能真浏览器取）；
 * ② **读写面数据是真的** —— 页面完整加载（订单 / 发货读面 / 工序 / 作业单）后，三个区域同时在场，
 *    而不是「加载中 / 空态」被当成三区齐备。
 *
 * fixture 模式（`E2E_MOCK_AUTH`）：认证与订单接口全部 mock，不依赖后端与真实数据。
 * 截图入口：`MIGAO_SHOT_DIR=/tmp/xxx MIGAO_SHOT_LABEL=before npx playwright test ...`
 * （截图在断言**之前**落盘 ⇒ 同一脚本跑改前基线时也能留下 Before 证据）。
 */
import { test, expect } from '../../fixtures'

const ORDER_ID = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'

const MOCK_ORDER = {
  id: ORDER_ID,
  orderNo: 'MG20261107001',
  status: 'shipped',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '浙江省杭州市余杭区某某路 1 号 3 幢 502',
  installCommunity: '春江花园',
  logisticsType: 'express',
  logisticsCompany: '顺丰速运',
  logistics: {
    logisticsCompany: '顺丰速运',
    trackingNo: 'SF1234567890',
    shippingMethod: 'logistics',
    shipperName: '李四',
  },
  totalAmount: 6120,
  discountAmount: 120,
  actualAmount: 6000,
  refundAmount: 0,
  createdAt: '2026-11-05T10:00:00+08:00',
  paidAt: '2026-11-05T10:30:00+08:00',
  shippedAt: '2026-11-06T09:00:00+08:00',
  work_order_kind: 'processing',
  isUrgent: true,
  requiredDeliveryDate: '2026-11-20',
  remark: '客户要求工作日送达，送货前电话联系。',
  items: [
    {
      id: 'item-1',
      productId: 'p-1',
      productName: '全遮光雪尼尔',
      skuCode: 'SKU-001',
      unitPrice: 168,
      quantity: 20,
      amount: 3360,
      subtotal: 3360,
      processingFee: 600,
      installRoom: '主卧',
      processingInfo: {
        colorName: '米白',
        sellingMethod: 'bulk_cut',
        doorWidth: '2.8米',
        remark: '按窗宽 × 2 倍褶皱',
        processingFeeDetail: {
          composition: '韩褶 + 定型',
          unit_price: 12,
          meters: 50,
          fee_source: 'matched',
          amount: 600,
        },
      },
    },
    {
      id: 'item-2',
      productId: 'p-2',
      productName: '亚麻拼接窗帘',
      skuCode: 'SKU-002',
      unitPrice: 216,
      quantity: 10,
      amount: 2160,
      subtotal: 2160,
      processingInfo: { colorName: '亚麻色', sellingMethod: 'bulk_cut', doorWidth: '2.5米' },
    },
  ],
  processingItems: [],
}

const MOCK_PROCESSING_ORDER = {
  id: 'po-1',
  orderId: ORDER_ID,
  orderNo: MOCK_ORDER.orderNo,
  customerName: MOCK_ORDER.customerName,
  processingOrderNo: 'JG20261106001',
  status: 'in_processing',
  order_kind: 'processing',
  items: [
    {
      productName: '全遮光雪尼尔',
      colorName: '米白',
      sellingMethod: '散剪',
      width: 2.8,
      height: 2.6,
      quantity: 20,
      unit: '米',
      processingItems: [{ id: 'p1', name: '韩褶', quantity: 20, unit: '米', options: ['四爪钩'] }],
    },
  ],
}

/** 详情页所需的全部旁路接口（fixture 模式无后端） */
async function mockOrderDetailApi(page: any) {
  // 兜底：未 mock 的旁路请求（通知未读数 / 企业配置…）给空成功 —— 否则 axios 拦截器会把
  // 「网络连接失败」toast 打进版式证据。**先注册**，后面更具体的路由会覆盖它（Playwright 后注册优先）。
  await page.route('**/api/**', async (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: null }),
    }),
  )

  // 页面级权限：真实 /me 下发 permissions=['*']（fixture 默认只给 admin 角色、不给权限码，
  // 侧边栏会只剩「通知中心」）——截图要的是**真实登录态下的版式**，故按真响应形状补权限。
  // ⚠️ 身份对象用**扁平**形态（与 `tests/e2e/fixtures.ts` 一致）：store 兼容 `{user:{...},…}` 包装，
  // 但 `test_mibao_chat_gate.py` 判据 ⑧ 的宿主对象解析只认「最近的 `{`」—— 再嵌一层 `user` 会让
  // 它把 `roles` 归到 user 对象、误判能力位缺失。扁平既保真又不触发该误判。
  await page.route('**/api/auth/me', async (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: {
          id: '1',
          username: '13800138000',
          name: '管理员',
          roles: ['admin'],
          permissions: ['*'],
          menus: [],
          capabilities: { mibaoChat: true, aiService: true },
          tenantId: 1,
          tenantName: '测试企业',
        },
      }),
    }),
  )

  await page.route('**/api/admin/notifications/unread-count', async (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { count: 0 } }),
    }),
  )

  await page.route('**/api/admin/orders/**', async (route: any) => {
    const url = route.request().url()
    if (url.endsWith('/shipments')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            order_id: ORDER_ID,
            order_no: MOCK_ORDER.orderNo,
            status: 'shipped',
            shipments: [],
          },
        }),
      })
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: MOCK_ORDER }),
    })
  })

  await page.route('**/api/admin/production/orders/**/operations', async (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { positions: [] } }),
    }),
  )

  await page.route(`**/api/admin/processing-orders/${ORDER_ID}`, async (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: MOCK_PROCESSING_ORDER }),
    }),
  )

  await page.route('**/api/admin/settings/payment-qrcodes**', async (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: {} }),
    }),
  )
}

test.describe('订单详情三区与操作层级（issue #8838 / #8848）', () => {
  test.use({ viewport: { width: 1440, height: 980 } })

  test('三区齐备 + 整体操作在顶部 + 加急/到货日与订单操作同区 + 编辑物流贴收货信息', async ({ page }) => {
    test.setTimeout(360_000)
    await mockOrderDetailApi(page)
    await page.goto(`/orders/${ORDER_ID}`, { waitUntil: 'domcontentloaded', timeout: 300_000 })
    await expect(page.getByRole('heading', { name: '订单详情' })).toBeVisible({ timeout: 120_000 })
    // 页面数据真的加载出来（订单 / 作业单；不是加载中 / 空态）。
    // ⚠️ 单号在屏幕区与隐藏的打印纸面上各有一份 ⇒ `.first()`；且这里**不能用三区锚点**
    //（改前基线没有它们）——截图要能在基线上先落盘，断言放在截图之后。
    await expect(page.getByText(MOCK_PROCESSING_ORDER.processingOrderNo).first()).toBeVisible()
    await expect(page.getByText(MOCK_ORDER.orderNo).first()).toBeVisible()

    // 等页面稳定（告警 toast 不进入版式证据）
    await page.waitForTimeout(1_500)

    // 截图落在**区域断言之前**：同一脚本跑改前基线时也能留下 Before 证据
    // （基线没有三区锚点，若先断言会直接失败、图就没了）。截图前先滚到顶。
    const shotDir = process.env.MIGAO_SHOT_DIR
    if (shotDir) {
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.screenshot({
        path: `${shotDir}/${process.env.MIGAO_SHOT_LABEL || 'order-detail'}.png`,
        fullPage: true,
      })
    }

    // 三个区域都要真正加载出来
    await expect(page.getByTestId('order-goods-region')).toBeVisible()
    await expect(page.getByTestId('order-work-order-region')).toBeVisible()
    await expect(page.getByTestId('order-operation-region')).toBeVisible()

    const operation = page.getByTestId('order-operation-region')
    const goods = page.getByTestId('order-goods-region')
    const workOrder = page.getByTestId('order-work-order-region')

    // ① 整体操作集中在顶部操作区（打印是页面级唯一入口，仍不跟状态挂钩）
    await expect(operation.getByTestId('order-print-entry')).toBeVisible()
    await expect(operation.getByRole('button', { name: '退款' })).toBeVisible()
    await expect(operation.getByRole('button', { name: /确认收货/ })).toBeVisible()

    // ①b 订单操作分层（issue #8898）：左列状态/进度，右列主操作；退款在次操作组
    const opFlow = operation.getByTestId('order-operation-flow')
    const opPrimary = operation.getByTestId('order-operation-primary')
    const opSecondary = operation.getByTestId('order-operation-secondary')
    await expect(opFlow).toBeVisible()
    await expect(opFlow.getByText('已发货')).toBeVisible()
    await expect(opPrimary.getByRole('button', { name: /确认收货/ })).toBeVisible()
    await expect(opSecondary.getByRole('button', { name: '退款' })).toBeVisible()
    const flowBox = await opFlow.boundingBox()
    const primaryBox = await opPrimary.boundingBox()
    if (!flowBox || !primaryBox) throw new Error('订单操作分层取不到真实几何 ⇒ 判据在扫空气')
    expect(primaryBox.x, '主操作列应在状态/进度列右侧（1440 宽下的分层）').toBeGreaterThan(
      flowBox.x + flowBox.width - 2,
    )

    // ② 商品信息区域 = 基础信息 + 商品明细 + 收货信息，且不夹带整体操作
    await expect(goods.getByTestId('order-basic-info')).toBeVisible()
    await expect(goods.getByTestId('order-product-info')).toBeVisible()
    await expect(goods.getByTestId('order-receiving-info')).toBeVisible()
    await expect(goods.getByRole('columnheader', { name: '商品合计' })).toBeVisible()
    await expect(goods.getByRole('button', { name: '退款' })).toHaveCount(0)
    await expect(goods.getByTestId('order-print-entry')).toHaveCount(0)
    // 加急/到货日已按 2026-11-09 口径上收顶部 ⇒ 商品信息区域（含基础信息）里不该再有它
    await expect(goods.getByTestId('order-urgency-panel')).toHaveCount(0)

    // ②b 费用明细：单块展示（卡头旧「订单实收款」撤掉），商品/加工/优惠/实收同屏
    const feePanel = goods.getByTestId('order-fee-breakdown')
    await expect(feePanel).toBeVisible()
    await expect(feePanel.getByTestId('fee-breakdown-goods')).toHaveText('¥5,520.00')
    await expect(feePanel.getByTestId('fee-breakdown-processing')).toHaveText('¥600.00')
    await expect(feePanel.getByTestId('fee-breakdown-discount')).toHaveText('-¥120.00')
    await expect(feePanel.getByTestId('fee-breakdown-order-total')).toHaveText('¥6,120.00')
    await expect(feePanel.getByTestId('fee-breakdown-actual')).toHaveText('¥6,000.00')
    await expect(page.getByText('订单实收款')).toHaveCount(0)

    // ②c 基础信息时间：年月日 + 时分同一行、不换行（真实几何：一行高度，且 computed white-space=nowrap）
    const payRow = goods.getByTestId('order-basic-info').getByText('支付时间：').locator('..')
    const payTime = payRow.locator('span.whitespace-nowrap')
    await expect(payTime).toBeVisible()
    await expect(payTime).toHaveText(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/)
    const payTimeBox = await payTime.boundingBox()
    if (!payTimeBox) throw new Error('支付时间取不到真实几何 ⇒ 判据在扫空气')
    expect(payTimeBox.height, '时间被折成两行（单行高度应 < 30px）').toBeLessThan(30)
    expect(await payTime.evaluate((el) => getComputedStyle(el).whiteSpace)).toBe('nowrap')

    // ③ 加急/到货日与「订单操作」同区；编辑物流仍贴收货信息
    await expect(
      goods.getByTestId('order-receiving-info').getByRole('button', { name: '编辑物流' }),
    ).toBeVisible()
    await expect(operation.getByTestId('order-urgency-panel')).toBeVisible()
    await expect(operation.getByRole('button', { name: '编辑物流' })).toHaveCount(0)

    // ④ 真实几何：操作区在商品信息区上方、商品信息区在作业单区上方（不是仅 DOM 顺序）
    const opBox = await operation.boundingBox()
    const goodsBox = await goods.boundingBox()
    const workBox = await workOrder.boundingBox()
    if (!opBox || !goodsBox || !workBox) {
      // 取不到几何 ⇒ 判据在扫空气，直接红（不用 `toBeTruthy` 这类弱断言）
      throw new Error('三个区域取不到真实几何 ⇒ 判据在扫空气')
    }
    expect(opBox.y).toBeLessThan(goodsBox.y)
    expect(goodsBox.y).toBeLessThan(workBox.y)

    // ⑤ 版式没有横向溢出（1440 宽视口）
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, `页面横向溢出 ${overflow}px`).toBeLessThanOrEqual(1)
  })
})
