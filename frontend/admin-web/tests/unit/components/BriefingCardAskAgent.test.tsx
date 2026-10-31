// case_ids: DA-029, DA-032
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

// 简报条目用 next/link 做一键直达
vi.mock('next/link', () => ({
  default: ({ children, href, ...props }: any) => <a href={href} {...props}>{children}</a>,
}))

const getToday = vi.fn()
const getConfig = vi.fn()
const recordAction = vi.fn()
vi.mock('@/lib/api', () => ({
  briefingApi: {
    getToday: () => getToday(),
    getConfig: () => getConfig(),
  },
}))

// 决策采纳记录（issue #8260）—— 独立模块：`lib/api.ts` 是冻结文件，新增接口不进它
vi.mock('@/lib/briefing-actions', () => ({
  briefingActionApi: { record: (data: any) => recordAction(data) },
}))

import BriefingCard from '@/components/dashboard/BriefingCard'
import { useChatStore } from '@/store/chat'
import type { BriefingContent } from '@/types'

const content: BriefingContent = {
  summary: '昨日订单 5 单，经营平稳',
  review: [],
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
  // 🔴 无 link 的条目：恰恰是「页面没地方可去」的那一类，最需要把问题交给黄金策
  suggestions: [
    {
      title: '补充知识库',
      detail: 'AI 无法回答 TOP 问题较多',
      metrics: [{ key: 'total_tickets', value: 2 }],
    },
  ],
}

async function renderCard() {
  recordAction.mockReset()
  recordAction.mockResolvedValue({ data: { data: { recorded: true } } })
  getToday.mockResolvedValue({
    data: { data: { generated: true, verifyStatus: 'verified', content, bizDate: '2026-10-31' } },
  })
  render(<BriefingCard enabled />)
  await waitFor(() => expect(screen.getByText('每日经营简报')).toBeInTheDocument())
}

describe('简报条目 → 问黄金策（issue #8236，DA-029）', () => {
  beforeEach(() => {
    getToday.mockReset()
    getConfig.mockReset()
    useChatStore.setState({ assistantOpen: false, assistantDraft: null })
  })

  it('有 link 的条目渲染「问黄金策」按钮（一键直达之外还有一条执行路径）', async () => {
    await renderCard()

    expect(screen.getByRole('button', { name: '问黄金策：10 个订单待发货' })).toBeInTheDocument()
  })

  it('无 link 的条目同样有入口（建议类条目不再无路可走）', async () => {
    await renderCard()

    expect(screen.getByRole('button', { name: '问黄金策：补充知识库' })).toBeInTheDocument()
  })

  it('点击 → 打开浮窗，且预置问题带上该条目的标题与上下文', async () => {
    await renderCard()

    fireEvent.click(screen.getByRole('button', { name: '问黄金策：补充知识库' }))

    const state = useChatStore.getState()
    expect(state.assistantOpen).toBe(true)
    expect(state.assistantDraft).toContain('补充知识库')
    // 预置问题要能落成「查数据 + 给建议 + 批量确认卡」，不是一句空泛的「帮我看看」
    expect(state.assistantDraft).toContain('处理建议')
    expect(state.assistantDraft).toContain('确认卡')

    // 🔴 上报（issue #8260）：点开 = opened_agent —— 只表示「点开问了」，**不表示**「照着做了」
    await waitFor(() => expect(recordAction).toHaveBeenCalledWith({
      bizDate: '2026-10-31',
      itemKind: 'suggestion',
      title: '补充知识库',
      action: 'opened_agent',
    }))
  })

  it('上报失败**不影响**浮窗打开（fire-and-forget：用户点的是「问黄金策」，不是「记日志」）', async () => {
    recordAction.mockRejectedValue(new Error('网络炸了'))
    await renderCard()

    fireEvent.click(screen.getByRole('button', { name: '问黄金策：补充知识库' }))

    const state = useChatStore.getState()
    expect(state.assistantOpen).toBe(true)
    expect(state.assistantDraft).toContain('补充知识库')
  })

  it('草稿取一次即消费（防严格模式/重渲染重复发送）', async () => {
    await renderCard()

    fireEvent.click(screen.getByRole('button', { name: '问黄金策：10 个订单待发货' }))

    expect(useChatStore.getState().consumeAssistantDraft()).toContain('10 个订单待发货')
    expect(useChatStore.getState().consumeAssistantDraft()).toBeNull()
  })

  it('关闭浮窗 → assistantOpen=false（外部入口不改变关闭语义）', async () => {
    await renderCard()

    fireEvent.click(screen.getByRole('button', { name: '问黄金策：补充知识库' }))
    useChatStore.getState().closeAssistant()

    expect(useChatStore.getState().assistantOpen).toBe(false)
  })
})
