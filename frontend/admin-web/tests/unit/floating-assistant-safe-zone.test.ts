// case_ids: UI-011
/**
 * 类级守卫：**常驻面（右下角黄金策浮球）不得吃掉可点元素**（issue #6687）
 *
 * ## 病灶（命中测试实测，2026-10-10）
 *
 * `frontend/admin-web/src/components/ai-assistant/FloatingAssistant.tsx` 的 FAB 是
 * `fixed bottom-6 right-6 z-50 w-14 h-14`（56×56 实体按钮）。满宽表格页（本例 `/products`）
 * 的表格容器右边界与它**必然相交**：1440×980 视口实测 —— 浮球 rect `(1360,900) 56×56`、
 * 第 8 行「推荐」`<a>` rect `(1366,930) 28×20`（**完全落在浮球矩形内**），
 * `document.elementFromPoint` 在重叠点命中浮球的 `span.animate-ping` ⇒ **点击被浮球吃掉**：
 * 点「推荐」实际打开 AI 助手。观感上读成「这一行没有『推荐』」（比缺按钮更坏）。
 *
 * ## 判据（几何关系，不靠肉眼）
 *
 * 修法 = **列表容器让位**（FAB 是黄金策的既定入口，见 UI-011，不动它）：
 * layout 的 `<main>` 预留**右侧安全区** `pr-16`，把内容右边界推到 FAB 左侧之外。
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | `<main>` 的右侧内边距 ≥ FAB 宽度 + 16px 行业余量 | 把 `pr-16` 改小 / 删掉 ⇒ 红 |
 * | 2 | FAB 仍是右下角 `fixed` 56×56 实体按钮（**锚点被挪走 ⇒ 红**，否则上面的算式失去对象） | 改尺寸/定位而不改安全区 ⇒ 红 |
 * | 3 | 判别力自证：旧形态（无右侧安全区）算出的余量为**负** ⇒ 红；修后形态 ⇒ 绿 | 判据退化成恒绿 ⇒ 红 |
 *
 * ## 边界（照实登记，§19.1）
 *
 * - 本文件判的是**确定性几何关系**（安全区 ≥ FAB 宽 + 余量），**不是**真实渲染后的
 *   `elementFromPoint` 命中读数 —— 后者由 Playwright 命中测试取证（命令见 PR body）。
 * - 只覆盖 `(dashboard)` 布局下的页面（FAB 都挂在这里）；小屏（<640px）下 `px-4` 仍在，
 *   但 `pr-16` **不随断点变化** ⇒ 安全区在小屏更大，不会反向失效。
 * - 「其他满宽表格页是否都让位」由**同一处** layout 覆盖（不是逐页抄一遍）；若将来某页把内容
 *   渲染到 `<main>` 之外（portal / fixed 自绘容器），本判据盖不到。
 */
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

const REPO = process.cwd()
const LAYOUT = join(REPO, 'src/app/(dashboard)/layout.tsx')
const FAB = join(REPO, 'src/components/ai-assistant/FloatingAssistant.tsx')
const PRODUCT_TABLE = join(REPO, 'src/components/products/ProductTable.tsx')

/** Tailwind 间距刻度（px）：n → n*4（`pr-20` = 80px） */
const spacingPx = (n: number) => n * 4
/** FAB 与内容的**最小**行业余量（px）—— 至少留出这么多，不许贴着算「不相交」 */
const MIN_GUTTER_PX = 16

function readMainClassName(): string {
  const src = readFileSync(LAYOUT, 'utf-8')
  const m = /<main\s+className="([^"]+)"/.exec(src)
  if (!m) throw new Error('layout.tsx 里找不到 <main className="…">（判据需同步更新）')
  return m[1]
}

