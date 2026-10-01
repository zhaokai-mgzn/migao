// case_ids: UI-075
//
// UI-075：订单列表**查询区**的形态判据 —— 不得**横向溢出**（issue #5841）、不得把控件**压到不可读**（issue #5850）、
// 且版式必须是**单一响应式 grid**（issue #5880：列对齐 / 每格可缩 / 主操作独立一行 / 日期区间是一个整体控件）。
//
// ## 为什么是「类级形态判据」而不是像素判据
// jsdom **没有布局引擎** —— `getBoundingClientRect()` 恒返回 0、`scrollWidth` 恒等于 0，
// 在这里量「溢出多少 px / 控件多宽」只会得到一份永远为 0 的假读数（= 空断言）。所以本文件钉的是
// **产生这些病的那个类名形态**，像素读数由真实浏览器截图复核（见 PR body 的读数表）。
//
// ## 三代形态（前两代是实测归因，第三代是本单要治的）
// **A. 溢出（#5841）**：第二行原用 `grid md:grid-cols-[repeat(4,1fr)_auto]`。CSS 里 `1fr` = `minmax(auto,1fr)`，
// **轨道最小尺寸 = 该格内容的 min-content，不可收缩**；实测各格 min-content = 下单时间 380px
// （label 4.5em + 2×`min-w-[130px]` 日期输入 + 「至」+ 间隙）·商品货号 251·商品标题 251·是否加工 141
// + 按钮列 228 ⇒ 内容合计 **1347px** > 卡片内容宽（1440 时 = 1060）⇒ 溢出 287px、按钮被顶出卡片。
// （注：四条 `1fr` 轨道**并非**等宽 —— 实测 380/251/251/141，各自等于本格 min-content；等宽只是特例。）
//
// **B. 压窄（#5850）**：#5841 把轨道改成可收缩的 `minmax(0,…)` ⇒ 溢出没了，但**改成了压扁** ——
// 1440 下 4 条轨道只剩 736px：商品货号/商品标题输入框各 **约 73px**（看得到 5 个字）、
// 下单时间格 276px 要装两个日期框 + 「至」⇒ 每个日期框 **约 80px，只显示得出「2026」**。
// ⇒ 当时的修法是「两行 `flex-wrap` + 每格 `min-w-[…]`」：放得下就一行、放不下就换行。
//
// **C. 列不对齐 / 主操作埋在行尾（#5880，本单）**：B 那个 flex 形态有它自己的病 ——
//   ① 两行**各自一个容器**、各自一套宽度（`flex-1` vs `flex-[1.5]` + 各格**不同的** `min-w-[…]`）
//      ⇒ **列与列不对齐**，行间起点参差；
//   ② 换行点由「各格最小宽之和 vs 可用宽」决定 ⇒ 换行位置随视口漂移，同一行的格宽也各异；
//   ③ 「查询 / 重置 / 刷新」塞在第二行末尾 —— 主操作在最左，「刷新」（**列表动作**）与筛选动作并列。
// ⇒ 本单改为**单一响应式 grid**（`grid-cols-1 md:grid-cols-2 xl:grid-cols-4`）：列天然对齐；
// 每格**可缩**（`min-w-0` —— 宽度由轨道给，不再靠 `min-w-[…]` 撑）；按钮**独立一行右对齐**；
// 日期区间合成**一个整体控件组**（`起 / 至 / 止` 同容器）。
//
// ## ⇒ 本文件钉住的形态判据（命中即红）
//   ① **单 grid**：查询区恰有 1 个 `grid-cols-…` 容器，且列梯是「基档 1 列 + 大轨道数只许在 ≥1536px 出现」
//      （防「每行各一个 grid ⇒ 列不对齐」与「窄屏 4 轨 ⇒ 压扁」两代回潮）；
//   ② **筛选项一个不少**：`input` / `select` 数量与 `placeholder` 集合**逐值相同**（fail-closed）；
//   ③ 下单时间单元格**跨 2 轨**；④ 按钮行是查询区**最后一个 grid item** 且**右对齐**（「刷新」与筛选动作间有分层）；
//   ⑤ 所有 label 共用**同一个固定宽**；⑥ 控件不得同时带 `flex-1` 与**固定长度**的 `min-w-[Npx|rem|em]`；
//   ⑦ grid 的 `fr` 轨道必须写 `minmax(0,…)`（防 A 类回潮）；⑧ 每个**字段格**必须可缩（`min-w-0`，且不得带固定 `min-w-[…]`）；
//   ⑨ fail-closed（把查询区删光 ⇒ 红，防 ①~⑧ 在空集上假绿）；⑩ **判别力自证**（①~⑤ 各喂一个内存坏样本 + ⑥⑦⑧ 的检测器自证）。
//
// ## 与前两代判据的关系（本单**替换**了两条形态判据，理由在此，不是"放宽"）
// #5850 时代的两条判据是「**每一行**必须 `flex-wrap`」与「**每个字段格**必须有固定 `min-w-[…]`」——
// 它们钉的是 B 那个 flex 形态**自身**的类名（行容器 = 查询区的直接子元素、格靠 `min-w-[…]` 定宽）。
// C 号方案把行轴从 flex 换成 grid：格宽由**轨道**给（不再靠 `min-w-[…]` 撑）、换行由 **grid 自动排布**完成、
// 窄屏不压扁由**列梯**（1/2/4）保证 ⇒ 那两条判据的对象已经不存在，**照抄会让本单的目标版式必然判红**。
// 故它们是**被替换**（各自的病由新判据 ① 的列梯 + ⑧ 的可缩性承接），而**控件侧的不可收缩形态（⑥）一字未动**。
import React from 'react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'

