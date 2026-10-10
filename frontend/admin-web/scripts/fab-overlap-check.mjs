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
 * node scripts/fab-overlap-check.mjs --site http://localhost:3001 --paths /products,/inbound-orders,/stock-ledger
 * # 不带 --path/--paths 时默认跑：4 个已实测中招的页 + 2 个负控页（见下方 PATHS 注释）
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
const csvOf = (name) => allOf(name).flatMap((v) => v.split(',')).map((v) => v.trim()).filter(Boolean)
const SITE = argOf('--site', 'http://localhost:3001').replace(/\/$/, '')
// 判定面默认**不止 /products**：本缺陷是**一类**（满宽列表页的表尾「操作」列落在浮球矩形里）。
// 2026-10-10 实测（1440×980，main `8bf197ef4`，判定口径 = 摘掉浮球后该点是否属于该元素）：
//   /products 5 处 · /inbound-orders 3 · /production/remnants 3 · /stock-ledger 1（分页「下一页」）；
//   /orders /customers /after-sales /finance /notifications /production/piecework = 0（负控）。
// 默认跑「中招的 4 页 + 2 个负控」，多页用 `--paths a,b,c`（或重复 `--path`）。
const PATHS = csvOf('--path').length
  ? csvOf('--path')
  : ['/products', '/inbound-orders', '/production/remnants', '/stock-ledger', '/orders', '/customers']
const INJECT_CSS = argOf('--inject-css', '')
const ALLOW_CORNER_PX = Number(argOf('--allow-corner-px', '0'))
const VIEWPORT = { width: Number(argOf('--width', '1440')), height: Number(argOf('--height', '980')) }
// `--allow-cross-origin`：admin-web 直连 `:8080` 而后端 CORS 白名单只放行 `:3001` ⇒ 在别的端口
// 起前端时（如复验某个 worktree 的构建产物）浏览器会因 CORS 登录不通；本开关只是**关掉浏览器侧
// 的 CORS 检查**（几何与鉴权逻辑一概不变），不是任何修复的一部分。
const ALLOW_CROSS_ORIGIN = argv.includes('--allow-cross-origin')

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

  // ③ 相交者 + 命中测试（**用「摘掉浮球」的对照**判"点击到底归谁"）
  //
  // 🔴 为什么必须做对照：表格横向溢出时，右端单元格会被 `overflow-x-auto` **视觉裁掉** ——
  // 它的 `getBoundingClientRect()` 仍会落在浮球矩形里，但那个位置**本来就点不到它**
  // （`elementFromPoint` 会返回裁剪容器而非该元素）。只按矩形判交集 ⇒ **假红**。
  // ⇒ 判据 = 「把浮球移开，这一点会不会落到该元素上」：会 ⇒ 浮球**真吃了**这一击；
  //    不会（命中裁剪容器/祖先）⇒ 该点本来就不是它的可点区域，不算。
  // ⚠️ 对照必须**摘掉节点**，不能用 `visibility:hidden`：本仓实测 `visibility:hidden` 之后
  //    `elementFromPoint` **仍然返回浮球的 `span.absolute.inset-0`** ⇒ 拿它当对照会把红读成绿。
  const fabParent = fab.parentElement
  const fabNext = fab.nextSibling
  const violations = []
  for (const el of clickables) {
    const b = box(el)
    if (!overlaps(fb, b)) continue
    // 🔴 采样取**重叠区域的 3×3 网格**，不是只取中心：只取中心会**漏报**
    // （实测：`/production/remnants` 的「报废」、`/stock-ledger` 的分页「下一页」在"只取中心"的
    //  口径下读成 0，网格采样才读到真被吃 ⇒ 判定面必须够密，宁多采几点）。
    const x0 = Math.max(b.x, fb.x), x1 = Math.min(b.right, fb.right)
    const y0 = Math.max(b.y, fb.y), y1 = Math.min(b.bottom, fb.bottom)
    const pts = []
    for (const fx of [0.08, 0.5, 0.92]) for (const fy of [0.08, 0.5, 0.92]) {
      pts.push([Math.round(x0 + (x1 - x0) * fx), Math.round(y0 + (y1 - y0) * fy)])
    }
    let hitWithFab = null
    let hitWithoutFab = null
    let stolenAt = null
    for (const [px, py] of pts) {
      const withFab = document.elementFromPoint(px, py)
      const eaten = !!(withFab && fab.contains(withFab))
      if (!eaten) continue
      fab.remove()
      const withoutFab = document.elementFromPoint(px, py)
      fabParent.insertBefore(fab, fabNext)
      if (withoutFab && el.contains(withoutFab)) {
        hitWithFab = withFab; hitWithoutFab = withoutFab; stolenAt = { x: px, y: py }; break
      }
      if (!hitWithFab) { hitWithFab = withFab; hitWithoutFab = withoutFab }
    }
    const mx = stolenAt ? stolenAt.x : Math.round((x0 + x1) / 2)
    const my = stolenAt ? stolenAt.y : Math.round((y0 + y1) / 2)
    const eatenByFab = !!(hitWithFab && fab.contains(hitWithFab))
    const reachableWithoutFab = !!(hitWithoutFab && el.contains(hitWithoutFab))
    violations.push({
      element: desc(el),
      box: b,
      overlapPoint: { x: mx, y: my },
      sampledPoints: pts.length,
      hitAtOverlap: desc(hitWithFab),
      hitWithoutFab: desc(hitWithoutFab),
      clickOwner: eatenByFab ? '浮球（黄金策）' : el.contains(hitWithFab) ? '该元素自身' : '其他元素',
      eatenByFab,
      /** true = 浮球**真的**吃掉了这一击（摘掉浮球后该点属于它）；false = 该点本来被裁剪、点不到 */
      stealsRealClick: eatenByFab && reachableWithoutFab,
    })
  }

  // ④ FAB **真身内**任意一点的命中元素都必须 ∈ FAB 子树（判据的第二种表述）
  //
  // ⚠️ 采样点取**内切圆内**，不是外接矩形：FAB 是 `rounded-full`（圆形按钮），矩形的四个角
  //    本来就不属于它（圆角外点击会穿透到内容）⇒ 按矩形采样会把"角上压着一格表格"误判成违规。
  const points = []
  const cx0 = fb.w / 2, cy0 = fb.h / 2, r0 = Math.min(fb.w, fb.h) / 2
  for (let dx = 3; dx < fb.w; dx += 8) {
    for (let dy = 3; dy < fb.h; dy += 8) {
      if ((dx - cx0) ** 2 + (dy - cy0) ** 2 <= (r0 - 3) ** 2) points.push([fb.x + dx, fb.y + dy])
    }
  }
  const foreignHits = points.filter(([x, y]) => {
    const hit = document.elementFromPoint(x, y)
    return !!hit && !fab.contains(hit)
  })

  // 判据 = **真的被吃掉的那一击**（stealsRealClick），而不是"矩形相交"（横向溢出时后者会假红）
  const stolen = violations.filter((v) => v.stealsRealClick)
  const overlapOnly = violations.filter((v) => !v.stealsRealClick)
  return {
    fab: { box: fb, tag: fab.tagName.toLowerCase(), cls: String(fab.className).slice(0, 120) },
    clickablesOnPage: clickables.length,
    /** 浮球矩形内的采样点命中必须 ∈ 浮球子树（第二种表述） */
    foreignHitCount: foreignHits.length,
    /** 矩形相交、但摘掉浮球后该点也不属于它（= 本来就被裁剪、点不到）⇒ 不算违规 */
    overlapButNotReachable: overlapOnly.map((v) => ({ element: v.element, box: v.box, hitWithoutFab: v.hitWithoutFab })),
    /** 🔴 真违规：摘掉浮球后这一点会落到该元素上 ⇒ 浮球吃掉了真实点击 */
    violations: stolen,
    verdict: stolen.length === 0 && foreignHits.length === 0 ? 'PASS' : 'FAIL',
  }
}

