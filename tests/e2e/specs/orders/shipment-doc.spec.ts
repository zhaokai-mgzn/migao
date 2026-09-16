// case_ids: UI-040
/**
 * 发货单（issue #3768 / UI-040）真实浏览器走查
 *
 * 这层要回答的是 vitest 答不了的问题（migao-dev-flow §15.3）：`@media print` 是否真的
 * 只把发货单印出来、屏幕上是否真的不重复显示、纸面内容是否完整。
 * jsdom 不解析媒体查询 ⇒ 只有真实渲染 + emulateMedia({ media: 'print' }) 能验证。
 *
 * fixture 模式（E2E_MOCK_AUTH）：认证与订单接口全部 mock，不依赖后端与真实数据。
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
      productCode: '0012',
      color: '米白',
      specification: '门幅2.8米',
      quantity: 12.5,
      unitPrice: 100,
      amount: 1250,
      subtotal: 1250,
    },
  ],
  processingItems: [],
}

/** 订单详情 GET + 物流 PUT 的 mock（按方法分流，避免把发货提交也吃掉） */
async function mockOrderApi(page: any, order: Record<string, unknown>) {
  let current = { ...order }
  const submitted: any[] = []

  await page.route('**/api/admin/orders/**', async (route: any) => {
    const req = route.request()
    const url = req.url()
    if (req.method() === 'PUT' && url.includes('/logistics')) {
      submitted.push(req.postDataJSON())
      current = {
        ...current,
        status: 'shipped',
        logistics: { logisticsCompany: '顺丰速运', trackingNo: 'SF20260915001', shipperName: '王五' },
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, data: null }),
      })
    }
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
    await expect(doc).toContainText('门幅2.8米')
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

    // 补打入口可见（发货页对 shipped 有状态守卫，重打只能从这里）
    const printBtn = page.getByRole('button', { name: /打印发货单/ })
    await expect(printBtn).toBeVisible()

    // 点击不报错（真实 window.print 在无头环境会静默返回）
    await printBtn.click()

    await page.emulateMedia({ media: 'print' })
    await page.waitForTimeout(600) // 同上：等 transition-all 结束，避免拍到过渡中间态
    const doc = page.locator('.shipment-print-area')
    await expect(doc).toBeVisible()
    await expect(page.locator('aside')).toBeHidden()
    await expect(doc).toContainText('李四')
    await expect(doc).toContainText('顺丰速运')
    await expect(doc).toContainText('SF20260915001')

    await page.screenshot({ path: '/tmp/ui040-shipment-doc-reprint.png', fullPage: true })
  })

  test('发货提交：发货人随 payload 下发（改过的值优先）', async ({ page }) => {
    const { submitted } = await mockOrderApi(page, baseOrder)

    await page.goto(`/orders/${ORDER_ID}/ship`)

    const shipperInput = page.getByPlaceholder('请输入实际发货人姓名')
    await shipperInput.fill('王五')
    await page.getByPlaceholder('请输入快递单号').fill('SF20260915001')
    await page.getByRole('button', { name: /确认发货/ }).click()

    await expect
      .poll(() => submitted.length, { message: '应发生一次物流提交' })
      .toBeGreaterThan(0)
    expect(submitted[0].shipperName).toBe('王五')
    expect(submitted[0].trackingNo).toBe('SF20260915001')
  })
})
