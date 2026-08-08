/**
 * ChatArea 组件测试 — 洞察抽屉开关链路
 *
 * 覆盖：会话头部栏渲染、抽屉默认收起、点击洞察按钮展开、点击遮罩关闭。
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

// ─── Module mocks ─────────────────────────────────

vi.mock('@/store/chat', () => ({
  useChatStore: () => ({
    currentSessionId: 's1',
    sessions: [
      { session_id: 's1', title: '客户咨询', status: 'active' },
    ],
    sendMessage: vi.fn(),
  }),
}))

vi.mock('@/components/chat/MessageList', () => ({ default: () => <div data-testid="message-list" /> }))
vi.mock('@/components/chat/MessageInput', () => ({ default: () => <div data-testid="message-input" /> }))
vi.mock('@/components/chat/QuickActions', () => ({ default: () => <div data-testid="quick-actions" /> }))

// SessionInsight mock 暴露 isOpen / onClose props，便于断言抽屉开关
vi.mock('@/components/chat/SessionInsight', () => ({
  default: ({ isOpen, onClose }: { isOpen?: boolean; onClose?: () => void }) => (
    <div data-testid="session-insight" data-open={String(Boolean(isOpen))} onClick={onClose} />
  ),
}))

import ChatArea from '@/components/chat/ChatArea'

describe('ChatArea', () => {
  beforeEach(() => { vi.clearAllMocks() })

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
})
