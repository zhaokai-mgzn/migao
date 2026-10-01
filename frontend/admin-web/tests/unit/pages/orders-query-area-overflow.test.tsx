// case_ids: UI-075
//
// UI-075（issue #5841）：订单列表**查询区**不得出现横向溢出（第二行的「查询/重置/刷新」被挤出卡片）。
//
// ## 为什么是「类级形态判据」而不是像素判据
// jsdom **没有布局引擎** —— `getBoundingClientRect()` 恒返回 0、`scrollWidth` 恒等于 0，
// 在这里量「溢出多少 px」只会得到一份永远为 0 的假读数（= 空断言）。所以本文件钉的是
// **产生溢出的那个类名形态**，而像素读数由真实浏览器复核（见 PR body 的读数表）。
//
// ## 被钉住的坏形态（实测归因，issue #5841）
// 查询区第二行用 `grid md:grid-cols-[repeat(4,1fr)_auto]`。CSS 里 `1fr` = `minmax(auto, 1fr)`，
// **轨道最小尺寸 = 该格内容的 min-content，不可收缩**；实测各格 min-content =
// 下单时间 380px（label 4.5em + 2×`min-w-[130px]` 日期输入 + 「至」+ 间隙）·商品货号 251px·
// 商品标题 251px·是否加工 141px·按钮列 228px ⇒ grid 内容合计 **1347px**，
// 而卡片内容宽只有「视口 - 380」（1440 时 = 1060）⇒ 溢出 287px、按钮被顶出卡片。
// （注：四条 `1fr` 轨道**并非**等宽 —— 实测 380/251/251/141，各自等于本格 min-content；
//   等宽只是「各格最小尺寸恰好相同」时的特例，不是本缺陷的机制。）
//
// ⇒ 两条**形态**判据（命中即红）：
//   ① 查询区任何 `grid-cols-…` 的 `fr` 轨道必须写成 `minmax(0, …)`（可收缩）；
//      裸 `1fr` / `repeat(n,1fr)` ⇒ 红。
//   ② 查询区的表单控件（input/select/textarea）不得同时带 `flex-1` 与**固定长度**的
//      `min-w-[<N>px|rem|em]` ⇒ 红（控件缩不下去，会把所在轨道顶到内容最小宽度，同样溢到卡片外）。
//      实测先例 = 两个日期输入的 `min-w-[130px]`。
//
// ## 回归时会怎么红（不是空断言：判据 ④ 用小样本反证检测器有效）
//   · 把第二行类名改回 `md:grid-cols-[repeat(4,1fr)_auto]` ⇒ 判据 ① 红并打印该类名；
//   · 把第一行改回 `md:grid-cols-[1fr_1fr_1.5fr]` ⇒ 判据 ① 红（**同类缺陷的第二处实例**：
//     实测 768~1100 视口下第一行自己就溢出 41~173px，doc 级横向滚动条由它贡献）；
//   · 给任一输入框加回 `min-w-[130px]` ⇒ 判据 ② 红并打印该元素；
//   · 删光查询区 grid / 控件 ⇒ 判据 ③ 红（fail-closed，避免判据 ①② 在空集上假绿）。
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

// ── 判据实现（纯函数；判据 ④ 直接喂坏样本，反证「检测器非空转」）──────────────

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

/** 判据 ①：`grid-cols-…` 里的不可收缩 `fr` 轨道。 */
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

/** 判据 ②：控件同时带 `flex-1` 与固定长度 `min-w-[…]` ⇒ 缩不下去。 */
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

function queryGrids(): Element[] {
  return [...queryArea().querySelectorAll('[class*="grid-cols-"]')]
}

function queryControls(): Element[] {
  return [...queryArea().querySelectorAll('input, select, textarea')]
}

describe('订单列表查询区 · 不产生横向溢出（issue #5841）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetOrders.mockResolvedValue({ data: { data: { items: [], total: 0 } } })
  })

  it('① 查询区每条 grid 的 fr 轨道都可收缩（minmax(0,…)），不得有裸 1fr', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    const bad = queryGrids().flatMap((g) => bareFrTracks(g.className))
    expect(bad).toEqual([]) // 命中即红：打印出具体类名，可直接定位到那一行
  })

  it('② 查询区表单控件不得同时带 flex-1 与固定 min-w-[…]（缩不下去 = 撑爆轨道）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    const bad = queryControls().flatMap((el) =>
      fixedMinWidthControls(el).map((cls) => `${el.tagName.toLowerCase()}[${cls}] = ${el.className}`)
    )
    expect(bad).toEqual([])
  })

  it('③ fail-closed：查询区 grid / 控件确实存在（删光即红，防止 ①② 在空集上假绿）', async () => {
    render(<OrdersPage />)
    await waitFor(() => expect(mockGetOrders).toHaveBeenCalled())

    expect(queryGrids().length).toBeGreaterThanOrEqual(2)
    // 查询区应有 8 个控件：订单ID / 收货人 / 制单人 / 起止日期 ×2 / 商品货号 / 商品标题 / 是否加工
    expect(queryControls().length).toBeGreaterThanOrEqual(8)
  })

  it('④ 反空跑：检测器对坏形态必报、对好形态不报（否则 ①② 是空断言）', () => {
    // 坏形态 = 本次缺陷的两处实例（改前 HEAD 逐字）
    expect(bareFrTracks('grid grid-cols-1 md:grid-cols-[repeat(4,1fr)_auto] gap-x-6')).toHaveLength(4)
    expect(bareFrTracks('grid grid-cols-1 md:grid-cols-[1fr_1fr_1.5fr] gap-x-6')).toHaveLength(3)
    expect(bareFrTracks('grid grid-cols-1 md:grid-cols-[minmax(auto,1fr)_auto]')).toHaveLength(1)
    // 好形态 = 本次修法（不报）
    expect(bareFrTracks('grid grid-cols-1 xl:grid-cols-[minmax(0,1.8fr)_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_auto]')).toEqual([])
    expect(bareFrTracks('grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.5fr)]')).toEqual([])
    // `grid-cols-1` = repeat(1, minmax(0,1fr)) ⇒ 不报；非 grid 类名也不报
    expect(bareFrTracks('grid grid-cols-1 gap-4')).toEqual([])
    expect(bareFrTracks('flex flex-1 min-w-[130px]')).toEqual([])

    const badInput = document.createElement('input')
    badInput.className = 'flex-1 min-w-[130px] h-9 border'
    expect(fixedMinWidthProblems(badInput)).toEqual(['min-w-[130px]'])
    const goodInput = document.createElement('input')
    goodInput.className = 'flex-1 min-w-0 h-9 border'
    expect(fixedMinWidthProblems(goodInput)).toEqual([])
  })
})

/** 判据 ④ 用的别名（与 `fixedMinWidthControls` 同一实现，避免两套判定）。 */
function fixedMinWidthProblems(el: Element): string[] {
  return fixedMinWidthControls(el)
}