const mockGetOrders = vi.fn()

// 只 mock「外部世界」（网络 / 路由），不 mock 被测组件
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/orders',
}))
vi.mock('next/link', () => ({
  default: ({ children, ...props }: any) => <a {...props}>{children}</a>,
}))
vi.mock('@/lib/api', () => ({
  orderApi: {
    getOrders: (...args: any[]) => mockGetOrders(...args),
    updateOrderStatus: vi.fn(),
    exportOrders: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), loading: vi.fn() } }))

import OrdersPage from '@/app/(dashboard)/orders/page'

// ── 改前的筛选项（基线 2a7568a37 逐值抄下来；版式重构**不得增删任何一个**）────────
// 判据 ② 就是拿这份常量去比"现在渲染出来的" —— 逐值比较（排序后 join），
// 避免"集合相等但取值不同"的漏判；改动任何一个 placeholder / 少一个字段 ⇒ 红。
const EXPECTED_PLACEHOLDERS = [
  '开始日期',
  '结束日期',
  '请输入订单ID',
  '请输入收货人姓名或手机号',
  '请输入制单人姓名',
  '请输入商品货号',
  '请输入商品标题',
].sort()
const EXPECTED_SELECT_OPTIONS = ['全部', '是', '否']

// ── 检测器（纯函数；判据 ⑩ 直接喂坏样本，反证「检测器非空转」）──────────────────

/** 一条类名 token 拆成「断点前缀 + 基名」（`xl:grid-cols-4` ⇒ `xl:` + `grid-cols-4`）。 */
function splitPrefix(token: string): { prefix: string; base: string } {
  const i = token.lastIndexOf(':')
  return i < 0 ? { prefix: '', base: token } : { prefix: token.slice(0, i + 1), base: token.slice(i + 1) }
}

/** 类名里的 `grid-cols-…` token（含断点前缀）。 */
function gridColsTokens(className: string): { prefix: string; value: string; token: string }[] {
  const out: { prefix: string; value: string; token: string }[] = []
  for (const token of String(className ?? '').split(/\s+/)) {
    const { prefix, base } = splitPrefix(token)
    const m = /^grid-cols-(.+)$/.exec(base)
    if (m) out.push({ prefix, value: m[1], token })
  }
  return out
}

