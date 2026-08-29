/**
 * 对话状态管理
 *
 * 参考管理后台 chat.ts，适配微信小程序
 * 使用 Zustand 管理会话列表、消息、流式状态
 */

import { create } from 'zustand'
import {
  createSession as apiCreateSession,
  getSessionList,
  deleteSession as apiDeleteSession,
  getSessionMessages,
  getQuickActions as apiGetQuickActions,
  createChatSSEClient,
  getAgentSessionByAi,
  sendAgentMessage,
} from '../services/chatService'
import type {
  Session,
  Message,
  QuickAction,
  CardData,
  ToolCallData,
  InteractiveData,
} from '../types'
import { SSEClient } from '../utils/sse'

// 生成唯一 ID
const generateId = () =>
  Math.random().toString(36).substring(2, 15) + Date.now().toString(36)

interface ChatState {
  // 状态
  currentSessionId: string | null
  sessions: Session[]
  messages: Message[]
  isStreaming: boolean
  streamingContent: string
  isLoadingSessions: boolean
  isLoadingMessages: boolean
  quickActions: QuickAction[]
  error: string | null

  // 转人工状态（handedOff 后消息走人工客服通道）
  handedOff: boolean
  agentSessionId: string | null
  _agentPollTimer: ReturnType<typeof setInterval> | null

  // 内部引用
  _sseClient: SSEClient | null

  // Actions
  createSession: () => Promise<void>
  loadSessions: () => Promise<void>
  deleteSession: (id: string) => Promise<void>
  selectSession: (id: string) => Promise<void>
  loadMessages: (sessionId: string) => Promise<void>
  sendMessage: (content: string, images?: string[]) => Promise<void>
  appendStreamContent: (content: string) => void
  addCardMessage: (data: CardData) => void
  setToolCallStatus: (toolName: string, status: ToolCallData['status']) => void
  finishStreaming: () => void
  stopStreaming: () => void
  clearMessages: () => void
  loadQuickActions: () => Promise<void>
  startAgentPolling: () => void
}

