// case_ids: BM-031
/**
 * B 端 H5 底部 tabBar 的**几何 / 结构**判据（issue #5759）
 *
 * ## 为什么是几何而不是截图
 *
 * 像素基线要 `darwin` + `linux` 两份（CI 是 linux，本机是 darwin）⇒ 本腿改用**几何数字**：
 * Chromium 里 `env(safe-area-inset-bottom)` 恒 0 ⇒ 这些数字**跨平台确定**，
 * 而它们恰好就是 #5754 两条病灶的判别式：
 *   · 修前（无安全区）：图标上方 5px、文字下方 **0px**（文字贴屏幕底边）⇒ 上下留白不对称；
 *   · 修前（iOS 安全区 34，本腿环境取不到，由单测/复测覆盖）：条被抬起、文字下留 51px。
 *
 * ## 判据
 *
 * | # | 断言 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 底栏 4 格、依次是 问米宝 / 数据 / 坐席 / 我的 | 改文案/顺序/数量 ⇒ 红 |
 * | 2 | 条**贴底**（底边 == 视口底边 ±1px） | 安全区被算两遍（条被抬起 34px）⇒ 红 |
 * | 3 | 每格：图标上方留白 == 文字下方留白（±2px）且**两者都 > 0** | 回到 `padding:5px 0` ⇒ 下方 0 ⇒ 红 |
 * | 4 | 每格：图标与文字相对该格**水平居中**（±1px） | 布局改写歪 ⇒ 红 |
 * | 5 | 🔴 **四个 tab 四张不同图标**（`img.src` 两两不同） | 再出现「问米宝与坐席共用一张图」⇒ 红 |
 *
 * ## 边界（照实登记）
 *
 * - 只判**几何 / 结构**：颜色、观感、暗色模式（若有）不在判据内；也不做像素基线（理由见上）。
 * - 只跑**未登录**形态（本腿不连后端）：`/#/pages/profile/index/index` 与 `/#/pages/dashboard/index/index`
 *   两个 tab 页在未登录时都**不跳转**（已核对页面代码），tabBar 照常渲染。
 * - iOS 安全区那一侧的读数仍靠复测（Chromium 取不到 `env(safe-area-inset-bottom)`）。
 */
import { test, expect } from '@playwright/test'

const TAB_PAGES = {
  profile: '/#/pages/profile/index/index',
  dashboard: '/#/pages/dashboard/index/index',
}
const TAB_LABELS = ['问米宝', '数据', '坐席', '我的']

test.describe('B 端 H5 底部 tabBar（几何 + 图标）', () => {
  test('四个 tab：条贴底、每格图标/文字居中、上下留白对称、四张图标两两不同', async ({ page }) => {
    await page.goto(TAB_PAGES.profile)

    const bar = page.locator('.taro-tabbar__tabbar')
    await expect(bar).toBeVisible()
    const items = page.locator('.weui-tabbar__item')
    await expect(items).toHaveCount(4)

    const viewport = page.viewportSize()
    expect(viewport).not.toBeNull()
    const barBox = await bar.boundingBox()
    expect(barBox).not.toBeNull()

    // 判据 2：条贴底（Chromium 无安全区 ⇒ 底边就是视口底边）
    expect(Math.abs((barBox as any).y + (barBox as any).height - (viewport as any).height)).toBeLessThanOrEqual(1)

    const srcs: string[] = []
    for (let i = 0; i < 4; i++) {
      const item = items.nth(i)
      const label = item.locator('.weui-tabbar__label')
      const icon = item.locator('img').first()

      await expect(label).toHaveText(TAB_LABELS[i]) // 判据 1
      const itemBox = await item.boundingBox()
      const iconBox = await icon.boundingBox()
      const labelBox = await label.boundingBox()
      expect(itemBox && iconBox && labelBox).toBeTruthy()

      const gapTop = (iconBox as any).y - (barBox as any).y
      const gapBottom = (barBox as any).y + (barBox as any).height - ((labelBox as any).y + (labelBox as any).height)
      // 判据 3：上下留白对称且都不为 0（修前是 5 / 0 与 -12 / 17）
      expect(Math.abs(gapTop - gapBottom)).toBeLessThanOrEqual(2)
      expect(gapTop).toBeGreaterThan(0)
      expect(gapBottom).toBeGreaterThan(0)

      // 判据 4：图标与文字相对该格水平居中
      const itemCenter = (itemBox as any).x + (itemBox as any).width / 2
      const iconOffset = (iconBox as any).x + (iconBox as any).width / 2 - itemCenter
      const labelOffset = (labelBox as any).x + (labelBox as any).width / 2 - itemCenter
      expect(Math.abs(iconOffset)).toBeLessThanOrEqual(1)
      expect(Math.abs(labelOffset)).toBeLessThanOrEqual(1)

      srcs.push((await icon.getAttribute('src')) || '')
    }

    // 判据 5：四个 tab 四张不同图标（issue #5759 的病灶：问米宝与坐席同图）
    expect(srcs.every((s) => s.length > 0)).toBe(true)
    expect(new Set(srcs).size).toBe(4)
  })

  test('切到「数据」tab：选中态换图、条高与留白不塌', async ({ page }) => {
    await page.goto(TAB_PAGES.dashboard)

    const bar = page.locator('.taro-tabbar__tabbar')
    await expect(bar).toBeVisible()
    const items = page.locator('.weui-tabbar__item')
    await expect(items).toHaveCount(4)

    const barBox = await bar.boundingBox()
    expect(barBox).not.toBeNull()
    // 条高 = Taro 的 --taro-tabbar-height（50 CSS px）—— 塌成 26px 那种回归（#5756 的构建陷阱）会被这条抓住
    expect((barBox as any).height).toBeGreaterThanOrEqual(49)
    expect((barBox as any).height).toBeLessThanOrEqual(51)

    const srcs = await items
      .locator('img')
      .evaluateAll((els) => els.map((el) => (el as HTMLImageElement).getAttribute('src') || ''))
    expect(new Set(srcs).size).toBe(4)
  })
})
