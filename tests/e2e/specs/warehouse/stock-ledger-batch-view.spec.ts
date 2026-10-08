// case_ids: UI-089
import { test, expect, type Page, type Locator } from '../../fixtures'

/**
 * 库存明细页的「批次余量」视图（`/stock-ledger`，issue #6417）—— **效果层**几何 + 内容判据。
 *
 * 用户 2026-10-06 逐字：「库存明细还是缺乏单批次的剩余量，比如 1 卷 = 67 米，经过加工裁剪后应该有个剩余米数」。
 *
 * 本 spec 用**真实浏览器 + 真实布局**回答三件单测（jsdom 不做布局）回答不了的事：
 *   ① **剩余米数那一列真的在屏幕上**（一行 = 一卷，能看到 46.5 / 0 这种读数）；
 *   ② **表头八列全部单行**（「列样式」这族缺陷 2026-10-06 已在入库单页爆过一次 ⇒ 新表**不该重犯**：
 *      见 `frontend/admin-web/tests/unit/list-table-nowrap-guard.test.ts` 的类级守卫 + 本文件的几何读数）；
 *   ③ **最右列「剩余米数」可达**：实测 8 列（内容较窄）在 1280 下**直接装得下**（表 940px = 容器 940px），
 *      1024 下若装不下则必须**真的能横向滚**、滚到底能到达 —— 两种形态都不许是「看不见且够不着」。
 *
 * ⚠️ 数据由本 spec 自己 mock（fixture 模式；认证由 `tests/e2e/fixtures.ts` 的 `/api/auth/me` 兜底）——
 * 不依赖后端，也就不会因为「本机没起 admin-api」把判据读成红（同族教训见 issue #6411）。
 */

const PRODUCTS = {
  success: true,
  data: { items: [{ id: 'prod-1', name: '遮光窗帘布料 米白' }], total: 1, page: 1, size: 20 },
}

const FLOW = {
  success: true,
  data: {
    items: [
      {
        id: 1,
        productId: 'prod-1',
        skuId: 12,
        skuCode: 'HZ-001-米白',
        delta: '67.0',
        beforeQty: '0.0',
        afterQty: '67.0',
        reason: 'inbound',
        refNo: 'RK-20261001-0001',
        note: null,
        unitCost: '24.80',
        costAmount: '1661.60',
        avgCostBefore: null,
        avgCostAfter: '24.80',
        operator: 'zhangsan',
        createdAt: '2026-10-01T10:00:00+08:00',
      },
    ],
    total: 1,
    page: 1,
    size: 20,
  },
}

/** 三卷：① 67 米裁剪掉 20 ⇒ 46.5（服务端值，**不等于** 67−20 —— 页面不得自算）；② 用尽；③ 未动过 */
const BATCHES = {
  success: true,
  data: [
    {
      batchId: 11,
      batchNo: 'PC-20261001-0001',
      productId: 'prod-1',
      skuId: 12,
      skuCode: 'HZ-001-米白',
      inboundNo: 'RK-20261001-0001',
      dyeLot: 'G-77',
      receivedDate: '2026-10-01',
      unitCost: '24.80',
      inboundMeters: '67.0',
      consumedMeters: '20.0',
      remainingMeters: '46.5',
    },
    {
      batchId: 12,
      batchNo: 'PC-20260920-0007',
      productId: 'prod-1',
      skuId: 12,
      skuCode: 'HZ-001-米白',
      inboundNo: 'RK-20260920-0003',
      dyeLot: null,
      receivedDate: '2026-09-20',
      unitCost: '24.10',
      inboundMeters: '50.0',
      consumedMeters: '50.0',
      remainingMeters: '0.0',
    },
    {
      batchId: 13,
      batchNo: 'PC-20261005-0012',
      productId: 'prod-1',
      skuId: 12,
      skuCode: 'HZ-001-米白',
      inboundNo: 'RK-20261005-0009',
      dyeLot: 'G-91',
      receivedDate: '2026-10-05',
      unitCost: '25.00',
      inboundMeters: '120.0',
      consumedMeters: '0.0',
      remainingMeters: '120.0',
    },
  ],
}

