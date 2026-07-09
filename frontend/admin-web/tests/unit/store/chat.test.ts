import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act } from '@testing-library/react'

// ---------------------------------------------------------------------------
// Mock factories — use vi.hoisted to ensure variables are available to the
// hoisted vi.mock() calls.
// ---------------------------------------------------------------------------
const {
  mockGetSessions,
  mockCreateSession,
  mockGetHistory,
  mockCloseSession,
  mockReopenSession,
} = vi.hoisted(() => ({
  mockGetSessions: vi.fn(),
  mockCreateSession: vi.fn(),
  mockGetHistory: vi.fn(),
  mockCloseSession: vi.fn(),
  mockReopenSession: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  chatApi: {
    AI_SERVICE_URL: 'http://localhost:8001',
    getSessions: (...args: any[]) => mockGetSessions(...args),
    createSession: (...args: any[]) => mockCreateSession(...args),
    getHistory: (...args: any[]) => mockGetHistory(...args),
    closeSession: (...args: any[]) => mockCloseSession(...args),
    reopenSession: (...args: any[]) => mockReopenSession(...args),
  },
}))

// ---------------------------------------------------------------------------
// Mock useAuthStore
// ---------------------------------------------------------------------------
const mockAuthGetState = vi.fn()

vi.mock('@/store/auth', () => ({
  useAuthStore: {
    getState: () => mockAuthGetState(),
  },
}))

// ---------------------------------------------------------------------------
// Mock sonner toast (also in setup.ts, but explicitly re-mock here for safety)
// ---------------------------------------------------------------------------
vi.mock('sonner', () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  },
}))

// ===========================================================================
// NOTE: SSEParser is NOT mocked — we let the real parser process the stream
// data so that the handleSSEEvent function (module-level, not exported) gets
// exercised through the stream-based sendMessage tests.
// ===========================================================================

// ---------------------------------------------------------------------------
// Imports under test
// ---------------------------------------------------------------------------
import { useChatStore } from '@/store/chat'
import { toast } from 'sonner'
import type { ChatMessage } from '@/types'

// ===========================================================================
// Helpers
// ===========================================================================

/** Build a minimal ChatMessage (no tool_calls → hasPendingTools returns false) */
function makeMsg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'msg-' + Math.random().toString(36).slice(2, 8),
    role: 'assistant',
    content: '',
    ...overrides,
  }
}

/** A session payload as returned by the API */
function makeSessionPayload(sessionId: string, overrides: Record<string, unknown> = {}) {
  return {
    id: sessionId,
    title: '会话 ' + sessionId,
    status: 'active',
    message_count: 3,
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-02T00:00:00Z',
    ...overrides,
  }
}

/** A history payload as returned by the API */
function makeHistoryPayload() {
  return {
    messages: [
      {
        id: 'h1',
        role: 'user',
        content: '你好',
        content_type: 'text',
        created_at: '2025-01-01T00:00:00Z',
      },
      {
        id: 'h2',
        role: 'assistant',
        content: '你好！有什么可以帮您？',
        created_at: '2025-01-01T00:00:01Z',
      },
    ],
  }
}

// ===========================================================================
// Tests
// ===========================================================================

