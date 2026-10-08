// case_ids: UI-086
// 入库单**列表表格**几何完整性（issue #6398）：`<table className="w-full text-sm">` 把宽度钉在容器
// 宽度上、外层卡片又是 `overflow-hidden`（没有横向逃逸口），而 `th` / `td` **都没有**
// `whitespace-nowrap` ⇒ 列可以一直被压到 **CJK min-content = 一个汉字**
//（`行数 / 总数量` 甚至在 `/` 处断行）⇒ 状态药丸「已过账」竖排成两行、表头折行。
// 用户实测（2026-10-06）：「状态样式展示不对，列的样式也有问题，要平铺开」。
//
// 断言**效果层几何**（文本行盒数 = 1 + 横向逃逸口存在 + 卡片不裁切），不是类名快照
// —— 范式同 UI-056（`tests/e2e/specs/warehouse/inbound-orders-button-geometry.spec.ts`）。
/**
 * ⚠️ 描述性注释（不是 docstring 场景）——判据口径：
 *   · 行盒数 = `Range.getClientRects()` 里**去重后的 top 个数**（多文本节点在同一行 ⇒ 同一个 top，
 *     所以「`{itemCount} / {totalQuantity}` 这种三文本节点的单元格」也能被正确判成 1 行）；
 *   · 逃逸口 = 表格祖先里存在 `overflow-x: auto|scroll`（**只有 nowrap 没有逃逸口 ⇒ 表格被
 *     `overflow-hidden` 裁切**，那是更难发现的假绿，本判据单列一条守住）；
 *   · 裁切 = 最近一个 `overflow-x: hidden` 祖先的 `scrollWidth - clientWidth`（必须为 0）。
 *
 * 实测读数（修复前，1280×800）：表头「行数 / 总数量」**2 行**、状态药丸「已过账」**2 行**、
 * 逃逸口 = **不存在**（最近祖先 overflow-x = hidden）⇒ 三条判据同时红；修复后全部 1 行 / 逃逸口在 / 裁切 0。
 */
import { test, expect } from '../../fixtures'
import type { Locator, Page } from '@playwright/test'

/** 列表数据（形状 = `GET /api/admin/inbound-orders` 的 `{success,data}` 包装；取用户截图里那一屏的读数） */
const LIST = {
  success: true,
  data: [
    {
      id: '1',
      inboundNo: 'RK-20261005-0008',
      supplier: '广州中大轻纺城-A132档',
      warehouse: '门店后仓',
      inboundDate: '2026-09-23',
      status: 'posted',
      totalAmount: 4005,
      itemCount: 1,
      totalQuantity: 90,
      batchNos: 'PC-20261005-0011',
    },
    {
      id: '2',
      inboundNo: 'RK-20261005-0004',
      supplier: '柯桥金梭纺织有限公司',
      warehouse: '主仓（一楼）',
      inboundDate: '2026-09-12',
      status: 'posted',
      totalAmount: 18120,
      itemCount: 2,
      totalQuantity: 420,
      batchNos: 'PC-20261005-0006,PC-20261005-0007',
    },
    {
      id: '3',
      inboundNo: 'RK-20261005-0015',
      supplier: '广州中大轻纺城-A132档',
      warehouse: '门店后仓',
      inboundDate: '2026-10-05',
      status: 'cancelled',
      totalAmount: 1650,
      itemCount: 1,
      totalQuantity: 50,
      batchNos: null,
    },
    {
      id: '4',
      inboundNo: 'RK-20261005-0014',
      supplier: '绍兴柯桥万隆布业',
      warehouse: '主仓（一楼）',
      inboundDate: '2026-10-01',
      status: 'draft',
      totalAmount: 7000,
      itemCount: 1,
      totalQuantity: 100,
      batchNos: null,
    },
  ],
}

