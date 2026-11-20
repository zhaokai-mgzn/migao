// case_ids: UI-154
/**
 * 商品详情两区与层级（issue #8934）—— 真实浏览器判据。
 *
 * 用户 2026-11-20 钉钉口径：商品信息作为一个整体展示；批次余量 / 批次盘点 / 剩余量分布 /
 * 库存对账作为另一个整体展示；两个整体不穿插、要有条理和层级。同日追加：信息不要重复、简洁明了。
 *
 * 这层要回答单测答不了的两件事：
 * ① 真实几何 —— 商品信息区在批次与库存区上方、两区不重叠，所有子块都落在自己的区域卡内；
 * ② 真数据 —— 商品 / 批次余量 / 分布 / 对账都加载完成后再取版式证据，而不是加载中或空态。
 *
 * fixture 模式（`E2E_MOCK_AUTH`）：认证与页面接口全部 mock，不依赖后端与真实数据。
 * 截图入口：`MIGAO_SHOT_DIR=/tmp/xxx MIGAO_SHOT_LABEL=before npx playwright test ...`
 * （截图在区域断言之前落盘 ⇒ 同一脚本跑改前基线时也能留下 Before 证据）。
 */
import { test, expect } from '../../fixtures'

const PRODUCT_ID = 'prod_detail_regions_001'

/** 纯本地占位图（不依赖外网 / OSS）：截图里商品图能正常出画，而不是破图。 */
const IMAGE = (label: string, color: string) =>
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"><rect width="400" height="400" fill="${color}"/><text x="200" y="210" font-size="28" text-anchor="middle" fill="#fff">${label}</text></svg>`,
  )

const MOCK_PRODUCT = {
  id: PRODUCT_ID,
  name: '天鹅绒遮光窗帘',
  sku: 'SKU-DETAIL-001',
  skuCode: 'SKU-DETAIL-001',
  brand: '观星台',
  categoryName: '窗帘布艺',
  description: '<p>优质天鹅绒材质，遮光率 95% 以上。</p>',
  pricingType: 'per_meter',
  pricingUnit: '米',
  price: 168,
  costPrice: 85,
  status: 'on_sale',
  totalStock: 250,
  stockDeductionMode: 'on_order',
  stockWarningThreshold: 100,
  sellingMethods: ['bulk_cut', 'full_roll'],
  rollLengthM: 30,
  salesCount: 1200,
  salesAmount: 119400,
  specifications: { weight: '300-400g', material: '绒布', function: '遮光' },
  colors: [
    { id: 1, colorName: '米白', mainColorHex: '#F5F5DC' },
    { id: 2, colorName: '深灰', mainColorHex: '#404040' },
  ],
  skus: [
    { id: 1, colorId: 1, colorName: '米白', doorWidth: '2.8米', skuCode: 'SKU-MB', stock: 100, price: 168 },
    { id: 2, colorId: 2, colorName: '深灰', doorWidth: '2.8米', skuCode: 'SKU-SG', stock: 150, price: 168 },
  ],
  images: [IMAGE('主图', '#8a7a66')],
  detailImages: [IMAGE('详情图', '#5b6b7f')],
  createdAt: '2026-10-15 10:00:00',
  updatedAt: '2026-11-18 15:00:00',
  editedBy: '管理员',
  editedAt: '2026-11-18 15:00:00',
}

const MOCK_BATCHES = [
  {
    batchId: 1,
    batchNo: 'PC-20261101-0001',
    productId: PRODUCT_ID,
    skuId: 1,
    skuCode: 'SKU-MB',
    receivedDate: '2026-11-01',
    inboundMeters: '120',
    consumedMeters: '20',
    remainingMeters: '100',
  },
  {
    batchId: 2,
    batchNo: 'PC-20261105-0002',
    productId: PRODUCT_ID,
    skuId: 2,
    skuCode: 'SKU-SG',
    receivedDate: '2026-11-05',
    inboundMeters: '150',
    consumedMeters: '0',
    remainingMeters: '150',
  },
]

const MOCK_DISTRIBUTION = {
  totalBatches: 2,
  buckets: [
    { key: 'le_0_2', label: '≤0.2 米', batchCount: 0, share: '0' },
    { key: 'b0_2_0_5', label: '0.2~0.5 米', batchCount: 0, share: '0' },
    { key: 'b0_5_1', label: '0.5~1 米', batchCount: 0, share: '0' },
    { key: 'gt_1', label: '>1 米', batchCount: 2, share: '100' },
  ],
}

const MOCK_RECONCILE = {
  totalDiff: '0',
  unreconciledCount: 0,
  rows: [
    {
      skuId: 1,
      skuCode: 'SKU-MB',
      productId: PRODUCT_ID,
      skuStock: '100',
      batchRemaining: '100',
      inboundMeters: '120',
      dispatchedMeters: '20',
      soldDeductedMeters: '0',
      otherLedgerDeltaMeters: '0',
      unbatchedMeters: '0',
      diff: '0',
      explainedDiff: '0',
      reconciled: true,
    },
    {
      skuId: 2,
      skuCode: 'SKU-SG',
      productId: PRODUCT_ID,
      skuStock: '150',
      batchRemaining: '150',
      inboundMeters: '150',
      dispatchedMeters: '0',
      soldDeductedMeters: '0',
      otherLedgerDeltaMeters: '0',
      unbatchedMeters: '0',
      diff: '0',
      explainedDiff: '0',
      reconciled: true,
    },
  ],
}

