// case_ids: UI-040
/**
 * 发货单（issue #3768 / UI-040）真实浏览器走查
 *
 * 这层要回答的是 vitest 答不了的问题（migao-dev-flow §15.3）：`@media print` 是否真的
 * 只把发货单印出来、屏幕上是否真的不重复显示、纸面内容是否完整。
 * jsdom 不解析媒体查询 ⇒ 只有真实渲染 + emulateMedia({ media: 'print' }) 能验证。
 *
 * fixture 模式（E2E_MOCK_AUTH）：认证与订单接口全部 mock，不依赖后端与真实数据。
 *
 * 🔴 issue #6983：发货提交的 mock 拦的是**原子端点** `POST /api/admin/production/orders/{id}/ship`
 * （改前拦 `PUT /orders/{id}/logistics` 两步老路 —— 那条路不建发货单、非原子、无幂等键）。
 * 本 spec 的提交用例同时钉 payload（发货人 / 运单号 / 发货方式 / 物流类型）与
 * 请求头 `X-Client-Request-Id`（幂等键）。
 */
import { test, expect } from '../../fixtures'

const ORDER_ID = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'

const baseOrder = {
  id: ORDER_ID,
  orderNo: 'ORD20260915001',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '浙江省杭州市余杭区某某路 1 号',
  totalAmount: 1500,
  actualAmount: 1500,
  status: 'confirmed',
  hasProcessing: false,
  createdAt: '2026-09-15T10:00:00+08:00',
  remark: '客户要求工作日送达',
  items: [
    {
      id: 'item-1',
      productId: 'p-1',
      productName: '布艺遮光帘A',
      // issue #6869：纸面身份走**响应真字段**（`skuCode` + `processingInfo.colorName/doorWidth`）——
      // 夹具按真 wire 形态写（原先的 `productCode` / `color` / `specification` **不在响应里**，
      // 纸面那几列在真单上恒空，而夹具却喂得出绿）
      skuCode: '0012',
      quantity: 12.5,
      unitPrice: 100,
      amount: 1250,
      subtotal: 1250,
      processingInfo: { colorName: '米白', doorWidth: '2.8米' },
    },
  ],
  processingItems: [],
}

/** 订单详情 GET + **原子发货端点** POST 的 mock（按方法分流，避免把发货提交也吃掉） */
async function mockOrderApi(page: any, order: Record<string, unknown>) {
  let current = { ...order }
  const submitted: any[] = []

  /**
   * 🔴 发货提交的**唯一入口** = 原子端点 `POST /api/admin/production/orders/{id}/ship`（issue #6983）。
   *
   * 改前这里拦的是 `PUT /api/admin/orders/{id}/logistics`（两步老路之一）—— 那条路**不建发货单**
   * （`order_shipments` 长期 0 行）、**非原子**，且不带幂等键。发货页收敛到原子端点后，拦旧端点
   * 就再也捕获不到提交（`submitted.length === 0`）；本 mock 随实现一起搬到新端点，
   * 并留下**载荷 + 请求头**两份读数。
   */
  await page.route('**/api/admin/production/orders/**', async (route: any) => {
    const req = route.request()
    if (req.method() === 'POST' && req.url().includes('/ship')) {
      submitted.push({ payload: req.postDataJSON(), headers: req.headers() })
      current = {
        ...current,
        status: 'shipped',
        logistics: { logisticsCompany: '顺丰速运', trackingNo: 'SF20260915001', shipperName: '王五' },
      }
      // 端点信封（服务端 `ProductionController.ship`）：单事务里记物流 + 流转 shipped + 建发货单
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          data: {
            order_id: ORDER_ID,
            status: 'shipped',
            shipment_no: 'SH20260915001',
            shipment_source: 'admin',
          },
        }),
      })
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: null }),
    })
  })

  await page.route('**/api/admin/orders/**', async (route: any) => {
    const req = route.request()
    if (req.method() === 'PUT') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: null }),
      })
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: current }),
    })
  })

  // 列表/统计等旁路接口给空壳，避免 layout 报错干扰
  await page.route('**/api/admin/notifications**', (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { items: [], total: 0, unreadCount: 0 } }),
    })
  )

  return { submitted }
}

