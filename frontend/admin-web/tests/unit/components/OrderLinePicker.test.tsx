// case_ids: OR-048, OR-008
/**
 * 选品面板（`components/image-recognize/OrderLinePicker.tsx`）—— 订单侧「明细 → 候选 → 选品 → 建行」
 * 的**必经一步**（issue #5345）。
 *
 * 为什么必须有本文件（除了判据本身）：面板是**唯一**能让商家把「图上写的商品名」对应到
 * 「目录里的商品」的地方 —— 它错了，下游一行都不会对（单价 / 门幅 / 用料都挂在所选 SKU 上）。
 *
 * 本文件钉住的四件事（其余在页面 / 纯函数侧，见 `orders-new-image-lines.test.tsx`、`order-line-match.test.ts`）：
 * 1. **候选可解释**：每个候选旁边就是它的理由（用户读得到），并按传入顺序（= 纯函数排好的序）渲染；
 * 2. **「都不是」恒在**（匹配不到时的唯一出口）且**排在末位**；
 * 3. **面板只回调、不自己建行**：点候选 ⇒ `onPick(entry, productId)`；已处理的条目**不再有按钮**
 *    （防重复建行）；空 `entries` ⇒ 面板不渲染（Modal 关）；
 * 4. **钱面口径在界面上可见**：图上写的价只标成「行价取自目录 / SKU（识别的价格不是真值）」。
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import OrderLinePicker, { type PickerEntryState } from '@/components/image-recognize/OrderLinePicker'
import { NO_MATCH_CHOICE, NO_MATCH_LABEL, type DetailEntry, type LineCandidate } from '@/lib/order-line-match'

const ENTRY: DetailEntry = { name: '雪尼尔遮光窗帘', quantity: 2, priceHint: '120元/米' }

const CANDIDATES: LineCandidate[] = [
  {
    productId: 'p1',
    productName: '雪尼尔遮光窗帘',
    score: 1.55,
    reason: '名称包含「雪尼尔遮光窗帘」（重合 7/7 字）；规格命中：材质「雪尼尔」',
  },
  {
    productId: 'p2',
    productName: '棉麻窗帘',
    score: 0.22,
    reason: '名称相似：与「棉麻窗帘」重合 2/9 字（重合 2/9 字）',
  },
]

/** 「都不是」选项（与纯函数给的那一条同源；本文件不另编文案） */
const NONE: LineCandidate = { productId: NO_MATCH_CHOICE, productName: NO_MATCH_LABEL, score: 0, reason: '都不是 / 匹配不到 ⇒ 不建行（明细留在备注，可照旧手工选商品）' }

/** 一条明细的面板状态（顺序 = 纯函数给的顺序：候选在前、「都不是」在末位） */
function entryState(over: Partial<PickerEntryState> = {}): PickerEntryState {
  return { entry: ENTRY, options: [...CANDIDATES, NONE], loading: false, resolved: null, ...over }
}

/** 该条目的选项按钮（按 DOM 顺序 —— 顺序本身就是判据：候选在前、「都不是」在末位） */
function optionIds(index: number): string[] {
  return Array.from(
    document.querySelectorAll(`[data-testid^="order-line-picker-option-${index}-"]`),
  ).map((el) => el.getAttribute('data-testid') || '')
}

