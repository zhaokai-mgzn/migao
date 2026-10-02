// case_ids: DA-021
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'

// Mock next/link（简报卡内 todo/risks/suggestions 用 Link 做一键直达）
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

const getToday = vi.fn()
vi.mock('@/lib/api', () => ({
  briefingApi: {
    getToday: () => getToday(),
  },
}))

import BriefingCard from '@/components/dashboard/BriefingCard'
import ProactiveStatusPanel from '@/components/dashboard/ProactiveStatusPanel'
import type { BriefingContent, ProactiveStatus } from '@/types'

const content: BriefingContent = {
  summary: '昨日订单 5 单，经营平稳',
  review: [],
  todo: [],
  risks: [],
  suggestions: [],
}

/** 判据 1 的快照形态：某规则**未接线**（引擎落 not_wired + 原因）—— 卡片面必须具名报出。 */
const NOT_WIRED: ProactiveStatus = {
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

/** 判据 2 的快照形态：规则齐全且无命中（全部 wired）。 */
const ALL_WIRED: ProactiveStatus = {
  repeat_returns: {
    rule_id: 'repeat_returns',
    rule_name: '连续退货',
    status: 'wired',
    reason: null,
    missing: [],
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

/** 判据 3：`wired` 的规则其 `caveats`（数据源固有边界，如审计 fail-open）也必须在场。 */
const WIRED_WITH_CAVEAT: ProactiveStatus = {
  price_change_over: {
    rule_id: 'price_change_over',
    rule_name: '改价幅度超阈值',
    status: 'wired',
    reason: null,
    missing: [],
    gaps: [],
    caveats: ['审计上报是 fail-open（3s 硬上限、允许丢行）⇒ 本项**可能漏报**'],
  },
}

function mockToday(proactive_status: ProactiveStatus | null | undefined) {
  getToday.mockResolvedValue({
    data: {
      data: {
        generated: true,
        verifyStatus: 'verified',
        content,
        bizDate: '2026-10-02',
        ...(proactive_status === undefined ? {} : { proactive_status }),
      },
    },
  })
}

describe('日报卡片面 proactive 四态可视化（issue #5955）', () => {
  beforeEach(() => {
    getToday.mockReset()
  })

  it('判据 1：某规则未接线 → 卡片面具名报出该规则 + 原因（不是「今天没问题」）', async () => {
    mockToday(NOT_WIRED)
    render(<BriefingCard enabled variant="page" />)

    await waitFor(() => expect(screen.getByText('连续退货')).toBeInTheDocument())
    // 「没检查」必须与「查了没问题」长得不一样：同一个面板里两种措辞并存
    expect(screen.getByText('系统尚未接入')).toBeInTheDocument()
    expect(screen.getByText('已检查、无命中')).toBeInTheDocument()
    // 原因在场（消费方据此知道「为什么没有提示」）
    expect(screen.getByText('快照未提供 returns 行数组（装配层未接线）')).toBeInTheDocument()
    // 未接线的那一行**只有**它自己的说法：不许被盖上「已检查、无命中」（两个说法不可互换）
    const row = screen.getByText('连续退货').closest('li') as HTMLElement
    expect(row.textContent).toContain('系统尚未接入')
    expect(row.textContent).not.toContain('已检查、无命中')
    // 聚合口径明说「不等于今天没问题」——「没检查」不许被读成「没问题」
    expect(screen.getByText(/1 项本次没有检查/)).toBeInTheDocument()
    expect(screen.getByText(/不等于「今天没问题」/)).toBeInTheDocument()
    // 有非绿项时面板不装成「全部已检查」
    expect(screen.queryByText('全部已检查，无命中')).not.toBeInTheDocument()
  })

  it('判据 2：规则齐全且无命中 → 「已检查、无命中」，且与判据 1 在 UI 上可分', async () => {
    mockToday(ALL_WIRED)
    render(<BriefingCard enabled variant="page" />)

    await waitFor(() => expect(screen.getByText('全部已检查，无命中')).toBeInTheDocument())
    expect(screen.getAllByText('已检查、无命中')).toHaveLength(2)
    // 互斥红：此形态下**不得**出现任何「未接入 / 没开启 / 不完整」的措辞
    expect(screen.queryByText('系统尚未接入')).not.toBeInTheDocument()
    expect(screen.queryByText('你还没开启')).not.toBeInTheDocument()
    expect(screen.queryByText('本次数据不完整')).not.toBeInTheDocument()
    expect(screen.queryByText(/本次没有检查/)).not.toBeInTheDocument()
  })

  it('判据 3：wired 的规则其 caveats（数据源固有边界）也必须在场', async () => {
    mockToday(WIRED_WITH_CAVEAT)
    render(<BriefingCard enabled variant="page" />)

    await waitFor(() => expect(screen.getByText('改价幅度超阈值')).toBeInTheDocument())
    expect(screen.getByText('已检查、无命中')).toBeInTheDocument()
    // 不许因为「绿」就不显示边界
    expect(screen.getByText(/边界：.*fail-open/)).toBeInTheDocument()
  })

  it('not_enabled（可行动）与 not_wired（不可行动）分开说，且 not_enabled 给开启引导', async () => {
    mockToday({
      below_cost_price: {
        rule_id: 'below_cost_price',
        rule_name: '低于成本价的订单',
        status: 'not_enabled',
        reason: '你还没开启成本核算（快照 cost_accounting=false）⇒ 本次未判定；录入入库单价后即可开启',
        missing: [],
        gaps: [],
        caveats: [],
      },
      repeat_returns: NOT_WIRED.repeat_returns,
    })
    render(<BriefingCard enabled variant="page" />)

    await waitFor(() => expect(screen.getByText('你还没开启')).toBeInTheDocument())
    expect(screen.getByText('系统尚未接入')).toBeInTheDocument()
    expect(screen.getByText(/收录入库单价后即可开启|录入入库单价后即可开启/)).toBeInTheDocument()
    expect(screen.getByText(/2 项本次没有检查/)).toBeInTheDocument()
  })

  it('未采集（proactive_status 为 null）→ 不渲染面板：未知 ≠ 没问题，也不许用空壳冒充「已检查」', async () => {
    mockToday(null)
    const { container } = render(<BriefingCard enabled variant="page" />)

    await waitFor(() => expect(screen.getByText('昨日订单 5 单，经营平稳')).toBeInTheDocument())
    expect(screen.queryByText('主动检查（逐规则）')).not.toBeInTheDocument()
    expect(container.textContent).not.toContain('全部已检查')
  })

  it('卡片面只读：面板不给任何处置入口（无按钮/无链接）', () => {
    const { container } = render(<ProactiveStatusPanel status={NOT_WIRED} variant="page" />)

    expect(within(container).queryAllByRole('button')).toHaveLength(0)
    expect(container.querySelectorAll('a')).toHaveLength(0)
  })

  it('看板首页形态（dashboard）：非绿行给原因，绿行只留在表内不额外铺开', () => {
    const { container } = render(<ProactiveStatusPanel status={NOT_WIRED} variant="dashboard" />)

    expect(container.textContent).toContain('连续退货')
    expect(container.textContent).toContain('快照未提供 returns 行数组（装配层未接线）')
    // 绿行仍**在**（四态可见），只是不给它铺开的原因噪音
    expect(container.textContent).toContain('已检查、无命中')
  })
})
