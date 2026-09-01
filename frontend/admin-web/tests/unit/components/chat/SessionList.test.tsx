// case_ids: UI-008
/**
 * SessionList 折叠/展开功能 — Issue #2691（参考 DSH sidebar 折叠交互）
 *
 * 覆盖：
 *   - 默认展开：完整列表 + 折叠按钮（aria-label「折叠会话列表」）
 *   - 点击折叠 → 列表项隐藏、窄 rail 出现、toggle aria-expanded=false
 *   - 再点展开 → 列表恢复
 *   - localStorage 持久化：折叠 → 卸载重挂 → 恢复折叠态
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

// ─── Mutable mock state (reset per test) ─────────

const mockUseChatStore = vi.fn()

vi.mock('@/store/chat', () => {
  const fn = (...args: any[]) => mockUseChatStore(...args)
  return {
    useChatStore: Object.assign(fn, { getState: () => mockUseChatStore() }),
  }
})

import SessionList from '@/components/chat/SessionList'

const COLLAPSED_STORAGE_KEY = 'chat.session-list.collapsed'

// ─── Helpers ─────────────────────────────────────

function makeDefaultChatState(overrides: Record<string, unknown> = {}) {
  return {
    sessions: [] as any[],
    currentSessionId: null as string | null,
    messages: [] as any[],
    isStreaming: false,
    isLoadingSessions: false,
    isLoadingMessages: false,
    searchKeyword: '',
    setSearchKeyword: vi.fn(),
    createSession: vi.fn(),
    selectSession: vi.fn(),
    sendMessage: vi.fn(),
    closeSession: vi.fn(),
    reopenSession: vi.fn(),
    stopStreaming: vi.fn(),
    clearCurrentSession: vi.fn(),
    fetchSessions: vi.fn(),
    fetchQuickActions: vi.fn(),
    abortController: null,
    quickActions: [],
    isLoadingQuickActions: false,
    error: null,
    ...overrides,
  }
}

const ACTIVE_SESSION = {
  session_id: 's1',
  title: '会话1',
  status: 'active',
  updated_at: '2025-01-02',
  created_at: '2025-01-01',
}

// ─── Setup / Teardown ────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  mockUseChatStore.mockReturnValue(makeDefaultChatState())
})

// ═══════════════════════════════════════════════════
// SessionList 折叠/展开（UI-008）
// ═══════════════════════════════════════════════════

describe('SessionList 折叠功能（UI-008）', () => {
  it('默认展开：渲染完整列表 + 折叠按钮', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({ sessions: [ACTIVE_SESSION] })
    )
    render(<SessionList />)

    // 折叠按钮存在，展开态 aria-expanded 同步为 true
    const collapseBtn = screen.getByRole('button', { name: '折叠会话列表' })
    expect(collapseBtn).toBeInTheDocument()
    expect(collapseBtn).toHaveAttribute('aria-expanded', 'true')

    // 完整列表：新建对话 + 搜索 + 会话项
    expect(screen.getByRole('button', { name: '新建对话' })).toBeInTheDocument()
    expect(screen.getByPlaceholderText('搜索会话...')).toBeInTheDocument()
    expect(screen.getByText('会话1')).toBeInTheDocument()
  })

  it('点击折叠 → 列表项隐藏、窄 rail 出现、toggle aria-expanded=false', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({ sessions: [ACTIVE_SESSION] })
    )
    render(<SessionList />)

    fireEvent.click(screen.getByRole('button', { name: '折叠会话列表' }))

    // 列表项与搜索隐藏
    expect(screen.queryByText('会话1')).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText('搜索会话...')).not.toBeInTheDocument()

    // 窄 rail：展开 toggle（aria-expanded=false）+ 新建图标按钮仍在
    const expandBtn = screen.getByRole('button', { name: '展开会话列表' })
    expect(expandBtn).toBeInTheDocument()
    expect(expandBtn).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('button', { name: '新建对话' })).toBeInTheDocument()
  })

  it('再点展开 → 列表恢复', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({ sessions: [ACTIVE_SESSION] })
    )
    render(<SessionList />)

    fireEvent.click(screen.getByRole('button', { name: '折叠会话列表' }))
    fireEvent.click(screen.getByRole('button', { name: '展开会话列表' }))

    expect(screen.getByText('会话1')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('搜索会话...')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '折叠会话列表' })).toBeInTheDocument()
  })

  it('折叠写入 localStorage，展开清除', () => {
    render(<SessionList />)

    fireEvent.click(screen.getByRole('button', { name: '折叠会话列表' }))
    expect(localStorage.getItem(COLLAPSED_STORAGE_KEY)).toBe('1')

    fireEvent.click(screen.getByRole('button', { name: '展开会话列表' }))
    expect(localStorage.getItem(COLLAPSED_STORAGE_KEY)).toBeNull()
  })

  it('localStorage 持久化：折叠 → 卸载重挂 → 恢复折叠态', () => {
    mockUseChatStore.mockReturnValue(
      makeDefaultChatState({ sessions: [ACTIVE_SESSION] })
    )
    const { unmount } = render(<SessionList />)
    fireEvent.click(screen.getByRole('button', { name: '折叠会话列表' }))
    expect(localStorage.getItem(COLLAPSED_STORAGE_KEY)).toBe('1')

    unmount()
    render(<SessionList />)

    // 重挂后恢复折叠态：窄 rail 展开按钮 + 列表项隐藏
    expect(screen.getByRole('button', { name: '展开会话列表' })).toBeInTheDocument()
    expect(screen.queryByText('会话1')).not.toBeInTheDocument()
  })
})
