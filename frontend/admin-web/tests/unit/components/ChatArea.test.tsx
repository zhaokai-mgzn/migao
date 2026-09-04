// case_ids: UI-006
/**
 * ChatArea 组件测试 — 洞察抽屉开关链路 + 已结束会话续聊 banner
 *
 * 覆盖：会话头部栏渲染、抽屉默认收起、点击洞察按钮展开、点击遮罩关闭、
 * 已结束会话顶部「会话已结束」banner 渲染、点击「继续此会话」调用 reopenSession 并聚焦输入框。
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

// ─── Mutable mock state ───────────────────────────

const mockUseChatStore = vi.fn()

// ─── Module mocks ─────────────────────────────────

vi.mock('@/store/chat', () => {
  const fn = (...args: any[]) => mockUseChatStore(...args)
  return {
    useChatStore: Object.assign(fn, { getState: () => mockUseChatStore() }),
  }
})

vi.mock('@/components/chat/MessageList', () => ({ default: () => <div data-testid="message-list" /> }))

// MessageInput mock 渲染真实 textarea（带 id，供「继续此会话」聚焦断言）
vi.mock('@/components/chat/MessageInput', () => ({
  default: () => <textarea id="chat-message-input" data-testid="message-input" readOnly />,
}))
vi.mock('@/components/chat/QuickActions', () => ({ default: () => <div data-testid="quick-actions" /> }))

// SessionInsight mock 暴露 isOpen / onClose props，便于断言抽屉开关
vi.mock('@/components/chat/SessionInsight', () => ({
  default: ({ isOpen, onClose }: { isOpen?: boolean; onClose?: () => void }) => (
    <div data-testid="session-insight" data-open={String(Boolean(isOpen))} onClick={onClose} />
  ),
}))

import ChatArea from '@/components/chat/ChatArea'

function makeDefaultChatState(overrides: Record<string, unknown> = {}) {
  return {
    currentSessionId: 's1',
    sessions: [
      { session_id: 's1', title: '客户咨询', status: 'active', updated_at: '2025-01-01' },
    ],
    reopenSession: vi.fn().mockResolvedValue(undefined),
    closeSession: vi.fn(),
    sendMessage: vi.fn(),
    ...overrides,
  }
}

describe('ChatArea', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseChatStore.mockReturnValue(makeDefaultChatState())
  })

  it('渲染会话头部栏：会话标题 + 状态标签', () => {
    render(<ChatArea />)
    expect(screen.getByText('客户咨询')).toBeInTheDocument()
    expect(screen.getByText('进行中')).toBeInTheDocument()
  })

  it('默认洞察抽屉收起（isOpen=false）', () => {
    render(<ChatArea />)
    expect(screen.getByTestId('session-insight')).toHaveAttribute('data-open', 'false')
  })

  it('点击洞察按钮展开抽屉', () => {
    render(<ChatArea />)
    fireEvent.click(screen.getByTestId('insight-toggle-btn'))
    expect(screen.getByTestId('session-insight')).toHaveAttribute('data-open', 'true')
  })

  it('点击遮罩（onClose）关闭抽屉', () => {
    render(<ChatArea />)
    fireEvent.click(screen.getByTestId('insight-toggle-btn'))
    expect(screen.getByTestId('session-insight')).toHaveAttribute('data-open', 'true')

    fireEvent.click(screen.getByTestId('session-insight'))
    expect(screen.getByTestId('session-insight')).toHaveAttribute('data-open', 'false')
  })

  // ── 已结束会话续聊 banner ──

  it('查看已结束会话时显示「会话已结束」banner + 继续此会话按钮', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        sessions: [
          { session_id: 's1', title: '旧对话', status: 'closed', updated_at: '2025-01-01' },
        ],
      })
    )
    render(<ChatArea />)

    expect(screen.getByTestId('closed-session-banner')).toBeInTheDocument()
    expect(screen.getByText('会话已结束，历史消息已保留')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '继续此会话' })).toBeInTheDocument()
  })

  it('活跃会话不显示续聊 banner', () => {
    render(<ChatArea />)
    expect(screen.queryByTestId('closed-session-banner')).not.toBeInTheDocument()
  })

  it('点击「继续此会话」调用 reopenSession 并聚焦输入框', async () => {
    const reopenSession = vi.fn().mockResolvedValue(undefined)
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({
        sessions: [
          { session_id: 's1', title: '旧对话', status: 'closed', updated_at: '2025-01-01' },
        ],
        reopenSession,
      })
    )
    render(<ChatArea />)

    fireEvent.click(screen.getByRole('button', { name: '继续此会话' }))

    await waitFor(() => expect(reopenSession).toHaveBeenCalledWith('s1'))
    await waitFor(() => {
      expect(document.activeElement).toBe(screen.getByTestId('message-input'))
    })
  })
})