/** 只放宽时间预算（`next dev` 冷编译本页实测可达 20s+），**断言一字未放宽** */
test.describe.configure({ timeout: 90_000 })

/**
 * 元素里的文本占**几行** = 各**文本节点**矩形按 `top` 去重后的个数。
 * ⚠️ 只数文本节点：`range.selectNodeContents(el)` 会把后代元素的边框盒也算进来（药丸的
 * 文字盒与边框盒 `top` 差几像素 ⇒ 1 行被数成 2 行，2026-10-06 实测踩过）。
 */
async function lines(locator: Locator): Promise<number> {
  return locator.evaluate((node) => {
    const tops = new Set<number>()
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT)
    let text = walker.nextNode()
    while (text) {
      const range = document.createRange()
      range.selectNodeContents(text)
      for (const rect of Array.from(range.getClientRects())) {
        if (rect.width > 0.5 && rect.height > 0.5) tops.add(Math.round(rect.top))
      }
      text = walker.nextNode()
    }
    return tops.size
  })
}

/** 本页挂载后还会打若干**非本判据**的接口；无后端时它们 401 ⇒ 应用会登出跳登录页 ⇒ 判据与被测行为无关地红 */
async function mockApis(page: Page) {
  const hits = { batches: 0 }
  await page.route('**/api/**', (route) =>
    route.request().url().includes('/api/auth/me')
      ? route.fallback()
      : route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: null }) }),
  )
  await page.route('**/api/admin/products**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(PRODUCTS) }),
  )
  await page.route('**/api/admin/stock-ledger**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FLOW) }),
  )
  await page.route('**/api/admin/batch-stock/batches**', (route) => {
    hits.batches += 1
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BATCHES) })
  })
  return hits
}

async function openLedger(page: Page, width: number) {
  const hits = await mockApis(page)
  await page.setViewportSize({ width, height: 900 })
  await page.goto('/stock-ledger', { timeout: 60_000 })
  // 冷启动前置：流水视图先渲染出来（不然下面的交互是在空页面上点）
  await expect(page.getByTestId('stock-ledger-row').first()).toBeVisible({ timeout: 30_000 })
  return hits
}

async function pickProductAndOpenBatch(page: Page) {
  await page.getByTestId('view-batch').click()
  await page.getByLabel('搜索商品').fill('遮光')
  await page.getByRole('button', { name: '搜索商品' }).click()
  await page.getByTestId('product-option').first().click()
  await expect(page.getByTestId('batch-row').first()).toBeVisible({ timeout: 20_000 })
}

test('批次余量视图：一行 = 一卷，剩余米数真的在屏幕上（67 裁剪掉 20 ⇒ 46.5；用尽的那卷也在）', async ({ page }) => {
  const hits = await openLedger(page, 1440)
  await pickProductAndOpenBatch(page)

  const rows = page.getByTestId('batch-row')
  await expect(rows).toHaveCount(3)
  expect(hits.batches, '批次读面必须真被调用（没调用 ⇒ 判据在扫空气）').toBeGreaterThan(0)

  const first = rows.first()
  await expect(first.getByTestId('batch-no')).toHaveText('PC-20261001-0001')
  await expect(first.getByTestId('batch-inbound')).toHaveText('67')
  await expect(first.getByTestId('batch-consumed')).toHaveText('20')
  await expect(first.getByTestId('batch-remaining')).toHaveText('46.5')
  await expect(first.getByTestId('batch-dyelot')).toHaveText('G-77')
  await expect(first.getByTestId('batch-received')).toHaveText('2026-10-01')

  // 用尽的那卷照样列出（余量 0 本身是要看的信息）；缸号缺失 ⇒ 「—」（不空白）
  const second = rows.nth(1)
  await expect(second.getByTestId('batch-remaining')).toHaveText('0')
  await expect(second.getByTestId('batch-dyelot')).toHaveText('—')

  await page.screenshot({ path: '/tmp/ui-6417/batch-1440.png', fullPage: true })
})

