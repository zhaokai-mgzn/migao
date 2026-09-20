// case_ids: PP-011
// PP-011（issue #4696，P1）：「未定价」显式可见块 —— 未定价 ≠ ¥0.00。
//
// 缺陷原形：未定价的报工在**算钱的地方**被静默折成 0 元，界面只在**读面徽标**上说「未定价」
// ⇒ 工人白干且无人知道，且「没定价」与「价本来就是 0」不可区分。
// 本组件把三件事摆到真正算钱的页面上：① 未定价工序的合格数量；② 逐条工序名；③ 定价入口。
import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import UnpricedNotice, { PRICING_ENTRY_HREF } from '@/components/production/UnpricedNotice'
import type { UnpricedPiecework } from '@/types'

/** 后端 `unpriced` 块（per-order 汇总 / 期间报表同形） */
const unpriced: UnpricedPiecework = {
  qty: 7,
  operations: [
    // `operation` = 工人端快照名（变体名）；界面必须渲染 `logical_name · position`
    { operation: '配料-布料', logical_name: '配料', position: '布料', qty: 5 },
    { operation: '打包', logical_name: '打包', position: null, qty: 2 },
  ],
  hint: '以下工序未定价（≠ ¥0.00，已从计件合计中排除）',
}

describe('UnpricedNotice（issue #4696）', () => {
  it('渲染未定价工序数、合计数量与逐条工序（显示名 = 逻辑名 · 部位，不渲染变体名）', () => {
    render(<UnpricedNotice unpriced={unpriced} />)

    expect(screen.getByTestId('piecework-unpriced-title')).toHaveTextContent('2 道工序未定价')
    expect(screen.getByTestId('piecework-unpriced-detail')).toHaveTextContent('7')
    expect(screen.getByTestId('piecework-unpriced-name-0')).toHaveTextContent('配料 · 布料')
    expect(screen.getByTestId('piecework-unpriced-0')).toHaveTextContent('未定价')
    expect(screen.getByTestId('piecework-unpriced-0')).toHaveTextContent('5')
    // 部位无关工序：显示名只含逻辑名（**不拼空部位**，不出现分隔符）
    expect(screen.getByTestId('piecework-unpriced-name-1')).toHaveTextContent('打包')
    expect(screen.getByTestId('piecework-unpriced-name-1').textContent).not.toContain('·')
    // 变体名（工人端快照名）**不得**出现在界面上（issue #4621/#4630 同一份纪律）
    expect(screen.getByTestId('piecework-unpriced').textContent).not.toContain('配料-布料')
  })

  it('给出**定价入口**（指向工艺配置 → 工艺路线 · 部位价目矩阵）', () => {
    render(<UnpricedNotice unpriced={unpriced} />)

    const link = screen.getByTestId('piecework-unpriced-pricing-link')
    expect(link).toHaveAttribute('href', PRICING_ENTRY_HREF)
    expect(PRICING_ENTRY_HREF).toBe('/production/routings')
    expect(link).toHaveTextContent('去定价')
  })

  it('零条未定价 ⇒ 不渲染任何东西（不制造噪音）', () => {
    const { container } = render(<UnpricedNotice unpriced={{ qty: 0, operations: [] }} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('未定价块缺省（老后端 / 老 bundle）⇒ 不渲染、不抛错', () => {
    const { container } = render(<UnpricedNotice unpriced={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('反向护栏：**价 0** 的账不进本块（本块只表达「未定价」）', () => {
    // 「价 0」在计件面是 `per_operation` 里一笔 ¥0.00 的账，而不是未定价清单的一项
    render(<UnpricedNotice unpriced={{ qty: 0, operations: [], hint: 'x' }} />)
    expect(screen.queryByTestId('piecework-unpriced')).not.toBeInTheDocument()
    expect(screen.queryByTestId('piecework-unpriced-pricing-link')).not.toBeInTheDocument()
  })

  it('数量逐条渲染（合计 = 各条之和，商家可核对「干了多少活没算钱」）', () => {
    render(<UnpricedNotice unpriced={unpriced} />)
    const list = screen.getByTestId('piecework-unpriced-list')
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(items[0]).toHaveTextContent('5')
    expect(items[1]).toHaveTextContent('2')
  })
})