function hasGridCols(className: string): boolean {
  return gridColsTokens(className).length > 0
}

/**
 * 判据 ① 的一半：**列梯** —— 窄屏不许出现大轨道数（#5850 的类级病：轨道多了只能压扁）。
 * 规则：基档必须是 `grid-cols-1`；列数 ≥3 的 token 只许出现在 `2xl:` / `min-[≥1536px]:` 上
 * （用户裁定 2026-10-01：4 轨档的断点 = **1536**，不是 1280 —— 1280 起 4 轨会把最长的 placeholder 截掉）。
 */
export function columnLadderProblems(className: string): string[] {
  const problems: string[] = []
  const cols = gridColsTokens(className)
  if (!cols.some((c) => c.prefix === '' && c.value === '1')) {
    problems.push(`缺少基档 grid-cols-1（窄屏必须 1 列）`)
  }
  for (const c of cols) {
    if (!/^\d+$/.test(c.value)) continue
    const n = Number(c.value)
    if (n < 3) continue
    const wideEnough =
      /^2xl:$/.test(c.prefix) ||
      (() => {
        const m = /^min-\[(\d+)px\]:$/.exec(c.prefix)
        return m !== null && Number(m[1]) >= 1536
      })()
    if (!wideEnough) problems.push(`轨道数 ${n} 出现在「${c.prefix || '基档'}」⇒ 窄屏只能把控件压扁（token「${c.token}」）`)
  }
  return problems
}

/**
 * 判据 ①：查询区**恰有 1 个** grid 容器，且它的列梯合规。
 * 病：查询区若允许「每行各一个 grid」，两套轨道定义必然列不对齐（#5880 的归因 ①）。
 */
export function singleGridProblems(root: Element): string[] {
  const grids = [root, ...root.querySelectorAll('*')].filter((el) => hasGridCols(el.className))
  if (grids.length !== 1) {
    return [
      `查询区应恰有 1 个 grid 容器（列才天然对齐），实际 ${grids.length} 个：` +
        grids.map((g) => `"${g.className}"`).join(' | '),
    ]
  }
  return columnLadderProblems(grids[0].className).map((p) => `${p} —— class="${grids[0].className}"`)
}

/** 判据 ②：筛选项一个不少 —— `input` / `select` 数量与 `placeholder` / 选项**逐值相同**。 */
export function fieldSetProblems(root: Element): string[] {
  const problems: string[] = []
  const inputs = [...root.querySelectorAll('input')]
  const selects = [...root.querySelectorAll('select')]
  if (inputs.length !== 7) problems.push(`input 数量应为 7（改前逐值），实际 ${inputs.length}`)
  if (selects.length !== 1) problems.push(`select 数量应为 1（改前逐值），实际 ${selects.length}`)

  const placeholders = inputs.map((i) => i.getAttribute('placeholder') ?? '').sort()
  if (placeholders.join('|') !== EXPECTED_PLACEHOLDERS.join('|')) {
    problems.push(`placeholder 集合与改前不一致：实际 [${placeholders.join(', ')}] ≠ 期望 [${EXPECTED_PLACEHOLDERS.join(', ')}]`)
  }
  const options = selects.flatMap((s) => [...s.querySelectorAll('option')].map((o) => (o.textContent ?? '').trim()))
  if (options.join('|') !== EXPECTED_SELECT_OPTIONS.join('|')) {
    problems.push(`select 选项与改前不一致：实际 [${options.join(', ')}] ≠ 期望 [${EXPECTED_SELECT_OPTIONS.join(', ')}]`)
  }
  return problems
}

/** 取 `el` 所属的 grid item（grid 的直接子元素）。 */
function gridItemOf(el: Element, grid: Element): Element | null {
  let cur: Element | null = el
  while (cur && cur.parentElement !== grid) cur = cur.parentElement
  return cur
}

