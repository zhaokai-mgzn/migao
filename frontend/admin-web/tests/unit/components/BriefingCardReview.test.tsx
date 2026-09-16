// case_ids: UI-019, UI-030
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

describe('BriefingCard 昨日回顾 ReviewStrip（#3888：弱化绝对值、保留环比）', () => {
  beforeEach(() => {
    getToday.mockReset()
    getConfig.mockReset()
  })

  const renderWithReview = async (review: BriefingContent['review']) => {
    getToday.mockResolvedValue({
      data: {
        data: {
          generated: true,
          verifyStatus: 'verified',
          content: { summary: '', review, todo: [], risks: [], suggestions: [] },
          bizDate: '2026-09-14',
        },
      },
    })
    render(<BriefingCard enabled />)
    await waitFor(() => expect(screen.getByText('昨日回顾')).toBeInTheDocument())
  }

  it('有 change（环比）→ 主展示环比、不渲染绝对值（#3888 数字重叠修复）', async () => {
    await renderWithReview([{ label: '订单量', value: 123, unit: '单', change: '较昨日 +66.7%' }])

    // 环比为主展示
    expect(screen.getByText('较昨日 +66.7%')).toBeInTheDocument()
    // 涨跌色：上升 → 绿色（与 StatCard 涨跌口径一致）
    expect(screen.getByText('较昨日 +66.7%')).toHaveClass('text-green-600')
    // 绝对值不再重复展示
    expect(screen.queryByText('123')).not.toBeInTheDocument()
    // label 保留
    expect(screen.getByText('订单量')).toBeInTheDocument()
  })

  it('有 change 且为下跌 → 红色涨跌色', async () => {
    await renderWithReview([{ label: '销售额', value: 12, unit: '元', change: '较昨日 -12.3%' }])

    expect(screen.getByText('较昨日 -12.3%')).toHaveClass('text-red-600')
    // 绝对值（含千分位）不展示
    expect(screen.queryByText('12')).not.toBeInTheDocument()
  })

  it('无 change → 保留原值兜底（value + unit，避免丢信息）', async () => {
    await renderWithReview([{ label: '解决率', value: 92.5, unit: '%' }])

    expect(screen.getByText('92.5')).toBeInTheDocument()
    expect(screen.getByText('%')).toBeInTheDocument()
    expect(screen.getByText('解决率')).toBeInTheDocument()
  })
})