// ⚠️ 本文件的超时**比全局默认宽**（全局 `timeout: 30_000` / 导航默认 15s）：本 spec 需要渲染**带数据的列表**，
// 而 `next dev` 对本页的**冷编译**在负载高的机器上实测 >15s（2026-10-06 实测 `page.goto: Timeout 15000ms`），
// 且本文件 6 条用例并行首触 ⇒ 并发冷编译。**只放宽时间预算，断言一字未放宽**（加宽的超时不会把红变绿：
// 页面渲染不出来时下面的前置断言照样红）。
test.describe.configure({ timeout: 90_000 })

async function openInboundPage(page: Page, width: number) {
  // 本 spec 自带**兜底 mock**：本页在挂载后还会打若干**非本判据**的接口（权限/菜单/简报…），
  // 本机/CI 无后端时它们会 401 ⇒ 应用的请求拦截器会**登出并跳登录页**（2026-10-06 实测：
  // 同目录 UI-056 的 spec 在这种状态下 3/3 全红，而代码一字未改）⇒ 「页面在不在列表态」会变成一个
  // 与被测行为无关的红。兜底返回空成功体，让本判据只依赖它自己声明的前置。
  // ⚠️ `/api/auth/me` **必须放行**（`route.fallback()`）—— 认证夹具给的是真登录态，不能被这里吞掉。
  await page.route('**/api/**', (route) =>
    route.request().url().includes('/api/auth/me')
      ? route.fallback()
      : route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, data: null }) }),
  )
  await page.route('**/api/admin/inbound-orders**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LIST) }),
  )
  await page.setViewportSize({ width, height: 800 })
  await page.goto('/inbound-orders', { timeout: 60_000 })
  // 非空前置：出现第一行（列表没数据 ⇒ 本判据会在扫空气，直接红而不是假绿）。
  // ⚠️ 冷启动时 `next dev` 首次编译本页可能远超默认 5s（实测 18s）⇒ 这条等待必须给足；
  //    真落到登录页（mock 认证没生效）时它同样会红，只是报错信息会指向「页面不在列表态」。
  await expect(
    page.getByRole('row', { name: /RK-20261005-0008/ }),
    '入库单列表没渲染出第一行（冷编译超时 / 认证夹具没生效 ⇒ 本判据会在扫空气）',
  ).toBeVisible({ timeout: 30_000 })
}

const row = (page: Page, inboundNo: string) => page.getByRole('row', { name: new RegExp(inboundNo) })

