// case_ids: CH-027
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act } from '@testing-library/react'

// ---------------------------------------------------------------------------
// Mock factories — 与 chat.test.ts 同构（chatApi / auth / sonner）
// ---------------------------------------------------------------------------
const {
  mockGetSessions,
  mockGetHistory,
} = vi.hoisted(() => ({
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
// Imports under test
// ---------------------------------------------------------------------------
import { useChatStore } from '@/store/chat'

// ===========================================================================
// Helpers
// ===========================================================================

function makeSessionPayload(sessionId: string) {
  return {
    id: sessionId,
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

/**
 * 可控 SSE 流：read() 在无数据时挂起，由外部 push()/end() 驱动。
 * 用于模拟「流仍在进行中」时进行会话切换。
 */
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

/** 让 sendMessage 跑到第一个 read() 挂起（消息占位已写入 store） */
async function flushMicrotasks() {
  await act(async () => {
    await new Promise(r => setTimeout(r, 0))
  })
}

// ===========================================================================
// Tests — issue #2901：流式回复中切换会话再切回
// ===========================================================================

describe('chat 流式回复 × 会话切换 (issue #2901, CH-027)', () => {
  beforeEach(() => {
    vi.clearAllMocks()

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
        liveMessage: null,
      })
    })

    mockAuthGetState.mockReturnValue({ accessToken: 'fake-token' })
    mockGetSessions.mockResolvedValue({ data: { items: [] } })
  })

  it('流式回复中切到其他会话再切回：等待占位恢复，流结束后最终回复可见', async () => {
    mockGetHistory.mockImplementation((sessionId: string) =>
      Promise.resolve({ data: makeHistoryPayload(sessionId) }),
    )

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

    // 1. 在会话 a 发消息（流阻塞在第一次 read，占位消息已在 store）
    const sendPromise = useChatStore.getState().sendMessage('查一下订单')
    await flushMicrotasks()

    let msgs = useChatStore.getState().messages
    expect(msgs[msgs.length - 1]?.isStreaming).toBe(true)

    // 2. 流进行中切到会话 b —— messages 换为 b 的历史
    await act(async () => {
      await useChatStore.getState().selectSession('b')
    })
    expect(useChatStore.getState().currentSessionId).toBe('b')

    // 3. 停留在 b 期间，a 的流继续推进（增量不能被丢弃）
    stream.push('event: text_delta\ndata: {"content":"正在为您查"}\n\n')
    await flushMicrotasks()

    // 4. 切回会话 a —— 等待占位必须恢复（issue #2901 的核心症状）
    await act(async () => {
      await useChatStore.getState().selectSession('a')
    })
    msgs = useChatStore.getState().messages
    expect(msgs.length).toBe(3) // h1 user + h2 assistant + 在途 AI 占位
    const restored = msgs[msgs.length - 1]
    expect(restored.role).toBe('assistant')
    expect(restored.isStreaming).toBe(true)
    expect(restored.content).toBe('正在为您查')

    // 5. 流结束：最终回复在会话 a 中可见
    stream.push('event: text_delta\ndata: {"content":"到了"}\n\n')
    stream.push('event: done\ndata: {}\n\n')
    stream.end()
    await act(async () => {
      await sendPromise
    })

    msgs = useChatStore.getState().messages
    const finalMsg = msgs[msgs.length - 1]
    expect(finalMsg.role).toBe('assistant')
    expect(finalMsg.isStreaming).toBe(false)
    expect(finalMsg.content).toBe('正在为您查到了')
    expect(useChatStore.getState().isStreaming).toBe(false)
  })

  it('流在别的会话期间结束后，切回原会话仍能看到最终回复（历史权威路径不回归）', async () => {
    mockGetHistory.mockImplementation((sessionId: string) =>
      Promise.resolve({
        data: {
          messages:
            sessionId === 'a'
              ? [
                  ...makeHistoryPayload('a').messages,
                  {
                    id: 'saved-ai',
                    role: 'assistant',
                    content: '答复内容',
                    created_at: '2025-01-02T00:00:10Z',
                  },
                ]
              : makeHistoryPayload(sessionId).messages,
        },
      }),
    )

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

    const sendPromise = useChatStore.getState().sendMessage('问')
    await flushMicrotasks()

    // 切到 b，随后 a 的流在后台整体完成
    await act(async () => {
      await useChatStore.getState().selectSession('b')
    })
    stream.push('event: text_delta\ndata: {"content":"答复"}\n\n')
    stream.push('event: done\ndata: {}\n\n')
    stream.end()
    await act(async () => {
      await sendPromise
    })

    expect(useChatStore.getState().isStreaming).toBe(false)

    // 切回 a：历史含后端已保存的最终回复
    await act(async () => {
      await useChatStore.getState().selectSession('a')
    })
    const msgs = useChatStore.getState().messages
    const last = msgs[msgs.length - 1]
    expect(last.role).toBe('assistant')
    expect(last.content).toContain('答复')
    expect(last.isStreaming).toBeFalsy()
  })
})