test('表头八列全部单行（列不许被压成竖排）+ 卡片不裁切表格', async ({ page }) => {
  await openLedger(page, 1280)
  await pickProductAndOpenBatch(page)

  const headers = page.getByRole('columnheader')
  await expect(headers).toHaveCount(8)
  const seen: string[] = []
  for (const th of await headers.all()) {
    const text = (await th.innerText()).trim()
    seen.push(text)
    expect(await lines(th), `表头「${text}」折行了（列被压到 CJK min-content）`).toBe(1)
  }
  expect(seen).toEqual(['批次号', '货号 / SKU', '缸号', '入库单', '入库米数', '已消耗', '剩余米数', '收货日期'])

  // 表格祖先里必须存在横向逃逸口；最近一个 overflow-x: hidden 的祖先不得裁掉内容
  const scroller = page.locator('table').last().locator('xpath=..')
  const overflowX = await scroller.evaluate((el) => getComputedStyle(el).overflowX)
  expect(['auto', 'scroll']).toContain(overflowX)
  const clipped = await page.evaluate(() => {
    let node: HTMLElement | null = document.querySelectorAll('table')[1] as HTMLElement | null
    while (node) {
      if (getComputedStyle(node).overflowX === 'hidden') return node.scrollWidth - node.clientWidth
      node = node.parentElement
    }
    return 0
  })
  expect(clipped, '右侧列被 overflow-hidden 裁掉了').toBeLessThanOrEqual(1)

  await page.screenshot({ path: '/tmp/ui-6417/batch-1280.png', fullPage: true })
})

test('1280：8 列直接装得下 ⇒ 最右的「剩余米数」列无需横向滚就在视口内', async ({ page }) => {
  await openLedger(page, 1280)
  await pickProductAndOpenBatch(page)

  const scroller = page.locator('table').last().locator('xpath=..')
  const { scrollWidth, clientWidth } = await scroller.evaluate((el) => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
  }))
  // 如实读数：批次表 8 列内容窄，1280 下不溢出（若哪天内容变长到溢出，这条会红 ⇒ 逼人去看下面那条可达性判据）
  expect(scrollWidth, `批次表在 1280 下溢出（${scrollWidth} > ${clientWidth}）—— 用户会看不见最右列`).toBeLessThanOrEqual(
    clientWidth + 1,
  )
  await expect(page.getByTestId('batch-remaining').first()).toBeInViewport()
  await expect(page.getByTestId('batch-received').first()).toBeInViewport()
})

test('1024 窄视口：最右两列**可达**（装得下就直接在视口内；装不下则滚到底必达）', async ({ page }) => {
  await openLedger(page, 1024)
  await pickProductAndOpenBatch(page)

  const scroller = page.locator('table').last().locator('xpath=..')
  const { scrollWidth, clientWidth } = await scroller.evaluate((el) => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
  }))
  const overflowX = await scroller.evaluate((el) => getComputedStyle(el).overflowX)
  if (scrollWidth > clientWidth) {
    expect(['auto', 'scroll'], '装不下却没有横向逃逸口 ⇒ 表格会被裁掉').toContain(overflowX)
  }
  await scroller.evaluate((el) => {
    el.scrollLeft = el.scrollWidth
  })
  // ⚠️ `toBeVisible()` 不判视口相交（滚动容器外的元素照样 visible）⇒ 必须用 toBeInViewport
  await expect(page.getByTestId('batch-remaining').first()).toBeInViewport()
  await expect(page.getByTestId('batch-received').first()).toBeInViewport()
  console.log(`[6417] 1024 读数：表 ${scrollWidth}px / 容器 ${clientWidth}px / overflow-x=${overflowX}`)
})

test('未选商品：显式提示，且**一次批次请求都不发**（端点是全量无分页）', async ({ page }) => {
  const hits = await openLedger(page, 1440)
  await page.getByTestId('view-batch').click()

  await expect(page.getByTestId('batch-need-product')).toBeVisible()
  await expect(page.getByTestId('batch-row')).toHaveCount(0)
  expect(hits.batches, '没选商品却拉了批次 ⇒ 「一次拉全量」的口径被破坏').toBe(0)
})
