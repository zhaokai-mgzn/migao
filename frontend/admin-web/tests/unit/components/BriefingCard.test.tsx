// case_ids: DA-001, DA-002, ST-001
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

// Mock next/link（简报卡里 todo/risks/suggestions 用 Link 做一键直达）
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

// Mock briefing API（企业开关 + 今日简报）
const getToday = vi.fn()
const getConfig = vi.fn()
vi.mock('@/lib/api', () => ({
  briefingApi: {
    getToday: () => getToday(),
    getConfig: () => getConfig(),
  },
}))

import BriefingCard from '@/components/dashboard/BriefingCard'
import type { BriefingContent } from '@/types'

const mockContent: BriefingContent = {
  summary: '昨日订单 5 单，经营平稳',
  review: [{ label: '今日订单', value: 5, unit: '单', change: '较昨日 +66.7%' }],
  todo: [
    {
      priority: 'high',
      title: '10 个订单待发货',
      reason: '超过发货时效',
      link: '/orders?status=待发货',
      metrics: [{ key: 'pending_ship_orders', value: 10 }],
    },
  ],
  risks: [],
  suggestions: [
    {
      title: '补充知识库',
      detail: 'AI 无法回答 TOP 问题较多',
      link: '/knowledge',
      metrics: [{ key: 'total_tickets', value: 2 }],
    },
  ],
}

describe('BriefingCard（智能每日经营简报卡，issue #3468）', () => {
  beforeEach(() => {
    getToday.mockReset()
    getConfig.mockReset()
  })

  it('开关关闭 → 整卡不渲染（红线 3：菜单/首页同时隐藏）', () => {
    render(<BriefingCard enabled={false} />)
    expect(screen.queryByText('每日经营简报')).not.toBeInTheDocument()
  })

  it('已生成 → 渲染四区块 + summary + 一键直达链接', async () => {
    getToday.mockResolvedValue({
      data: { data: { generated: true, verifyStatus: 'verified', content: mockContent, bizDate: '2026-09-14' } },
    })
    render(<BriefingCard enabled />)

    await waitFor(() => expect(screen.getByText('每日经营简报')).toBeInTheDocument())
    // summary 可见（结果可见断言，非函数调用级）
    expect(screen.getByText('昨日订单 5 单，经营平稳')).toBeInTheDocument()
    // 四区块标题
    expect(screen.getByText('昨日回顾')).toBeInTheDocument()
    expect(screen.getByText('今日必办')).toBeInTheDocument()
    expect(screen.getByText('优化建议')).toBeInTheDocument()
    // 待办条目 + 一键直达链接（断言用户可见的成果物与跳转目标）
    expect(screen.getByText('10 个订单待发货')).toBeInTheDocument()
    const todoLink = screen.getByText('10 个订单待发货').closest('a')
    expect(todoLink).toHaveAttribute('href', '/orders?status=待发货')
    // 优化建议 + 直达知识库
    expect(screen.getByText('补充知识库')).toBeInTheDocument()
    expect(screen.getByText('补充知识库').closest('a')).toHaveAttribute('href', '/knowledge')
  })

  it('未生成 → 引导空态（不展示假数据，红线 4）', async () => {
    getToday.mockResolvedValue({
      data: { data: { generated: false, verifyStatus: null, content: null, bizDate: null } },
    })
    render(<BriefingCard enabled />)

    await waitFor(() => expect(screen.getByText('今日简报尚未生成')).toBeInTheDocument())
    expect(screen.queryByText('昨日订单 5 单')).not.toBeInTheDocument()
  })

  it('生成失败（failed）→ 安全提示而非编造内容', async () => {
    getToday.mockResolvedValue({
      data: { data: { generated: true, verifyStatus: 'failed', content: null, bizDate: '2026-09-14' } },
    })
    render(<BriefingCard enabled />)

    await waitFor(() => expect(screen.getByText(/未通过数字校验/)).toBeInTheDocument())
  })

  it('content 为空对象（failed 落库形态）→ 不崩溃，展示安全提示（UI 旅程实证回归）', async () => {
    // 后端 failed 时 content={}（空对象）：修复前渲染期对 undefined.length 崩溃
    getToday.mockResolvedValue({
      data: { data: { generated: true, verifyStatus: 'failed', content: {}, bizDate: '2026-09-14' } },
    })
    render(<BriefingCard enabled />)

    await waitFor(() => expect(screen.getByText(/未通过数字校验/)).toBeInTheDocument())
    // 不崩溃 = 页面主体仍在
    expect(screen.getByText('每日经营简报')).toBeInTheDocument()
  })

  it('接口异常 → 降级为空态，不影响页面主体', async () => {
    getToday.mockRejectedValue(new Error('network'))
    render(<BriefingCard enabled />)

    await waitFor(() => expect(screen.getByText('今日简报尚未生成')).toBeInTheDocument())
  })
})
