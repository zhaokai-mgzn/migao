// case_ids: UI-027
/**
 * 打印链路（issue #5914）—— 真实浏览器判据。
 *
 * 这层要回答的是 vitest / jsdom 答不了的四件事（`migao-dev-flow` §15.3）：
 *
 * ① **`window.print()` 触发的那一刻，DOM 里目标已置位吗** —— 旧写法（同 tick
 *    `setState` + `print`）实测 `beforeprint:TARGET_MISSING` ⇒ **首次打印一张空白纸**；
 * ② **同页四份单据时纸型是哪一张** —— 同一文档多条 `@page` ⇒ 最后声明的那条赢
 *    （旧实现点「打印发货单」出纸 240.96×140.04mm = 销售单的三联纸）；
 * ③ **非目标单据会不会一起上纸**（`visibility:hidden` 仍占版面 ⇒ 空白页）；
 * ④ **截图复制到底有没有产出真实尺寸的 PNG**（`SVG foreignObject` 这条链路只有真浏览器跑得通）。
 *
 * fixture 模式（`E2E_MOCK_AUTH`）：认证与订单接口全部 mock，不依赖后端与真实数据。
 */
import { test, expect } from '../../fixtures'

const ORDER_ID = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890'

const buildItems = (count: number) =>
  Array.from({ length: count }, (_, i) => ({
    id: `item-${i + 1}`,
    productId: `p-${i + 1}`,
    productName: `布艺遮光帘${i + 1}`,
    productCode: `00${i + 1}`,
    color: '米白',
    specification: '门幅2.8米',
    quantity: 12.5,
    unitPrice: 100,
    amount: 1250,
    subtotal: 1250,
  }))

const baseOrder = (itemCount = 3) => ({
  id: ORDER_ID,
  orderNo: 'ORD20261001001',
  customerName: '张三',
  customerPhone: '13800138000',
  customerAddress: '浙江省杭州市余杭区某某路 1 号',
  totalAmount: 3750,
  actualAmount: 3750,
  discountAmount: 0,
  status: 'shipped',
  hasProcessing: false,
  createdAt: '2026-10-01T10:00:00+08:00',
  remark: '客户要求工作日送达',
  items: buildItems(itemCount),
  processingItems: [],
})

/** 订单详情所需的全部旁路接口（fixture 模式无后端） */
async function mockOrderApi(page: any, order: Record<string, unknown>) {
  await page.route('**/api/admin/orders/**/shipments', (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        success: true,
        data: { order_id: ORDER_ID, order_no: order.orderNo, status: 'shipped', shipments: [] },
      }),
    })
  )
  await page.route('**/api/admin/orders/**', (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: order }),
    })
  )
  await page.route('**/api/admin/settings/payment-qrcodes**', (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: {} }),
    })
  )
  await page.route('**/api/admin/notifications**', (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { items: [], total: 0, unreadCount: 0 } }),
    })
  )
}

