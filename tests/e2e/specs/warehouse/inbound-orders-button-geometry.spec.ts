// case_ids: UI-056
// 入库单页按钮几何完整性（issue #5558）：`Button` 基类缺 `whitespace-nowrap` ⇒ 在 flex 行里它是
// 可收缩项、min-content = **一个汉字** ⇒ 空间不足时被压到 ~1 字宽，固定 `h-9` 的盒子里标签换行
// （内容溢出）。断言**效果层几何**（`scrollHeight − clientHeight` + 宽度下限），不是类名快照
// —— 范式同 UI-041（`tests/e2e/specs/settings/toggle-geometry.spec.ts`）。
//
// 实测读数（修复前）：期初建账导入 w=101/溢出 3px、新建入库单 w=90/溢出 2px、
// 查询 w=70/溢出 3px、重置 w=68/溢出 2px；修复后 w=140/124/84/82、溢出 0。
import { test, expect } from '../../fixtures'
import type { Page } from '@playwright/test'

/** 空列表足够：本判据只看**页头 / 筛选行**的按钮几何，与列表内容无关 */
const EMPTY_LIST = { success: true, data: [] }

async function openInboundPage(page: Page, width: number) {
  await page.route('**/api/admin/inbound-orders**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(EMPTY_LIST) }),
  )
  await page.setViewportSize({ width, height: 800 })
  await page.goto('/inbound-orders')
}

/**
 * 标签必须落在**一行**里：`h-9` 的按钮内容溢出 ⇒ 标签被压成了两行（issue #5558 的症状）。
 * 同时钉宽度下限 —— 防「换行被 overflow:hidden 藏起来」式的假绿（压扁了但看不见换行）。
 */
async function expectLabelOnOneLine(page: Page, name: RegExp, minWidth: number) {
  const button = page.getByRole('button', { name })
  await expect(button).toBeVisible()
  const overflow = await button.evaluate((el) => el.scrollHeight - el.clientHeight)
  const box = await button.boundingBox()
  // ⚠️ 不写「包围盒非空」那一类**弱断言**（仓内弱断言台账只许非增，issue #5477；本单实测被拦一次）。
  //    这里直接读**几何量**：内容溢出 + 宽度下限 —— 两条都是业务可感的读数，「有包围盒」由它们蕴含。
  expect(overflow, `「${name}」标签换行了（内容溢出 ${overflow}px）—— 按钮被 flex 压到 min-content`).toBeLessThanOrEqual(1)
  expect(box?.width ?? 0, `「${name}」被压扁（宽 ${box?.width ?? 0}px < 下限 ${minWidth}px）`).toBeGreaterThanOrEqual(minWidth)
}

test.describe('入库单页按钮几何完整性（issue #5558）', () => {
  test('页头：期初建账导入 / 新建入库单 标签单行、不被压扁', async ({ page }) => {
    await openInboundPage(page, 1100)
    await expectLabelOnOneLine(page, /期初建账导入/, 130)
    await expectLabelOnOneLine(page, /新建入库单/, 118)
  })

  test('筛选行：查询 / 重置 标签单行、不被压扁（`w-full` 控件抢宽的场景）', async ({ page }) => {
    await openInboundPage(page, 1100)
    await expectLabelOnOneLine(page, /^查询$/, 78)
    await expectLabelOnOneLine(page, /^重置$/, 76)
  })

  test('窄视口（1280×800）下四个按钮同样单行', async ({ page }) => {
    await openInboundPage(page, 1280)
    await expectLabelOnOneLine(page, /期初建账导入/, 130)
    await expectLabelOnOneLine(page, /新建入库单/, 118)
    await expectLabelOnOneLine(page, /^查询$/, 78)
    await expectLabelOnOneLine(page, /^重置$/, 76)
  })
})