function readFabClassNames(): string {
  const src = readFileSync(FAB, 'utf-8')
  const m = /<button\b[\s\S]*?className=\{cn\(([\s\S]*?)\)\}/.exec(src)
  if (!m) throw new Error('FloatingAssistant.tsx 里找不到 FAB 的 cn(…) className（判据需同步更新）')
  return m[1]
}

/**
 * `ProductTable` 钉的表格最小宽度（px）。
 *
 * 它是「表格宽度」那一半：**最小宽度越大 ⇒ 横向滚动区越宽 ⇒ 「操作」列越容易被推到浮球底下**
 * （「操作」是表尾列）。收窄它 = 把表尾列拉回安全区内。
 */
function productTableMinWidthPx(): number {
  const m = /minWidth=\{(\d+)\}/.exec(readFileSync(PRODUCT_TABLE, 'utf-8'))
  if (!m) throw new Error('ProductTable.tsx 里找不到 `minWidth={n}`（判据需同步更新）')
  return Number(m[1])
}

/** `<main>` 上生效的右侧内边距（px）：取所有 `pr-<n>` 里最大的那个 */
function reservedRightPx(className: string): number {
  const nums = [...className.matchAll(/(?:^|\s)pr-(\d+)(?:\s|$)/g)].map((m) => Number(m[1]))
  return nums.length ? Math.max(...nums.map(spacingPx)) : 0
}

/**
 * 右侧安全区在**每个断点**下的最小值（px）—— 这才是真判据。
 *
 * 🔴 为什么不能用「最大 pr」：Tailwind 里 `padding-inline`（`px-*`）与 `pr-*` 都作用于
 * **padding-right**，且媒体查询（`sm:*`）的规则**排在基础规则之后** ⇒ 宽屏下
 * `sm:px-6`（24px）会把基础 `pr-20`（80px）**覆盖回 24px**（本单实测踩过：
 * 只写 `pr-20` 时滚动容器 clientWidth 仍是 1100 = 安全区**根本没生效**，而"取最大 pr"的判据照样绿 ⇒ 假绿）。
 *
 * 级联口径（Tailwind 生成顺序）：同一断点内 `pr-*` 排在 `px-*` 之后 ⇒ `pr` 胜；
 * 跨断点时媒体查询规则胜基础规则 ⇒ `sm:px-*` 会压过基础 `pr-*`。
 */
function minRightPxAcrossBreakpoints(className: string): number {
  const tokens = className.split(/\s+/).filter(Boolean)
  const pick = (bp: string, kind: 'pr' | 'px'): number | null => {
    const re = bp === 'base' ? /^(pr|px)-(\d+)$/ : new RegExp(`^${bp}:(pr|px)-(\\d+)$`)
    let v: number | null = null
    for (const t of tokens) {
      const m = re.exec(t)
      if (m && m[1] === kind) v = spacingPx(Number(m[2]))
    }
    return v
  }
  const baseEff = pick('base', 'pr') ?? pick('base', 'px') ?? 0
  let min = baseEff
  let prev = baseEff
  for (const bp of ['sm', 'md', 'lg', 'xl', '2xl']) {
    const eff = pick(bp, 'pr') ?? pick(bp, 'px') ?? prev
    min = Math.min(min, eff)
    prev = eff
  }
  return min
}

/** FAB 宽度（px）：`w-14` ⇒ 56 */
function fabWidthPx(classNames: string): number {
  const m = /(?:^|\s)w-(\d+)(?:\s|$)/.exec(classNames)
  if (!m) throw new Error('FAB 上没有 `w-<n>` 宽度刻度（判据需同步更新）')
  return spacingPx(Number(m[1]))
}

