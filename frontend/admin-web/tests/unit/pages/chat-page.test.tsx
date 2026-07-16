import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), forward: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
  usePathname: () => '/chat',
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}))

vi.mock('@/lib/utils', () => ({ cn: (...args: any[]) => args.filter(Boolean).join(' ') }))

vi.mock('@/hooks/useResizableHeight', () => ({
  useResizableHeight: vi.fn(() => ({
    containerStyle: { height: '85vh' },
    handleProps: { onMouseDown: vi.fn(), role: 'separator', tabIndex: 0, 'aria-label': 'drag', 'aria-orientation': 'horizontal' },
    isDragging: false,
    resetHeight: vi.fn(),
  })),
}))

const mockFetchSessions = vi.fn()
vi.mock('@/store/chat', () => {
  const fn = () => ({
    fetchSessions: mockFetchSessions, selectSession: vi.fn(),
    sessions: [], currentSessionId: null, messages: [], isStreaming: false,
    isLoadingSessions: false, isLoadingMessages: false,
  })
  return { useChatStore: Object.assign(fn, { getState: () => fn() }) }
})

vi.mock('@/components/chat/SessionList', () => ({ default: () => <div data-testid="session-list">SessionList</div> }))
vi.mock('@/components/chat/ChatArea', () => ({ default: () => <div data-testid="chat-area">ChatArea</div> }))
vi.mock('@/components/chat/SessionInsight', () => ({ default: () => <div data-testid="session-insight">SessionInsight</div> }))

import ChatPage from '@/app/(dashboard)/chat/page'

describe('ChatPage', () => {
  beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); Element.prototype.scrollIntoView = vi.fn() })

  it('renders three-column layout', () => {
    render(<ChatPage />)
    expect(screen.getByTestId('session-list')).toBeInTheDocument()
    expect(screen.getByTestId('chat-area')).toBeInTheDocument()
    expect(screen.getByTestId('session-insight')).toBeInTheDocument()
  })

  it('renders resize handle from MibaoChatPanel', () => {
    render(<ChatPage />)
    const handle = screen.getByTestId('chat-panel-resize-handle')
    expect(handle).toBeInTheDocument()
  })

  it('calls fetchSessions on mount', () => {
    render(<ChatPage />)
    expect(mockFetchSessions).toHaveBeenCalled()
  })

  it('renders MibaoChatPanel container', () => {
    render(<ChatPage />)
    expect(screen.getByTestId('chat-panel-resize-container')).toBeInTheDocument()
    expect(screen.getByTestId('chat-panel-content')).toBeInTheDocument()
  })
})
