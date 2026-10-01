// case_ids: UI-075
//
// UI-075：订单列表**查询区**在窄屏既不得**横向溢出**（issue #5841），也不得把控件**压到不可读**（issue #5850）。
//
// ## 为什么是「类级形态判据」而不是像素判据
// jsdom **没有布局引擎** —— `getBoundingClientRect()` 恒返回 0、`scrollWidth` 恒等于 0，
// 在这里量「溢出多少 px / 控件多宽」只会得到一份永远为 0 的假读数（= 空断言）。所以本文件钉的是
// **产生这两种病的那个类名形态**，像素读数由真实浏览器复核（见 PR body 的读数表）。
//
// ## 被钉住的两代坏形态（都是实测归因）
// **A. 溢出（#5841）**：第二行原用 `grid md:grid-cols-[repeat(4,1fr)_auto]`。CSS 里 `1fr` = `minmax(auto,1fr)`，
// **轨道最小尺寸 = 该格内容的 min-content，不可收缩**；实测各格 min-content = 下单时间 380px
// （label 4.5em + 2×`min-w-[130px]` 日期输入 + 「至」+ 间隙）·商品货号 251·商品标题 251·是否加工 141
// + 按钮列 228 ⇒ 内容合计 **1347px** > 卡片内容宽（1440 时 = 1060）⇒ 溢出 287px、按钮被顶出卡片。
// （注：四条 `1fr` 轨道**并非**等宽 —— 实测 380/251/251/141，各自等于本格 min-content；等宽只是特例。）
//
// **B. 压窄（#5850）**：#5841 把轨道改成可收缩的 `minmax(0,…)` ⇒ 溢出没了，但**改成了压扁** ——
// 1440 下 4 条轨道只剩 736px：商品货号/商品标题输入框各 **约 73px**（看得到 5 个字）、
// 下单时间格 276px 要装两个日期框 + 「至」⇒ 每个日期框 **约 80px，只显示得出「2026」**。
// 而 1440 恰是最常见的笔记本宽度 ⇒ 病根是**「不可换行的单行布局」**这个形态本身：
// grid 的单行轨道只会把格压小，不会换行；`flex-1` 的格若没有 `min-w-[…]`，也一样会被压到 0。
//
// ## ⇒ 本文件钉住的四条形态判据（命中即红）
//   ① **每一行都必须可换行**：查询区的行容器必须带 `flex-wrap`（`grid-cols-*` 的单行布局不可换行 ⇒ 红）；
//   ② **每个字段格必须有固定 `min-w-[…]`**（`flex-1` 且无最小宽 ⇒ 会被压到 0 ⇒ 红）；
//   ③ 控件本身不得同时带 `flex-1` 与**固定长度**的 `min-w-[<N>px|rem|em]`（缩不下去、撑爆所在格 ⇒ 红）；
//   ④ 若查询区**又出现** `grid-cols-…` 行，其 `fr` 轨道必须写成 `minmax(0,…)`（防 A 类回潮）。
//
// ## 回归时会怎么红（不是空断言：判据 ⑥ 用小样本反证三个检测器都有效）
//   · 把任一行改回 `grid grid-cols-1 xl:grid-cols-[…]` ⇒ 判据 ① 红并打印该行类名；
//   · 去掉某个字段格的 `min-w-[…]` ⇒ 判据 ② 红并打印该格；
//   · 给任一输入框加回 `min-w-[130px]` ⇒ 判据 ③ 红并打印该元素；
//   · 把某条轨道写回裸 `1fr` ⇒ 判据 ④ 红；
//   · 删光查询区的行 / 字段格 / 控件 ⇒ 判据 ⑤ 红（fail-closed，避免 ①②③④ 在空集上假绿）。
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

// ── 判据实现（纯函数；判据 ⑥ 直接喂坏样本，反证「检测器非空转」）──────────────

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