test.describe('发货单 — 真实浏览器打印旅程（UI-040）', () => {
  test('发货页：发货人预填 + 打印媒体下只印单据、屏幕不重复显示', async ({ page }) => {
    await mockOrderApi(page, baseOrder)

    await page.goto(`/orders/${ORDER_ID}/ship`)

    // 1) 页面上确实有发货人输入，且预填当前登录人（fixtures 的 /api/auth/me 返回 name=管理员）
    const shipperInput = page.getByPlaceholder('请输入实际发货人姓名')
    await expect(shipperInput).toBeVisible()
    await expect(shipperInput).toHaveValue('管理员')

    // 2) 屏幕上发货单**不可见**（页面已有商品/收货区块，避免重复呈现）
    const doc = page.locator('.shipment-print-area')
    await expect(doc).toBeHidden()

    // 3) 切到打印媒体：单据显形，页面外壳（标题/按钮/侧边栏）不打印
    await page.emulateMedia({ media: 'print' })
    // ⚠️ 必须等过渡结束再取证：侧边栏/浮窗带 `transition-all duration-300`，而 `visibility`
    // 是可过渡属性 —— 切换媒体后 300ms 内 getComputedStyle 仍报 visible（实测），
    // 此时截图会拍到「侧边栏盖住纸面左列」的假象（z-50 绘制在单据之上）。
    await page.waitForTimeout(600)
    await expect(doc).toBeVisible()
    // 页面外壳真的不打印（不是"看起来没打印"）
    await expect(page.locator('aside')).toBeHidden()
    await expect(page.getByPlaceholder('请输入实际发货人姓名')).toBeHidden()
    await expect(page.getByRole('button', { name: /确认发货/ })).toBeHidden()

    // 4) 纸面内容完整（拣货/打包要照着这张纸干活）
    await expect(doc).toContainText('发货单')
    await expect(doc).toContainText('ORD20260915001')
    await expect(doc).toContainText('张三')
    await expect(doc).toContainText('13800138000')
    await expect(doc).toContainText('余杭区某某路 1 号')
    await expect(doc).toContainText('布艺遮光帘A')
    // issue #6869：发货单「规格尺寸」列改印真值「门幅」（原读 `item.specification` —— 不在响应里）
    await expect(doc).toContainText('0012')
    await expect(doc).toContainText('米白')
    await expect(doc).toContainText('2.8米')
    await expect(doc).toContainText('客户要求工作日送达')
    // 经手人 = 当前输入值（发货前打印也要有经手人栏）
    await expect(doc).toContainText('管理员')
    // 发货前没有运单号 → 纸面留空供手写，绝不编造
    await expect(doc).not.toContainText('SF20260915001')

    // 5) 几何证据：单据占据可打印宽度且从页面顶部开始（未被外壳挤压/偏移）
    const rect = await doc.evaluate((el) => {
      const r = el.getBoundingClientRect()
      return { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width) }
    })
    const viewportWidth = page.viewportSize()!.width
    expect(rect.x).toBeLessThanOrEqual(2)
    expect(rect.y).toBeLessThanOrEqual(2)
    expect(rect.width).toBeGreaterThan(viewportWidth * 0.9)

    await page.screenshot({ path: '/tmp/ui040-shipment-doc-print.png', fullPage: true })
  })

  test('订单详情：已发货可补打，纸面带运单号与已落库发货人', async ({ page }) => {
    await mockOrderApi(page, {
      ...baseOrder,
      status: 'shipped',
      logistics: { logisticsCompany: '顺丰速运', trackingNo: 'SF20260915001', shipperName: '李四' },
    })

    await page.goto(`/orders/${ORDER_ID}`)

    // 补打入口（发货页对 shipped 有状态守卫，重打只能从这里）。
    // 🔴 issue #7544：详情页不再有独立的「打印发货单」按钮 —— 页面级唯一「打印」入口里选「发货单」，
    //    先看纸面预览，「打印」才真正置位打印目标（真实 window.print 在无头环境静默返回）。
    await page.getByTestId('order-print-entry').click()
    await expect(page.getByTestId('print-preview')).toBeVisible()
    await page.getByTestId('print-preview-doc-shipment').click()
    await page.getByTestId('print-preview-print').click()

    await page.emulateMedia({ media: 'print' })
    await page.waitForTimeout(600) // 同上：等 transition-all 结束，避免拍到过渡中间态
    // ⚠️ 选择器精确到「**上纸那一份**」（issue #5914）：点「打印发货单」会打开纸面自检层，
    // 层里还有一份**不带 data-print-target 的预览副本**（屏幕态显形、打印态不上纸），
    // 裸 `.shipment-print-area` 会命中 2 个 ⇒ strict mode 红。
    const doc = page.locator('.shipment-print-area[data-print-target="shipment"]')
    await expect(doc).toBeVisible()
    // 预览副本**不上纸**（否则同一份单据会出两张）
    await expect(page.locator('.print-preview-doc .shipment-print-area')).toBeHidden()
    await expect(page.locator('aside')).toBeHidden()
    await expect(doc).toContainText('李四')
    await expect(doc).toContainText('顺丰速运')
    await expect(doc).toContainText('SF20260915001')

    await page.screenshot({ path: '/tmp/ui040-shipment-doc-reprint.png', fullPage: true })
  })

  test('发货提交：走原子端点，发货人/运单号/发货方式随 payload 下发，且带幂等键', async ({ page }) => {
    const { submitted } = await mockOrderApi(page, baseOrder)

    await page.goto(`/orders/${ORDER_ID}/ship`)

    const shipperInput = page.getByPlaceholder('请输入实际发货人姓名')
    await shipperInput.fill('王五')
    await page.getByPlaceholder('请输入快递单号').fill('SF20260915001')
    await page.getByRole('button', { name: /确认发货/ }).click()

    // 🔴 判别力不许丢：**必须真的发生了一次提交**（空跑 ⇒ 红）。
    // 提交被拦到的前提是页面调的是**原子端点**（issue #6983）—— 页面若退回两步老路的
    // `PUT /orders/{id}/logistics`，本 mock 捕不到 ⇒ 这条在 5s 内超时判红。
    await expect
      .poll(() => submitted.length, { message: '应发生一次发货提交（原子端点 POST …/ship）' })
      .toBeGreaterThan(0)

    const { payload, headers } = submitted[0]
    // 改过的值优先（发货人随 payload 下发）
    expect(payload.shipperName).toBe('王五')
    expect(payload.trackingNo).toBe('SF20260915001')
    // 发货方式 / 物流类型（issue #6239 / #6983）：页面上采集的选择必须真的下发，
    // 不许在客户端被静默丢掉（改前原子端点根本没有这两个字段的落点）
    expect(payload.shippingMethod).toBe('logistics')
    expect(payload.logisticsType).toBe('express')
    // 🔴 幂等键（issue #6935 / #6983）：发货提交必须带 —— 服务端同键回放首次结果，
    // 客户端超时重试不会把这一单发两次货（请求头名与服务端 `ClientRequestIdService.HEADER` 逐字一致）
    expect(headers['x-client-request-id']).toBeTruthy()
  })
})
