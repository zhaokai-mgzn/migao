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
vi.mock('@/components/chat/SessionInsight', () => ({ default: () => <div data-testid="session-insight">SessionInsight</div> }))

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

  it('点击 FAB 打开面板，显示三栏布局', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开米宝'))

    // 面板标题可见
    expect(screen.getByText('米宝 · 智能助手')).toBeInTheDocument()
    // 三栏布局可见
    expect(screen.getByTestId('session-list')).toBeInTheDocument()
    expect(screen.getByTestId('chat-area')).toBeInTheDocument()
    expect(screen.getByTestId('session-insight')).toBeInTheDocument()
    // FAB 变为关闭图标
    expect(screen.getByTitle('关闭米宝')).toBeInTheDocument()
  })

  it('点击关闭按钮收起面板', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开米宝'))
    expect(screen.getByText('米宝 · 智能助手')).toBeInTheDocument()

    fireEvent.click(screen.getByTitle('关闭'))
    expect(screen.queryByText('米宝 · 智能助手')).not.toBeInTheDocument()
  })

  it('点击最小化按钮后只显示标题栏', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开米宝'))
    fireEvent.click(screen.getByTitle('最小化'))

    // 标题栏仍在，但内容区隐藏
    expect(screen.getByText('米宝 · 智能助手')).toBeInTheDocument()
    expect(screen.queryByTestId('session-list')).not.toBeInTheDocument()
  })

  it('最小化后点击标题栏可还原', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开米宝'))
    fireEvent.click(screen.getByTitle('最小化'))

    // 点击最小化后的标题栏还原
    fireEvent.click(screen.getByText('米宝 · 智能助手'))

    expect(screen.getByTestId('session-list')).toBeInTheDocument()
  })

  it('打开面板时自动加载会话列表', () => {
    render(<FloatingAssistant />)

    fireEvent.click(screen.getByTitle('打开米宝'))

    expect(mockFetchSessions).toHaveBeenCalled()
  })
})
