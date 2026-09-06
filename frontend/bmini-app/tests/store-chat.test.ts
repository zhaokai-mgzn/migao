/**
 * Chat Zustand Store 测试
 *
 * 覆盖: 会话管理(创建/加载/删除/选择)、消息管理、流式状态
 */
// case_ids: UI-013

// Mock chatService
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

// Mock sse
jest.mock('../src/utils/sse', () => ({
  SSEClient: jest.fn(),
}))

import {
  createSession as apiCreateSession,
  getSessionList,
  deleteSession as apiDeleteSession,
  getSessionMessages,
  getQuickActions,
  createChatSSEClient,
} from '../src/services/chatService'

const mockApiCreateSession = apiCreateSession as jest.MockedFunction<typeof apiCreateSession>
const mockGetSessionList = getSessionList as jest.MockedFunction<typeof getSessionList>
const mockApiDeleteSession = apiDeleteSession as jest.MockedFunction<typeof apiDeleteSession>
const mockGetSessionMessages = getSessionMessages as jest.MockedFunction<typeof getSessionMessages>
const mockGetQuickActions = getQuickActions as jest.MockedFunction<typeof getQuickActions>
const mockCreateChatSSEClient = createChatSSEClient as jest.MockedFunction<typeof createChatSSEClient>

function getChatStore() {
  jest.resetModules()
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
  const { useChatStore } = require('../src/store/chatStore')
  return useChatStore
}

describe('chatStore', () => {
  describe('初始状态', () => {
    it('应有正确的初始状态', () => {
      const store = getChatStore()
      const state = store.getState()
      expect(state.currentSessionId).toBeNull()
      expect(state.sessions).toEqual([])
      expect(state.messages).toEqual([])
      expect(state.isStreaming).toBe(false)
      expect(state.streamingContent).toBe('')
      expect(state.quickActions).toEqual([])
      expect(state.error).toBeNull()
    })
  })

  describe('createSession', () => {
    it('创建会话成功应更新 sessions 和 currentSessionId', async () => {
      const store = getChatStore()
      const { createSession: mockCreate } = require('../src/services/chatService')
      const session = { id: 's1', title: '新对话', created_at: '2024-01-01', updated_at: '2024-01-01' }
      mockCreate.mockResolvedValueOnce(session)

      await store.getState().createSession()

      const state = store.getState()
      expect(state.sessions).toHaveLength(1)
      expect(state.sessions[0]).toEqual(session)
      expect(state.currentSessionId).toBe('s1')
      expect(state.messages).toEqual([])
    })

    it('创建会话失败应设置 error', async () => {
      const store = getChatStore()
      const { createSession: mockCreate } = require('../src/services/chatService')
      mockCreate.mockRejectedValueOnce(new Error('创建失败'))

      await store.getState().createSession()

      expect(store.getState().error).toBe('创建会话失败')
    })
  })

  describe('loadSessions', () => {
    it('加载会话列表应更新 sessions', async () => {
      const store = getChatStore()
      const { getSessionList: mockList } = require('../src/services/chatService')
      mockList.mockResolvedValueOnce({
        items: [
          { id: 's1', title: '对话1', created_at: '2024-01-01', updated_at: '2024-01-01' },
          { id: 's2', title: '对话2', created_at: '2024-01-02', updated_at: '2024-01-02' },
        ],
      })

      await store.getState().loadSessions()

      expect(store.getState().sessions).toHaveLength(2)
      expect(store.getState().isLoadingSessions).toBe(false)
    })

    it('加载失败不应崩溃', async () => {
      const store = getChatStore()
      const { getSessionList: mockList } = require('../src/services/chatService')
      mockList.mockRejectedValueOnce(new Error('网络错误'))

      await store.getState().loadSessions()

      expect(store.getState().isLoadingSessions).toBe(false)
    })
  })

  describe('deleteSession', () => {
    it('删除会话应从列表移除', async () => {
      const store = getChatStore()
      const { createSession: mockCreate, deleteSession: mockDel } = require('../src/services/chatService')

      const session = { id: 's1', title: '对话', created_at: '2024-01-01', updated_at: '2024-01-01' }
      mockCreate.mockResolvedValueOnce(session)
      await store.getState().createSession()

      mockDel.mockResolvedValueOnce(undefined)
      await store.getState().deleteSession('s1')

      expect(store.getState().sessions).toHaveLength(0)
      expect(store.getState().currentSessionId).toBeNull()
    })
  })

  describe('selectSession', () => {
    it('选择会话应加载消息', async () => {
      const store = getChatStore()
      const { getSessionMessages: mockMsgs } = require('../src/services/chatService')

      const msgs = [
        { id: 'm1', role: 'user', content: '你好', created_at: '2024-01-01' },
        { id: 'm2', role: 'assistant', content: '你好！', created_at: '2024-01-01' },
      ]
      mockMsgs.mockResolvedValueOnce(msgs)

      // 先设置 currentSessionId 为 null
      await store.getState().selectSession('s1')

      expect(store.getState().currentSessionId).toBe('s1')
    })

    it('选择相同会话不应重复加载', async () => {
      const store = getChatStore()
      const { getSessionMessages: mockMsgs } = require('../src/services/chatService')
      mockMsgs.mockResolvedValueOnce([])

      await store.getState().selectSession('s1')
      await store.getState().selectSession('s1')

      // selectSession 内部第二次会跳过因为 id === currentSessionId
      expect(mockMsgs).toHaveBeenCalledTimes(1)
    })
  })

  describe('流式状态管理', () => {
    it('appendStreamContent 应追加内容', () => {
      const store = getChatStore()
      store.getState().appendStreamContent('你')
      store.getState().appendStreamContent('好')
      expect(store.getState().streamingContent).toBe('你好')
    })

    it('finishStreaming 应重置流式状态', () => {
      const store = getChatStore()
      store.setState({ isStreaming: true, streamingContent: '内容' })
      store.getState().finishStreaming()

      expect(store.getState().isStreaming).toBe(false)
      expect(store.getState().streamingContent).toBe('')
    })

    it('stopStreaming 应取消并重置', () => {
      const store = getChatStore()
      const mockAbort = jest.fn()
      store.setState({
        isStreaming: true,
        _sseClient: { abort: mockAbort } as any,
      })

      store.getState().stopStreaming()

      expect(mockAbort).toHaveBeenCalled()
      expect(store.getState().isStreaming).toBe(false)
    })
  })

  describe('clearMessages', () => {
    it('应清空所有消息和会话状态', () => {
      const store = getChatStore()
      store.setState({
        messages: [{ id: 'm1' }],
        sessions: [{ id: 's1' }],
        currentSessionId: 's1',
        error: '错误',
      })

      store.getState().clearMessages()

      const state = store.getState()
      expect(state.messages).toEqual([])
      expect(state.sessions).toEqual([])
      expect(state.currentSessionId).toBeNull()
      expect(state.error).toBeNull()
    })
  })

  describe('loadQuickActions', () => {
    it('应加载快捷操作', async () => {
      const store = getChatStore()
      const { getQuickActions: mockQa } = require('../src/services/chatService')
      const actions = [
        { id: 'q1', name: '查订单', prompt: '查一下我的订单' },
      ]
      mockQa.mockResolvedValueOnce(actions)

      await store.getState().loadQuickActions()

      expect(store.getState().quickActions).toEqual(actions)
    })
  })

  // UI-013: 纯图消息放行（拍照识别：无文本仅图片 → SSE 带 images 发送）
  describe('sendMessage 纯图', () => {
    it('纯图消息（空文本 + images）应放行并携带 images 发送', async () => {
      const store = getChatStore()
      const { createChatSSEClient: mockCreate } = require('../src/services/chatService')
      const sseSend = jest.fn()
      mockCreate.mockReturnValue({ sendMessage: sseSend })
      store.setState({ currentSessionId: 's1', isStreaming: false, handedOff: false })

      await store.getState().sendMessage('', ['https://img.example.com/curtain.jpg'])

      // SSE 客户端已发送：sessionId / message='' / images 透传
      expect(sseSend).toHaveBeenCalledTimes(1)
      expect(sseSend.mock.calls[0][0]).toBe('s1')
      expect(sseSend.mock.calls[0][1]).toBe('')
      expect(sseSend.mock.calls[0][2]).toEqual(['https://img.example.com/curtain.jpg'])
      // 用户消息入 messages：content 空但 images 保留
      const userMsg = store.getState().messages[0]
      expect(userMsg.role).toBe('user')
      expect(userMsg.content).toBe('')
      expect(userMsg.images).toEqual(['https://img.example.com/curtain.jpg'])
    })

    it('空文本且无图片仍被拦截（不发送）', async () => {
      const store = getChatStore()
      const { createChatSSEClient: mockCreate } = require('../src/services/chatService')
      const sseSend = jest.fn()
      mockCreate.mockReturnValue({ sendMessage: sseSend })
      store.setState({ currentSessionId: 's1', isStreaming: false, handedOff: false })

      await store.getState().sendMessage('   ')

      expect(sseSend).not.toHaveBeenCalled()
      expect(store.getState().messages).toHaveLength(0)
    })

    it('转人工态下纯图消息静默忽略（人工会话仅文本通道）', async () => {
      const store = getChatStore()
      const { sendAgentMessage: mockSendAgent } = require('../src/services/chatService')
      store.setState({
        currentSessionId: 's1',
        isStreaming: false,
        handedOff: true,
        agentSessionId: 'agent-1',
      })

      await store.getState().sendMessage('', ['https://img.example.com/curtain.jpg'])

      expect(mockSendAgent).not.toHaveBeenCalled()
    })
  })
})

