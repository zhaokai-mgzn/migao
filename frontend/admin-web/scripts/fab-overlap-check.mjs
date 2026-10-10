#!/usr/bin/env node
/**
 * #6687 的**几何判据**：常驻面（右下角黄金策浮球）**不得与任何可点元素相交**。
 *
 * ## 为什么是一条可复用脚本，而不是一次性探针
 *
 * 「FAB 吃掉表格操作列」这一类的**共同形态**是：`fixed` + 高 z-index + 实体按钮，
 * 与满宽内容右边界必然相交 —— 单个页面修完，别的宽表页照旧复发。
 * ⇒ 判据收敛成一句话：**「FAB 矩形内不许有其它可点元素」**，对**任意页面**都能跑。
 *
 * ## 判据（几何，不靠肉眼）
 *
 * 1. 在页面里找到 FAB（`<button>`，computed `position:fixed` + `rounded-full` + 宽 ≥ 48）；
 * 2. 枚举页面里所有可点元素（`a` / `button` / `[role=button]` / `[onclick]` / `summary` / 表单控件），
 *    取**可见**（有盒、非 `visibility:hidden`、非 `display:none`）的人；
 * 3. 断言：**没有一个**可点元素的矩形与 FAB 矩形相交（FAB 自身与其子树除外）；
 * 4. 对相交者做 `document.elementFromPoint` **命中测试**（取重叠点）——
 *    命中落在 FAB 子树里 ⇒ **clickOwner = 浮球**（点击真被吃掉，不只是"看着重叠"）。
 *
 * ## 用法
 *
 * ```bash
 * node scripts/fab-overlap-check.mjs --site http://localhost:3001 --path /products
 * node scripts/fab-overlap-check.mjs --site http://localhost:3001 --path /orders --path /customers
 * # 只读探针：不改任何源码，注入一段 CSS 以对照「修前 / 修后」两种几何
 * node scripts/fab-overlap-check.mjs --path /products --inject-css 'main{padding-right:80px !important}'
 * ```
 *
 * 退出码（三态）：`0` = 全部页面零相交；`1` = 至少一页相交（逐条报出）；`3` = 无法判定
 * （登录失败 / 找不到 FAB / 页面没渲染出可点元素）—— **`3` 不得当 `0` 读**。
 *
 * ## 前置与边界（照实登记）
 *
 * - 需要**真登录**（手机号 `13800138000` / 验证码 `123456`，登录页有「管理员登录」页签）
 *   与一个**在跑的前端**（`--site`，默认 `http://localhost:3001`）；本脚本**只读**，不写库不改源码。
 * - `@playwright/test` 从**主仓** `tests/package.json` 解析（`createRequire`）—— 与其它探针同款。
 * - 判「相交」用的是**矩形**：圆形 FAB 的四个角是空区，矩形判定更严（角落相交也报）——
 *   这是**有意从严**：宁可报一个角，也不放过一次真遮挡。`--allow-corner-px N` 可放宽（默认 0）。
 * - **不判**「被 fixed 的其它常驻面」（弹窗 / toast / 侧边抽屉）：它们**本该**浮在内容上。
 *   本判据的对象只有 FAB 一个（其余常驻面的克制见 §31）。
 */
import { createRequire } from 'node:module'

const require = createRequire('/Users/guangzhen.zk/ai native/migao/tests/package.json')
const { chromium } = require('@playwright/test')

// ── 参数 ──
const argv = process.argv.slice(2)
const argOf = (name, dflt) => {
  const i = argv.indexOf(name)
  return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt
}
const allOf = (name) => argv.reduce((acc, a, i) => (a === name && argv[i + 1] ? [...acc, argv[i + 1]] : acc), [])
const SITE = argOf('--site', 'http://localhost:3001').replace(/\/$/, '')
const PATHS = allOf('--path').length ? allOf('--path') : ['/products']
const INJECT_CSS = argOf('--inject-css', '')
const ALLOW_CORNER_PX = Number(argOf('--allow-corner-px', '0'))
const VIEWPORT = { width: Number(argOf('--width', '1440')), height: Number(argOf('--height', '980')) }

