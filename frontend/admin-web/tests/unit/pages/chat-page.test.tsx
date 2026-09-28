// case_ids: UI-011, BM-008
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

// 米宝唤出能力位（issue #5642 功能⑤）：页面**只**消费 `/api/auth/me` 下发的
// `user.capabilities.mibaoChat`。这里用一个可切换的假状态驱动两侧分支。
const mockAuthState = vi.hoisted(() => ({ mibaoChat: true as boolean | undefined }))
vi.mock('@/store/auth', () => {
  const state = () => ({ user: { capabilities: { mibaoChat: mockAuthState.mibaoChat } } })
  return {
    useAuthStore: Object.assign(
      (selector?: (s: any) => any) => (selector ? selector(state()) : state()),
      { getState: () => state() },
    ),
  }
})

vi.mock('@/components/chat/SessionList', () => ({ default: () => <div data-testid="session-list">SessionList</div> }))
vi.mock('@/components/chat/ChatArea', () => ({ default: () => <div data-testid="chat-area">ChatArea</div> }))
vi.mock('@/components/chat/SessionInsight', () => ({ default: () => <div data-testid="session-insight">SessionInsight</div> }))

import ChatPage from '@/app/(dashboard)/chat/page'

describe('ChatPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    Element.prototype.scrollIntoView = vi.fn()
    mockAuthState.mibaoChat = true
  })

  it('renders two-column layout (session list + chat area)', () => {
    render(<ChatPage />)
    expect(screen.getByTestId('session-list')).toBeInTheDocument()
    expect(screen.getByTestId('chat-area')).toBeInTheDocument()
    // SessionInsight 已改为 ChatArea 内部抽屉，不再作为页面第三栏直接渲染
    expect(screen.queryByTestId('session-insight')).not.toBeInTheDocument()
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

  // ── 米宝唤出授权门（issue #5642 功能⑤）────────────────────────────────────
  it('capabilities.mibaoChat=false ⇒ 明确「需要管理员授权」+ 可行动引导，且不发任何会话请求', () => {
    mockAuthState.mibaoChat = false
    render(<ChatPage />)
    // 入口可见（拒绝态渲染出来了，不是静默隐藏、不是 403 白屏）
    expect(screen.getByTestId('mibao-gate-denied')).toBeInTheDocument()
    expect(screen.getByText('需要管理员授权')).toBeInTheDocument()
    expect(screen.getByText(/员工管理/)).toBeInTheDocument()
    // 对话区不渲染，且**不拉会话列表**（避免「页面看起来正常、一发消息什么都没有」的静默形态）
    expect(screen.queryByTestId('session-list')).not.toBeInTheDocument()
    expect(screen.queryByTestId('chat-area')).not.toBeInTheDocument()
    expect(mockFetchSessions).not.toHaveBeenCalled()
  })

  it('capabilities 缺席（/me 未回来）⇒ 不渲染拒绝态（不误报「没权限」）', () => {
    mockAuthState.mibaoChat = undefined
    render(<ChatPage />)
    expect(screen.queryByTestId('mibao-gate-denied')).not.toBeInTheDocument()
    expect(screen.queryByTestId('session-list')).not.toBeInTheDocument()
    expect(mockFetchSessions).not.toHaveBeenCalled()
  })
})