/** 类名里的 `col-span-N` token。 */
export function colSpanTokens(className: string): string[] {
  return String(className ?? '')
    .split(/\s+/)
    .filter((t) => /^(?:[a-z0-9-]+:)*col-span-\d+$/.test(t))
}

/** 判据 ③：下单时间单元格（=`input[type=date]` 所在的 grid item）必须跨 2 轨。 */
export function dateRangeSpanProblems(grid: Element): string[] {
  const dates = [...grid.querySelectorAll('input[type="date"]')]
  if (dates.length !== 2) return [`日期输入应为 2 个（起 / 止），实际 ${dates.length} 个`]
  const cell = gridItemOf(dates[0], grid)
  if (!cell) return ['日期输入不在 grid 的直接子元素（字段格）里']
  const spans = colSpanTokens(cell.className)
  if (!spans.some((t) => Number(t.replace(/^.*col-span-/, '')) === 2)) {
    return [`下单时间单元格未跨 2 轨（类名里没有 col-span-2）：class="${cell.className}"`]
  }
  return []
}

/** 判据 ④：按钮行 = 查询区**最后一个 grid item**；右对齐；按钮顺序不变；「刷新」与筛选动作之间有分层分隔。 */
export function buttonRowProblems(grid: Element): string[] {
  const items = [...grid.children]
  const last = items[items.length - 1]
  if (!last) return ['grid 没有子元素（fail-closed）']
  if (last.querySelector('input, select, textarea')) {
    return [`查询区最后一个 grid item 是字段格、不是按钮行：class="${last.className}"`]
  }
  const problems: string[] = []
  const buttons = [...last.querySelectorAll('button')]
  const labels = buttons.map((b) => (b.textContent ?? '').trim())
  if (labels.join('|') !== '查询|重置|刷新') {
    problems.push(`按钮行内顺序/文案应为 查询→重置→刷新，实际 [${labels.join(', ')}]`)
  }
  if (!/(?:^|\s)justify-end(?:\s|$)/.test(last.className)) {
    problems.push(`按钮行未右对齐（缺 justify-end）：class="${last.className}"`)
  }
  const refresh = buttons.find((b) => (b.getAttribute('aria-label') ?? '') === '刷新')
  if (!refresh) {
    problems.push('按钮行里找不到 aria-label="刷新" 的按钮（e2e 定位器依赖这个属性）')
    return problems
  }
  // 「刷新」是**列表动作**、「查询/重置」是**筛选动作** ⇒ 二者之间要有一条细分隔（`border-l`）
  let cur: Element | null = refresh.parentElement
  let divider: Element | null = null
  while (cur && cur !== last) {
    if (/(?:^|\s)border-l(?:\s|$)/.test(cur.className)) {
      divider = cur
      break
    }
    cur = cur.parentElement
  }
  if (!divider) {
    problems.push('「刷新」与「查询 / 重置」之间没有分层（找不到带 border-l 的分隔容器）')
  } else if (divider.querySelector('button')?.textContent?.trim() !== '刷新') {
    problems.push(
      `分层容器里混进了筛选动作（分隔必须只包住「刷新」）：${[...divider.querySelectorAll('button')]
        .map((b) => (b.textContent ?? '').trim())
        .join(', ')}`
    )
  }
  return problems
}

/** 类名里的**固定宽** `w-[…]` token（注意：`min-w-[…]` 不是 `w-[…]` —— 它只设下限，宽度仍随内容变）。 */
export function labelWidthTokens(className: string): string[] {
  return (String(className ?? '').match(/(?:^|\s)(?:[a-z0-9-]+:)*w-\[[^\]]+\]/g) ?? []).map((s) => s.trim())
}