/** 页面内取数：FAB 矩形 + 相交的可点元素 + 命中族谱 */
const PROBE = (allowCornerPx) => {
  const round = (n) => Math.round(n)
  const box = (el) => {
    const b = el.getBoundingClientRect()
    return { x: round(b.x), y: round(b.y), w: round(b.width), h: round(b.height), right: round(b.right), bottom: round(b.bottom) }
  }
  const overlaps = (a, b) =>
    a.right - allowCornerPx > b.x && a.x < b.right - allowCornerPx && a.bottom - allowCornerPx > b.y && a.y < b.bottom - allowCornerPx
  const visible = (el) => {
    const cs = getComputedStyle(el)
    if (cs.visibility === 'hidden' || cs.display === 'none' || Number(cs.opacity) === 0) return false
    const b = el.getBoundingClientRect()
    return b.width > 0 && b.height > 0
  }
  const desc = (el) =>
    el ? `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''} "${(el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 16)}"` : 'null'

  // ① FAB：fixed 的圆按钮（含 animate-ping 光晕的那个 span 的父级）
  const fab = [...document.querySelectorAll('button')].find((el) => {
    const cs = getComputedStyle(el)
    return cs.position === 'fixed' && /rounded-full/.test(String(el.className)) && el.getBoundingClientRect().width >= 48
  })
  if (!fab) return { error: '找不到浮球 FAB（选择器需更新）' }
  const fb = box(fab)

  // ② 可点元素（页面里算得上"能点"的那几族）
  const selector = 'a[href], button, [role="button"], [onclick], summary, input, select, textarea, [tabindex]:not([tabindex="-1"])'
  const clickables = [...document.querySelectorAll(selector)].filter(
    (el) => visible(el) && !fab.contains(el) && el !== fab,
  )

  // ③ 相交者 + 命中测试
  const violations = []
  for (const el of clickables) {
    const b = box(el)
    if (!overlaps(fb, b)) continue
    // 取重叠区域中心（+1 避开边界奇点）
    const mx = Math.max(b.x, fb.x) + Math.max(1, Math.floor((Math.min(b.right, fb.right) - Math.max(b.x, fb.x)) / 2))
    const my = Math.max(b.y, fb.y) + Math.max(1, Math.floor((Math.min(b.bottom, fb.bottom) - Math.max(b.y, fb.y)) / 2))
    const hit = document.elementFromPoint(mx, my)
    violations.push({
      element: desc(el),
      box: b,
      overlapPoint: { x: mx, y: my },
      hitAtOverlap: desc(hit),
      clickOwner: fab.contains(hit) ? '浮球（黄金策）' : el.contains(hit) ? '该元素自身' : '其他元素',
      eatenByFab: !!(hit && fab.contains(hit)),
    })
  }

  // ④ FAB 矩形内**任意一点**的命中元素都必须 ∈ FAB 子树（判据的第二种表述）
  const points = []
  for (let dx = 4; dx < fb.w; dx += 16) for (let dy = 4; dy < fb.h; dy += 16) points.push([fb.x + dx, fb.y + dy])
  const foreignHits = points.filter(([x, y]) => {
    const hit = document.elementFromPoint(x, y)
    return !!hit && !fab.contains(hit)
  })

  return {
    fab: { box: fb, tag: fab.tagName.toLowerCase(), cls: String(fab.className).slice(0, 120) },
    clickablesOnPage: clickables.length,
    violations,
    verdict: violations.length === 0 && foreignHits.length === 0 ? 'PASS' : 'FAIL',
    foreignHitCount: foreignHits.length,
  }
}

// ── 登录（形态锚点：管理员登录页签 + 手机号 + 获取验证码 + 123456）──
async function login(page) {
  await page.goto(`${SITE}/login`, { waitUntil: 'domcontentloaded' })
  const adminTab = page.getByText('管理员登录', { exact: false }).first()
  if (await adminTab.count()) await adminTab.click()
  await page.locator('input[placeholder*="手机号"]').first().fill('13800138000')
  await page.getByText('获取验证码', { exact: false }).first().click()
  await page.locator('input[placeholder*="验证码"]').first().fill('123456')
  await page.getByRole('button', { name: /登\s*录/ }).first().click()
  await page.waitForURL(/dashboard|products|orders/, { timeout: 30000 })
}

const browser = await chromium.launch({ channel: 'chrome' })
const ctx = await browser.newContext({ viewport: VIEWPORT })
const page = await ctx.newPage()
let exitCode = 0
const report = { site: SITE, viewport: VIEWPORT, injectedCss: INJECT_CSS || null, pages: {} }

try {
  await login(page)
  for (const p of PATHS) {
    await page.goto(SITE + p, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle').catch(() => {})
    await page.waitForTimeout(1200)
    if (INJECT_CSS) {
      await page.addStyleTag({ content: INJECT_CSS })
      await page.waitForTimeout(300)
    }
    const res = await page.evaluate(PROBE, ALLOW_CORNER_PX)
    report.pages[p] = res
    if (res.error) {
      exitCode = 3
    } else if (res.verdict !== 'PASS') {
      exitCode = exitCode === 3 ? 3 : 1
    }
  }
} catch (e) {
  report.error = String(e && e.message ? e.message : e)
  exitCode = 3
} finally {
  await browser.close()
}

console.log(JSON.stringify(report, null, 2))
process.exit(exitCode)