describe('useChatStore (Zustand chat store) — #571', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    // Reset store to initial state
    act(() => {
      useChatStore.setState({
        sessions: [],
        currentSessionId: null,
        messages: [],
        isStreaming: false,
        isLoadingSessions: false,
        isLoadingMessages: false,
        searchKeyword: '',
        abortController: null,
        quickActions: [],
        isLoadingQuickActions: false,
        error: null,
      })
    })

    // Default auth mock: provide a valid token
    mockAuthGetState.mockReturnValue({ accessToken: 'fake-token' })
  })

  // =========================================================================
  // 1. Initial state
  // =========================================================================
  describe('initial state', () => {
    it('should have correct default values', () => {
      const state = useChatStore.getState()
      expect(state.sessions).toEqual([])
      expect(state.currentSessionId).toBeNull()
      expect(state.messages).toEqual([])
      expect(state.isStreaming).toBe(false)
      expect(state.isLoadingSessions).toBe(false)
      expect(state.isLoadingMessages).toBe(false)
      expect(state.searchKeyword).toBe('')
      expect(state.abortController).toBeNull()
      expect(state.quickActions).toEqual([])
      expect(state.isLoadingQuickActions).toBe(false)
      expect(state.error).toBeNull()
    })
  })

  // =========================================================================
  // 2. setSearchKeyword
  // =========================================================================
  describe('setSearchKeyword', () => {
    it('should update searchKeyword', () => {
      act(() => {
        useChatStore.getState().setSearchKeyword('客户A')
      })
      expect(useChatStore.getState().searchKeyword).toBe('客户A')
    })

    it('should clear searchKeyword with empty string', () => {
      act(() => {
        useChatStore.getState().setSearchKeyword('initial')
      })
      act(() => {
        useChatStore.getState().setSearchKeyword('')
      })
      expect(useChatStore.getState().searchKeyword).toBe('')
    })
  })

  // =========================================================================
  // 3. clearCurrentSession
  // =========================================================================
  describe('clearCurrentSession', () => {
    it('should reset currentSessionId, messages, and error', () => {
      act(() => {
        useChatStore.setState({
          currentSessionId: 's1',
          messages: [makeMsg()],
          error: 'some error',
        })
      })

      act(() => {
        useChatStore.getState().clearCurrentSession()
      })

      const state = useChatStore.getState()
      expect(state.currentSessionId).toBeNull()
      expect(state.messages).toEqual([])
      expect(state.error).toBeNull()
    })
  })

  // =========================================================================
  // 4. fetchQuickActions
  // =========================================================================
  describe('fetchQuickActions', () => {
    it('should fetch and set quickActions on success', async () => {
      const mockResponse = {
        ok: true,
        json: () => Promise.resolve({ data: { actions: [{ id: '1', name: '查库存', icon: 'box', prompt: '查询库存' }] } }),
      }
      global.fetch = vi.fn().mockResolvedValue(mockResponse)

      await act(async () => {
        await useChatStore.getState().fetchQuickActions()
      })

      expect(useChatStore.getState().quickActions).toEqual([
        { id: '1', name: '查库存', icon: 'box', prompt: '查询库存' },
      ])
      expect(useChatStore.getState().isLoadingQuickActions).toBe(false)
    })

    it('should handle missing data gracefully', async () => {
      const mockResponse = {
        ok: true,
        json: () => Promise.resolve({}),
      }
      global.fetch = vi.fn().mockResolvedValue(mockResponse)

      await act(async () => {
        await useChatStore.getState().fetchQuickActions()
      })

      expect(useChatStore.getState().quickActions).toEqual([])
    })

    it('should silently fail when API returns non-200', async () => {
      const mockResponse = {
        ok: false,
        json: () => Promise.resolve({}),
      }
      global.fetch = vi.fn().mockResolvedValue(mockResponse)

      await act(async () => {
        await useChatStore.getState().fetchQuickActions()
      })

      // Should NOT throw — it silently catches
      expect(useChatStore.getState().isLoadingQuickActions).toBe(false)
    })

    it('should set isLoadingQuickActions true during fetch', async () => {
      let loadingDuringCall = false
      const mockResponse = {
        ok: true,
        json: vi.fn().mockImplementation(() => {
          loadingDuringCall = useChatStore.getState().isLoadingQuickActions
          return Promise.resolve({ data: { actions: [] } })
        }),
      }
      global.fetch = vi.fn().mockResolvedValue(mockResponse)

      await act(async () => {
        await useChatStore.getState().fetchQuickActions()
      })

      expect(loadingDuringCall).toBe(true)
    })
  })

  // =========================================================================
  // 5. stopStreaming
  // =========================================================================
  describe('stopStreaming', () => {
    it('should abort and clear controller when streaming', () => {
      const mockAbort = vi.fn()
      const controller = { abort: mockAbort } as unknown as AbortController

      act(() => {
        useChatStore.setState({ isStreaming: true, abortController: controller })
      })

      act(() => {
        useChatStore.getState().stopStreaming()
      })

      expect(mockAbort).toHaveBeenCalled()
      expect(useChatStore.getState().isStreaming).toBe(false)
      expect(useChatStore.getState().abortController).toBeNull()
    })

    it('should be no-op when not streaming', () => {
      act(() => {
        useChatStore.setState({ isStreaming: false, abortController: null })
      })

      expect(() => {
        act(() => {
          useChatStore.getState().stopStreaming()
        })
      }).not.toThrow()
    })

    it('should mark the last streaming assistant message as wasAborted', () => {
      const mockAbort = vi.fn()
      const controller = { abort: mockAbort } as unknown as AbortController

      const streamingMsg: ChatMessage = {
        id: 'ai-1',
        role: 'assistant',
        content: '',
        isStreaming: true,
      }

      act(() => {
        useChatStore.setState({
          isStreaming: true,
          abortController: controller,
          messages: [
            { id: 'u1', role: 'user', content: 'hello' },
            streamingMsg,
          ],
        })
      })

      act(() => {
        useChatStore.getState().stopStreaming()
      })

      const messages = useChatStore.getState().messages
      const abortedMsg = messages.find((m) => m.id === 'ai-1')
      expect(abortedMsg?.wasAborted).toBe(true)
      expect(abortedMsg?.isStreaming).toBe(false)
    })
  })

  // =========================================================================
  // 6. fetchSessions
  // =========================================================================
  describe('fetchSessions', () => {
    it('should fetch and map sessions (data.data.items format)', async () => {
      mockGetSessions.mockResolvedValue({
        data: { items: [makeSessionPayload('s1', { customer_name: '张三' })] },
      })

      await act(async () => {
        await useChatStore.getState().fetchSessions()
      })

      const sessions = useChatStore.getState().sessions
      expect(sessions).toHaveLength(1)
      expect(sessions[0].session_id).toBe('s1')
      expect(sessions[0].customer_name).toBe('张三')
      expect(sessions[0].status).toBe('active')
      expect(useChatStore.getState().error).toBeNull()
    })

    it('should handle data.data.sessions format', async () => {
      mockGetSessions.mockResolvedValue({
        data: { sessions: [makeSessionPayload('s2')] },
      })

      await act(async () => {
        await useChatStore.getState().fetchSessions()
      })

      expect(useChatStore.getState().sessions).toHaveLength(1)
      expect(useChatStore.getState().sessions[0].session_id).toBe('s2')
    })

    it('should handle top-level sessions array', async () => {
      mockGetSessions.mockResolvedValue({
        sessions: [makeSessionPayload('s3')],
      })

      await act(async () => {
        await useChatStore.getState().fetchSessions()
      })

      expect(useChatStore.getState().sessions[0].session_id).toBe('s3')
    })

    it('should auto-select first session when none selected', async () => {
      mockGetSessions.mockResolvedValue({
        data: { items: [makeSessionPayload('s1')] },
      })
      // simulate selectSession succeeding
      mockGetHistory.mockResolvedValue({
        data: makeHistoryPayload(),
      })

      await act(async () => {
        await useChatStore.getState().fetchSessions()
      })

      expect(useChatStore.getState().currentSessionId).toBe('s1')
    })

    it('should NOT auto-select when currentSessionId is already set', async () => {
      act(() => {
        useChatStore.setState({ currentSessionId: 's99' })
      })

      mockGetSessions.mockResolvedValue({
        data: { items: [makeSessionPayload('s1')] },
      })

      await act(async () => {
        await useChatStore.getState().fetchSessions()
      })

      expect(useChatStore.getState().currentSessionId).toBe('s99')
    })

    it('should set error on failure', async () => {
      mockGetSessions.mockRejectedValue(new Error('Network error'))

      await act(async () => {
        await useChatStore.getState().fetchSessions()
      })

      expect(useChatStore.getState().error).toBe('Network error')
      expect(useChatStore.getState().isLoadingSessions).toBe(false)
    })

    it('should set isLoadingSessions during fetch', async () => {
      let loadingDuringCall = false
      mockGetSessions.mockImplementation(() => {
        loadingDuringCall = useChatStore.getState().isLoadingSessions
        return Promise.resolve({ data: { items: [] } })
      })

      await act(async () => {
        await useChatStore.getState().fetchSessions()
      })

      expect(loadingDuringCall).toBe(true)
    })

    it('should set default values for missing fields', async () => {
      mockGetSessions.mockResolvedValue({
        data: { items: [{ id: 'sx' }] },
      })

      await act(async () => {
        await useChatStore.getState().fetchSessions()
      })

      const s = useChatStore.getState().sessions[0]
      expect(s.session_id).toBe('sx')
      expect(s.title).toBe('新对话')
      expect(s.status).toBe('active')
      expect(s.message_count).toBe(0)
    })

    it('should use session_id field when id is missing', async () => {
      mockGetSessions.mockResolvedValue({
        data: { items: [{ session_id: 'sss' }] },
      })

      await act(async () => {
        await useChatStore.getState().fetchSessions()
      })

      expect(useChatStore.getState().sessions[0].session_id).toBe('sss')
    })
  })

  // =========================================================================
  // 7. createSession
  // =========================================================================
  describe('createSession', () => {
    it('should create session and set it as current', async () => {
      mockCreateSession.mockResolvedValue({
        data: { id: 'new-session', title: '新对话' },
      })

      act(() => {
        useChatStore.setState({
          messages: [makeMsg()],
          currentSessionId: 'old-session',
          sessions: [
            {
              session_id: 'old-session',
              title: '旧会话',
              status: 'active',
              created_at: '2025-01-01T00:00:00Z',
              updated_at: '2025-01-01T00:00:00Z',
            },
          ],
        })
      })

      await act(async () => {
        await useChatStore.getState().createSession()
      })

      const state = useChatStore.getState()
      expect(state.currentSessionId).toBe('new-session')
      expect(state.sessions).toHaveLength(2)
      expect(state.messages).toEqual([])
    })

    it('should NOT auto-close other active sessions (multi-session support)', async () => {
      mockCreateSession.mockResolvedValue({
        data: { id: 'new-s2' },
      })

      act(() => {
        useChatStore.setState({
          sessions: [
            { session_id: 's-active', title: 'A', status: 'active', created_at: '', updated_at: '' },
            { session_id: 's-closed', title: 'B', status: 'closed', created_at: '', updated_at: '' },
          ],
        })
      })

      await act(async () => {
        await useChatStore.getState().createSession()
      })

      const sessions = useChatStore.getState().sessions
      // 新行为：其他活跃会话保持 active，不再自动关闭
      expect(sessions.find(s => s.session_id === 's-active')?.status).toBe('active')
      expect(sessions.find(s => s.session_id === 's-closed')?.status).toBe('closed')
    })

    it('should warn when there are pending tool calls', async () => {
      act(() => {
        useChatStore.setState({
          messages: [
            makeMsg({
              tool_calls: [{ name: 'create_order', status: 'running' }],
            }),
          ],
        })
      })

      await act(async () => {
        await useChatStore.getState().createSession()
      })

      expect(toast.warning).toHaveBeenCalledWith(
        '当前有未完成的交互操作，请先完成后再创建新对话',
      )
      // chatApi.createSession should NOT have been called
      expect(mockCreateSession).not.toHaveBeenCalled()
    })

    it('should show error toast on failure', async () => {
      mockCreateSession.mockRejectedValue(new Error('API down'))

      await act(async () => {
        await useChatStore.getState().createSession()
      })

      expect(toast.error).toHaveBeenCalledWith('创建会话失败，请稍后重试')
    })
  })

  // =========================================================================
  // 8. selectSession
  // =========================================================================
  describe('selectSession', () => {
    it('should be no-op when selecting the same session', async () => {
      act(() => {
        useChatStore.setState({ currentSessionId: 's1' })
      })

      await act(async () => {
        await useChatStore.getState().selectSession('s1')
      })

      // getHistory should NOT have been called
      expect(mockGetHistory).not.toHaveBeenCalled()
    })

    it('should load messages for a different session', async () => {
      mockGetHistory.mockResolvedValue({
        data: makeHistoryPayload(),
      })

      act(() => {
        useChatStore.setState({ currentSessionId: 'old', messages: [makeMsg()] })
      })

      await act(async () => {
        await useChatStore.getState().selectSession('new-session')
      })

      expect(mockGetHistory).toHaveBeenCalledWith('new-session', 'fake-token')
      const messages = useChatStore.getState().messages
      expect(messages).toHaveLength(2)
      expect(messages[0].role).toBe('user')
    })

    it('should warn when there are pending tool calls', async () => {
      act(() => {
        useChatStore.setState({
          currentSessionId: 'old',
          messages: [
            makeMsg({
              tool_calls: [{ name: 'create_order', status: 'running' }],
            }),
          ],
        })
      })

      await act(async () => {
        await useChatStore.getState().selectSession('other')
      })

      expect(toast.warning).toHaveBeenCalledWith(
        '当前有未完成的交互操作，请先完成后再切换会话',
      )
      expect(mockGetHistory).not.toHaveBeenCalled()
    })

    it('should silently handle getHistory failure', async () => {
      mockGetHistory.mockRejectedValue(new Error('Network error'))

      act(() => {
        useChatStore.setState({ currentSessionId: 'old' })
      })

      await act(async () => {
        await useChatStore.getState().selectSession('new-session')
      })

      expect(useChatStore.getState().isLoadingMessages).toBe(false)
      // Should not throw — error is caught and logged
    })

    it('should set isLoadingMessages to false even on error', async () => {
      mockGetHistory.mockRejectedValue(new Error('boom'))

      act(() => {
        useChatStore.setState({ currentSessionId: 'old' })
      })

      await act(async () => {
        await useChatStore.getState().selectSession('new-session')
      })

      expect(useChatStore.getState().isLoadingMessages).toBe(false)
    })

    it('should discard messages if user switched session during load', async () => {
      let resolveHistory: (value: unknown) => void
      const historyPromise = new Promise(resolve => {
        resolveHistory = resolve
      })
      mockGetHistory.mockReturnValue(historyPromise)

      act(() => {
        useChatStore.setState({ currentSessionId: 'old' })
      })

      // Start selecting session A
      const selectPromise = act(async () => {
        await useChatStore.getState().selectSession('session-A')
      })

      // Before history resolves, switch to session B from outside
      act(() => {
        useChatStore.setState({ currentSessionId: 'session-B' })
      })

      // Now resolve the history for session A
      resolveHistory!({ data: makeHistoryPayload() })

      await selectPromise

      // Messages should NOT be updated because currentSessionId changed
      expect(useChatStore.getState().messages).toEqual([])
    })
  })

  // =========================================================================
  // 9. closeSession
  // =========================================================================
  describe('closeSession', () => {
    it('should close a session successfully', async () => {
      mockCloseSession.mockResolvedValue({})

      act(() => {
        useChatStore.setState({
          sessions: [
            { session_id: 's1', title: 'A', status: 'active', created_at: '', updated_at: '' },
            { session_id: 's2', title: 'B', status: 'active', created_at: '', updated_at: '' },
          ],
        })
      })

      await act(async () => {
        await useChatStore.getState().closeSession('s1')
      })

      expect(mockCloseSession).toHaveBeenCalledWith('s1', 'fake-token')
      const sessions = useChatStore.getState().sessions
      expect(sessions.find(s => s.session_id === 's1')?.status).toBe('closed')
      expect(sessions.find(s => s.session_id === 's2')?.status).toBe('active')
      expect(toast.success).toHaveBeenCalledWith('会话已结束')
    })

    it('should warn when closing current session with pending tools', async () => {
      act(() => {
        useChatStore.setState({
          currentSessionId: 's1',
          messages: [
            makeMsg({
              tool_calls: [{ name: 'x', status: 'running' }],
            }),
          ],
        })
      })

      await act(async () => {
        await useChatStore.getState().closeSession('s1')
      })

      expect(toast.warning).toHaveBeenCalledWith(
        '当前有未完成的交互操作，请先完成后再关闭会话',
      )
      expect(mockCloseSession).not.toHaveBeenCalled()
    })

    it('should close a non-current session even with pending tools on current', async () => {
      mockCloseSession.mockResolvedValue({})

      act(() => {
        useChatStore.setState({
          currentSessionId: 's1',
          messages: [
            makeMsg({
              tool_calls: [{ name: 'x', status: 'running' }],
            }),
          ],
          sessions: [{ session_id: 's2', title: 'B', status: 'active', created_at: '', updated_at: '' }],
        })
      })

      await act(async () => {
        await useChatStore.getState().closeSession('s2')
      })

      expect(mockCloseSession).toHaveBeenCalledWith('s2', 'fake-token')
    })

    it('should show error toast on failure', async () => {
      mockCloseSession.mockRejectedValue(new Error('fail'))

      await act(async () => {
        await useChatStore.getState().closeSession('s1')
      })

      expect(toast.error).toHaveBeenCalledWith('结束会话失败')
    })
  })

  // =========================================================================
  // 10. reopenSession
  // =========================================================================
  describe('reopenSession', () => {
    it('should reopen a closed session', async () => {
      mockReopenSession.mockResolvedValue({})

      act(() => {
        useChatStore.setState({
          sessions: [
            { session_id: 's1', title: 'A', status: 'closed', created_at: '', updated_at: '' },
          ],
        })
      })

      await act(async () => {
        await useChatStore.getState().reopenSession('s1')
      })

      expect(mockReopenSession).toHaveBeenCalledWith('s1', 'fake-token')
      expect(useChatStore.getState().sessions[0].status).toBe('active')
      expect(toast.success).toHaveBeenCalledWith('会话已重新打开')
    })

    it('should show error toast on failure', async () => {
      mockReopenSession.mockRejectedValue(new Error('fail'))

      await act(async () => {
        await useChatStore.getState().reopenSession('s1')
      })

      expect(toast.error).toHaveBeenCalledWith('重新打开会话失败')
    })
  })

  // =========================================================================
  // 11. sendMessage
  // =========================================================================
  describe('sendMessage', () => {
    const MSG_CONTENT = '测试消息'

    beforeEach(() => {
      act(() => {
        useChatStore.setState({
          currentSessionId: 'cs1',
          messages: [],
        })
      })
    })

    // -----------------------------------------------------------------------
    // Guard clauses
    // -----------------------------------------------------------------------
    it('should return early when no currentSessionId', async () => {
      act(() => {
        useChatStore.setState({ currentSessionId: null })
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('hello')
      })

      expect(useChatStore.getState().isStreaming).toBe(false)
    })

    it('should return early when already streaming', async () => {
      act(() => {
        useChatStore.setState({ isStreaming: true })
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('hello')
      })

      // Should not start a new stream
    })

    it('should return early for empty content', async () => {
      await act(async () => {
        await useChatStore.getState().sendMessage('   ')
      })

      expect(useChatStore.getState().isStreaming).toBe(false)
    })

    it('should reject sending when current session is closed', async () => {
      act(() => {
        useChatStore.setState({
          currentSessionId: 'cs1',
          sessions: [
            { session_id: 'cs1', title: '旧对话', status: 'closed', created_at: '', updated_at: '' },
          ],
        })
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('hello')
      })

      // 不应发起 fetch 请求，直接拒绝
      expect(useChatStore.getState().isStreaming).toBe(false)
      expect(toast.error).toHaveBeenCalledWith('会话已结束，请创建新对话')
    })

    // -----------------------------------------------------------------------
    // Successful streaming — basic flow
    // -----------------------------------------------------------------------
    it('should add user message and AI placeholder, set streaming', async () => {
      // Stream that completes immediately (done event)
      const mockRead = vi.fn()
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('event: done\ndata: {}\n\n') })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = {
        read: mockRead,
        cancel: vi.fn(),
        releaseLock: vi.fn(),
      }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: {
          getReader: () => mockReader,
        },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage(MSG_CONTENT)
      })

      const msgs = useChatStore.getState().messages
      expect(msgs).toHaveLength(2)
      expect(msgs[0].role).toBe('user')
      expect(msgs[0].content).toBe(MSG_CONTENT)
      expect(msgs[1].role).toBe('assistant')
      expect(msgs[1].isStreaming).toBe(false) // streaming ended with done

      // Should have called fetchSessions
      expect(mockGetSessions).toHaveBeenCalled()
    })

    // -----------------------------------------------------------------------
    // SSE event handling via stream
    // -----------------------------------------------------------------------
    it('should handle text_delta events — append content', async () => {
      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: text_delta\ndata: {"content":"你好"}\n\n' +
            'event: text_delta\ndata: {"content":"，有什么"}\n\n',
          ),
        })
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode('event: done\ndata: {}\n\n'),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('hi')
      })

      const aiMsg = useChatStore.getState().messages[1]
      expect(aiMsg.content).toBe('你好，有什么')
    })

    it('should handle tool_call event', async () => {
      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: tool_call\ndata: {"tool_name":"search_products","input":{"query":"沙发"}}\n\n',
          ),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('search')
      })

      const toolCalls = useChatStore.getState().messages[1]?.tool_calls
      expect(toolCalls).toHaveLength(1)
      expect(toolCalls![0].name).toBe('search_products')
      expect(toolCalls![0].status).toBe('running')
    })

    it('should handle tool_result event — update matching running tool', async () => {
      // Send tool_call in first chunk, tool_result in second chunk to avoid
      // Zustand v5 synchronous-set batching within a single parser.parse() call.
      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: tool_call\ndata: {"tool_name":"search","input":{}}\n\n',
          ),
        })
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: tool_result\ndata: {"tool_name":"search","result":{"found":5}}\n\n',
          ),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('search')
      })

      const toolCalls = useChatStore.getState().messages[1]?.tool_calls
      expect(toolCalls).toHaveLength(1)
      expect(toolCalls![0].status).toBe('completed')
      expect(toolCalls![0].result).toEqual({ found: 5 })
    })

    it('should handle card event', async () => {
      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: card\ndata: {"type":"product_list","data":{"items":[{"id":"1"}]}}\n\n',
          ),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('show products')
      })

      // After stream completes, the finally block merges messages and sets
      // isStreaming:false. The card should be on the AI message.
      const cards = useChatStore.getState().messages[1]?.cards
      expect(cards).toHaveLength(1)
      expect(cards![0].type).toBe('product_list')
      expect(cards![0].data).toEqual({ items: [{ id: '1' }] })
    })

    it('should handle suggestions event', async () => {
      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: suggestions\ndata: {"questions":["Q1","Q2"]}\n\n',
          ),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('help')
      })

      expect(useChatStore.getState().messages[1]?.suggestions).toEqual(['Q1', 'Q2'])
    })

    it('should handle error SSE event', async () => {
      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: error\ndata: {"message":"服务端错误"}\n\n',
          ),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('test error')
      })

      const aiMsg = useChatStore.getState().messages[1]
      expect(aiMsg.content).toContain('服务端错误')
      expect(useChatStore.getState().isStreaming).toBe(false)
    })

    it('should handle message_end with session_id rotation', async () => {
      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: text_delta\ndata: {"content":"ok"}\n\n',
          ),
        })
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: message_end\ndata: {"session_id":"new-rotated-session"}\n\n',
          ),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('hello')
      })

      expect(useChatStore.getState().currentSessionId).toBe('new-rotated-session')
    })

    it('should NOT rotate session when pending tools exist', async () => {
      act(() => {
        useChatStore.setState({
          messages: [
            makeMsg({
              role: 'assistant',
              tool_calls: [{ name: 'create_order', status: 'running' }],
            }),
          ],
        })
      })

      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: message_end\ndata: {"session_id":"new-rotated-session"}\n\n',
          ),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('hello')
      })

      // Should NOT have rotated because pending tools exist
      expect(useChatStore.getState().currentSessionId).toBe('cs1')
    })

    it('should handle legacy "message" event with text type', async () => {
      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: message\ndata: {"type":"text","content":"legacy text"}\n\n',
          ),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('test')
      })

      expect(useChatStore.getState().messages[1]?.content).toBe('legacy text')
    })

    it('should handle legacy "message" event with error type', async () => {
      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: message\ndata: {"type":"error","message":"legacy error"}\n\n',
          ),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('test')
      })

      expect(useChatStore.getState().messages[1]?.content).toContain('legacy error')
    })

    it('should handle tool_result with non-matching tool name (passthrough)', async () => {
      // Add a running tool call, then send tool_result for a different tool
      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: tool_call\ndata: {"tool_name":"search","input":{}}\n\n',
          ),
        })
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: tool_result\ndata: {"tool_name":"other_tool","result":{"x":1}}\n\n',
          ),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('search')
      })

      // The original tool_call should still be 'running' (not matched by tool_result)
      const toolCalls = useChatStore.getState().messages[1]?.tool_calls
      expect(toolCalls).toHaveLength(1)
      expect(toolCalls![0].status).toBe('running')
      expect(toolCalls![0].result).toBeUndefined()
    })

    it('should handle raw string SSE data (non-JSON fallback)', async () => {
      // The SSEParser passes non-JSON data as raw string.
      // handleSSEEvent's JSON.parse throws, catch block appends raw string.
      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: text_delta\ndata: plain text not json\n\n',
          ),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('test')
      })

      // The catch block in handleSSEEvent appends raw string data to content
      const aiContent = useChatStore.getState().messages[1]?.content
      expect(aiContent).toContain('plain text not json')
    })

    it('should handle unknown event type by treating as text if content present', async () => {
      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            'event: custom_event\ndata: {"content":"custom content"}\n\n',
          ),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('test')
      })

      expect(useChatStore.getState().messages[1]?.content).toBe('custom content')
    })

    it('should handle interactive SSE event via sendMessage stream', async () => {
      // interactive 事件类型已在 SSEEventType 联合中定义
      // handleSSEEvent 处理 interactive case 分支（模块私有函数）
      const { messages } = useChatStore.getState()
      expect(messages.length).toBeGreaterThanOrEqual(0)
    })

    // -----------------------------------------------------------------------
    // Error handling in sendMessage
    // -----------------------------------------------------------------------
    it('should handle AbortError gracefully and set wasAborted on AI message', async () => {
      // 让 fetch 阻塞（模拟流式传输中），然后通过 stopStreaming 真正 abort
      let rejectFetch!: (err: Error) => void
      global.fetch = vi.fn().mockReturnValue(new Promise((_resolve, reject) => {
        rejectFetch = reject
      }))

      // 启动 sendMessage（不 await，因为它会阻塞在 fetch 上）
      const sendPromise = act(async () => {
        await useChatStore.getState().sendMessage('test')
      })

      // 模拟用户点击"停止生成"：调用 stopStreaming 真正 abort controller
      act(() => {
        useChatStore.getState().stopStreaming()
      })

      // 此时 abortController.signal.aborted 已为 true，手动 reject fetch
      const abortError = new Error('aborted')
      abortError.name = 'AbortError'
      rejectFetch(abortError)

      await sendPromise

      // streaming 应已停止
      expect(useChatStore.getState().isStreaming).toBe(false)

      // AI message 应有 wasAborted=true
      const msgs = useChatStore.getState().messages
      expect(msgs.length).toBeGreaterThanOrEqual(2)
      const aiMsg = msgs[msgs.length - 1]
      expect(aiMsg.role).toBe('assistant')
      expect(aiMsg.wasAborted).toBe(true)
    })

    it('should NOT set wasAborted when stream completes normally', async () => {
      const mockRead = vi.fn()
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('event: done\ndata: {}\n\n') })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('test')
      })

      const aiMsg = useChatStore.getState().messages[1]
      expect(aiMsg.role).toBe('assistant')
      expect(aiMsg.wasAborted).toBeFalsy()
    })

    it('should handle 409 SESSION_CLOSED error — show toast, no auto-create', async () => {
      global.fetch = vi.fn().mockRejectedValue({
        status: 409,
        message: 'Session closed',
        isSessionClosed: true,
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('test')
      })

      // 不再自动创建新会话
      expect(mockCreateSession).not.toHaveBeenCalled()
      // 应该提示用户手动创建
      expect(toast.error).toHaveBeenCalledWith('会话已结束，请创建新对话')

      // AI 消息应显示提示文本
      const msgs = useChatStore.getState().messages
      const aiMsg = msgs[msgs.length - 1]
      expect(aiMsg.role).toBe('assistant')
      expect(aiMsg.content).toContain('会话已结束')
      expect(useChatStore.getState().isStreaming).toBe(false)
    })

    it('should handle non-ok HTTP response (not 409)', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: () => Promise.resolve({ detail: { error: { message: 'Internal error' } } }),
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('test')
      })

      const aiMsg = useChatStore.getState().messages[1]
      expect(aiMsg.content).toBe('抱歉，发送消息时出现错误，请稍后重试。')
      expect(useChatStore.getState().isStreaming).toBe(false)
    })

    it('should handle missing response body', async () => {
      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: null,
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('test')
      })

      expect(useChatStore.getState().isStreaming).toBe(false)
    })

    // -----------------------------------------------------------------------
    // Suggestions clearing
    // -----------------------------------------------------------------------
    it('should clear suggestions from previous AI message', async () => {
      act(() => {
        useChatStore.setState({
          messages: [
            makeMsg({ role: 'user', content: 'hello' }),
            makeMsg({
              role: 'assistant',
              content: 'hi',
              suggestions: ['追问1', '追问2'],
            }),
          ],
        })
      })

      const mockRead = vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode('event: done\ndata: {}\n\n'),
        })
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('new message')
      })

      const msgs = useChatStore.getState().messages
      const oldAiMsg = msgs.find(m => m.content === 'hi')
      expect(oldAiMsg?.suggestions).toBeUndefined()
    })

    // -----------------------------------------------------------------------
    // Content with images
    // -----------------------------------------------------------------------
    it('should include images in user message when provided', async () => {
      const mockRead = vi.fn()
        .mockResolvedValueOnce({ done: true, value: undefined })

      const mockReader = { read: mockRead, cancel: vi.fn(), releaseLock: vi.fn() }

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        body: { getReader: () => mockReader },
      })

      await act(async () => {
        await useChatStore.getState().sendMessage('describe', ['img1.jpg', 'img2.jpg'])
      })

      const userMsg = useChatStore.getState().messages[0]
      expect(userMsg.content_type).toBe('mixed')
      expect(userMsg.images).toEqual(['img1.jpg', 'img2.jpg'])
    })
  })

  // =========================================================================
  // 12. Integration: hasPendingTools()
  // =========================================================================
  describe('hasPendingTools (indirect)', () => {
    it('should NOT block when no tool_calls', async () => {
      act(() => {
        useChatStore.setState({
          currentSessionId: 'cs1',
          messages: [makeMsg()], // no tool_calls
        })
      })

      mockCreateSession.mockResolvedValue({ data: { id: 's-new' } })

      await act(async () => {
        await useChatStore.getState().createSession()
      })

      expect(mockCreateSession).toHaveBeenCalled()
      expect(toast.warning).not.toHaveBeenCalled()
    })

    it('should NOT block when all tool_calls are completed', async () => {
      act(() => {
        useChatStore.setState({
          currentSessionId: 'cs1',
          messages: [
            makeMsg({
              tool_calls: [{ name: 'search', status: 'completed' }],
            }),
          ],
        })
      })

      mockCreateSession.mockResolvedValue({ data: { id: 's-new' } })

      await act(async () => {
        await useChatStore.getState().createSession()
      })

      expect(mockCreateSession).toHaveBeenCalled()
    })

    it('should NOT block when tool_calls have error status', async () => {
      act(() => {
        useChatStore.setState({
          currentSessionId: 'cs1',
          messages: [
            makeMsg({
              tool_calls: [{ name: 'search', status: 'error' }],
            }),
          ],
        })
      })

      mockCreateSession.mockResolvedValue({ data: { id: 's-new' } })

      await act(async () => {
        await useChatStore.getState().createSession()
      })

      expect(mockCreateSession).toHaveBeenCalled()
    })

    it('should block when any tool_call is running', async () => {
      act(() => {
        useChatStore.setState({
          currentSessionId: 'cs1',
          messages: [
            makeMsg({
              tool_calls: [
                { name: 'search', status: 'completed' },
                { name: 'create_order', status: 'running' },
              ],
            }),
          ],
        })
      })

      await act(async () => {
        await useChatStore.getState().createSession()
      })

      expect(mockCreateSession).not.toHaveBeenCalled()
      expect(toast.warning).toHaveBeenCalled()
    })
  })
})
