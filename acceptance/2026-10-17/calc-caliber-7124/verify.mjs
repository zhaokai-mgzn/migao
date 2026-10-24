// 多模态验收轮（issue #7124「算料口径 = 分组表单」）——
// 真栈（:3001 admin-web + :8080 admin-api）+ 真登录 + 1440×980 截图 + 几何读数。
//
// 判据（机器可读，见文末 RESULT）：
//   ① 每个字段**标签在控件上方**（bbox 不重叠）；
//   ② 字段**不再有行底细线**（`border-b`）；
//   ③ 同组标量输入框的**左边界只有两类**（两列栅格）——「参差」的机器读数。
import { createRequire } from 'node:module'
import { mkdirSync, writeFileSync } from 'node:fs'

const REPO_ROOT = '/Users/guangzhen.zk/ai native/migao'
const { chromium } = createRequire(`${REPO_ROOT}/tests/package.json`)('playwright')
const OUT = `${REPO_ROOT}/acceptance/2026-10-17/calc-caliber-7124`
mkdirSync(OUT, { recursive: true })
const BASE = 'http://localhost:3001'

const browser = await chromium.launch({ headless: true })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 980 } })
const page = await ctx.newPage()
page.on('console', (m) => {
  if (m.type() === 'error') console.log('[console.error]', m.text().slice(0, 160))
})

// ── 真登录（persona 手机号 + 万能码，同 scripts/ui_smoke_merchant.sh） ──
await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' })
const phone = page.locator('#phone')
if (!(await phone.isVisible().catch(() => false))) {
  await page.getByRole('tab', { name: /管理员|手机/ }).first().click()
  await page.waitForTimeout(400)
}
await page.fill('#phone', '13800138000')
await page.fill('#code', '123456')
await page.locator('button[type="submit"]:visible').last().click()
await page.waitForURL(/dashboard|\/settings|\/orders/, { timeout: 30000 }).catch(() => {})
await page.waitForTimeout(2500)
console.log('登录后 URL:', page.url())

// ── 算料口径域 ──
await page.goto(`${BASE}/settings?domain=calc`, { waitUntil: 'domcontentloaded' })
await page.waitForSelector('[data-testid="calc-caliber-panel"]', { timeout: 30000 })
await page.waitForTimeout(2500)
await page.screenshot({ path: `${OUT}/算料口径-首屏.png` })

// 静止首屏：保存出口**不吸底**（吸底就会盖内容 —— 独立复核第二轮实测；本轮改成「滚过首屏才吸」）
const restReadout = await page.evaluate(() => {
  const dock = document.querySelector('[data-testid="calc-caliber-save-dock"]')
  const btn = document.querySelector('[data-testid="calc-caliber-save"]')
  if (!dock || !btn) return null
  const d = dock.getBoundingClientRect()
  return {
    pinned: dock.className.includes('sticky'),
    scrollY: Math.round(window.scrollY),
    dockTop: Math.round(d.top),
    dockHeight: Math.round(d.height),
    viewportH: window.innerHeight,
    belowFold: d.top >= window.innerHeight,
    saveButtonBottom: Math.round(btn.getBoundingClientRect().bottom),
  }
})
console.log('静止首屏保存出口读数:', JSON.stringify(restReadout))

// 展开「高级」后再拍整页（两份形态都要看得到）
const adv = page.locator('[data-testid="param-advanced-toggle-calc"]')
if (await adv.count()) await adv.first().click()
await page.waitForTimeout(800)
await page.screenshot({ path: `${OUT}/算料口径-整页.png`, fullPage: true })

// 档位与拼色区块单独一张（看定宽列有没有被裁 / 行内间隙是否失控）
await page
  .locator('[data-testid="calc-caliber-group-rules"]')
  .first()
  .screenshot({ path: `${OUT}/档位与拼色.png` })

// 滚到「档位与拼色」再拍视口：保存条应 sticky 在底部（改完不用滚到底才够得着「保存」）
await page.locator('[data-testid="calc-caliber-group-rules"]').first().scrollIntoViewIfNeeded()
await page.waitForTimeout(600)
const stickyReadout = await page.evaluate(() => {
  const dock = document.querySelector('[data-testid="calc-caliber-save-dock"]')
  const btn = document.querySelector('[data-testid="calc-caliber-save"]')
  if (!dock || !btn) return null
  const r = btn.getBoundingClientRect()
  return {
    pinned: dock.className.includes('sticky'),
    scrollY: Math.round(window.scrollY),
    buttonTop: Math.round(r.top),
    buttonBottom: Math.round(r.bottom),
    viewportH: window.innerHeight,
    inViewport: r.top >= 0 && r.bottom <= window.innerHeight,
  }
})
await page.screenshot({ path: `${OUT}/保存条-sticky.png` })
console.log('保存条读数:', JSON.stringify(stickyReadout))