/** 判据 ④：`grid-cols-…` 里的不可收缩 `fr` 轨道（A 类坏形态的检测器）。 */
export function bareFrTracks(className: string): string[] {
  const bad: string[] = []
  for (const token of String(className ?? '').split(/\s+/)) {
    const m = /^(?:[a-z0-9-]+:)*grid-cols-(.+)$/.exec(token)
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

/** 判据 ①：一行容器是否**不可换行**（`grid-cols-…` 单行布局；`flex` 但缺 `flex-wrap` 同样不可换行）。 */
export function nonWrappingRowProblems(className: string): string[] {
  const cls = String(className ?? '')
  const tokens = cls.split(/\s+/)
  const hasGridCols = tokens.some((t) => /^(?:[a-z0-9-]+:)*grid-cols-/.test(t))
  const isFlex = tokens.some((t) => /^(?:[a-z0-9-]+:)*flex$/.test(t))
  const hasWrap = tokens.some((t) => /^(?:[a-z0-9-]+:)*flex-wrap$/.test(t))
  if (hasGridCols) return [`用了不可换行的 grid 行（grid 的单行轨道只会把格压小，不会换行）`]
  if (isFlex && !hasWrap) return [`flex 行缺 flex-wrap（窄屏只能压扁，不会换行）`]
  return []
}

/** 判据 ②：字段格有没有**固定长度**的 `min-w-[…]`（没有 ⇒ `flex-1` 会把它压到 0）。 */
export function hasFixedMinWidth(className: string): boolean {
  return /(?:^|\s)(?:[a-z0-9-]+:)*min-w-\[[0-9.]+(?:px|rem|em)\]/.test(String(className ?? ''))
}

/** 判据 ③：控件同时带 `flex-1` 与固定长度 `min-w-[…]` ⇒ 缩不下去。 */
export function fixedMinWidthControls(el: Element): string[] {
  const cls = typeof el.className === 'string' ? el.className : ''
  if (!/(?:^|\s)(?:[a-z0-9-]+:)*flex-1(?:\s|$)/.test(cls)) return []
  return (cls.match(/(?:^|\s)(?:[a-z0-9-]+:)*min-w-\[[0-9.]+(?:px|rem|em)\]/g) ?? []).map((s) => s.trim())
}

const QUERY_AREA = '[data-testid="search-area"]'

function queryArea(): HTMLElement {
  const el = document.querySelector(QUERY_AREA)
  if (!el) throw new Error('查询区不存在（data-testid="search-area"）—— 判据会在空集上假绿，故直接判红')
  return el as HTMLElement
}

/** 查询区的每一**行**容器 = 查询区的直接子元素（页面就是两行） */
function queryRows(): Element[] {
  return [...queryArea().children]
}

/** 行里的**字段格** = 该行直接子元素中「含表单控件」的那些（按钮格不含控件 ⇒ 不在此列） */
function fieldCells(root: Element): Element[] {
  return [...root.children].filter((el) => el.querySelector('input, select, textarea') !== null)
}

function rowsWithGrid(): Element[] {
  return [...queryArea().querySelectorAll('[class*="grid-cols-"]')]
}

function queryControls(): Element[] {
  return [...queryArea().querySelectorAll('input, select, textarea')]
}

describe('订单列表查询区 · 窄屏不溢出、也不压窄（issue #5841 / #5850）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetOrders.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
  })

  it('① 查询区每一行都必须可换行（flex-wrap），不得用不可换行的单行 grid', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    const bad = queryRows().flatMap((row) =>
      nonWrappingRowProblems(row.className).map((why) => `${why} —— class="${row.className}"`)
    )
    expect(bad).toEqual([])
  })

  it('② 每个字段格必须有固定 min-w-[…]（否则 flex-1 会把它压到不可读 / 压到 0）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    const cells = queryRows().flatMap((row) => fieldCells(row))
    expect(cells.length).toBeGreaterThanOrEqual(6) // fail-closed：字段格找不到 ⇒ 判据会在空集上假绿
    const bad = cells
      .filter((el) => !hasFixedMinWidth(el.className))
      .map((el) => `字段格 ${el.className || '(无类名)'} 缺 min-w-[…]`)
    expect(bad).toEqual([])
  })

  it('③ 查询区表单控件不得同时带 flex-1 与固定 min-w-[…]（缩不下去 = 撑爆所在格）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    const bad = queryControls().flatMap((el) =>
      fixedMinWidthControls(el).map((cls) => `${el.tagName.toLowerCase()}[${cls}] = ${el.className}`)
    )
    expect(bad).toEqual([])
  })

  it('④ 防 A 类回潮：查询区若又出现 grid 行，其 fr 轨道必须是 minmax(0,…)', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    const bad = rowsWithGrid().flatMap((g) => bareFrTracks(g.className))
    expect(bad).toEqual([])
  })

  it('⑤ fail-closed：行 / 字段格 / 控件确实存在（删光即红，防止 ①~④ 在空集上假绿）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    expect(queryRows().length).toBeGreaterThanOrEqual(2) // 第一行 3 格 + 第二行 4 格 + 按钮格
    expect(queryRows().flatMap((r) => fieldCells(r)).length).toBeGreaterThanOrEqual(6)
    // 查询区应有 8 个控件：订单ID / 收货人 / 制单人 / 起止日期 ×2 / 商品货号 / 商品标题 / 是否加工
    expect(queryControls().length).toBeGreaterThanOrEqual(8)
  })

  it('⑥ 反空跑：三个检测器对坏形态必报、对好形态不报（否则 ①②③④ 是空断言）', () => {
    // ── 坏形态（两代缺陷的真实类名）──
    expect(nonWrappingRowProblems(
      'grid grid-cols-1 xl:grid-cols-[minmax(0,1.8fr)_minmax(0,1fr)_auto] gap-x-6'
    )).toHaveLength(1)
    expect(nonWrappingRowProblems('flex items-center gap-x-6')).toHaveLength(1) // 缺 flex-wrap
    expect(hasFixedMinWidth('flex items-center gap-2 flex-1')).toBe(false)
    expect(hasFixedMinWidth('flex items-center gap-2 flex-1 min-w-[180px]')).toBe(true)
    expect(bareFrTracks('grid grid-cols-1 md:grid-cols-[repeat(4,1fr)_auto] gap-x-6')).toHaveLength(4)
    expect(bareFrTracks('grid grid-cols-1 md:grid-cols-[1fr_1fr_1.5fr] gap-x-6')).toHaveLength(3)

    // ── 好形态（本次修法）──
    expect(nonWrappingRowProblems('flex flex-wrap items-center gap-x-6 gap-y-4')).toEqual([])
    expect(bareFrTracks('grid grid-cols-1 xl:grid-cols-[minmax(0,1.8fr)_minmax(0,1fr)_auto]')).toEqual([])
    expect(bareFrTracks('grid grid-cols-1 gap-4')).toEqual([]) // grid-cols-1 = minmax(0,1fr)
    expect(bareFrTracks('flex flex-1 min-w-[130px]')).toEqual([]) // 非 grid 类名不报

    const badInput = document.createElement('input')
    badInput.className = 'flex-1 min-w-[130px] h-9 border'
    expect(fixedMinWidthControls(badInput)).toEqual(['min-w-[130px]'])
    const goodInput = document.createElement('input')
    goodInput.className = 'flex-1 min-w-0 h-9 border'
    expect(fixedMinWidthControls(goodInput)).toEqual([])
  })
})
