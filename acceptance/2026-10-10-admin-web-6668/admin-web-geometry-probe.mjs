/**
 * admin-web 设计基线**几何探针**（issue #6668 盲区③）—— 商家后台页面的浏览器几何读数。
 *
 * 目的：把「条高 / 被常驻面遮住 / 触达区太小 / 首屏被常驻面占掉」四条**肉眼才看得见**的形态
 * 变成**机器读数**（同族先例 = `acceptance/2026-10-09-bmini-three-fixes/bmini-geometry-probe.mjs`）。
 *
 * ## 怎么跑（复算入口；判据文件会核这几个串）
 *
 * ```bash
 * cd frontend/admin-web && npm run build
 * cd ../../tests && npm ci && npx playwright install chromium   # 首次
 * node ../../acceptance/2026-10-10-admin-web-6668/admin-web-geometry-probe.mjs http://localhost:3001
 * ```
 * 输出：stdout 一行 JSON（机器读数）+ `out/*.png` 截图 + `out/report.json`。
 *
 * ⚠️ **本包没有跑真浏览器**（本机没起 3001，也不在开发包预算内）⇒ 探针是**可复算入口**，
 * 不是"已验过"的证据。读数必须由人 / 验收会话真跑一次才能当结论（登记在 README 的未跑项）。
 *
 * ## 量什么（每一项都对应设计基线的一条口径）
 *
 * | 读数 | 口径（`docs/design/design-baseline.md` §几何） |
 * |---|---|
 * | `tapTargets` | 所有 `button / a[href] / [role=button] / input / select` 的 `rect` ⇒ 宽高 ≥ 40 CSS px（主内容区） |
 * | `barHeights` | `header / nav / [data-testid$=-bar]` 的 `rect.height` ⇒ 常驻条不得吞掉首屏 |
 * | `occlusion` | 每页**最靠下的叶子文本 bottom** vs 各常驻面 top ⇒ `> 0` 即被压住 |
 * | `firstScreen` | 常驻面（sticky/fixed 顶栏 + 底栏 + 告警条）在 1440×980 上占的**垂直比** ⇒ ≤ 40% |
 *
 * 判据文件（`frontend/admin-web/tests/unit/design-baseline-geometry.test.ts`）守的是
 * **这套读数的可复算入口 + 四个判据函数的判别力**（真几何只能在真浏览器里取）。
 */
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'

/**
 * 设计基线的几何阈值（与 `docs/design/design-baseline.md` §几何 的表格逐字同源）。
 *
 * ⚠️ **门面不同，下限不同**（判别力自证里两边都钉住）：
 * - **触屏门面**（`worker-h5` 现场端 / 两个 Taro app）：**40**（Apple HIG 44 / Material 48 的下沿）；
 * - **桌面商家后台**（本探针的射程，1440×980 鼠标 + 键盘）：**36** —— 与 `Button` / `Input` 的
 *   `h-9`（36px）逐字一致。写 40 会把**整站既有主控件**判红（那是假红，不是缺陷）。
 */
export const GEOMETRY_LIMITS = {
  /** 桌面后台**主控件**高度下限（CSS px）—— 实测基线 = `h-9` = 36 */
  minControlHeight: 36,
  /** 触屏门面（worker-h5 / Taro）的触达区下限（CSS px）—— **不是**本探针的射程，登记备查 */
  minTapTarget: 40,
  /** 单条常驻面高度上限（CSS px）—— 超过就是"横幅式告警"，违反 §31 P1 的常驻面克制 */
  maxBarHeight: 96,
  /** 首屏被常驻面占掉的垂直比上限（1440×980） */
  maxFirstScreenShare: 0.4,
  /** 遮挡容差（CSS px）：叶子文本底边 − 常驻面顶边，> 此值才算被压住 */
  occlusionTolerance: 0.5,
}

/** 视口（与 `migao-dev-flow` §15.7 的读图口径一致：桌面 1440×980） */
export const VIEWPORT = { width: 1440, height: 980 }

/** 走一遍的页面（商家后台第一屏的三个代表面：看板 / 列表 / 生产池） */
export const ROUTES = ['/dashboard', '/orders', '/production/pool']