/** 判据 ⑤：查询区内所有 label 必须**共用同一个固定宽**（防"各格各写一个宽度 ⇒ 行间起点参差"）。 */
export function labelWidthProblems(root: Element): string[] {
  const labels = [...root.querySelectorAll('label')]
  if (labels.length === 0) return ['查询区里找不到 label（fail-closed）']
  const problems: string[] = []
  for (const l of labels) {
    if (labelWidthTokens(l.className).length !== 1) {
      problems.push(`label「${(l.textContent ?? '').trim()}」没有唯一的**固定宽**类（形如 w-[4.5em]）：class="${l.className}"`)
    }
  }
  const distinct = [...new Set(labels.map((l) => labelWidthTokens(l.className).join(',')))]
  if (distinct.length !== 1) {
    problems.push(`各 label 的宽度类不一致（必须共用同一常量）：${distinct.map((d) => `"${d}"`).join(' / ')}`)
  }
  return problems
}

/** 判据 ⑧：每个**字段格**必须可缩 —— 有 `min-w-0`、且**不得**带固定长度 `min-w-[…]`。 */
export function cellShrinkProblems(grid: Element): string[] {
  const cells = [...grid.children].filter((el) => el.querySelector('input, select, textarea') !== null)
  return cells.flatMap((cell) => {
    const problems: string[] = []
    if (!/(?:^|\s)min-w-0(?:\s|$)/.test(cell.className)) {
      problems.push(`字段格不可缩（缺 min-w-0）：class="${cell.className}"`)
    }
    if (hasFixedMinWidth(cell.className)) {
      problems.push(`字段格带固定 min-w-[…]（grid 轨道已经给了宽度，再固定就是 #5841 的溢出）：class="${cell.className}"`)
    }
    return problems
  })
}

/** 判据 ⑥ 的检测器：控件同时带 `flex-1` 与固定长度 `min-w-[…]` ⇒ 缩不下去。 */
export function fixedMinWidthControls(el: Element): string[] {
  const cls = typeof el.className === 'string' ? el.className : ''
  if (!/(?:^|\s)(?:[a-z0-9-]+:)*flex-1(?:\s|$)/.test(cls)) return []
  return (cls.match(/(?:^|\s)(?:[a-z0-9-]+:)*min-w-\[[0-9.]+(?:px|rem|em)\]/g) ?? []).map((s) => s.trim())
}

/** 判据 ⑧ 的检测器：类名里有没有**固定长度**的 `min-w-[…]`。 */
export function hasFixedMinWidth(className: string): boolean {
  return /(?:^|\s)(?:[a-z0-9-]+:)*min-w-\[[0-9.]+(?:px|rem|em)\]/.test(String(className ?? ''))
}

/** 把 arbitrary 值里的 track 列表拆开，并把 `repeat(n, X)` 展开成 n 条 `X`。 */
function expandTracks(value: string): string[] {
  const parts: string[] = []
  let depth = 0
  let cur = ''
  for (const ch of value) {
    if (ch === '(') depth++
    else if (ch === ')') depth--
    if (/\s/.test(ch) && depth === 0) {
      if (cur) parts.push(cur)
      cur = ''
      continue
    }
    cur += ch
  }
  if (cur) parts.push(cur)
  return parts.flatMap((p) => {
    const r = /^repeat\(\s*(\d+)\s*,\s*([\s\S]+)\)$/.exec(p.trim())
    return r ? Array.from({ length: Number(r[1]) }, () => r[2].trim()) : [p.trim()]
  })
}

/**
 * 一条轨道是否「不可收缩的 fr」：裸 `1fr`（= `minmax(auto,1fr)`）或
 * `minmax(<非 0>, …fr)`（如 `minmax(auto,1fr)` / `minmax(130px,1fr)`）。
 * 只有 `minmax(0, …fr)` 的最小尺寸是 0，才允许被压到比内容更窄。
 */
function isNonShrinkableFr(track: string): boolean {
  const t = track.trim()
  const mm = /^minmax\(\s*([^,]+?)\s*,\s*([\s\S]+)\)$/i.exec(t)
  if (mm) return /fr$/i.test(mm[2].trim()) && !/^0(px|rem|em|%)?$/i.test(mm[1].trim())
  return /fr$/i.test(t)
}

