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

// 静止首屏：常驻保存出口（右下角小条）**盖住了什么内容**（4px 采样；只算「内容元素」，不算容器 div）
const dockCover = await page.evaluate(() => {
  const btn = document.querySelector('[data-testid="calc-caliber-save"]')
  const dock = btn ? btn.closest('div.backdrop-blur-sm') : null
  if (!dock) return null
  const r = dock.getBoundingClientRect()
  // 先「摘掉」吸底条再量它盖住了什么（visibility:hidden 去掉命中测试、保留布局）
  const prev = dock.style.visibility
  dock.style.visibility = 'hidden'
  // 吸底条**自己那一族**（sticky 容器 + 内层 flex + 按钮）不算「被盖住的内容」
  const bar = dock.closest('div.sticky') || dock
  const cached = new Map()
  const textRectsOf = (el) => {
    if (cached.has(el)) return cached.get(el)
    const out = []
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
    let node
    while ((node = walker.nextNode())) {
      if (!(node.textContent || '').trim()) continue
      // 吸底条自己的文本、以及 visibility:hidden 的文本都**不算被盖住的内容**
      if (bar.contains(node.parentElement) || getComputedStyle(node.parentElement).visibility === 'hidden') continue
      const range = document.createRange()
      range.selectNodeContents(node)
      for (const rr of range.getClientRects()) out.push(rr)
    }
    cached.set(el, out)
    return out
  }
  let samples = 0
  let hits = 0
  const under = new Map()
  for (let y = Math.ceil(r.top); y < r.bottom; y += 4) {
    for (let x = Math.ceil(r.left); x < r.right; x += 4) {
      samples += 1
      const hit = document
        .elementsFromPoint(x, y)
        .find(
          (el) =>
            !bar.contains(el) &&
            textRectsOf(el).some((rr) => x >= rr.left && x <= rr.right && y >= rr.top && y <= rr.bottom),
        )
      if (hit) {
        hits += 1
        const key =
          hit.getAttribute('data-testid') || `${hit.tagName}:${(hit.textContent || '').trim().slice(0, 12)}`
        under.set(key, (under.get(key) || 0) + 1)
      }
    }
  }
  dock.style.visibility = prev
  return {
    dock: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
    dockBottom: Math.round(r.bottom),
    viewportH: window.innerHeight,
    samples,
    contentHits: hits,
    ratio: samples ? +(hits / samples).toFixed(3) : null,
    under: [...under.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5),
  }
})
console.log('静止首屏遮挡读数:', JSON.stringify(dockCover))

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
  const btn = document.querySelector('[data-testid="calc-caliber-save"]')
  if (!btn) return null
  const bar = btn.closest('div.sticky')
  const r = btn.getBoundingClientRect()
  return {
    position: bar ? getComputedStyle(bar).position : null,
    buttonBottom: Math.round(r.bottom),
    viewportH: window.innerHeight,
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
        labelText: (label?.textContent || '').trim(),
        label: lb,
        input: ib,
        labelAboveInput: lb && ib ? lb.bottom <= ib.top : null,
        hasBottomBorder: /border-b/.test(f.className),
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
const badFields = geo.fields.filter((f) => f.labelAboveInput !== true || f.hasBottomBorder)

writeFileSync(`${OUT}/geometry.json`, JSON.stringify({ ...geo, distinctScalarX: distinctX }, null, 2))
console.log('区块标题:', JSON.stringify(geo.sectionTitles))
console.log(
  '字段读数:',
  JSON.stringify(
    geo.fields.map((f) => ({ id: f.id, labelAboveInput: f.labelAboveInput, borderB: f.hasBottomBorder, x: f.input?.x })),
    null,
    1,
  ),
)
console.log('RESULT', JSON.stringify({ fieldCount: geo.fields.length, bad: badFields.map((f) => f.id), distinctScalarX: distinctX }))

await browser.close()
process.exit(badFields.length === 0 && distinctX.length === 2 ? 0 : 1)