export const useChatStore = create<ChatState>()((set, get) => ({
  currentSessionId: null,
  sessions: [],
  messages: [],
  isStreaming: false,
  streamingContent: '',
  isLoadingSessions: false,
  isLoadingMessages: false,
  quickActions: [],
  error: null,
  handedOff: false,
  agentSessionId: null,
  _agentPollTimer: null,
  _sseClient: null,

  /**
   * 创建新会话
   */
  createSession: async () => {
    try {
      const session = await apiCreateSession()
      set(state => ({
        sessions: [session, ...state.sessions],
        currentSessionId: session.id,
        messages: [],
        error: null,
      }))
    } catch (error: any) {
      console.error('创建会话失败:', error)
      set({ error: '创建会话失败' })
    }
  },

  /**
   * 加载会话列表
   */
  loadSessions: async () => {
    set({ isLoadingSessions: true })
    try {
      const data = await getSessionList()
      const sessions: Session[] = (data.items || []).map((s: any) => ({
        id: s.id,
        title: s.title || '新对话',
        tenant_id: s.tenant_id,
        user_id: s.user_id,
        message_count: s.message_count,
        created_at: s.created_at,
        updated_at: s.updated_at,
      }))
      set({ sessions })
    } catch (error: any) {
      console.error('获取会话列表失败:', error)
    } finally {
      set({ isLoadingSessions: false })
    }
  },

  /**
   * 删除会话
   */
  deleteSession: async (id: string) => {
    try {
      await apiDeleteSession(id)
      set(state => ({
        sessions: state.sessions.filter(s => s.id !== id),
        ...(state.currentSessionId === id
          ? { currentSessionId: null, messages: [] }
          : {}),
      }))
    } catch (error: any) {
      console.error('删除会话失败:', error)
      set({ error: '删除会话失败' })
    }
  },

  /**
   * 选择会话
   */
  selectSession: async (id: string) => {
    const { currentSessionId } = get()
    if (id === currentSessionId) return

    set({ currentSessionId: id, messages: [], isLoadingMessages: true, error: null })

    try {
      await get().loadMessages(id)
    } catch {
      // loadMessages 内部已处理错误
    }
  },

  /**
   * 加载消息
   */
  loadMessages: async (sessionId: string) => {
    set({ isLoadingMessages: true })
    try {
      const messages = await getSessionMessages(sessionId)
      // 仅当用户未切换到其他会话时更新
      if (get().currentSessionId === sessionId) {
        set({ messages })
      }
    } catch (error: any) {
      console.error('获取历史消息失败:', error)
    } finally {
      set({ isLoadingMessages: false })
    }
  },

  /**
   * 发送消息并处理 SSE 流
   */
  sendMessage: async (content: string, images?: string[]) => {
    const { currentSessionId, isStreaming, handedOff, agentSessionId } = get()
    if (!currentSessionId || isStreaming || !content.trim()) return

    // 转人工后：消息直接进人工客服会话，不再走 AI
    if (handedOff && agentSessionId) {
      const userMsg: Message = {
        id: generateId(),
        session_id: currentSessionId,
        role: 'user',
        content: content.trim(),
        created_at: new Date().toISOString(),
      }
      set(state => ({ messages: [...state.messages, userMsg] }))
      const ok = await sendAgentMessage(agentSessionId, content.trim())
      if (!ok) {
        set({ error: '消息发送失败，请稍后重试' })
      }
      // 立即拉取一次人工会话（客服可能已回复）
      await get().startAgentPolling()
      return
    }

    // 添加用户消息
    const userMsg: Message = {
      id: generateId(),
      session_id: currentSessionId,
      role: 'user',
      content: content.trim(),
      created_at: new Date().toISOString(),
      ...(images?.length ? { images, content_type: 'mixed' as const } : {}),
    }

    // AI 消息占位
    const aiMsgId = generateId()
    const aiMsg: Message = {
      id: aiMsgId,
      session_id: currentSessionId,
      role: 'assistant',
      content: '',
      created_at: new Date().toISOString(),
      isStreaming: true,
    }

    set(state => ({
      messages: [...state.messages, userMsg, aiMsg],
      isStreaming: true,
      streamingContent: '',
      error: null,
    }))

    // 创建 SSE 客户端
    const sseClient = createChatSSEClient()
    set({ _sseClient: sseClient })

    sseClient.sendMessage(currentSessionId, content.trim(), images, {
      onText: (data) => {
        set(state => {
          const newContent = state.streamingContent + (data.content || '')
          return {
            streamingContent: newContent,
            messages: state.messages.map(msg =>
              msg.id === aiMsgId
                ? { ...msg, content: newContent }
                : msg
            ),
          }
        })
      },

      onToolCall: (data) => {
        const toolCall: ToolCallData = {
          tool: data.tool,
          args: data.args,
          status: 'running',
        }

        // 检测转人工：human_handoff 工具被调用 → 进入人工客服模式
        if (data.tool === 'human_handoff') {
          set(state => ({
            handedOff: true,
            agentSessionId: state.agentSessionId || null,
            messages: state.messages.map(msg =>
              msg.id === aiMsgId
                ? { ...msg, tool_calls: [...(msg.tool_calls || []), toolCall] }
                : msg
            ),
          }))
          // 延迟启动人工会话轮询（等 human_handoff 完成创建会话）
          setTimeout(() => {
            get().startAgentPolling()
          }, 1500)
          return
        }

        set(state => ({
          messages: state.messages.map(msg =>
            msg.id === aiMsgId
              ? { ...msg, tool_calls: [...(msg.tool_calls || []), toolCall] }
              : msg
          ),
        }))
      },

      onToolResult: (data) => {
        set(state => ({
          messages: state.messages.map(msg => {
            if (msg.id !== aiMsgId) return msg
            const toolCalls = (msg.tool_calls || []).map(tc =>
              tc.tool === data.tool && tc.status === 'running'
                ? { ...tc, result: data.result, status: 'completed' as const }
                : tc
            )
            return { ...msg, tool_calls: toolCalls }
          }),
        }))
      },

      onCard: (data) => {
        const card: CardData = {
          type: data.type,
          data: data.data,
        }
        set(state => ({
          messages: state.messages.map(msg =>
            msg.id === aiMsgId
              ? { ...msg, cards: [...(msg.cards || []), card] }
              : msg
          ),
        }))
      },

      onInteractive: (data) => {
        const interactive: InteractiveData = {
          type: (data.type || data.component || 'confirm') as InteractiveData['type'],
          component: data.component,
          title: data.title || '',
          options: data.options,
          fields: data.fields,
          confirmLabel: data.confirmLabel,
          cancelLabel: data.cancelLabel,
          confirmValue: data.confirmValue,
          cancelValue: data.cancelValue,
          formFields: data.formFields,
          submitLabel: data.submitLabel,
        }
        set(state => ({
          messages: state.messages.map(msg =>
            msg.id === aiMsgId
              ? { ...msg, interactive }
              : msg
          ),
        }))
      },

      onSuggestions: (data) => {
        set(state => ({
          messages: state.messages.map(msg =>
            msg.id === aiMsgId
              ? { ...msg, suggestions: data.questions || [] }
              : msg
          ),
        }))
      },

      onLoading: (_data) => {
        // 加载状态，不追加到内容
      },

      onDone: (_data) => {
        set(state => ({
          isStreaming: false,
          streamingContent: '',
          _sseClient: null,
          messages: state.messages.map(msg =>
            msg.id === aiMsgId ? { ...msg, isStreaming: false } : msg
          ),
        }))
        // 刷新会话列表
        get().loadSessions()
      },

      onError: (error) => {
        console.error('SSE 错误:', error)
        set(state => ({
          isStreaming: false,
          streamingContent: '',
          _sseClient: null,
          error: error.message,
          messages: state.messages.map(msg =>
            msg.id === aiMsgId
              ? {
                  ...msg,
                  content: msg.content || `抱歉，发生错误: ${error.message}`,
                  isStreaming: false,
                }
              : msg
          ),
        }))
      },
    })
  },

  /**
   * 追加流式内容
   */
  appendStreamContent: (content: string) => {
    set(state => ({
      streamingContent: state.streamingContent + content,
    }))
  },

  /**
   * 添加卡片消息
   */
  addCardMessage: (data: CardData) => {
    const { messages } = get()
    // 找到最后一条 assistant 消息，附加卡片
    const lastAiIdx = [...messages].reverse().findIndex(m => m.role === 'assistant')
    if (lastAiIdx === -1) return
    const idx = messages.length - 1 - lastAiIdx
    set(state => ({
      messages: state.messages.map((msg, i) =>
        i === idx
          ? { ...msg, cards: [...(msg.cards || []), data] }
          : msg
      ),
    }))
  },

  /**
   * 设置工具调用状态
   */
  setToolCallStatus: (toolName: string, status: ToolCallData['status']) => {
    set(state => ({
      messages: state.messages.map(msg => {
        if (msg.role !== 'assistant' || !msg.tool_calls) return msg
        return {
          ...msg,
          tool_calls: msg.tool_calls.map(tc =>
            tc.tool === toolName ? { ...tc, status } : tc
          ),
        }
      }),
    }))
  },

  /**
   * 结束流式
   */
  finishStreaming: () => {
    set(state => ({
      isStreaming: false,
      streamingContent: '',
      _sseClient: null,
      messages: state.messages.map(msg =>
        msg.isStreaming ? { ...msg, isStreaming: false } : msg
      ),
    }))
  },

  /**
   * 停止流式（用户主动取消）
   */
  stopStreaming: () => {
    const { _sseClient } = get()
    if (_sseClient) {
      _sseClient.abort()
    }
    set(state => ({
      isStreaming: false,
      streamingContent: '',
      _sseClient: null,
      messages: state.messages.map(msg =>
        msg.isStreaming ? { ...msg, isStreaming: false } : msg
      ),
    }))
  },

  /**
   * 清空消息和会话状态（登出时调用）
   */
  clearMessages: () => {
    const { _sseClient, _agentPollTimer } = get()
    if (_sseClient) {
      _sseClient.abort()
    }
    if (_agentPollTimer) {
      clearInterval(_agentPollTimer)
    }
    set({
      messages: [],
      sessions: [],
      currentSessionId: null,
      error: null,
      isStreaming: false,
      streamingContent: '',
      handedOff: false,
      agentSessionId: null,
      _agentPollTimer: null,
      _sseClient: null,
    })
  },

  /**
   * 加载快捷操作
   */
  loadQuickActions: async () => {
    try {
      const actions = await apiGetQuickActions()
      set({ quickActions: actions })
    } catch (error) {
      console.error('获取快捷操作失败:', error)
    }
  },

  /**
   * 轮询人工客服会话消息（转人工后显示客服回复）
   * 通过 AI 会话 ID 查询人工会话，把客服消息追加到消息列表（去重）。
   */
  startAgentPolling: () => {
    const { _agentPollTimer, currentSessionId, agentSessionId } = get()
    // 清掉旧轮询
    if (_agentPollTimer) {
      clearInterval(_agentPollTimer)
    }

    const pollOnce = async () => {
      const { currentSessionId: sid, handedOff } = get()
      if (!sid || !handedOff) return
      const detail = await getAgentSessionByAi(sid)
      if (!detail || !detail.messages) return

      set(state => {
        // 首次拿到 agentSessionId
        const resolvedAgentId = state.agentSessionId || detail.id
        // 把人工客服消息映射为 assistant 消息（去重 by id）
        const existingIds = new Set(state.messages.map(m => m.id))
        const agentMsgs = (detail.messages || [])
          .filter(m => m.senderType === 'agent')
          .map(m => ({
            id: `agent-${m.id}`,
            session_id: sid,
            role: 'assistant' as const,
            content: m.content,
            created_at: m.createdAt,
          }))
          .filter(m => !existingIds.has(m.id))
        if (agentMsgs.length === 0 && state.agentSessionId === resolvedAgentId) {
          return state
        }
        return {
          ...state,
          agentSessionId: resolvedAgentId,
          messages: [...state.messages, ...agentMsgs],
        }
      })
    }

    // 立即拉一次
    pollOnce()
    // 每 3s 轮询（POC 简单版）
    const timer = setInterval(pollOnce, 3000)
    set({ _agentPollTimer: timer })
    void agentSessionId
  },
}))

export default useChatStore