describe('常驻浮球安全区：容器让位，二者不相交（issue #6687）', () => {
  it('🔴 layout 的 <main> 在**所有断点**下右侧安全区 ≥ FAB 宽 + 16px', () => {
    const main = readMainClassName()
    const fab = readFabClassNames()
    expect(minRightPxAcrossBreakpoints(main)).toBeGreaterThanOrEqual(fabWidthPx(fab) + MIN_GUTTER_PX)
  })

  it('🔴 FAB 仍是右下角 fixed 56×56 实体按钮（锚点没被挪走）', () => {
    const fab = readFabClassNames()
    expect(fab).toContain('fixed')
    expect(fab).toContain('bottom-6')
    expect(fab).toContain('right-6')
    expect(fabWidthPx(fab)).toBe(56)
  })

  it('安全区覆盖到宽屏断点（`sm:px-6` 会覆盖基础 `pr-*` ⇒ 必须显式给 `sm:pr-*`）', () => {
    const main = readMainClassName()
    // 这一条是**踩坑固化**：只写基础 `pr-20` 时，`sm:px-6`（媒体查询、排在后面）把它覆盖回 24px
    expect(main).toMatch(/sm:pr-\d+/)
    // 负控：基础值与 sm 值都不能小于 FAB 宽
    const fab = readFabClassNames()
    expect(minRightPxAcrossBreakpoints(main)).toBeGreaterThanOrEqual(fabWidthPx(fab))
  })

  it('🔴 宽表不再硬撑出宽于容器的宽度（ProductTable 的最小宽度 ≤ 原 1200）', () => {
    // 1200 是**硬撑**：1440×980 上容器只有 ~1100px ⇒ 多出来的宽度全在横向滚动区里 ⇒
    // 表尾「操作」列被推到浮球矩形里（本单实测）。判据 = 收窄（不许回到 1200 及以上）。
    expect(productTableMinWidthPx()).toBeLessThanOrEqual(1120)
  })
})

describe('判别力自证（issue #6687 判据 3）', () => {
  it('旧形态（修前 className，右侧只有 `px-4` / `sm:px-6`）⇒ 远小于安全区 ⇒ 判红', () => {
    const legacyMain = 'flex-1 px-4 sm:px-6 pt-4 sm:pt-6 pb-24'
    const fab = readFabClassNames()
    // 最小值取小屏：`px-4` = 16px（宽屏是 `sm:px-6` = 24px）—— 都远小于 72px 安全区
    expect(minRightPxAcrossBreakpoints(legacyMain)).toBe(16)
    expect(minRightPxAcrossBreakpoints(legacyMain)).toBeLessThan(fabWidthPx(fab) + MIN_GUTTER_PX)
  })

  it('🔴 半修形态（只有基础 `pr-20`、没给 `sm:pr-20`）⇒ 宽屏断点仍是 24px ⇒ 判红', () => {
    // 这正是本单踩过的假绿：`sm:px-6` 覆盖基础 `pr-20`，而"取最大 pr"的判据照样绿
    const halfFixed = 'flex-1 px-4 sm:px-6 pr-20 pt-4 sm:pt-6 pb-24'
    const fab = readFabClassNames()
    expect(reservedRightPx(halfFixed)).toBe(80) // 老口径（取最大）→ 假绿
    expect(minRightPxAcrossBreakpoints(halfFixed)).toBe(24) // 真口径 → 宽屏下只有 24px
    expect(minRightPxAcrossBreakpoints(halfFixed)).toBeLessThan(fabWidthPx(fab) + MIN_GUTTER_PX)
  })

  it('修后形态 ⇒ 判绿', () => {
    const main = readMainClassName()
    expect(reservedRightPx(main)).toBe(80)
    expect(minRightPxAcrossBreakpoints(main)).toBe(80)
  })

  it('`sm:pr-2` 这种断点里的刻度**不算**基础安全区（不误判为绿）', () => {
    expect(reservedRightPx('flex-1 px-4 sm:pr-2 pt-4')).toBe(0)
  })

  it('🔴 反向对照：最小宽度回到 1200 ⇒ 上一条判据会红', () => {
    const legacyMinWidth = 1200
    expect(legacyMinWidth).toBeGreaterThan(1120)
  })
})
