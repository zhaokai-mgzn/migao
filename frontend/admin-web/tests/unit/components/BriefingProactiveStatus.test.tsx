// case_ids: DA-021
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

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
import type { BriefingContent, ProactiveStatus } from '@/types'

const content: BriefingContent = {
  summary: '昨日订单 5 单，经营平稳',
  review: [],
  todo: [],
  risks: [],
  suggestions: [],
}

/** 判据 1 的形态：某规则**没有数据**（引擎落 `not_wired` + 诊断原因 + 商家话术）—— 卡片面必须具名报出。 */
const NOT_WIRED: ProactiveStatus = {
  repeat_returns: {
    rule_id: 'repeat_returns',
    rule_name: '连续退货',
    status: 'not_wired',
    reason: '快照未提供 returns 行数组（装配层未接线）',
    missing: ['returns'],
    gaps: [],
    caveats: [],
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

describe('BriefingCard 的协议接线（issue #5955）', () => {
  beforeEach(() => {
    getToday.mockReset()
  })

  it('接口返回 proactive_status → 卡片面具名报出「本次没有检查」+ 商家话术（不抛诊断原文）', async () => {
    mockToday(NOT_WIRED)
    render(<BriefingCard enabled variant="page" />)

    await waitFor(() => expect(screen.getByText('连续退货')).toBeInTheDocument())
    expect(screen.getByText('本次没有检查')).toBeInTheDocument()
    // 🔴 商家面只读引擎给的 display；诊断面（reason/caveats）不上屏（§31 P3/P4）
    expect(screen.getByText('这项检查还没有可用数据，本次没有执行')).toBeInTheDocument()
    expect(screen.queryByText(/装配层/)).not.toBeInTheDocument()
    // 「没检查」与「查了没问题」在同一张卡里可分（后者只进汇总）
    expect(screen.getByText(/1 项本次没有结果/)).toBeInTheDocument()
    expect(screen.queryByText('库存告急')).not.toBeInTheDocument()
  })

  it('接口未给 proactive_status（旧版后端 / 未采集）→ 不渲染面板：未知 ≠ 没问题', async () => {
    mockToday(undefined)
    render(<BriefingCard enabled variant="page" />)

    await waitFor(() => expect(screen.getByText('昨日订单 5 单，经营平稳')).toBeInTheDocument())
    expect(screen.queryByText('主动检查')).not.toBeInTheDocument()
    expect(screen.queryByText('全部已检查，无命中')).not.toBeInTheDocument()
  })

  it('接口显式给 null（存量行未采集）→ 同样不渲染面板', async () => {
    mockToday(null)
    render(<BriefingCard enabled variant="page" />)

    await waitFor(() => expect(screen.getByText('昨日订单 5 单，经营平稳')).toBeInTheDocument())
    expect(screen.queryByText('主动检查')).not.toBeInTheDocument()
  })

  it('日报没有可执行条目时，兜底文案不替主动检查下「经营平稳」的结论', async () => {
    mockToday(NOT_WIRED)
    render(<BriefingCard enabled variant="page" />)

    await waitFor(() => expect(screen.getByText('连续退货')).toBeInTheDocument())
    // 没有 todo/risks/suggestions ⇒ 出现兜底句；它必须把「有没有问题」交回给主动检查面板
    expect(screen.getByText(/是否代表「没问题」请看上方「主动检查」/)).toBeInTheDocument()
  })
})