/** 详情页所需的全部接口（fixture 模式无后端）。 */
async function mockProductDetailApi(page: any) {
  // 兜底：未 mock 的旁路请求给空成功 —— 否则 axios 拦截器把「网络连接失败」toast 打进版式证据。
  // 先注册，后面更具体的路由会覆盖它（Playwright 后注册优先）。
  await page.route('**/api/**', async (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: null }),
    }),
  )

  // 真实登录态的形状：admin 权限位齐全（侧边栏 / 页面授权门按真响应渲染）。
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

  await page.route(`**/api/admin/products/${PRODUCT_ID}`, async (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: MOCK_PRODUCT }),
    }),
  )

  await page.route(/\/api\/admin\/batch-stock\//, async (route: any) => {
    const pathname = new URL(route.request().url()).pathname
    const data = pathname.endsWith('/batches')
      ? MOCK_BATCHES
      : pathname.endsWith('/distribution')
        ? MOCK_DISTRIBUTION
        : pathname.endsWith('/reconcile')
          ? MOCK_RECONCILE
          : null
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data }),
    })
  })

  await page.route('**/api/admin/notifications/unread-count', async (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, data: { count: 0 } }),
    }),
  )
}

test.describe('商品详情两区与层级（issue #8934）', () => {
  test.use({ viewport: { width: 1440, height: 980 } })

  test('商品信息一个整体、批次与库存一个整体、两区不穿插 + 无重复库存读数', async ({ page }) => {
    test.setTimeout(360_000)
    await mockProductDetailApi(page)
    await page.goto(`/products/${PRODUCT_ID}`, { waitUntil: 'domcontentloaded', timeout: 300_000 })

    // 页面数据真的加载出来（商品 + 批次账；不是加载中 / 空态）。
    await expect(page.getByRole('heading', { name: '天鹅绒遮光窗帘' })).toBeVisible({ timeout: 120_000 })
    await expect(page.getByTestId('batch-remaining-table')).toBeVisible({ timeout: 60_000 })
    await expect(page.getByTestId('reconcile-table')).toBeVisible()

    // 等页面稳定（图片 / toast 不进入版式证据）
    await page.waitForTimeout(1_500)

    // 截图落在区域断言之前：同一脚本跑改前基线时也能留下 Before 证据。
    const shotDir = process.env.MIGAO_SHOT_DIR
    if (shotDir) {
      await page.evaluate(() => window.scrollTo(0, 0))
      await page.screenshot({
        path: `${shotDir}/${process.env.MIGAO_SHOT_LABEL || 'product-detail'}.png`,
        fullPage: true,
      })
    }

    const info = page.getByTestId('product-info-region')
    const stock = page.getByTestId('product-stock-region')
    await expect(info).toBeVisible()
    await expect(stock).toBeVisible()

    // ① 层级：两个区域卡各有一个 h2；子块是 h3（商品信息 6 块 / 批次与库存 5 块）
    await expect(info.getByRole('heading', { level: 2, name: '商品信息' })).toBeVisible()
    await expect(stock.getByRole('heading', { level: 2, name: '批次与库存' })).toBeVisible()
    for (const name of ['基本信息', '商品属性', '销售信息', '商品颜色', '商品描述', '商品图片']) {
      await expect(info.getByRole('heading', { level: 3, name })).toBeVisible()
    }
    for (const name of ['库存概览', '批次余量', '按批次盘点', '剩余量分布', '库存对账']) {
      await expect(stock.getByRole('heading', { level: 3, name })).toBeVisible()
    }

    // ② 两个整体不穿插：所有商品信息子块都在商品信息区，批次/库存子块都在批次与库存区
    for (const id of [
      'product-basic-info',
      'product-attributes',
      'product-sales-info',
      'product-colors',
      'product-description',
      'product-images',
    ]) {
      await expect(info.getByTestId(id)).toBeVisible()
      await expect(stock.getByTestId(id)).toHaveCount(0)
    }
    for (const id of [
      'product-stock-summary',
      'batch-remaining-section',
      'batch-stocktake',
      'batch-distribution-section',
      'batch-reconcile-section',
    ]) {
      await expect(stock.getByTestId(id)).toBeVisible()
      await expect(info.getByTestId(id)).toHaveCount(0)
    }

    // ③ 真实几何：商品信息区在批次与库存区上方，且两区不重叠
    const infoBox = await info.boundingBox()
    const stockBox = await stock.boundingBox()
    if (!infoBox || !stockBox) throw new Error('两个区域取不到真实几何 ⇒ 判据在扫空气')
    expect(infoBox.y + infoBox.height, '批次与库存区压在商品信息区上（两区重叠）').toBeLessThanOrEqual(
      stockBox.y + 1,
    )

    // ④ 无重复库存读数：商品级库存总量只在「库存概览」出现一次；
    //    批次余量 / 剩余量分布 / 库存对账标题全页各只一处（不在商品信息里再讲一遍）
    await expect(page.getByTestId('stock-total')).toHaveText('250')
    await expect(info.getByTestId('stock-total')).toHaveCount(0)
    await expect(info.getByText('库存扣减方式')).toHaveCount(0)
    await expect(info.getByText('库存预警阈值')).toHaveCount(0)
    for (const name of ['库存概览', '批次余量', '按批次盘点', '剩余量分布', '库存对账']) {
      await expect(page.getByRole('heading', { level: 3, name })).toHaveCount(1)
    }

    // ⑤ 版式没有横向溢出（1440 宽视口）
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow, `页面横向溢出 ${overflow}px`).toBeLessThanOrEqual(1)
  })
})
