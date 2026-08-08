/**
 * FloatingAssistant 组件测试 — 重构后版本
 *
 * 覆盖：FAB 打开/关闭、最小化/还原、标题栏按钮
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

// Mock dependencies
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}))

vi.mock('@/components/icons/MibaoLogo', () => ({
  MibaoLogo: ({ size }: { size: number }) => <span data-testid="mibao-logo" data-size={size}>🤖</span>,
}))

vi.mock('@/lib/utils', () => ({ cn: (...args: any[]) => args.filter(Boolean).join(' ') }))

// Mock chat store
const mockFetchSessions = vi.fn()
vi.mock('@/store/chat', () => {
  const fn = () => ({
    fetchSessions: mockFetchSessions,
    sessions: [],
    currentSessionId: null,
    messages: [],
    isStreaming: false,
    isLoadingSessions: false,
    isLoadingMessages: false,
  })
  return { useChatStore: Object.assign(fn, { getState: () => fn() }) }
})

// Mock chat components
vi.mock('@/components/chat/SessionList', () => ({ default: () => <div data-testid="session-list">SessionList</div> }))
vi.mock('@/components/chat/ChatArea', () => ({ default: () => <div data-testid="chat-area">ChatArea</div> }))

import FloatingAssistant from '@/components/ai-assistant/FloatingAssistant'

describe('FloatingAssistant', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    Element.prototype.scrollIntoView = vi.fn()
  })

  it('默认状态下只显示 FAB 按钮', () => {
    render(<FloatingAssistant />)

    expect(screen.getByTitle('打开米宝')).toBeInTheDocument()
    expect(screen.queryByText('米宝 · 智能助手')).not.toBeInTheDocument()
  })

  it('点击 FAB 打开面板，正常态单栏聊天，全屏才显示会话列表', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开米宝'))

    // 面板标题可见
    expect(screen.getByText('米宝 · 智能助手')).toBeInTheDocument()
    // 正常浮动：单栏（仅聊天区，聚焦对话，避免窄窗两栏挤压）
    expect(screen.getByTestId('chat-area')).toBeInTheDocument()
    expect(screen.queryByTestId('session-list')).not.toBeInTheDocument()
    // 全屏后显示会话列表（两栏）
    fireEvent.click(screen.getByTitle('全屏'))
    expect(screen.getByTestId('session-list')).toBeInTheDocument()
    // FAB 在面板打开时隐藏
    expect(screen.queryByTitle('打开米宝')).not.toBeInTheDocument()
  })

  it('点击关闭按钮收起面板', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开米宝'))
    expect(screen.getByText('米宝 · 智能助手')).toBeInTheDocument()

    fireEvent.click(screen.getByTitle('关闭'))
    expect(screen.queryByText('米宝 · 智能助手')).not.toBeInTheDocument()
  })

  it('打开面板时自动加载会话列表', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开米宝'))

    expect(mockFetchSessions).toHaveBeenCalled()
  })
})
