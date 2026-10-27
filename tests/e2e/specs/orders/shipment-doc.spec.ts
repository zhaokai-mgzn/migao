// case_ids: UI-040
/**
 * 发货面真实浏览器走查（issue #3768 → **issue #7902 发货单退场**）
 *
 * 这层要回答的是 vitest 答不了的问题（migao-dev-flow §15.3）：`@media print` 是否真的
 * 只把**选中的那份纸**印出来、屏幕上是否真的不重复显示、纸面内容是否完整。
 *
 * 🔴 issue #7902（用户 2026-10-27「移除发货单打印」「统一到销售单上打印」）：发货单这张纸与
 * 它的入口整体退场 ⇒ 本文件判两件事：① 发货页**零打印入口**；② 订单详情页的打印层里
 * **没有**发货单、销售单能正常上纸。文件名沿用（case_ids UI-040 的判据载体不变）。
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
  test('发货页：发货人预填，且**没有任何打印入口**（发货单已退场，issue #7902）', async ({ page }) => {
    await mockOrderApi(page, baseOrder)

    await page.goto(`/orders/${ORDER_ID}/ship`)

    // 1) 页面上确实有发货人输入，且预填当前登录人（fixtures 的 /api/auth/me 返回 name=管理员）
    const shipperInput = page.getByPlaceholder('请输入实际发货人姓名')
    await expect(shipperInput).toBeVisible()
    await expect(shipperInput).toHaveValue('管理员')

    // 2) 🔴 issue #7902（用户 2026-10-27「移除发货单打印」「统一到销售单上打印」）：
    //    这张纸整体退场 ⇒ 本页既没有打印按钮，也没有任何纸面容器（不是藏起来，是不存在）
    await expect(page.getByRole('button', { name: /打印/ })).toHaveCount(0)
    await expect(page.locator('.shipment-print-area')).toHaveCount(0)
    await expect(page.locator('.print-doc')).toHaveCount(0)

    // 3) 发货动作本身不受影响（反向自证：本页不是空页）
    await expect(page.getByRole('button', { name: /确认发货/ })).toBeVisible()
    // 反向自证：页面确实渲染出了这单的商品明细（不是空页 / 不是阻断页）
    await expect(page.getByText('布艺遮光帘A').first()).toBeVisible()
  })

  test('订单详情：打印层里没有发货单，销售单仍能上纸（真实浏览器打印媒体）', async ({ page }) => {
    await mockOrderApi(page, {
      ...baseOrder,
      status: 'shipped',
      logistics: { logisticsCompany: '顺丰速运', trackingNo: 'SF20260915001', shipperName: '李四' },
    })

    await page.goto(`/orders/${ORDER_ID}`)

    // 先等订单数据落地（订单号进 DOM）——否则入口按钮会在订单加载前后的重渲染里被 detach，
    // 点击可能落在已卸载的节点上（实测 CI：preview 一直不出现）
    await expect(page.getByText('ORD20260915001').first()).toBeVisible()
    // 打开页面级唯一打印入口（issue #7544 / #7902）
    await expect(page.getByTestId('order-print-entry')).toBeVisible()
    await page.getByTestId('order-print-entry').click()
    await expect(page.getByTestId('print-preview')).toBeVisible()
    // 发货单已退场：标签行里没有它，未派单也没有加工单/水洗唛
    await expect(page.getByTestId('print-preview-doc-shipment')).toHaveCount(0)
    await expect(page.getByTestId('print-preview-doc-processing')).toHaveCount(0)

    // 打销售单：三联纸 241×140，打印媒体下只有这一份上纸
    await page.getByTestId('print-preview-print').click()
    await page.emulateMedia({ media: 'print' })
    await page.waitForTimeout(600) // 等 transition-all 结束，避免拍到过渡中间态
    const doc = page.locator('.sales-print-area[data-print-target="sales"]')
    await expect(doc).toBeVisible()
    await expect(page.locator('.print-preview-doc .sales-print-area')).toBeHidden()
    await expect(page.locator('.shipment-print-area')).toHaveCount(0)
    await expect(page.locator('aside')).toBeHidden()
    // 纸面内容完整（随货给客户的那张）：单号 / 收货人 / 明细
    await expect(doc).toContainText('ORD20260915001')
    await expect(doc).toContainText('张三')
    await expect(doc).toContainText('布艺遮光帘A')

    await page.screenshot({ path: '/tmp/ui040-sales-doc-print.png', fullPage: true })
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
