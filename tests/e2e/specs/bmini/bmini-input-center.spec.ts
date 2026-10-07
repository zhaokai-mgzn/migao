// case_ids: BM-039
/**
 * B 端 H5 **输入框文字竖向居中**的**真几何**判据（issue #6478）
 *
 * ## 为什么必须是几何而不是字符串断言
 *
 * 缺陷本体是**布局**，不是样式文本：Taro h5 的 `<Input>` 渲染成两层 ——
 * 外层自定义元素 `taro-input-core`（拿 `className`，就是用户看到的圆角框）+
 * 内层原生 `<input class="weui-input">`（Taro 自带 `height:1.47059em`）。外层是 `display:block`
 * 且没有任何居中规则 ⇒ 内层行盒**贴在框顶**。
 * 「scss 里写了 `display:flex`」**不等于**「页面上真的居中了」（选择器被覆盖 / 被构建改写都会让文本断言照样绿）——
 * 所以本腿量的是**渲染出来的盒子**：
 *
 * | # | 断言 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 内层原生 `input` 高 ÷ 外框高 ≥ 0.90（撑满） | 回到 Taro 的 `height:1.47059em` ⇒ 比值 ≈ 0.52 ⇒ 红 |
 * | 2 | 内层相对外框的**上留白 == 下留白**（±1 CSS px） | 内层贴顶 ⇒ 0.5 vs 23.4（差 23）⇒ 红 |
 * | 3 | 上留白 > 0（内层**没有**贴死框顶） | 内层贴死 ⇒ 0 ⇒ 红 |
 * | 4 | 每个可见输入面都过 1~3（登录页三个 tab + 独立工人登录页 + 首登强制改密页） | 漏一个面 ⇒ 该面读数判红 |
 *
 * ## 实测读数（390×844，Chromium，本地 dist 重建实测；「修前」= 临时撤掉共享样式层的引入后重建）
 *
 * | 面 | 修前 内层/外框（占比） | 修前 上/下留白 | 修后 内层/外框（占比） | 修后 上/下留白 |
 * |---|---|---|---|---|
 * | 登录页 `.login-field__input`（7 个） | 26.0 / 49.906（52.1%） | 1.0 / 22.91 | 47.906 / 49.906（96.0%） | 1.0 / 1.0 |
 * | 工人登录页 `.worker-login__input`（3 个） | 22.94 / 47.75（48.0%） | 1.0 / 23.81 | 45.75 / 47.75（95.8%） | 1.0 / 1.0 |
 * | 首登强制改密页 `.cp-field__input`（3 个） | 24.47 / 47.75（51.2%） | 1.0 / 22.28 | 45.75 / 47.75（95.8%） | 1.0 / 1.0 |
 *
 * （上/下留白各 1 CSS px = 各页自己的 1px 边框 —— 内外层之间**没有**任何多余留白，文字在整框里居中。）
 *
 * ## 边界（照实登记，§19.1）
 * - 只判**竖向几何**：颜色 / 观感 / 暗色模式不在判据内，也不做像素基线（与 `bmini-tabbar.spec.ts` 同口径）。
 * - 覆盖「**有显式高度的圆角框**」这一族输入面里的 **3 个页面 / 13 个输入框**（登录页 7 + 工人登录页 3 +
 *   首登强制改密页 3）—— 它们是**未登录即可到达**的输入面，也是本缺陷的判别面。
 *   ⚠️ **未实测**的输入面（报工页 / 坐席会话详情 / 工人入库 / 工人补打 / WorkerBar / FormCard ——
 *   需要登录态或业务数据才能到达）**不在本腿**；它们靠**同一个全局选择器**（共享样式层作用于
 *   `taro-input-core`，与具体 className 无关）**构造性覆盖**，并由
 *   `frontend/bmini-app/tests/input-center-guard.test.ts` 的台账元守卫保证「新增输入面必须登记」。
 * - 输入框的**尺寸 / 圆角 / 字号**不在本判据内（不许把「修竖向对齐」做成「改尺寸」）：
 *   字号下限另有判据（`tests/unit_ci_workflows/test_bmini_mobile_typography_floor.py`、
 *   `tests/unit_ci_workflows/test_bmini_h5_delivery_contract.py`）。
 * - 🔴 本文件**不许出现弱断言**（QA Growth Gate 对新文件的弱断言判定是 fail-closed）：取不到就
 *   `must()` **抛**，不做「元素在不在」的期望式。
 */
import { test, expect, type Page } from '@playwright/test'

const LOGIN_PAGE = '/#/pages/auth/login/index'
const WORKER_LOGIN_PAGE = '/#/pages/worker/login/index'
const CHANGE_PASSWORD_PAGE = '/#/pages/auth/change-password/index'

/** 外框（拿到 `className` 的那层 = 用户看到的圆角框）÷ 内层原生 input 的最小高度比 */
const MIN_FILL_RATIO = 0.9
/** 上下留白允许的差（CSS px） */
const MAX_GAP_DELTA = 1

interface Reading {
  label: string
  outerHeight: number
  innerHeight: number
  gapTop: number
  gapBottom: number
}

/** 取不到就**抛**（不是弱断言）：后面的数值断言必须跑在真实取到的 box 上 */
function must<T>(value: T | null | undefined, what: string): T {
  if (value === null || value === undefined) {
    throw new Error(`拿不到 ${what} —— 页面白屏 / 输入框没渲染出来 / 结构变了？`)
  }
  return value
}

