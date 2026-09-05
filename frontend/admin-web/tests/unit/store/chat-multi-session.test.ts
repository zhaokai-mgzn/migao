// case_ids: CH-028, CH-027
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act } from '@testing-library/react'

// ---------------------------------------------------------------------------
// Mock factories — 与 chat.test.ts 同构（chatApi / auth / sonner）
// ---------------------------------------------------------------------------
const { mockGetSessions, mockGetHistory } = vi.hoisted(() => ({
  mockGetSessions: vi.fn(),
  mockGetHistory: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  chatApi: {
    AI_SERVICE_URL: 'http://localhost:8001',
    getSessions: (...args: any[]) => mockGetSessions(...args),
    getHistory: (...args: any[]) => mockGetHistory(...args),
  },
}))

const mockAuthGetState = vi.fn()
vi.mock('@/store/auth', () => ({
  useAuthStore: {
    getState: () => mockAuthGetState(),
  },
}))

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

// ---------------------------------------------------------------------------
import { useChatStore } from '@/store/chat'

// ===========================================================================
// Helpers
// ===========================================================================

function makeSessionPayload(sessionId: string) {
  return {
    id: sessionId,
    session_id: sessionId,
    title: '会话 ' + sessionId,
    status: 'active',
    message_count: 2,
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2025-01-02T00:00:00Z',
  }
}

function makeHistoryPayload(sessionId: string) {
  return {
    messages: [
      {
        id: `h1-${sessionId}`,
        role: 'user',
        content: '你好',
        content_type: 'text',
        created_at: '2025-01-01T00:00:00Z',
      },
      {
        id: `h2-${sessionId}`,
        role: 'assistant',
        content: '你好！有什么可以帮您？',
        created_at: '2025-01-01T00:00:01Z',
      },
    ],
  }
}

/** 可控 SSE 流：read() 无数据时挂起，由外部 push()/end() 驱动（模拟两路并发流） */
function makeControlledStream() {
  let pendingResolve: ((v: { done: boolean; value?: Uint8Array }) => void) | null = null
  let finished = false
  const queue: { done: boolean; value?: Uint8Array }[] = []

  const read = vi.fn().mockImplementation(() => {
    if (queue.length > 0) {
      const item = queue.shift()!
      if (item.done) finished = true
      return Promise.resolve(item)
    }
    if (finished) return Promise.resolve({ done: true, value: undefined })
    return new Promise(resolve => {
      pendingResolve = resolve
    })
  })

  return {
    read,
    push(chunk: string) {
      const item = { done: false, value: new TextEncoder().encode(chunk) }
      if (pendingResolve) {
        pendingResolve(item)
        pendingResolve = null
      } else {
        queue.push(item)
      }
    },
    end() {
      if (pendingResolve) {
        pendingResolve({ done: true, value: undefined })
        pendingResolve = null
      } else {
        queue.push({ done: true, value: undefined })
      }
      finished = true
    },
    reader: { read, cancel: vi.fn(), releaseLock: vi.fn() },
  }
}

async function flushMicrotasks() {
  await act(async () => {
    await new Promise(r => setTimeout(r, 0))
  })
}

// ===========================================================================
// Tests — issue #2906：多会话并发流（CH-028）
// ===========================================================================

