// 算料口径「3 位小数 + 允许设 0」的视觉 / 行为验收（issue #7548）。
//
// 用法（在 `frontend/admin-web` 先 `npm run build`）：
//   1) `npx next start -p 3127`
//   2) `npm --prefix /tmp i playwright && npx playwright install chromium`（仅首次）
//   3) `node scripts/visual-check/settings-calc-caliber-decimals.mjs`（在**仓库根**跑）
// 产物：
//   /tmp/calc-caliber-decimals.png   填了 `0.125`（3 位小数）与 `0`（余量）之后的整页
//   /tmp/calc-caliber-zero.png       余量为 0 时保存态那一段（已保存 / 失败理由）
//
// 为什么要有它：本单改的是**输入框的精度与 0 值**，单测在 jsdom 里断言的是 DOM 值；
// 真浏览器还多一层 —— `inputMode="decimal"` 的框在失焦归一化后**屏幕上到底显示什么**、
// 同屏 16 个框是不是同一套精度、0 有没有被当成「空」抹掉。只读、mock 全部 API。
import { chromium } from 'playwright'

const BASE = process.env.VISUAL_BASE || 'http://127.0.0.1:3127'

/** 读面替身：值里**故意带 3 位小数**（读面能存 3 位、前端以前只收 2 位 = 本单的靶心） */
const CONFIG = {
  per_fold_single: 0.255,
  per_fold_mixed_times: { 1: 0.655, 2: 1.2 },
  margin_single: 0.2,
  margin_multi: 0.3,
  min_fullness: 1.5,
  tiers: {
    standard: { fullness: 2, label: '标准工艺' },
    economy: { fullness: 1.8, label: '经济工艺' },
  },
  default_formula: 'pleat',
  hem_margin: 0.305,
  meters_rounding_step: 0.1,
  oversize_width_threshold: 6,
  oversize_height_threshold: 4,
}

const json = (data) => ({ status: 200, contentType: 'application/json', body: JSON.stringify(data) })
const ok = (data) => json({ success: true, data })

const browser = await chromium.launch()
const ctx = await browser.newContext({ viewport: { width: 1440, height: 980 }, deviceScaleFactor: 1 })
const page = await ctx.newPage()

/** 记下每一次 PUT 的正文（判「0 真的发出去了」） */
const puts = []
page.on('console', (m) => {
  if (m.type() === 'error') console.log('[console]', m.text().slice(0, 200))
})

// ⚠️ Playwright：**先注册的通配优先**（后注册的具体路由覆盖它）⇒ 通配必须第一个注册
await page.route('**/api/**', (r) => r.fulfill(ok([])))
await page.route('**/api/auth/refresh', (r) => r.fulfill(ok({ accessToken: 't', expiresIn: 3600 })))
await page.route('**/api/auth/me', (r) =>
  r.fulfill(
    ok({
      id: 'u1',
      username: 'admin',
      name: '管理员',
      tenantId: 1,
      roles: ['admin'],
      permissions: ['*'],
      menus: [],
    }),
  ),
)
// ⚠️ 这两条用**正则**而不是 glob：读面带查询串（`?with_defaults=true`），
//    glob 是按整串 URL 匹配的 ⇒ `**/…/craft-calc-config` 匹配不上带 `?` 的形态（实测踩过）。
await page.route(/\/api\/admin\/production\/craft-calc-config/, async (r) => {
  if (r.request().method() === 'PUT') {
    const body = JSON.parse(r.request().postData() || '{}')
    puts.push(body)
    return r.fulfill(ok({ source: 'stored', config: body }))
  }
  return r.fulfill(ok({ source: 'stored', config: CONFIG }))
})
// 阈值试算（页面同屏）——给一份合法形状，免得它报「试算失败」把注意力引开
await page.route(/\/api\/admin\/orders\/auto-features/, (r) =>
  r.fulfill(ok({ auto_features: [], reasons: [] })),
)

await page.goto(`${BASE}/settings?domain=calc`, { waitUntil: 'domcontentloaded' })
await page
  .waitForSelector('[data-testid="calc-caliber-panel"]', { timeout: 45000 })
  .catch(() => console.log('!! 算料口径面板没渲染出来'))
