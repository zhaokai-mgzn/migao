// case_ids: CH-031
/**
 * SSE 失败：气泡只给人类可读的一句，技术原文只进日志（issue #6666 判据 4）
 *
 * ## 治的形态（审计称，读码复核为真）
 *
 * `src/utils/sse.ts` 把技术原文塞进 `onError({message: '请求失败: 500'})`，`chatStore` 又原样拼成
 * `抱歉，发生错误: 请求失败: 500` 写进 **AI 气泡**；同页顶部另有一条横幅（`store.error`）说同一句
 * ⇒ ① 商家读到的是技术原文；② 同一个失败在同屏说了两遍（§31 P2「信息不重复」）。
 *
 * ## 判据
 *
 * | # | 判据 | 回归时会怎么红 |
 * |---|---|---|
 * | 1 | 气泡文案是**人类可读的一句** + 可重试指引，不含 `请求失败` / `500` 这类技术原文 | 把 `error.message` 拼回气泡 ⇒ 红 |
 * | 2 | 技术原文**只进日志**（`console.error`） | 去掉日志 ⇒ 红（现场就没法查了） |
 * | 3 | 🔴 同一个失败**只说一遍**：顶部横幅（`error`）不复述气泡那句 | 两处都说 ⇒ 红（§31 P2） |
 * | 4 | 失败后仍是「可再发一次」的状态（流结束、输入条可用、不卡在流式中） | 忘了收尾 ⇒ 红 |
 */
jest.mock('../src/services/chatService', () => ({
  createSession: jest.fn(),
  getSessionList: jest.fn(),
  getLatestSession: jest.fn(),
  deleteSession: jest.fn(),
  getSessionMessages: jest.fn(),
  getQuickActions: jest.fn(),
  createChatSSEClient: jest.fn(),
  getAgentSessionByAi: jest.fn(),
  sendAgentMessage: jest.fn(),
}))
jest.mock('../src/utils/sse', () => ({ SSEClient: jest.fn() }))

import { createChatSSEClient } from '../src/services/chatService'
import { useChatStore } from '../src/store/chatStore'

const mockCreateSSEClient = createChatSSEClient as jest.MockedFunction<typeof createChatSSEClient>

/** SSE 客户端桩：把回调抓出来，由测试决定何时报错 */
function captureCallbacks() {
  let captured: any = null
  mockCreateSSEClient.mockImplementation(
    () =>
      ({
        sendMessage: (_s: string, _m: string, _i: any, cb: any) => {
          captured = cb
        },
        abort: jest.fn(),
      }) as any,
  )
  return () => captured
}

async function sendOneMessage() {
  useChatStore.setState({
    currentSessionId: 's1',
    messages: [],
    isStreaming: false,
    streamingContent: '',
    error: null,
    handedOff: false,
    agentSessionId: null,
  })
  await useChatStore.getState().sendMessage('你好')
}

describe('SSE 失败文案（issue #6666 判据 4）', () => {
  let errSpy: jest.SpyInstance

  beforeEach(() => {
    jest.clearAllMocks()
    errSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    errSpy.mockRestore()
  })

  it('🔴 气泡给人类可读的一句 + 可重试指引，不含技术原文', async () => {
    const callbacks = captureCallbacks()
    await sendOneMessage()
    callbacks().onError({ message: '请求失败: 500', code: '500' })

    const state = useChatStore.getState()
    const ai = state.messages[state.messages.length - 1]
    expect(ai.role).toBe('assistant')
    expect(ai.content).not.toContain('请求失败')
    expect(ai.content).not.toContain('500')
    expect(ai.content).toMatch(/再发一次|重试/)
  })

  it('技术原文只进日志（console.error 里能查到原文）', async () => {
    const callbacks = captureCallbacks()
    await sendOneMessage()
    callbacks().onError({ message: '请求失败: 500', code: '500' })

    const logged = errSpy.mock.calls.map((c) => c.map(String).join(' ')).join('\n')
    expect(logged).toContain('请求失败: 500')
  })

  it('🔴 同一个失败只说一遍：顶部横幅不复述气泡那句（§31 P2）', async () => {
    const callbacks = captureCallbacks()
    await sendOneMessage()
    callbacks().onError({ message: '请求失败: 500', code: '500' })

    const state = useChatStore.getState()
    const bubble = state.messages[state.messages.length - 1].content
    expect(state.error).toBeNull()
    expect(bubble.length).toBeGreaterThan(0)
  })

  it('失败后回到可再发一次的状态（不卡在流式）', async () => {
    const callbacks = captureCallbacks()
    await sendOneMessage()
    callbacks().onError({ message: '请求失败: 500', code: '500' })

    const state = useChatStore.getState()
    expect(state.isStreaming).toBe(false)
    expect(state.streamingContent).toBe('')
  })
})