describe('chat 多会话并发流 (issue #2906, CH-028)', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    act(() => {
      useChatStore.setState({
        sessions: [],
        currentSessionId: null,
        messageStore: {},
        streams: {},
        messages: [],
        isStreaming: false,
        isLoadingSessions: false,
        isLoadingMessages: false,
        searchKeyword: '',
        abortController: null,
        quickActions: [],
        isLoadingQuickActions: false,
        error: null,
        choiceSelections: {},
      })
    })

    mockAuthGetState.mockReturnValue({ accessToken: 'fake-token' })
    mockGetSessions.mockResolvedValue({ data: { items: [] } })
    mockGetHistory.mockImplementation((sessionId: string) =>
      Promise.resolve({ data: makeHistoryPayload(sessionId) }),
    )
  })

  it('会话 A 回复中，会话 B 可发送并同时流式回复（两路并发流共存）', async () => {
    // 模拟服务端持久化：流完成后历史必须包含已落库消息（selectSession 切回会重拉历史）
    const serverHistory: Record<string, any[]> = {
      a: [...makeHistoryPayload('a').messages],
      b: [...makeHistoryPayload('b').messages],
    }
    mockGetHistory.mockImplementation((id: string) =>
      Promise.resolve({ data: { messages: serverHistory[id] ?? [] } }),
    )

    act(() => {
      useChatStore.setState({
        sessions: [makeSessionPayload('a') as any, makeSessionPayload('b') as any],
        currentSessionId: 'a',
      })
    })

    const streamA = makeControlledStream()
    const streamB = makeControlledStream()
    global.fetch = vi.fn()
      .mockReturnValueOnce(Promise.resolve({ ok: true, body: { getReader: () => streamA.reader } }))
      .mockReturnValueOnce(Promise.resolve({ ok: true, body: { getReader: () => streamB.reader } }))

    // A 起流
    const sendA = useChatStore.getState().sendMessage('A 的问题')
    await flushMicrotasks()
    expect(useChatStore.getState().streams.a).toBeDefined()
    expect(useChatStore.getState().streams.b).toBeUndefined()

    // 切到 B —— 不应被 A 的流挡住
    await act(async () => {
      await useChatStore.getState().selectSession('b')
    })

    // B 发送 —— 必须成功（红：旧实现 isStreaming 全局挡）
    const sendB = useChatStore.getState().sendMessage('B 的问题')
    await flushMicrotasks()

    expect(useChatStore.getState().streams.a).toBeDefined()
    expect(useChatStore.getState().streams.b).toBeDefined()

    // 各自增量互不串流
    streamA.push('event: text_delta\ndata: {"content":"甲"}\n\n')
    streamB.push('event: text_delta\ndata: {"content":"乙"}\n\n')
    await flushMicrotasks()

    // 当前视图 B：末条 = 乙
    let view = useChatStore.getState().messages
    expect(view[view.length - 1]?.content).toBe('乙')

    // 切到 A：末条 = 甲（互不污染）
    await act(async () => {
      await useChatStore.getState().selectSession('a')
    })
    view = useChatStore.getState().messages
    expect(view[view.length - 1]?.content).toBe('甲')

    // 各自独立完成（先 A 后 B）
    streamA.push('event: text_delta\ndata: {"content":"答甲"}\n\n')
    streamA.push('event: done\ndata: {}\n\n')
    streamA.end()
    await act(async () => {
      await sendA
    })
    serverHistory.a = [...useChatStore.getState().messageStore.a] // 服务端已持久化 A 轮

    streamB.push('event: text_delta\ndata: {"content":"答乙"}\n\n')
    streamB.push('event: done\ndata: {}\n\n')
    streamB.end()
    await act(async () => {
      await sendB
    })
    serverHistory.b = [...useChatStore.getState().messageStore.b] // 服务端已持久化 B 轮

    // A 视图终态
    await act(async () => {
      await useChatStore.getState().selectSession('a')
    })
    view = useChatStore.getState().messages
    expect(view[view.length - 1]?.content).toBe('甲答甲')
    expect(useChatStore.getState().streams.a).toBeUndefined()
    expect(useChatStore.getState().isStreaming).toBe(false)

    // B 视图终态
    await act(async () => {
      await useChatStore.getState().selectSession('b')
    })
    view = useChatStore.getState().messages
    expect(view[view.length - 1]?.content).toBe('乙答乙')
    expect(useChatStore.getState().streams.b).toBeUndefined()
  })

  it('停止只停当前会话的流，另一会话流不受影响', async () => {
    act(() => {
      useChatStore.setState({
        sessions: [makeSessionPayload('a') as any, makeSessionPayload('b') as any],
        currentSessionId: 'a',
      })
    })

    const streamA = makeControlledStream()
    const streamB = makeControlledStream()
    global.fetch = vi.fn()
      .mockReturnValueOnce(Promise.resolve({ ok: true, body: { getReader: () => streamA.reader } }))
      .mockReturnValueOnce(Promise.resolve({ ok: true, body: { getReader: () => streamB.reader } }))

    const sendA = useChatStore.getState().sendMessage('A 的问题')
    await flushMicrotasks()
    await act(async () => {
      await useChatStore.getState().selectSession('b')
    })
    const sendB = useChatStore.getState().sendMessage('B 的问题')
    await flushMicrotasks()

    // 停在 B（当前视图）
    act(() => {
      useChatStore.getState().stopStreaming()
    })

    expect(useChatStore.getState().streams.b).toBeUndefined()
    const viewB = useChatStore.getState().messages
    expect(viewB[viewB.length - 1]?.wasAborted).toBe(true)

    // A 的流仍在
    expect(useChatStore.getState().streams.a).toBeDefined()

    // 让 A 在后台正常结束（B 已被 stop，mock 流不再驱动，sendB 挂起即可）
    streamA.push('event: done\ndata: {}\n\n')
    streamA.end()
    await act(async () => {
      await sendA
    })
  })

  it('CH-027 场景在新架构下保持：流式中切走再切回，等待占位恢复、最终回复可见', async () => {
    act(() => {
      useChatStore.setState({
        sessions: [makeSessionPayload('a') as any, makeSessionPayload('b') as any],
        currentSessionId: 'a',
      })
    })

    const stream = makeControlledStream()
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: { getReader: () => stream.reader },
    })

    const sendPromise = useChatStore.getState().sendMessage('查一下订单')
    await flushMicrotasks()

    await act(async () => {
      await useChatStore.getState().selectSession('b')
    })
    stream.push('event: text_delta\ndata: {"content":"正在为您查"}\n\n')
    await flushMicrotasks()

    await act(async () => {
      await useChatStore.getState().selectSession('a')
    })
    let msgs = useChatStore.getState().messages
    const restored = msgs[msgs.length - 1]
    expect(restored.role).toBe('assistant')
    expect(restored.isStreaming).toBe(true)
    expect(restored.content).toBe('正在为您查')

    stream.push('event: text_delta\ndata: {"content":"到了"}\n\n')
    stream.push('event: done\ndata: {}\n\n')
    stream.end()
    await act(async () => {
      await sendPromise
    })

    msgs = useChatStore.getState().messages
    expect(msgs[msgs.length - 1]?.content).toBe('正在为您查到了')
    expect(useChatStore.getState().isStreaming).toBe(false)
  })
})