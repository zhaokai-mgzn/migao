// case_ids: DA-021
import { describe, it, expect } from 'vitest'
import { render, screen, within } from '@testing-library/react'

import ProactiveStatusPanel from '@/components/dashboard/ProactiveStatusPanel'
import type { ProactiveStatus } from '@/types'

/**
 * 未检查 + 已检查并存：两种说法必须都在，且已检查的不逐条铺开（§31 P1/P2）。
 * 🔴 `reason` / `caveats` 是诊断面（文件路径 / issue 号 / 列名）—— **不许上屏**（§31 P3）。
 */
const MIXED: ProactiveStatus = {
  repeat_returns: {
    rule_id: 'repeat_returns',
    rule_name: '连续退货',
    status: 'not_wired',
    reason: '快照未提供 returns 行数组（装配层未接线）',
    missing: ['returns'],
    gaps: [],
    caveats: ['审计上报是 fail-open（3s 硬上限）⇒ 本项可能漏报'],
    display: '这项检查还没有可用数据，本次没有执行',
  },
  low_stock: {
    rule_id: 'low_stock',
    rule_name: '库存告急',
    status: 'wired',
    reason: null,
    missing: [],
    gaps: [],
    caveats: [],
    display: null,
  },
}

describe('ProactiveStatusPanel（主动检查 · 逐规则四态，issue #5955 / #7195）', () => {
  it('只列「本次没有结果」的规则：具名 + 状态标签 + 商家话术', () => {
    render(<ProactiveStatusPanel status={MIXED} variant="page" />)

    const row = screen.getByText('连续退货').closest('li') as HTMLElement
    expect(within(row).getByText('本次没有检查')).toBeInTheDocument()
    expect(within(row).getByText('这项检查还没有可用数据，本次没有执行')).toBeInTheDocument()
    // 「查了没问题」不再逐条念一遍（§31 P2）—— 它只进汇总
    expect(screen.queryByText('库存告急')).not.toBeInTheDocument()
  })

  it('汇总口径明说「不代表没问题」，且不装成「全部已检查」', () => {
    render(<ProactiveStatusPanel status={MIXED} variant="page" />)

    expect(screen.getByText(/1 项本次没有结果/)).toBeInTheDocument()
    expect(screen.getByText(/不代表没问题/)).toBeInTheDocument()
    expect(screen.queryByText('全部已检查，无命中')).not.toBeInTheDocument()
  })

  it('🔴 诊断面不上屏：reason / caveats 的原文（含内部标识）一个字都不许出现', () => {
    const { container } = render(<ProactiveStatusPanel status={MIXED} variant="page" />)

    const text = container.textContent || ''
    expect(text).not.toContain('装配层')
    expect(text).not.toContain('fail-open')
    expect(text).not.toContain('快照')
    expect(text).not.toContain('行数组')
  })

  it('全部已检查 → 一行收口，无逐条列表', () => {
    const { container } = render(
      <ProactiveStatusPanel status={{ low_stock: MIXED.low_stock }} variant="page" />,
    )

    expect(screen.getByText('全部已检查，无命中')).toBeInTheDocument()
    expect(container.querySelectorAll('li')).toHaveLength(0)
    expect(screen.queryByText(/本次没有结果/)).not.toBeInTheDocument()
  })

  it('not_enabled（可行动）与 not_wired（没有数据）分开说，各自带商家指引', () => {
    render(
      <ProactiveStatusPanel
        status={{
          below_cost_price: {
            rule_id: 'below_cost_price',
            rule_name: '低于成本价的订单',
            status: 'not_enabled',
            reason: '你还没开启成本核算（快照 cost_accounting=false）⇒ 本次未判定',
            missing: [],
            gaps: [],
            caveats: [],
            display: '在商品入库时录入单价（成本），录完就能检查这一项',
          },
          repeat_returns: MIXED.repeat_returns,
        }}
        variant="page"
      />,
    )

    expect(screen.getByText('还没开启')).toBeInTheDocument()
    expect(screen.getByText('本次没有检查')).toBeInTheDocument()
    expect(screen.getByText('在商品入库时录入单价（成本），录完就能检查这一项')).toBeInTheDocument()
    expect(screen.getByText(/2 项本次没有结果/)).toBeInTheDocument()
  })

  it('incomplete 有自己的说法 + 商家话术（不把截断原文抛给商家）', () => {
    render(
      <ProactiveStatusPanel
        status={{
          unshipped_overdue: {
            rule_id: 'unshipped_overdue',
            rule_name: '超时未发货',
            status: 'incomplete',
            reason: 'orders 数组已被行数上限截断（上限 500 行）⇒ 结论不完整',
            missing: [],
            gaps: ['orders 数组已被行数上限截断'],
            caveats: [],
            display: '本次数据不完整，可能有遗漏',
          },
        }}
        variant="page"
      />,
    )

    expect(screen.getByText('数据不完整')).toBeInTheDocument()
    expect(screen.getByText('本次数据不完整，可能有遗漏')).toBeInTheDocument()
    expect(screen.queryByText(/行数上限截断/)).not.toBeInTheDocument()
  })

  it('旧载荷（无 display）→ 只显示状态标签，不拿 reason 顶替', () => {
    const { container } = render(
      <ProactiveStatusPanel
        status={{
          low_stock: {
            rule_id: 'low_stock',
            rule_name: '库存告急',
            status: 'not_wired',
            reason: '快照未提供 skus 行数组（装配层未接线）',
            missing: ['skus'],
            gaps: [],
            caveats: [],
          },
        }}
        variant="page"
      />,
    )

    expect(screen.getByText('本次没有检查')).toBeInTheDocument()
    expect(container.textContent).not.toContain('装配层')
  })

  it('未采集（null / 空表 / 缺省）→ 不渲染：未知 ≠ 没问题，也不许用空壳冒充「已检查」', () => {
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
})