// ── 几何读数 ──
const geo = await page.evaluate(() => {
  const read = (el) => {
    if (!el) return null
    const r = el.getBoundingClientRect()
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height), bottom: Math.round(r.bottom), top: Math.round(r.top) }
  }
  const SCALAR = /^param-(per_fold_single|margin_single|margin_multi|hem_margin|oversize_width_threshold|oversize_height_threshold|min_fullness|meters_rounding_step)$/
  const fields = [...document.querySelectorAll('[data-testid^="param-"]')].filter((el) =>
    SCALAR.test(el.getAttribute('data-testid') || ''),
  )
  return {
    viewport: { w: window.innerWidth, h: window.innerHeight },
    fields: fields.map((f) => {
      const label = f.firstElementChild
      const input = f.querySelector('input, select')
      const lb = read(label)
      const ib = read(input)
      return {
        id: f.getAttribute('data-testid'),
        // 左栏 = 「标签 span + 提示 p」⇒ 标签文本只取**第一个子元素**（提示里本来就有括号，例如「（单开）」）
        labelText: (label?.firstElementChild?.textContent || '').trim(),
        label: lb,
        input: ib,
        // 🔴 issue #7133：属性行 —— 标签块在**左**、控件在**右列**（标签右沿不得压到控件左沿）
        labelLeftOfInput: lb && ib ? lb.x + lb.w <= ib.x + 1 : null,
        hasBottomBorder: /border-b/.test(f.className),
        // 🔴 本轮判据：单位**不再写在标签里**（`单色每折用料（米）` ⇒ `单色每折用料` + 框内后缀「米」）
        labelHasUnitParen: /（/.test((label?.firstElementChild?.textContent || '').trim()),
        unitInBox: [...f.querySelectorAll('span')].some(
          (s) => /absolute/.test(s.className) && (s.textContent || '').trim() === '米',
        ),
        groupSection: f.closest('section')?.getAttribute('data-testid') ?? null,
      }
    }),
    inputs: [...document.querySelectorAll('[data-testid^="calc-caliber-"]')]
      .filter((el) => el.tagName === 'INPUT' || el.tagName === 'SELECT')
      .map((el) => ({ id: el.getAttribute('data-testid'), ...read(el), cls: el.className })),
    sectionTitles: [...document.querySelectorAll('section h3')].map((h) => h.textContent?.trim()),
  }
})

// 同组标量输入框的左边界（只有一个 x ⇒ 一列对齐；两列栅格 ⇒ 恰好两个 x）
const scalarInputs = geo.inputs.filter((i) => /^calc-caliber-scalar-/.test(i.id))
const distinctX = [...new Set(scalarInputs.map((i) => i.x))].sort((a, b) => a - b)
// 属性行：控件的**右沿**也必须共一条线（主流设置页的「控件列」）
const distinctRight = [...new Set(scalarInputs.map((i) => i.x + i.w))].sort((a, b) => a - b)
// 有单位的键（`CALC_PARAM_COPY` 里带「（米）」的那些）；`min_fullness`（褶倍下限）**没有**单位
const UNIT_KEYS = /(per_fold_single|margin_single|margin_multi|hem_margin|oversize_|meters_rounding_step)/
const badFields = geo.fields.filter(
  (f) =>
    f.labelLeftOfInput !== true ||
    f.hasBottomBorder ||
    f.labelHasUnitParen ||
    (UNIT_KEYS.test(f.id) && !f.unitInBox),
)

writeFileSync(
  `${OUT}/geometry.json`,
  JSON.stringify({ ...geo, distinctScalarX: distinctX, distinctScalarRight: distinctRight }, null, 2),
)
console.log('区块标题:', JSON.stringify(geo.sectionTitles))
console.log(
  '字段读数:',
  JSON.stringify(
    geo.fields.map((f) => ({ id: f.id, labelAboveInput: f.labelAboveInput, borderB: f.hasBottomBorder, x: f.input?.x })),
    null,
    1,
  ),
)
console.log('RESULT', JSON.stringify({ fieldCount: geo.fields.length, bad: badFields.map((f) => f.id), distinctScalarX: distinctX, distinctScalarRight: distinctRight, restPinned: restReadout?.pinned, deepPinned: stickyReadout?.pinned, deepSaveInViewport: stickyReadout?.inViewport }))

await browser.close()
process.exit(
  badFields.length === 0 &&
    distinctX.length === 1 &&
    distinctRight.length === 1 &&
    restReadout?.pinned === false &&
    stickyReadout?.pinned === true &&
    stickyReadout?.inViewport === true
    ? 0
    : 1,
)