/** 判据 ⑦：`grid-cols-…` 里的不可收缩 `fr` 轨道（A 类坏形态的检测器）。 */
export function bareFrTracks(className: string): string[] {
  const bad: string[] = []
  for (const token of String(className ?? '').split(/\s+/)) {
    const { base } = splitPrefix(token)
    const m = /^grid-cols-(.+)$/.exec(base)
    if (!m) continue
    const value = m[1]
    if (/^\d+$/.test(value)) continue // grid-cols-4 = repeat(4, minmax(0,1fr))，本身可收缩
    if (!value.startsWith('[') || !value.endsWith(']')) continue
    for (const track of expandTracks(value.slice(1, -1).replace(/_/g, ' '))) {
      if (isNonShrinkableFr(track)) bad.push(`${token} ⇒ 不可收缩的 fr 轨道「${track}」`)
    }
  }
  return bad
}

const QUERY_AREA = '[data-testid="search-area"]'

function queryArea(): HTMLElement {
  const el = document.querySelector(QUERY_AREA)
  if (!el) throw new Error('查询区不存在（data-testid="search-area"）—— 判据会在空集上假绿，故直接判红')
  return el as HTMLElement
}

/** 查询区的布局 grid（恰一个；不恰一个时直接判红，而不是让后面的判据在空集上假绿）。 */
function layoutGrid(): HTMLElement {
  const problems = singleGridProblems(queryArea())
  if (problems.length > 0) throw new Error(`查询区不是「单一 grid」：${problems.join('；')}`)
  return [queryArea(), ...queryArea().querySelectorAll('*')].filter((el) => hasGridCols(el.className))[0] as HTMLElement
}

function queryControls(): Element[] {
  return [...queryArea().querySelectorAll('input, select, textarea')]
}

function fragment(html: string): HTMLElement {
  const div = document.createElement('div')
  div.innerHTML = html
  return div
}

