// case_ids: DA-004
/**
 * agent-workspace/sessions — 会话管理工作台（客服中心 / 会话管理）
 *
 * 会话管理重构落地页：把占位页改造成真实会话管理工作台。
 * 复用已重构的 SessionService API（chatApi，ai-agent-service /api/chat/*）：
 *   - 顶部监控统计条：活跃 / 已关闭 / 总数（从 store.sessions 派生）
 *   - 主体复用 /chat 组件链：SessionList（会话列表）+ ChatArea（聊天 + 会话洞察抽屉）
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

// ── Mock chat store（提供真实形状的 sessions 数据，派生统计）──
const mockFetchSessions = vi.fn()
const mockSessions = [
  { session_id: 's1', title: '会话一', status: 'active', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z' },
  { session_id: 's2', title: '会话二', status: 'active', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z' },
  { session_id: 's3', title: '会话三', status: 'closed', created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z' },
]

vi.mock('@/store/chat', () => ({
  useChatStore: () => ({
    sessions: mockSessions,
    fetchSessions: mockFetchSessions,
    currentSessionId: null,
    messages: [],
    isStreaming: false,
    isLoadingSessions: false,
    isLoadingMessages: false,
    searchKeyword: '',
    quickActions: [],
    isLoadingQuickActions: false,
    error: null,
    createSession: vi.fn(),
    selectSession: vi.fn(),
    sendMessage: vi.fn(),
    closeSession: vi.fn(),
    reopenSession: vi.fn(),
    setSearchKeyword: vi.fn(),
    stopStreaming: vi.fn(),
    clearCurrentSession: vi.fn(),
    fetchQuickActions: vi.fn(),
  }),
}))

// ── Mock 复用的组件链（本测试聚焦页面组合 + 统计派生）──
vi.mock('@/components/chat/SessionList', () => ({
  default: () => <div data-testid="session-list">SessionList</div>,
}))
vi.mock('@/components/chat/ChatArea', () => ({
  default: () => <div data-testid="chat-area">ChatArea</div>,
}))

import AgentSessionsPage from '@/app/(dashboard)/agent-workspace/sessions/page'

describe('AgentSessionsPage — 会话管理工作台', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('进入页面时拉取会话列表', () => {
    render(<AgentSessionsPage />)
    expect(mockFetchSessions).toHaveBeenCalled()
  })

  it('顶部统计条展示活跃 / 已关闭 / 总会话数（从 store 派生）', () => {
    render(<AgentSessionsPage />)
    expect(screen.getByText('活跃')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('已关闭')).toBeInTheDocument()
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('共')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('复用会话列表 + 聊天区组件链', () => {
    render(<AgentSessionsPage />)
    expect(screen.getByTestId('session-list')).toBeInTheDocument()
    expect(screen.getByTestId('chat-area')).toBeInTheDocument()
  })

  it('页面标题为「会话管理」', () => {
    render(<AgentSessionsPage />)
    expect(screen.getByRole('heading', { name: '会话管理' })).toBeInTheDocument()
  })
})
