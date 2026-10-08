// case_ids: MC-067
//
// 黄金策**主动新手引导**（issue #5989 · P2）**前端面**判据 —— 前端**只递交、不判定**。
//
// 判定唯一真值在服务端（`backend/ai-agent-service/app/context/menu_navigator.py::build_proactive_push`
// + `app/api/chat.py::_handle_page_enter_request`）：哪一页能推、推什么、推几次，前端说了不算。
// 本文件判三件事：
//   ① 首次进页 ⇒ 递一轮 `__PAGE_ENTER__|{"route": …}`（运输形态 = 复用既有 `/api/chat/send`）；
//   ② 服务端回**静默流** ⇒ 什么都不渲染（不留空助手气泡、不弹错）；
//   ③ 递上去的 body 里**只有 route**（不带角色、不带页面清单 —— 否则就是把判定抄到客户端）。
//
// ⚠️ 频率上限（每页每会话 1 次）**不在这里判**：服务端是承载体（前端只做「同 route 不重复递」的省流）。

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act } from '@testing-library/react'

const mockAuthGetState = vi.fn()

vi.mock('@/lib/api', () => ({
  chatApi: {
    AI_SERVICE_URL: 'http://localhost:8001',
    getSessions: vi.fn().mockResolvedValue({ sessions: [] }),
    createSession: vi.fn(),
    getHistory: vi.fn(),
    closeSession: vi.fn(),
    reopenSession: vi.fn(),
  },
}))

vi.mock('@/store/auth', () => ({
  useAuthStore: { getState: () => mockAuthGetState() },
}))

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn(), loading: vi.fn(), dismiss: vi.fn() },
}))

import { useChatStore } from '@/store/chat'

const AI_URL = 'http://localhost:8001/api/chat/send'

/** 造一个 SSE 流（事件串照抄服务端契约）。 */
function sseResponse(body: string, ok = true, status = 200): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      if (body) controller.enqueue(encoder.encode(body))
      controller.close()
    },
  })
  return { ok, status, body: stream, json: async () => ({}) } as unknown as Response
}

const PUSH_SSE =
  'event: text\ndata: {"content":"你在【商品管理】（/products）。"}\n\n' +
  'event: done\ndata: {"session_id":"cs1","message_id":null}\n\n'

/** 服务端「不推」时回的静默流：只有一个 done，**没有任何 text**。 */
const SILENT_SSE = 'event: done\ndata: {"session_id":"cs1","message_id":null}\n\n'

function setRoute(pathname: string) {
  window.history.replaceState({}, '', pathname)
}

function assistantMessages(sessionId: string) {
  return (useChatStore.getState().messageStore[sessionId] ?? []).filter(m => m.role === 'assistant')
}

beforeEach(() => {
  vi.clearAllMocks()
  mockAuthGetState.mockReturnValue({ accessToken: 'tok' })
  setRoute('/products')
  act(() => {
    useChatStore.setState({
      sessions: [{ session_id: 'cs1', title: '对话', status: 'active', created_at: '', updated_at: '' }],
      currentSessionId: 'cs1',
      messageStore: { cs1: [] },
      streams: {},
      isStreaming: false,
    })
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('notifyPageEnter（首次进页 ⇒ 递一轮「进页」事件）', () => {
  it('递上一轮进页事件，并把服务端回的主动导航提示渲染进对话区', async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(PUSH_SSE))
    vi.stubGlobal('fetch', fetchMock)

    await act(async () => {
      await useChatStore.getState().notifyPageEnter('/products')
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe(AI_URL)
    const body = JSON.parse(fetchMock.mock.calls[0][1].body)
    expect(body.session_id).toBe('cs1')
    expect(body.message).toBe('__PAGE_ENTER__|{"route":"/products"}')
    // 🔴 只递交 route：不带 role / permissions / 页面清单（判定只能发生在服务端）
    expect(Object.keys(body).sort()).toEqual(['message', 'session_id'])

    const msgs = assistantMessages('cs1')
    expect(msgs).toHaveLength(1)
    expect(msgs[0].content).toContain('商品管理')
    expect(msgs[0].isStreaming).toBe(false)
    // **没有用户气泡**：主动引导不是用户说的话
    expect((useChatStore.getState().messageStore['cs1'] ?? []).filter(m => m.role === 'user')).toHaveLength(0)
  })

  it('服务端回静默流（不推）⇒ 什么都不渲染、不留空气泡', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse(SILENT_SSE)))

    await act(async () => {
      await useChatStore.getState().notifyPageEnter('/nope-not-registered')
    })

    expect(assistantMessages('cs1')).toHaveLength(0)
    expect(useChatStore.getState().streams['cs1']).toBeUndefined()
  })

  it('未登记形态的路径（无法规范化）⇒ 根本不发请求', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    await act(async () => {
      await useChatStore.getState().notifyPageEnter('/bad path with space')
    })

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('跳过 /chat（黄金策自己的会话页不推）', async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(SILENT_SSE))
    vi.stubGlobal('fetch', fetchMock)

    await act(async () => {
      await useChatStore.getState().notifyPageEnter('/chat')
    })

    // `/chat` 也是合法路径 ⇒ 前端会递；**服务端**按未登记页面静默（这里只断言不发用户气泡）
    expect(assistantMessages('cs1')).toHaveLength(0)
  })

  it('没有会话 / 正在流式回复 ⇒ 不打断本轮', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    act(() => { useChatStore.setState({ currentSessionId: null }) })
    await act(async () => { await useChatStore.getState().notifyPageEnter('/finance') })
    expect(fetchMock).not.toHaveBeenCalled()

    act(() => { useChatStore.setState({ currentSessionId: 'cs1', isStreaming: true }) })
    await act(async () => { await useChatStore.getState().notifyPageEnter('/finance') })
    expect(fetchMock).not.toHaveBeenCalled()

    // 🔴 **被跳过 ≠ 永久丢掉**：条件恢复后（会话在、不在流式中）这一页仍应递出去
    act(() => { useChatStore.setState({ currentSessionId: 'cs1', isStreaming: false }) })
    await act(async () => { await useChatStore.getState().notifyPageEnter('/finance') })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('同一 route 连续两次 ⇒ 只递一次（省流；**权威上限在服务端**）', async () => {
    const fetchMock = vi.fn().mockResolvedValue(sseResponse(SILENT_SSE))
    vi.stubGlobal('fetch', fetchMock)

    // 用一个本文件前面没用过的 route：前端省流是**模块级**的（跨用例不清空，
    // 与真实浏览器会话同构）⇒ 用「本用例专属 route」才能断言「第一次一定递」
    await act(async () => { await useChatStore.getState().notifyPageEnter('/employees') })
    await act(async () => { await useChatStore.getState().notifyPageEnter('/employees') })
    expect(fetchMock).toHaveBeenCalledTimes(1)

    // 换一页 ⇒ 照常递（「每页」各自计数）
    await act(async () => { await useChatStore.getState().notifyPageEnter('/knowledge') })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(JSON.parse(fetchMock.mock.calls[1][1].body).message).toBe('__PAGE_ENTER__|{"route":"/knowledge"}')
  })

  it('网络失败 ⇒ 静默（主动引导是尽力而为，不打扰用户）', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))

    await act(async () => {
      await useChatStore.getState().notifyPageEnter('/products')
    })

    expect(assistantMessages('cs1')).toHaveLength(0)
    expect(useChatStore.getState().streams['cs1']).toBeUndefined()
  })
})