describe('转人工轮询映射（GB-02, issue #2780）', () => {
  it('人工客服消息映射为 assistant 且 source=human（与 AI 回复可区分）', async () => {
    const store = getChatStore()
    const chatService = require('../src/services/chatService')
    const mockByAi = chatService.getAgentSessionByAi as jest.Mock
    mockByAi.mockResolvedValue({
      id: 'agent-sess-1',
      messages: [
        {
          id: 'am1',
          senderType: 'agent',
          senderId: 'emp-1',
          senderName: '客服小王',
          contentType: 'text',
          content: '您好，我是人工客服，已看到您和 AI 的沟通',
          createdAt: '2026-09-01T10:00:00Z',
        },
        {
          id: 'um1',
          senderType: 'customer',
          senderId: 'cust-1',
          contentType: 'text',
          content: '在吗',
          createdAt: '2026-09-01T10:00:01Z',
        },
      ],
    })
    store.setState({ currentSessionId: 's1', handedOff: true })

    // 启动轮询（立即拉取一次）
    store.getState().startAgentPolling()
    await new Promise(r => setTimeout(r, 10))

    const msgs = store.getState().messages
    // 仅 agent（人工客服）消息被映射；customer 消息忽略
    expect(msgs).toHaveLength(1)
    expect(msgs[0].role).toBe('assistant')
    expect(msgs[0].source).toBe('human')
    expect(msgs[0].content).toContain('我是人工客服')

    // 清理轮询定时器，避免 open handle
    const timer = (store.getState() as any)._agentPollTimer
    if (timer) clearInterval(timer)
  })
})