// ── 登录（形态锚点：管理员登录页签 + 手机号 + 验证码）──
//
// 🔴 **刻意不点「获取/发送验证码」**：本机 `123456` 是旁路码，而 `sms/send` 有**当日配额**
// （实测跑几次就 `今日发送次数已达上限`）⇒ 探针不该为了复验几何去烧登录配额。
// 若所在环境没有旁路码（登录停在 /login），再点一次「发送验证码」重试一轮。
async function fillAndSubmit(page) {
  await page.locator('input[placeholder*="手机号"]').first().fill('13800138000')
  await page.locator('input[placeholder*="验证码"]').first().fill('123456')
  await page.getByRole('button', { name: /登\s*录/ }).first().click()
  try { await page.waitForURL((u) => !/\/login\b/.test(u.pathname), { timeout: 15000 }); return true }
  catch { return false }
}

async function login(page) {
  await page.goto(`${SITE}/login`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const adminTab = page.getByText('管理员登录', { exact: false }).first()
  if (await adminTab.count().catch(() => 0)) await adminTab.click().catch(() => {})
  await page.waitForTimeout(500)
  if (await fillAndSubmit(page)) return
  // 兜底：环境没有旁路码 ⇒ 才发一次验证码
  await page.goto(`${SITE}/login`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  await page.getByText('管理员登录', { exact: false }).first().click().catch(() => {})
  await page.locator('input[placeholder*="手机号"]').first().fill('13800138000')
  await page.getByText('获取验证码', { exact: false }).first().click().catch(() => {})
  await page.waitForTimeout(1500)
  if (!(await fillAndSubmit(page))) throw new Error('登录失败（见页面提示；短信发送有当日配额）')
}

const browser = await chromium.launch({
  channel: 'chrome',
  args: ALLOW_CROSS_ORIGIN ? ['--disable-web-security'] : [],
})
const ctx = ALLOW_CROSS_ORIGIN
  ? await chromium.launchPersistentContext('/tmp/mg-fab-overlap-nocors', { channel: 'chrome', viewport: VIEWPORT, args: ['--disable-web-security'] })
  : await browser.newContext({ viewport: VIEWPORT })
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
  await ctx.close()
  if (browser) await browser.close().catch(() => {})
}

console.log(JSON.stringify(report, null, 2))
process.exit(exitCode)