/** 量一个面里的全部输入框：外框 box 与内层原生 input box */
async function measureAll(page: Page, outerSelector: string, face: string): Promise<Reading[]> {
  const outers = page.locator(outerSelector)
  const count = await outers.count()
  const readings: Reading[] = []
  for (let i = 0; i < count; i++) {
    const outer = outers.nth(i)
    await expect(outer).toBeVisible()
    const outerBox = must(await outer.boundingBox(), `${face}[${i}] 的外框 box`)
    const innerBox = must(await outer.locator('input').first().boundingBox(), `${face}[${i}] 的内层 input box`)
    readings.push({
      label: `${face}[${i}]`,
      outerHeight: outerBox.height,
      innerHeight: innerBox.height,
      gapTop: innerBox.y - outerBox.y,
      gapBottom: outerBox.y + outerBox.height - (innerBox.y + innerBox.height),
    })
  }
  return readings
}

/** 判据 1~3：内层撑满外框 + 上下留白对称且都 > 0 */
function expectCentered(reading: Reading): void {
  const ratio = reading.innerHeight / reading.outerHeight
  expect(
    ratio,
    `${reading.label}：内层 input 只占外框的 ${(ratio * 100).toFixed(1)}%（内层 ${reading.innerHeight}px / 外框 ${reading.outerHeight}px）` +
      `—— 没撑满外框 ⇒ 文字贴顶`,
  ).toBeGreaterThanOrEqual(MIN_FILL_RATIO)

  const delta = Math.abs(reading.gapTop - reading.gapBottom)
  expect(
    delta,
    `${reading.label}：上下留白不对称（上 ${reading.gapTop.toFixed(1)}px / 下 ${reading.gapBottom.toFixed(1)}px，差 ${delta.toFixed(1)}px）`,
  ).toBeLessThanOrEqual(MAX_GAP_DELTA)

  expect(
    reading.gapTop,
    `${reading.label}：内层贴死框顶（上留白 ${reading.gapTop}px）`,
  ).toBeGreaterThan(0)
}

test.describe('B 端 H5 输入框文字竖向居中（issue #6478）', () => {
  test('登录页三个 tab（员工 / 管理员 / 工人）的每个输入框都撑满外框且上下留白对称', async ({ page }) => {
    await page.goto(LOGIN_PAGE)
    await expect(page.locator('.login-field__input').first()).toBeVisible()

    const all: Reading[] = []
    // 员工 tab（默认）：用户名@企业编码 / 密码
    const employee = await measureAll(page, '.login-field__input', '登录页·员工')
    expect(employee.length).toBeGreaterThanOrEqual(2)
    all.push(...employee)

    // 管理员 tab：手机号 / 短信验证码（验证码框是与按钮同行的那个）
    await page.locator('.login-tab').nth(1).click()
    await expect(page.locator('.login-field__input--code')).toBeVisible()
    const admin = await measureAll(page, '.login-field__input', '登录页·管理员')
    expect(admin.length).toBeGreaterThanOrEqual(2)
    all.push(...admin)

    // 工人 tab：工号 / PIN / 设备标签
    await page.locator('.login-tab').nth(2).click()
    const worker = await measureAll(page, '.login-field__input', '登录页·工人')
    expect(worker.length).toBeGreaterThanOrEqual(3)
    all.push(...worker)

    // 反空跑：三个 tab 合起来至少 7 个输入框（少一个说明 tab 没切过去 ⇒ 下面的绿没有意义）
    expect(all.length).toBeGreaterThanOrEqual(7)
    // 把读数打进日志（证据可复算：失败时也能看到是哪一面、差多少）
    console.log(`[input-center] 登录页读数 ${JSON.stringify(all)}`)

    for (const reading of all) expectCentered(reading)
  })

  test('独立工人登录页（另一个输入面）同样撑满外框且上下留白对称', async ({ page }) => {
    await page.goto(WORKER_LOGIN_PAGE)
    await expect(page.locator('.worker-login__input').first()).toBeVisible()

    const readings = await measureAll(page, '.worker-login__input', '工人登录页')
    // 工号 / PIN / 设备标签
    expect(readings.length).toBeGreaterThanOrEqual(3)
    console.log(`[input-center] 工人登录页读数 ${JSON.stringify(readings)}`)

    for (const reading of readings) expectCentered(reading)
  })

  test('首登强制改密页（第三个输入面）同样撑满外框且上下留白对称', async ({ page }) => {
    // 本页**无登录前提即可渲染**（它只在登录响应带 mustChangePassword 时被 redirectTo 过来，
    // 页面自身不做鉴权分流）⇒ 可以直接当第三个受测输入面。
    await page.goto(CHANGE_PASSWORD_PAGE)
    await expect(page.locator('.cp-field__input').first()).toBeVisible()

    const readings = await measureAll(page, '.cp-field__input', '改密页')
    // 原密码 / 新密码 / 确认新密码
    expect(readings.length).toBeGreaterThanOrEqual(3)
    console.log(`[input-center] 改密页读数 ${JSON.stringify(readings)}`)

    for (const reading of readings) expectCentered(reading)
  })
})