describe('OrderLinePicker — 选品面板只给候选、只回调（#5345）', () => {
  it('判据 2：每个候选旁边就是它的理由（用户读得到的相似度 / 规格命中）', () => {
    render(
      <OrderLinePicker entries={[entryState()]} onPick={vi.fn()} onSkipAll={vi.fn()} onClose={vi.fn()} />,
    )

    const first = screen.getByTestId('order-line-picker-reason-0-p1')
    expect(first.textContent).toContain('重合 7/7 字')
    expect(first.textContent).toContain('规格命中：材质「雪尼尔」')
    const second = screen.getByTestId('order-line-picker-reason-0-p2')
    expect(second.textContent).toContain('重合 2/9 字')
    // 两条候选都在（不是只给第一名）
    expect(optionIds(0)).toHaveLength(3)
  })

  it('判据 1：「都不是」恒在，且**排在末位**（候选前缀 + 出口后缀）', () => {
    render(
      <OrderLinePicker entries={[entryState()]} onPick={vi.fn()} onSkipAll={vi.fn()} onClose={vi.fn()} />,
    )

    const ids = optionIds(0)
    expect(ids[ids.length - 1]).toBe(`order-line-picker-option-0-${NO_MATCH_CHOICE}`)
    expect(ids.slice(0, -1)).toEqual(['order-line-picker-option-0-p1', 'order-line-picker-option-0-p2'])
    // 匹配不到时（零候选）也必须有这个出口
    render(
      <OrderLinePicker
        entries={[entryState({ options: [NONE] })]}
        onPick={vi.fn()}
        onSkipAll={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getAllByTestId(`order-line-picker-option-0-${NO_MATCH_CHOICE}`).length).toBeGreaterThan(0)
  })

  it('判据 1/4：点候选只**回调**（带条目与商品 id），不自己建任何东西', () => {
    const onPick = vi.fn()
    render(
      <OrderLinePicker entries={[entryState()]} onPick={onPick} onSkipAll={vi.fn()} onClose={vi.fn()} />,
    )

    fireEvent.click(screen.getByTestId('order-line-picker-option-0-p1'))
    expect(onPick).toHaveBeenCalledTimes(1)
    expect(onPick).toHaveBeenCalledWith(ENTRY, 'p1')

    fireEvent.click(screen.getByTestId(`order-line-picker-option-0-${NO_MATCH_CHOICE}`))
    expect(onPick).toHaveBeenLastCalledWith(ENTRY, NO_MATCH_CHOICE)
  })

  it('判据 7：已处理的条目显示处置结果，且**按钮消失**（同一条不会被重复建行）', () => {
    const { unmount } = render(
      <OrderLinePicker
        entries={[entryState({ resolved: { productId: 'p1', label: '雪尼尔遮光窗帘' } })]}
        onPick={vi.fn()}
        onSkipAll={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByTestId('order-line-picker-resolved-0').textContent).toContain('已建订单行：雪尼尔遮光窗帘')
    expect(screen.queryByTestId('order-line-picker-option-0-p1')).toBeNull()
    unmount()

    render(
      <OrderLinePicker
        entries={[entryState({ resolved: { productId: NO_MATCH_CHOICE, label: NO_MATCH_LABEL } })]}
        onPick={vi.fn()}
        onSkipAll={vi.fn()}
        onClose={vi.fn()}
      />,
    )
    expect(screen.getByTestId('order-line-picker-resolved-0').textContent).toContain('已跳过')
  })

  it('判据 6（界面侧）：图上写的价只标成复核提示（行价取自目录 / SKU）', () => {
    render(
      <OrderLinePicker entries={[entryState()]} onPick={vi.fn()} onSkipAll={vi.fn()} onClose={vi.fn()} />,
    )
    const hint = screen.getByTestId('order-line-picker-price-hint-0').textContent || ''
    expect(hint).toContain('120元/米')
    expect(hint).toContain('行价一律取自目录 / SKU')
  })

  it('候选还在查 ⇒ 不给假候选（只显示"匹配中"）；「都不建行」⇒ 只回调', () => {
    const onSkipAll = vi.fn()
    render(
      <OrderLinePicker
        entries={[entryState({ options: [], loading: true })]}
        onPick={vi.fn()}
        onSkipAll={onSkipAll}
        onClose={vi.fn()}
      />,
    )
    expect(optionIds(0)).toEqual([])
    expect(screen.getByTestId('order-line-picker-entry-0').textContent).toContain('正在匹配目录里的商品')
    fireEvent.click(screen.getByTestId('order-line-picker-skip-all'))
    expect(onSkipAll).toHaveBeenCalledTimes(1)
  })

  it('没有待选明细 ⇒ 面板不渲染（页面据此"处理完就关"）', () => {
    render(<OrderLinePicker entries={[]} onPick={vi.fn()} onSkipAll={vi.fn()} onClose={vi.fn()} />)
    expect(screen.queryByTestId('order-line-picker')).toBeNull()
  })
})