// case_ids: CH-008, CH-017
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

// lucide-react mock — 页面使用 Bot/MessageSquare/Send
vi.mock('lucide-react', () => {
  const stub = (name: string) => (props: any) => <span data-testid={`icon-${name}`} {...props} />
  return {
    Bot: stub('bot'),
    MessageSquare: stub('message-square'),
    Send: stub('send'),
  }
})

const { getSessionsMock, getSessionMock } = vi.hoisted(() => ({
  getSessionsMock: vi.fn(),
  getSessionMock: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  agentSessionApi: {
    getSessions: (...args: any[]) => getSessionsMock(...args),
    getSession: (...args: any[]) => getSessionMock(...args),
  },
}))

import HumanAgentSessionsPage from '@/app/(dashboard)/agent-workspace/human-sessions/page'

function listResolve(items: any[]) {
  return Promise.resolve({ data: { success: true, data: { items, total: items.length } } })
}

function detailResolve(detail: any) {
  return Promise.resolve({ data: { success: true, data: detail } })
}

const baseSession = {
  id: 'as-1',
  customerId: 'cust-1',
  customerName: '张先生',
  aiSessionId: 'ai-1',
  status: 'waiting' as const,
  priority: 1,
  reason: '窗帘色差',
  queuePosition: 0,
  createdAt: '2026-09-01T10:00:00Z',
  startedAt: '2026-09-01T10:00:00Z',
}

const detailWithAiContext = {
  ...baseSession,
  status: 'active',
  aiContextSummary: '顾客反馈窗帘色差，要求人工处理',
  aiContext: [
    { role: 'user', content: '窗帘有色差吗？' },
    { role: 'assistant', content: '正在为您核实，请稍候。' },
  ],
  messages: [
    {
      id: 'msg-1',
      senderType: 'agent',
      senderId: 'emp-1',
      senderName: '客服小王',
      contentType: 'text',
      content: '您好，我是人工客服，已看到您之前和 AI 客服的沟通，我来帮您处理。',
      isInternal: false,
      createdAt: '2026-09-01T10:01:00Z',
    },
  ],
}

const detailWithoutAiContext = {
  ...baseSession,
  aiContextSummary: null,
  aiContext: null,
  messages: [
    {
      id: 'msg-2',
      senderType: 'agent',
      senderId: 'emp-1',
      senderName: '客服小王',
      contentType: 'text',
      content: '您好，请问有什么可以帮您？',
      isInternal: false,
      createdAt: '2026-09-01T10:01:00Z',
    },
  ],
}

describe('人工客服工作台 - 转人工前 AI 对话上下文展示（GB/T 47746-2026, issue #2776）', () => {
  beforeEach(() => {
    getSessionsMock.mockReset()
    getSessionMock.mockReset()
  })

  it('会话含 aiContext 时展示 AI 对话分区 + 摘要 + 人工接待分隔，人工消息照常渲染', async () => {
    getSessionsMock.mockResolvedValue(listResolve([baseSession]))
    getSessionMock.mockResolvedValue(detailResolve(detailWithAiContext))

    render(<HumanAgentSessionsPage />)

    // 等待会话列表加载 → 点击会话
    await waitFor(() => expect(getSessionsMock).toHaveBeenCalled())
    fireEvent.click(screen.getByText('张先生'))

    // AI 上下文分区（标题/摘要/角色标注/内容）
    expect(await screen.findByText(/顾客与 AI 客服（小布）的对话 · 转人工前/)).toBeInTheDocument()
    expect(screen.getByText(/📋 对话摘要：顾客反馈窗帘色差，要求人工处理/)).toBeInTheDocument()
    expect(screen.getByText('小布 · AI')).toBeInTheDocument()
    expect(screen.getByText('窗帘有色差吗？')).toBeInTheDocument()
    expect(screen.getByText('正在为您核实，请稍候。')).toBeInTheDocument()
    // 人工接待分隔
    expect(screen.getByText(/以下为人工接待记录/)).toBeInTheDocument()
    // 人工客服消息仍正常展示
    expect(screen.getByText(/您好，我是人工客服/)).toBeInTheDocument()
  })

  it('会话无 aiContext（老会话/空快照）时不渲染 AI 分区，页面正常', async () => {
    getSessionsMock.mockResolvedValue(listResolve([baseSession]))
    getSessionMock.mockResolvedValue(detailResolve(detailWithoutAiContext))

    render(<HumanAgentSessionsPage />)

    await waitFor(() => expect(getSessionsMock).toHaveBeenCalled())
    fireEvent.click(screen.getByText('张先生'))

    await waitFor(() => expect(getSessionMock).toHaveBeenCalled())
    expect(screen.queryByText(/顾客与 AI 客服（小布）的对话 · 转人工前/)).not.toBeInTheDocument()
    expect(screen.queryByText(/以下为人工接待记录/)).not.toBeInTheDocument()
    // 人工消息正常
    expect(screen.getByText(/您好，请问有什么可以帮您/)).toBeInTheDocument()
  })
})