test.describe('商家后台打印链路（UI-026 / issue #5914）', () => {
  test('① 点「打印」时目标已置位：beforeprint 抓到的不是空白纸（旧实现 = NONE）', async ({ page }) => {
    await mockOrderApi(page, baseOrder())
    await page.goto(`/orders/${ORDER_ID}`)

    // 在**真浏览器**里抓 print 那一刻的 DOM（`window.print()` 在无头模式会静默返回，
    // 但 `beforeprint` 照常派发 —— 这正是旧实现出空白纸的那个时刻）
    await page.evaluate(() => {
      const marks: string[] = []
      ;(window as unknown as { __printMarks: string[] }).__printMarks = marks
      window.addEventListener('beforeprint', () => {
        const targets = Array.from(document.querySelectorAll('[data-print-target]'))
          .map((el) => el.getAttribute('data-print-target'))
          .join(',')
        marks.push(targets || 'NONE')
      })
    })

    await page.getByRole('button', { name: /打印销售单/ }).click()
    // 打印前的**纸面自检层**（先看见再上纸）
    await expect(page.getByTestId('print-preview')).toBeVisible()
    await page.getByTestId('print-preview-print').click()

    const marks = await page.evaluate(
      () => (window as unknown as { __printMarks: string[] }).__printMarks
    )
    expect(marks, 'beforeprint 时目标没置位 ⇒ 目标单据拿不到 visibility 防御 ⇒ 空白纸').toEqual([
      'sales',
    ])
  })

  test('② 同页四份单据只放一份上纸：文档里恰好一条 @page，且是本次那张纸', async ({ page }) => {
    await mockOrderApi(page, baseOrder())
    await page.goto(`/orders/${ORDER_ID}`)
    await expect(page.getByRole('button', { name: /打印销售单/ })).toBeVisible()

    // 🔴 打印前：文档里**一条 @page 都没有**（没有任何单据在抢纸型）
    const before = await readPageRules(page)
    expect(before.count).toBe(0)

    await page.getByRole('button', { name: /打印销售单/ }).click()
    await expect(page.getByTestId('print-preview')).toBeVisible()

    // 点「打印」之后：只有销售单发表纸型 —— 恰好一条，且是三联纸 241×140
    await page.getByTestId('print-preview-print').click()
    const after = await readPageRules(page)
    expect(after.count, `实测 @page 规则：${JSON.stringify(after.rules)}`).toBe(1)
    // ⚠️ 纸型读**样式文本**：Chrome 的 CSSOM **不序列化 `@page` 的 `size` 描述符**
    //    （实测 `rule.cssText` 只剩 `@page { margin: 6mm 12mm; }`），拿 cssText 判尺寸会假红
    const pageCss = await readStyleText(page)
    expect(pageCss).toContain('@page { size: 241mm 140mm; margin: 6mm 12mm; }')

    // 打印媒体下：只有目标单据在版面上，兄弟单据既不显形也不占版面
    await page.emulateMedia({ media: 'print' })
    await page.waitForTimeout(600) // 等 transition-all 结束（见 shipment-doc.spec.ts 的同款说明）
    // ⚠️ 选择器必须精确到「**上纸那一份**」：预览层里还有一份不带 target 的副本
    // （`page.locator('.sales-print-area')` 会命中 2 个 ⇒ strict mode 红）
    await expect(page.locator('.sales-print-area[data-print-target="sales"]')).toBeVisible()
    // 而预览副本在打印媒体下**不上纸**（这条防的是「一次出两份」）
    await expect(page.locator('.print-preview-doc .sales-print-area')).toBeHidden()
    for (const sibling of ['.shipment-print-area', '.quotation-print-area', '.processing-print-area']) {
      await expect(page.locator(sibling)).toBeHidden()
    }
  })

  test('③ 纸面自检：明细行装得下 / 装不下都要说清楚（销售单单联 128mm）', async ({ page }) => {
    // 8 行明细：实测内容 ≈136.5mm > 单联可用 128mm ⇒ 必须报溢出（旧实现是**静默裁掉**金额与收款码）
    await mockOrderApi(page, baseOrder(8))
    await page.goto(`/orders/${ORDER_ID}`)
    await page.getByRole('button', { name: /打印销售单/ }).click()

    const media = page.getByTestId('print-preview-media')
    await expect(media).toContainText('241mm × 140mm')
    await expect(media).toContainText('217mm × 128mm')
    await expect(page.getByTestId('print-preview-check')).toContainText('超出')
  })

  test('③ 5 行明细装得下 ⇒ 不许报溢出（判据不是「恒报警」）', async ({ page }) => {
    await mockOrderApi(page, baseOrder(5))
    await page.goto(`/orders/${ORDER_ID}`)
    await page.getByRole('button', { name: /打印销售单/ }).click()
    await expect(page.getByTestId('print-preview-check')).toContainText('装得下')
  })

  test('④ 复制截图：剪贴板拿到**真尺寸**的 PNG（241×140 的三联纸单据）', async ({ page, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write'])
    await mockOrderApi(page, baseOrder(2))
    await page.goto(`/orders/${ORDER_ID}`)
    await page.getByRole('button', { name: /打印销售单/ }).click()
    await expect(page.getByTestId('print-preview')).toBeVisible()

    await page.getByTestId('print-preview-capture').click()
    await expect(page.getByText(/已复制|已改为下载/)).toBeVisible()

    const shot = await page.evaluate(async () => {
      const items = await navigator.clipboard.read()
      const png = items.find((item) => item.types.includes('image/png'))
      if (!png) return { ok: false as const, types: items.flatMap((i) => i.types) }
      const blob = await png.getType('image/png')
      const bitmap = await createImageBitmap(blob)
      // 🔴 内容必须**铺满整张纸**：预览里纸框被 scale 缩放适配屏幕，若截图把那个 transform
      // 一起内联进去，画面会缩在左上角、四周留白 —— 而画布尺寸断言**看不出来**。
      // 这条按非白像素的包围盒判（真尺寸截图的边框/文字应当铺满整幅）。
      const canvas = document.createElement('canvas')
      canvas.width = bitmap.width
      canvas.height = bitmap.height
      const ctx = canvas.getContext('2d')!
      ctx.drawImage(bitmap, 0, 0)
      const { data } = ctx.getImageData(0, 0, canvas.width, canvas.height)
      let minX = canvas.width
      let minY = canvas.height
      let maxX = -1
      let maxY = -1
      for (let y = 0; y < canvas.height; y += 2) {
        for (let x = 0; x < canvas.width; x += 2) {
          const i = (y * canvas.width + x) * 4
          const ink = data[i] < 235 || data[i + 1] < 235 || data[i + 2] < 235
          if (!ink) continue
          if (x < minX) minX = x
          if (y < minY) minY = y
          if (x > maxX) maxX = x
          if (y > maxY) maxY = y
        }
      }
      return {
        ok: true as const,
        size: blob.size,
        width: bitmap.width,
        height: bitmap.height,
        inkWidthRatio: (maxX - minX) / canvas.width,
        inkHeightRatio: (maxY - minY) / canvas.height,
      }
    })

    expect(shot.ok, `剪贴板里没有 image/png：${JSON.stringify(shot)}`).toBe(true)
    if (!shot.ok) return
    // 3 倍放大（≈288dpi）：241mm ≈ 911px ⇒ ≈2733px；宽高比 = 241:140 ≈ 1.72
    expect(shot.size).toBeGreaterThan(10_000)
    expect(shot.width).toBeGreaterThan(2400)
    expect(shot.width / shot.height).toBeGreaterThan(1.6)
    expect(shot.width / shot.height).toBeLessThan(1.85)
    // 铺满整张纸 —— 判据是**像素覆盖率**（实测读数，见 PR body 的独立探针）：
    // 正常截图 inkW≈0.90；而把预览的 `scale(0.82)` 一起内联进截图时内容会缩在左上角
    // ⇒ inkW ≈ 0.90 × 0.82 ≈ 0.74 ⇒ 阈值 0.8 是**可归因分界**。
    expect(shot.inkWidthRatio).toBeGreaterThan(0.8)
    // 纵向**只做下界限**：销售单单联固定 128mm，明细少的单子底部本来就是空白
    // （实测 2 行 ⇒ inkH≈0.64），拿它当「铺满」判据会假红；缩在左上角的截图会同时掉到 <0.55。
    expect(shot.inkHeightRatio).toBeGreaterThan(0.5)
  })
})

/** 读出文档里所有 `<style>` 的文本（`@page` 的 `size` 描述符只有这里读得到） */
async function readStyleText(page: any): Promise<string> {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll('style'))
      .map((el) => el.textContent || '')
      .join('\n')
  )
}

/** 读出文档里所有 `@page` 规则（CSSOM；跨域表读不到就跳过，不静默当成 0） */
async function readPageRules(page: any): Promise<{ count: number; rules: string[] }> {
  return page.evaluate(() => {
    const rules: string[] = []
    for (const sheet of Array.from(document.styleSheets)) {
      let list: CSSRuleList
      try {
        list = sheet.cssRules
      } catch {
        continue
      }
      for (const rule of Array.from(list)) {
        if (rule.cssText.startsWith('@page')) rules.push(rule.cssText)
      }
    }
    return { count: rules.length, rules }
  })
}