// 「高级」默认收起（进位步长在那一组里）⇒ 先展开，否则取不到那个框
await page.locator('[data-testid="param-advanced-toggle-calc"]').click().catch(() => {})
await page.waitForTimeout(200)

/** 填一个数字框再点别处失焦（真浏览器里失焦触发的是 `NumberInput` 的归一化） */
async function typeAndBlur(testid, value) {
  const el = page.locator(`[data-testid="${testid}"]`)
  await el.fill(value)
  await page.locator('[data-testid="calc-caliber-panel"] h3').first().click({ trial: true }).catch(() => {})
  await el.evaluate((n) => n.blur())
  await page.waitForTimeout(120)
  return el.inputValue()
}

const readings = {}
readings.per_fold_single_before = await page.locator('[data-testid="calc-caliber-scalar-per_fold_single"]').inputValue()
readings.per_fold_single_0_125 = await typeAndBlur('calc-caliber-scalar-per_fold_single', '0.125')
readings.tier_fullness_0_125 = await typeAndBlur('calc-caliber-tier-standard-fullness', '0.125')
readings.mixed_1_0_125 = await typeAndBlur('calc-caliber-mixed-1', '0.125')
readings.margin_single_0 = await typeAndBlur('calc-caliber-scalar-margin_single', '0')
readings.hem_margin_0 = await typeAndBlur('calc-caliber-scalar-hem_margin', '0')
readings.rounding_step_0 = await typeAndBlur('calc-caliber-scalar-meters_rounding_step', '0')
readings.preview_threshold_width_0_125 = await typeAndBlur('preview-threshold-width', '0.125')

// 等防抖（0.6s）把最后一次变更发出去
await page.waitForTimeout(1200)

await page.screenshot({ path: '/tmp/calc-caliber-decimals.png', fullPage: true })
console.log('shot /tmp/calc-caliber-decimals.png')

const saveState = await page.locator('[data-testid="calc-caliber-save-state"]').textContent().catch(() => '')
console.log('保存态：', saveState)

console.log('读数：', JSON.stringify(readings, null, 2))
const lastPut = puts[puts.length - 1] || {}
console.log('最后一次 PUT 的 0 值键：', {
  margin_single: lastPut.margin_single,
  hem_margin: lastPut.hem_margin,
  meters_rounding_step: lastPut.meters_rounding_step,
})

/** 机械断言（读图是另一半）；失败非零退出 ⇒ 本脚本可当本地判据用 */
const failures = []
if (readings.per_fold_single_0_125 !== '0.125') failures.push(`标量 3 位小数：${readings.per_fold_single_0_125}`)
if (readings.tier_fullness_0_125 !== '0.125') failures.push(`档位褶倍 3 位小数：${readings.tier_fullness_0_125}`)
if (readings.mixed_1_0_125 !== '0.125') failures.push(`拼色每折 3 位小数：${readings.mixed_1_0_125}`)
if (readings.preview_threshold_width_0_125 !== '0.125') failures.push(`试算阈值 3 位小数：${readings.preview_threshold_width_0_125}`)
if (readings.margin_single_0 !== '0') failures.push(`余量设 0：${readings.margin_single_0}`)
if (readings.hem_margin_0 !== '0') failures.push(`卷边设 0：${readings.hem_margin_0}`)
if (readings.rounding_step_0 !== '0') failures.push(`进位步长设 0：${readings.rounding_step_0}`)
if (lastPut.margin_single !== 0) failures.push(`PUT 正文 margin_single 不是 0：${lastPut.margin_single}`)
if (lastPut.meters_rounding_step !== 0) failures.push(`PUT 正文 meters_rounding_step 不是 0：${lastPut.meters_rounding_step}`)

await browser.close()

if (failures.length > 0) {
  console.error('❌ 视觉/行为验收失败：')
  for (const f of failures) console.error('   -', f)
  process.exit(1)
}
console.log('✅ 真浏览器读数全部符合预期（3 位小数 + 0）；截图见 /tmp/calc-caliber-decimals.png')