/**
 * 触达区判据的射程：**只判主控件**（`button` / `[role=button]`）。
 * **有意不判** `<a href>`：后台的文本链接天然是行高（如「查看」14px 文字），
 * 判它只会造一堆假红 —— 而真正的触屏触达面在 worker-h5 / Taro，那两个门面另有判据。
 */
export const TAP_TARGET_SELECTOR = 'button, [role="button"]'

/** 常驻面选择器（顶栏 / 底栏 / 告警条 / 吸底汇总条） */
export const PERSISTENT_FACE_SELECTOR =
  'header, nav, [data-testid$="-bar"], [data-testid$="-warnings"], [class*="sticky"]'

// ───────────────────────── 纯判据（可内存注入取证，不需要浏览器） ─────────────────────────

/**
 * @typedef {object} Rect
 * @property {number} width
 * @property {number} height
 * @property {number} top
 * @property {number} bottom
 */

/** 判据①：主控件高度是否达标（桌面 36；触屏门面另有 40 的口径，见 GEOMETRY_LIMITS） */
export function checkTapTarget(rect, min = GEOMETRY_LIMITS.minControlHeight) {
  return rect.height >= min
}

/** 判据②：常驻面是否过高 */
export function checkBarHeight(rect, max = GEOMETRY_LIMITS.maxBarHeight) {
  return rect.height <= max
}

/** 判据③：内容是否被常驻面压住（叶子文本底边 − 常驻面顶边 > 容差） */
export function occludedPx(leafBottom, faceTop) {
  return +(leafBottom - faceTop).toFixed(1)
}
export function checkOcclusion(leafBottom, faceTop, tol = GEOMETRY_LIMITS.occlusionTolerance) {
  return occludedPx(leafBottom, faceTop) > tol
}

/** 判据④：首屏被常驻面占掉的垂直比 */
export function firstScreenShare(faceHeights, viewportHeight = VIEWPORT.height) {
  const sum = faceHeights.reduce((a, b) => a + b, 0)
  return +(sum / viewportHeight).toFixed(4)
}
export function checkFirstScreen(faceHeights, max = GEOMETRY_LIMITS.maxFirstScreenShare) {
  return firstScreenShare(faceHeights) <= max
}

// ───────────────────────── 真浏览器部分 ─────────────────────────

/** 从 `tests/node_modules` 解析 playwright（admin-web 自己不装浏览器驱动） */
async function loadChromium() {
  const candidates = [
    process.env.MIGAO_PLAYWRIGHT,
    '/Users/guangzhen.zk/ai native/migao/tests/node_modules/playwright/index.mjs',
  ].filter(Boolean)
  for (const c of candidates) {
    if (fs.existsSync(c)) return (await import(c)).chromium
  }
  const require_ = createRequire(import.meta.url)
  try {
    return require_('playwright').chromium
  } catch {
    throw new Error('找不到 playwright —— 先 `cd tests && npm ci`，或用 MIGAO_PLAYWRIGHT=<path/index.mjs> 指定')
  }
}

/** 在页面里取几何读数（注入到浏览器上下文执行） */
export function collectInPage(selectors) {
  const rect = (el) => {
    const r = el.getBoundingClientRect()
    return { width: +r.width.toFixed(1), height: +r.height.toFixed(1), top: +r.top.toFixed(1), bottom: +r.bottom.toFixed(1) }
  }
  /** @type {Array<Record<string, unknown>>} */
  const tapTargets = []
  for (const el of document.querySelectorAll('button, a[href], [role="button"], input, select')) {
    const r = rect(el)
    const visible = r.width > 0 && r.height > 0
    if (!visible) continue
    tapTargets.push({ tag: el.tagName.toLowerCase(), text: (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 24), ...r })
  }
  /** @type {Array<Record<string, unknown>>} */
  const bars = []
  for (const el of document.querySelectorAll(selectors.face)) {
    const r = rect(el)
    if (r.height <= 0 || r.height >= window.innerHeight * 0.9) continue
    bars.push({ selector: el.tagName.toLowerCase() + (el.getAttribute('data-testid') ? `[${el.getAttribute('data-testid')}]` : ''), ...r })
  }
  // 最靠下的叶子文本（滚到底后再取，才能量出"最后一行"）
  const leaves = [...document.querySelectorAll('body *')].filter(
    (el) => el.children.length === 0 && (el.textContent || '').trim().length > 0,
  )
  const leafBottom = leaves.reduce((m, el) => Math.max(m, el.getBoundingClientRect().bottom), 0)
  return { tapTargets, bars, leafBottom: +leafBottom.toFixed(1), viewport: { w: window.innerWidth, h: window.innerHeight } }
}

