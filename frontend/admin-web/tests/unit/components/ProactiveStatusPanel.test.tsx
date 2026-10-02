// case_ids: DA-021
import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'

import ProactiveStatusPanel from '@/components/dashboard/ProactiveStatusPanel'
import type { ProactiveStatus } from '@/types'

/** 未接线 + 已接线并存：同一个面板里两种说法必须都在，且不可互换。 */
const MIXED: ProactiveStatus = {
  repeat_returns: {
    rule_id: 'repeat_returns',
    rule_name: '连续退货',
    status: 'not_wired',
    reason: '快照未提供 returns 行数组（装配层未接线）',
    missing: ['returns'],
    gaps: [],
    caveats: [],
  },
  low_stock: {
    rule_id: 'low_stock',
    rule_name: '库存告急',
    status: 'wired',
    reason: null,
    missing: [],
    gaps: [],
    caveats: [],
  },
}

describe('ProactiveStatusPanel（主动检查 · 逐规则四态，issue #5955）', () => {
  it('每规则一行：状态 + 原因；未接线与「已检查、无命中」分开说', () => {
    render(<ProactiveStatusPanel status={MIXED} variant="page" />)

    // 具名报出规则（不是「今天没问题」）
    expect(screen.getByText('连续退货')).toBeInTheDocument()
    expect(screen.getByText('库存告急')).toBeInTheDocument()
    // 「没检查」与「查了没问题」在同一面板里各有各的说法
    expect(screen.getByText('系统尚未接入')).toBeInTheDocument()
    expect(screen.getByText('已检查、无命中')).toBeInTheDocument()
    // 原因在场
    expect(screen.getByText('快照未提供 returns 行数组（装配层未接线）')).toBeInTheDocument()
    // 未接线那一行**不许**被盖上「已检查、无命中」
    const row = screen.getByText('连续退货').closest('li') as HTMLElement
    expect(row.textContent).toContain('系统尚未接入')
    expect(row.textContent).not.toContain('已检查、无命中')
  })

  it('聚合口径明说「不等于今天没问题」，且不装成「全部已检查」', () => {
    render(<ProactiveStatusPanel status={MIXED} variant="page" />)

    expect(screen.getByText(/1 项本次没有检查/)).toBeInTheDocument()
    expect(screen.getByText(/不等于「今天没问题」/)).toBeInTheDocument()
    expect(screen.queryByText('全部已检查，无命中')).not.toBeInTheDocument()
  })

  it('规则齐全且无命中 → 「全部已检查，无命中」，且无任何未接线/没开启措辞', () => {
    render(<ProactiveStatusPanel status={{ low_stock: MIXED.low_stock }} variant="page" />)

    expect(screen.getByText('全部已检查，无命中')).toBeInTheDocument()
    expect(screen.getByText('已检查、无命中')).toBeInTheDocument()
    expect(screen.queryByText('系统尚未接入')).not.toBeInTheDocument()
    expect(screen.queryByText('你还没开启')).not.toBeInTheDocument()
    expect(screen.queryByText('本次数据不完整')).not.toBeInTheDocument()
    expect(screen.queryByText(/本次没有检查/)).not.toBeInTheDocument()
  })

  it('wired 的规则其 caveats（数据源固有边界）也必须在场 —— 不许因为「绿」就不显示边界', () => {
    render(
      <ProactiveStatusPanel
        status={{
          price_change_over: {
            rule_id: 'price_change_over',
            rule_name: '改价幅度超阈值',
            status: 'wired',
            reason: null,
            missing: [],
            gaps: [],
            caveats: ['审计上报是 fail-open（3s 硬上限、允许丢行）⇒ 本项可能漏报'],
          },
        }}
        variant="page"
      />,
    )

    expect(screen.getByText('已检查、无命中')).toBeInTheDocument()
    expect(screen.getByText(/边界：.*fail-open/)).toBeInTheDocument()
  })

  it('not_enabled（可行动）与 not_wired（不可行动）分开说，且各自带原因', () => {
    render(
      <ProactiveStatusPanel
        status={{
          below_cost_price: {
            rule_id: 'below_cost_price',
            rule_name: '低于成本价的订单',
            status: 'not_enabled',
            reason: '你还没开启成本核算（快照 cost_accounting=false）⇒ 本次未判定；录入入库单价后即可开启',
            missing: [],
            gaps: [],
            caveats: [],
          },
          repeat_returns: MIXED.repeat_returns,
        }}
        variant="page"
      />,
    )

    expect(screen.getByText('你还没开启')).toBeInTheDocument()
    expect(screen.getByText('系统尚未接入')).toBeInTheDocument()
    expect(screen.getByText(/录入入库单价后即可开启/)).toBeInTheDocument()
    expect(screen.getByText(/2 项本次没有检查/)).toBeInTheDocument()
  })

  it('不完整（incomplete）有自己的说法 + 原因', () => {
    render(
      <ProactiveStatusPanel
        status={{
          unshipped_overdue: {
            rule_id: 'unshipped_overdue',
            rule_name: '超 N 天未发货',
            status: 'incomplete',
            reason: 'orders 数组已被行数上限截断（上限 500 行，本次给出 500 行）⇒ 结论不完整',
            missing: [],
            gaps: ['orders 数组已被行数上限截断'],
            caveats: [],
          },
        }}
        variant="page"
      />,
    )

    expect(screen.getByText('本次数据不完整')).toBeInTheDocument()
    expect(screen.getByText(/行数上限截断/)).toBeInTheDocument()
  })

  it('未采集（null / 空表）→ 不渲染：未知 ≠ 没问题，也不许用空壳冒充「已检查」', () => {
    const { container: c1 } = render(<ProactiveStatusPanel status={null} variant="page" />)
    expect(c1.textContent).toBe('')

    const { container: c2 } = render(<ProactiveStatusPanel status={{}} variant="page" />)
    expect(c2.textContent).toBe('')

    const { container: c3 } = render(<ProactiveStatusPanel variant="page" />)
    expect(c3.textContent).toBe('')
  })

  it('卡片面只读：面板内无任何按钮 / 链接（不给「一键处置」入口）', () => {
    const { container } = render(<ProactiveStatusPanel status={MIXED} variant="page" />)

    expect(within(container).queryAllByRole('button')).toHaveLength(0)
    expect(container.querySelectorAll('a')).toHaveLength(0)
  })

  it('dashboard 形态：非绿行给原因，绿行只在表内、不额外铺开原因', () => {
    const { container } = render(<ProactiveStatusPanel status={MIXED} variant="dashboard" />)

    expect(container.textContent).toContain('连续退货')
    expect(container.textContent).toContain('快照未提供 returns 行数组（装配层未接线）')
    expect(container.textContent).toContain('已检查、无命中')
  })
})