describe('订单列表查询区 · 单一 grid（#5880）/ 不溢出（#5841）/ 不压窄（#5850）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetOrders.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
  })

  it('① 查询区恰有一个 grid 容器，且列梯为「基档 1 列 + 大轨道数只在 ≥1536px」', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    expect(singleGridProblems(queryArea())).toEqual([])
    // 字段格与按钮行都必须是这个 grid 的直接子元素（不给「第二个 grid」留位置）
    expect([...layoutGrid().children].length).toBeGreaterThanOrEqual(8)
    expect([...layoutGrid().children].every((c) => c.parentElement === layoutGrid())).toBe(true)
  })

  it('② 筛选项一个不少：input/select 数量与 placeholder 集合与改前逐值相同', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    expect(fieldSetProblems(queryArea())).toEqual([])
  })

  it('③ 下单时间单元格跨 2 轨（两个日期框 + 「至」是一个整体控件组）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    expect(dateRangeSpanProblems(layoutGrid())).toEqual([])
  })

  it('④ 按钮行是查询区最后一个 grid item、右对齐，且「刷新」与筛选动作之间有分层分隔', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    expect(buttonRowProblems(layoutGrid())).toEqual([])
  })

  it('⑤ 查询区内所有 label 共用同一个固定宽（行间起点才对齐）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    const labels = [...queryArea().querySelectorAll('label')]
    expect(labels.length).toBeGreaterThanOrEqual(7) // fail-closed
    expect(labelWidthProblems(queryArea())).toEqual([])
  })

  it('⑥ 查询区表单控件不得同时带 flex-1 与固定 min-w-[…]（缩不下去 = 撑爆所在格）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    const bad = queryControls().flatMap((el) =>
      fixedMinWidthControls(el).map((cls) => `${el.tagName.toLowerCase()}[${cls}] = ${el.className}`)
    )
    expect(bad).toEqual([])
  })

  it('⑦ 防 A 类回潮：查询区若又出现 grid 行，其 fr 轨道必须是 minmax(0,…)', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    const grids = [queryArea(), ...queryArea().querySelectorAll('*')].filter((el) => hasGridCols(el.className))
    expect(grids.length).toBeGreaterThanOrEqual(1) // fail-closed：没有 grid ⇒ 该判据会空转
    const bad = grids.flatMap((g) => bareFrTracks(g.className))
    expect(bad).toEqual([])
  })

  it('⑧ 每个字段格必须可缩（min-w-0，且不得带固定 min-w-[…]）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    const cells = [...layoutGrid().children].filter((el) => el.querySelector('input, select, textarea') !== null)
    expect(cells.length).toBeGreaterThanOrEqual(7) // fail-closed
    expect(cellShrinkProblems(layoutGrid())).toEqual([])
  })

  it('⑨ fail-closed：查询区确实是 grid、且字段格 / 控件 / label 都在（删光即红）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    expect(hasGridCols(queryArea().className)).toBe(true)
    expect([...layoutGrid().children].length).toBeGreaterThanOrEqual(8)
    // 查询区应有 8 个控件：订单ID / 收货人 / 制单人 / 起止日期 ×2 / 商品货号 / 商品标题 / 是否加工
    expect(queryControls().length).toBeGreaterThanOrEqual(8)
    expect([...queryArea().querySelectorAll('label')].length).toBeGreaterThanOrEqual(7)
  })

  it('⑩ 反空跑：①~⑤ 的检测器对坏样本必报、对好样本不报（否则它们是空断言）', () => {
    // ── ① 单 grid：两个 grid（#5880 的原始病）必红 ──
    expect(
      singleGridProblems(
        fragment(
          '<div class="flex flex-wrap gap-4"><div class="grid grid-cols-1 md:grid-cols-2"></div>' +
            '<div class="grid grid-cols-1 xl:grid-cols-4"></div></div>'
        )
      )
    ).toHaveLength(1)
    // ── ① 列梯：基档不是 1 列 / 大轨道数出现在窄档 ⇒ 必红 ──
    expect(columnLadderProblems('grid grid-cols-2 2xl:grid-cols-4')).toHaveLength(1)
    expect(columnLadderProblems('grid grid-cols-1 grid-cols-4')).toHaveLength(1)
    // 用户裁定（2026-10-01）：4 轨档的断点是 1536 ⇒ 写在 xl:(1280) 上**必须红**
    expect(columnLadderProblems('grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4')).toHaveLength(1)
    expect(columnLadderProblems('grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-4 gap-x-6')).toEqual([])
    expect(columnLadderProblems('grid grid-cols-1 min-[1536px]:grid-cols-4')).toEqual([])

    // ── ② 筛选项：少一个 input 必红；好样本（= 真页面的 7+1）不红 ──
    expect(
      fieldSetProblems(
        fragment(
          '<input placeholder="请输入订单ID" /><input placeholder="请输入收货人姓名或手机号" />' +
            '<select><option>全部</option><option>是</option><option>否</option></select>'
        )
      ).length
    ).toBeGreaterThanOrEqual(1)
    expect(
      fieldSetProblems(
        fragment(
          ['请输入订单ID', '请输入收货人姓名或手机号', '请输入制单人姓名'].map((p) => `<input placeholder="${p}" />`).join('') +
            '<input type="date" placeholder="开始日期" /><input type="date" placeholder="结束日期" />' +
            '<input placeholder="请输入商品货号" /><input placeholder="请输入商品标题" />' +
            '<select><option>全部</option><option>是</option><option>否</option></select>'
        )
      )
    ).toEqual([])

    // ── ③ 跨 2 轨：日期格没有 col-span-2 必红；有则不红 ──
    const dateCell = (cls: string) =>
      fragment(
        `<div class="grid grid-cols-1"><div class="${cls}"><input type="date" /><span>至</span><input type="date" /></div></div>`
      ).firstElementChild as Element
    expect(dateRangeSpanProblems(dateCell('flex items-center gap-2 min-w-0'))).toHaveLength(1)
    expect(dateRangeSpanProblems(dateCell('md:col-span-2 flex items-center gap-2 min-w-0'))).toEqual([])

    // ── ④ 按钮行：最后一个 grid item 不是按钮行 / 缺 justify-end / 缺分层分隔 ⇒ 必红 ──
    const buttonRow = (cls: string, divider: string) =>
      fragment(
        `<div class="grid grid-cols-1"><div class="flex min-w-0"><input /></div><div class="${cls}">` +
          '<button>查询</button><button>重置</button>' +
          `<span class="${divider}"><button aria-label="刷新">刷新</button></span></div></div>`
      ).firstElementChild as Element
    expect(buttonRowProblems(fragment('<div class="grid grid-cols-1"><div class="flex"><input /></div></div>').firstElementChild as Element)).toHaveLength(1)
    expect(buttonRowProblems(buttonRow('flex items-center gap-2', 'flex border-l border-neutral-200 pl-3'))).toHaveLength(1) // 缺 justify-end
    expect(buttonRowProblems(buttonRow('flex items-center justify-end gap-2', 'flex'))).toHaveLength(1) // 缺分层分隔
    expect(buttonRowProblems(buttonRow('flex items-center justify-end gap-2', 'flex border-l border-neutral-200 pl-3'))).toEqual([])

    // ── ⑤ label 固定宽：宽度不一致 / 只有 min-w-[…] ⇒ 必红 ──
    expect(labelWidthProblems(fragment('<label class="w-[4.5em]">订单ID</label><label class="w-[6em]">收货人</label>'))).toHaveLength(1)
    expect(labelWidthProblems(fragment('<label class="min-w-[4.5em] text-right">订单ID</label>'))).toHaveLength(1)
    expect(labelWidthProblems(fragment('<label class="w-[4.5em] text-right">订单ID</label><label class="w-[4.5em]">收货人</label>'))).toEqual([])

    // ── ⑧ 字段格可缩：带固定 min-w-[…] 必红；min-w-0 不红 ──
    const cellGrid = (cls: string) =>
      fragment(`<div class="grid grid-cols-1"><div class="${cls}"><input /></div></div>`).firstElementChild as Element
    expect(cellShrinkProblems(cellGrid('flex items-center gap-2 flex-1 min-w-[200px]'))).toHaveLength(2)
    expect(cellShrinkProblems(cellGrid('flex items-center gap-2 min-w-0'))).toEqual([])

    // ── ⑥⑦ 原有检测器：坏形态必报、好形态不报 ──
    expect(hasFixedMinWidth('flex items-center gap-2 flex-1')).toBe(false)
    expect(hasFixedMinWidth('flex items-center gap-2 flex-1 min-w-[180px]')).toBe(true)
    expect(bareFrTracks('grid grid-cols-1 md:grid-cols-[repeat(4,1fr)_auto] gap-x-6')).toHaveLength(4)
    expect(bareFrTracks('grid grid-cols-1 md:grid-cols-[1fr_1fr_1.5fr] gap-x-6')).toHaveLength(3)
    expect(bareFrTracks('grid grid-cols-1 xl:grid-cols-[minmax(0,1.8fr)_minmax(0,1fr)_auto]')).toEqual([])
    expect(bareFrTracks('grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4')).toEqual([])
    expect(bareFrTracks('flex flex-1 min-w-[130px]')).toEqual([]) // 非 grid 类名不报

    const badInput = document.createElement('input')
    badInput.className = 'flex-1 min-w-[130px] h-9 border'
    expect(fixedMinWidthControls(badInput)).toEqual(['min-w-[130px]'])
    const goodInput = document.createElement('input')
    goodInput.className = 'flex-1 min-w-0 h-9 border'
    expect(fixedMinWidthControls(goodInput)).toEqual([])
  })
})