/**
 * 元素里的文本占**几行** = 各**文本节点**的矩形按 `top` 去重后的个数。
 *
 * ⚠️ 必须**只数文本节点**（`TreeWalker(SHOW_TEXT)`），不能用 `range.selectNodeContents(el)`：
 * 后者会把**后代元素的边框盒**也算进来 —— 单元格里的药丸（`inline-flex` + `py-0.5` + 1px 边框）
 * 其**文字**与**盒子**的 `top` 差几像素 ⇒ 会被数成 2 行（**实测踩过**：全单元格判据首跑就因此误红）。
 * 多文本节点在同一行时它们的 `top` 相同 ⇒ 仍记 1 行（`1 / 90` 这种三文本节点单元格照样正确）。
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

test.describe('入库单列表表格几何完整性（issue #6398）', () => {
  test('表头全部单行（「行数 / 总数量」不得折成两行）', async ({ page }) => {
    await openInboundPage(page, 1280)
    const headers = page.getByRole('columnheader')
    const count = await headers.count()
    expect(count, '列表表头应当有 9 列（扫不到 ⇒ 判据在扫空气）').toBeGreaterThanOrEqual(9)
    for (let i = 0; i < count; i += 1) {
      const header = headers.nth(i)
      const text = (await header.innerText()).trim()
      const n = await lines(header)
      expect(n, `表头「${text}」占了 ${n} 行（列被压到 CJK min-content = 一个汉字）`).toBe(1)
    }
  })

  test('状态药丸单行（已过账 / 已作废 / 草稿 三种都不得竖排）', async ({ page }) => {
    await openInboundPage(page, 1280)
    for (const [no, label] of [
      ['RK-20261005-0008', '已过账'],
      ['RK-20261005-0015', '已作废'],
      ['RK-20261005-0014', '草稿'],
    ] as const) {
      const pill = row(page, no).getByText(label, { exact: true })
      await expect(pill, `状态药丸「${label}」不在场`).toBeVisible()
      const n = await lines(pill)
      expect(n, `状态药丸「${label}」占了 ${n} 行（药丸被压成 ~1 个汉字宽 ⇒ 竖排）`).toBe(1)
    }
  })

  test('每一列的内容都单行（逐单元格，含供应商/仓库/单号/日期/金额/数量/批次号/状态/操作）', async ({ page }) => {
    await openInboundPage(page, 1280)
    // 两行：0008 = 单批次 + 「1 / 90」（**三文本节点**单元格）；0004 = 聚合批次号「… 等 2 个」
    for (const no of ['RK-20261005-0008', 'RK-20261005-0004']) {
      const cells = row(page, no).getByRole('cell')
      const count = await cells.count()
      expect(count, `${no} 应当有 9 个单元格（扫不到 ⇒ 判据在扫空气）`).toBe(9)
      for (let i = 0; i < count; i += 1) {
        const cell = cells.nth(i)
        const text = (await cell.innerText()).trim()
        const n = await lines(cell)
        expect(n, `${no} 第 ${i + 1} 列「${text}」的内容占了 ${n} 行（列被压到 CJK min-content）`).toBe(1)
      }
    }
  })

  test('横向逃逸口存在 + 卡片不裁切表格', async ({ page }) => {
    await openInboundPage(page, 1280)
    const table = page.locator('table').first()
    const hasScroller = await table.evaluate((el) => {
      let node: HTMLElement | null = el.parentElement
      while (node) {
        const overflowX = getComputedStyle(node).overflowX
        if (overflowX === 'auto' || overflowX === 'scroll') return true
        node = node.parentElement
      }
      return false
    })
    expect(hasScroller, '表格没有 overflow-x-auto 横向逃逸口 ⇒ 列只能被压扁（折行）').toBe(true)

    const clipped = await table.evaluate((el) => {
      let node: HTMLElement | null = el.parentElement
      while (node) {
        if (getComputedStyle(node).overflowX === 'hidden') return node.scrollWidth - node.clientWidth
        node = node.parentElement
      }
      return 0
    })
    expect(clipped, '表格比卡片宽而卡片 overflow-hidden ⇒ 右侧列被裁掉（看不见的假绿）').toBeLessThanOrEqual(1)
  })

  test('窄视口（1280）：逃逸口真的可滚，滚到底后状态列与操作列进入视口', async ({ page }) => {
    await openInboundPage(page, 1280)
    const scroller = page.locator('table').first().locator('xpath=..')
    const { scrollWidth, clientWidth } = await scroller.evaluate((el) => ({
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
    }))
    expect(
      scrollWidth,
      `1280 宽下 9 列装不下（表 ${scrollWidth}px > 容器 ${clientWidth}px）⇒ 逃逸口必须**真的可滚**`
        + '（只断言「祖先里有个 overflow 容器」不够 —— 那可能是被 overflow-hidden 裁掉的假绿）',
    ).toBeGreaterThan(clientWidth)
    await scroller.evaluate((el) => {
      el.scrollLeft = el.scrollWidth
    })
    // ⚠️ `toBeVisible()` **不判视口相交**（在滚动容器外也算 visible）⇒ 这里必须用 `toBeInViewport`
    await expect(row(page, 'RK-20261005-0008').getByText('已过账', { exact: true })).toBeInViewport()
    await expect(row(page, 'RK-20261005-0008').getByRole('button', { name: '详情' })).toBeInViewport()
  })

  test('宽视口（1440×900）同样：表头与状态药丸单行', async ({ page }) => {
    await openInboundPage(page, 1440)
    const headers = page.getByRole('columnheader')
    for (let i = 0; i < (await headers.count()); i += 1) {
      const n = await lines(headers.nth(i))
      expect(n, `表头第 ${i + 1} 列占了 ${n} 行`).toBe(1)
    }
    const pill = row(page, 'RK-20261005-0008').getByText('已过账', { exact: true })
    expect(await lines(pill), '状态药丸「已过账」竖排').toBe(1)
  })
})