/**
 * @typedef {object} ProbeReport
 * @property {string} base
 * @property {object} viewport
 * @property {object} limits
 * @property {Array<object>} pages
 * @property {{pass: boolean, failures: string[]}} verdict
 */

/** 对一份 `collectInPage` 读数跑四条判据 */
export function judge(page, key) {
  /** @type {string[]} */
  const failures = []
  for (const t of page.tapTargets ?? []) {
    if (!checkTapTarget(t)) failures.push(`[${key}] GE-control-height: ${t.tag}「${t.text}」高 ${t.height} < ${GEOMETRY_LIMITS.minControlHeight}`)
  }
  for (const b of page.bars ?? []) {
    if (!checkBarHeight(b)) failures.push(`[${key}] GE-bar-height: ${b.selector} 高 ${b.height} > ${GEOMETRY_LIMITS.maxBarHeight}`)
    // 只有**浮在内容之上**（fixed/sticky）的面才会真遮挡；普通文档流里的顶栏不判（否则恒红）
    if (b.overlays && checkOcclusion(page.leafBottom ?? 0, b.top)) {
      failures.push(`[${key}] GE-occlusion: 最后一行 ${page.leafBottom} 落在 ${b.selector} 顶边 ${b.top} 之下（压住 ${occludedPx(page.leafBottom, b.top)}px）`)
    }
  }
  const faces = (page.bars ?? []).filter((b) => b.top <= 0 || b.bottom >= (page.viewport?.h ?? VIEWPORT.height)).map((b) => b.height)
  if (faces.length > 0 && !checkFirstScreen(faces)) {
    failures.push(`[${key}] GE-first-screen: 常驻面占首屏 ${(firstScreenShare(faces) * 100).toFixed(1)}% > ${GEOMETRY_LIMITS.maxFirstScreenShare * 100}%`)
  }
  return failures
}

async function main() {
  const base = (process.argv[2] || 'http://localhost:3001').replace(/\/$/, '')
  const outDir = process.env.PROBE_OUT || path.join(process.cwd(), 'out')
  fs.mkdirSync(outDir, { recursive: true })
  const chromium = await loadChromium()
  const browser = await chromium.launch()
  /** @type {ProbeReport} */
  const report = { base, viewport: VIEWPORT, limits: GEOMETRY_LIMITS, pages: [], verdict: { pass: true, failures: [] } }
  for (const route of ROUTES) {
    const page = await browser.newPage({ viewport: VIEWPORT })
    await page.goto(base + route, { waitUntil: 'networkidle' })
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
    const data = await page.evaluate(collectInPage, { face: PERSISTENT_FACE_SELECTOR, tap: TAP_TARGET_SELECTOR })
    await page.screenshot({ path: path.join(outDir, `${route.replace(/\W+/g, '_') || 'root'}.png`), fullPage: false })
    report.pages.push({ route, ...data })
    report.verdict.failures.push(...judge(data, route))
    await page.close()
  }
  await browser.close()
  report.verdict.pass = report.verdict.failures.length === 0
  fs.writeFileSync(path.join(outDir, 'report.json'), JSON.stringify(report, null, 2))
  console.log(JSON.stringify(report))
  process.exit(report.verdict.pass ? 0 : 1)
}

// 只在被直接执行时跑（被 vitest `import` 时只取纯函数）
if (process.argv[1] && import.meta.url.endsWith(path.basename(process.argv[1]))) {
  main().catch((e) => {
    console.error(e)
    process.exit(2)
  })
}
