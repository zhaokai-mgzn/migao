import { create } from 'zustand'
import { chatApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import type { ChatSession, ChatMessage, ChatToolCall, ChatCard, QuickAction } from '@/types'
import { toast } from 'sonner'
import { SSEParser, type SSEEvent } from '@/lib/sse-parser'

// 生成唯一 ID
const generateId = () => Math.random().toString(36).substring(2, 15) + Date.now().toString(36)

interface ChatState {
  // 状态
  sessions: ChatSession[]
  currentSessionId: string | null
  messages: ChatMessage[]
  isStreaming: boolean
  isLoadingSessions: boolean
  isLoadingMessages: boolean
  searchKeyword: string
  abortController: AbortController | null
  quickActions: QuickAction[]
  isLoadingQuickActions: boolean
  error: string | null

  // 方法
  fetchSessions: () => Promise<void>
  createSession: () => Promise<void>
  selectSession: (id: string) => Promise<void>
  sendMessage: (content: string, images?: string[]) => Promise<void>
  closeSession: (id: string) => Promise<void>
  setSearchKeyword: (keyword: string) => void
  stopStreaming: () => void
  clearCurrentSession: () => void
  fetchQuickActions: () => Promise<void>
}

const getToken = () => useAuthStore.getState().accessToken || ''

export const useChatStore = create<ChatState>()((set, get) => ({
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

  setSearchKeyword: (keyword: string) => set({ searchKeyword: keyword }),

  clearCurrentSession: () => set({ currentSessionId: null, messages: [], error: null }),

  fetchQuickActions: async () => {
    set({ isLoadingQuickActions: true })
    try {
      const token = getToken()
      const AI_SERVICE_URL = chatApi.AI_SERVICE_URL
      const res = await fetch(`${AI_SERVICE_URL}/api/chat/quick-actions`, {
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
      })
      if (!res.ok) throw new Error('获取快捷操作失败')
      const data = await res.json()
      const actions = data?.data?.actions || []
      set({ quickActions: actions })
    } catch (error) {
      console.error('获取快捷操作失败:', error)
    } finally {
      set({ isLoadingQuickActions: false })
    }
  },

  stopStreaming: () => {
    const { abortController } = get()
    if (abortController) {
      abortController.abort()
      set({ isStreaming: false, abortController: null })
    }
  },

  fetchSessions: async () => {
    set({ isLoadingSessions: true })
    try {
      const data = await chatApi.getSessions(getToken())
      const items = data?.data?.items || data?.data?.sessions || data?.sessions || []
      const sessions: ChatSession[] = items.map((s: any) => ({
        session_id: s.id || s.session_id,
        title: s.title || '新对话',
        status: s.status || 'active',
        customer_name: s.customer_name || undefined,
        last_message: s.last_message || undefined,
        message_count: s.message_count || 0,
        created_at: s.created_at || new Date().toISOString(),
        updated_at: s.updated_at || s.created_at || new Date().toISOString(),
      }))
      set({ sessions, error: null })

      // 如果当前没有选中会话，自动选中第一个
      if (!get().currentSessionId && sessions.length > 0) {
        get().selectSession(sessions[0].session_id)
      }
    } catch (error) {
      console.error('获取会话列表失败:', error)
      const message = error instanceof Error ? error.message : '获取会话列表失败'
      set({ error: message })
      toast.error('获取会话列表失败，请刷新页面重试')
    } finally {
      set({ isLoadingSessions: false })
    }
  },

  createSession: async () => {
    try {
      const data = await chatApi.createSession(getToken())
      const sessionData = data?.data || data
      const newSession: ChatSession = {
        session_id: sessionData.id || sessionData.session_id,
        title: sessionData.title || '新对话',
        status: 'active',
        created_at: sessionData.created_at || new Date().toISOString(),
        updated_at: sessionData.updated_at || new Date().toISOString(),
      }
      set(state => ({
        sessions: [newSession, ...state.sessions],
        currentSessionId: newSession.session_id,
        messages: [],
      }))
    } catch (error) {
      console.error('创建会话失败:', error)
      toast.error('创建会话失败，请稍后重试')
    }
  },

  selectSession: async (id: string) => {
    const { currentSessionId } = get()
    if (id === currentSessionId) return

    set({ currentSessionId: id, messages: [], isLoadingMessages: true })

    try {
      const data = await chatApi.getHistory(id, getToken())
      const rawMessages = data?.data?.messages || data?.messages || []
      const messages: ChatMessage[] = rawMessages.map((msg: any) => ({
        id: msg.id || generateId(),
        session_id: id,
        role: msg.role,
        content: msg.content,
        content_type: msg.content_type,
        images: msg.images,
        tool_calls: msg.tool_calls,
        created_at: msg.created_at,
      }))
      // 仅当用户没有切换到其他会话时更新
      if (get().currentSessionId === id) {
        set({ messages })
      }
    } catch (error) {
      console.error('获取历史消息失败:', error)
    } finally {
      set({ isLoadingMessages: false })
    }
  },

  closeSession: async (id: string) => {
    try {
      await chatApi.deleteSession(id, getToken())
      set(state => ({
        sessions: state.sessions.map(s =>
          s.session_id === id ? { ...s, status: 'closed' as const } : s
        ),
        ...(state.currentSessionId === id
          ? { currentSessionId: null, messages: [] }
          : {}),
      }))
      toast.success('会话已结束')
    } catch (error) {
      console.error('结束会话失败:', error)
      toast.error('结束会话失败')
    }
  },

  sendMessage: async (content: string, images?: string[]) => {
    const { currentSessionId, isStreaming } = get()
    if (!currentSessionId || isStreaming || !content.trim()) return

    const abortController = new AbortController()

    // 添加用户消息
    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: content.trim(),
      ...(images && images.length > 0 ? { content_type: 'mixed' as const, images } : {}),
      created_at: new Date().toISOString(),
    }

    // 添加空 AI 消息占位
    const aiMsgId = generateId()
    const aiMsg: ChatMessage = {
      id: aiMsgId,
      role: 'assistant',
      content: '',
      isStreaming: true,
      created_at: new Date().toISOString(),
    }

    set(state => ({
      messages: [...state.messages, userMsg, aiMsg],
      isStreaming: true,
      abortController,
    }))

    try {
      const token = getToken()
      const AI_SERVICE_URL = chatApi.AI_SERVICE_URL

      const response = await fetch(`${AI_SERVICE_URL}/api/chat/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          session_id: currentSessionId,
          message: content.trim(),
          ...(images && images.length > 0 ? { images } : {}),
        }),
        signal: abortController.signal,
      })

      if (!response.body) {
        throw new Error('No response body')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()

      // 创建 SSE 解析器
      const parser = new SSEParser((event: SSEEvent) => {
        handleSSEEvent(event.event, event.data, aiMsgId, set, get)
      })

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const text = decoder.decode(value, { stream: true })
        parser.parse(text)
      }
    } catch (error: any) {
      if (error.name === 'AbortError') return
      console.error('发送消息失败:', error)
      set(state => ({
        messages: state.messages.map(msg =>
          msg.id === aiMsgId
            ? { ...msg, content: '抱歉，发送消息时出现错误，请稍后重试。', isStreaming: false }
            : msg
        ),
      }))
    } finally {
      // 标记 AI 消息流式结束
      set(state => ({
        isStreaming: false,
        abortController: null,
        messages: state.messages.map(msg =>
          msg.id === aiMsgId
            ? { ...msg, isStreaming: false }
            : msg
        ),
      }))

      // 刷新会话列表以更新标题/最后消息
      get().fetchSessions()
    }
  },
}))

/** 处理 SSE 事件 */
function handleSSEEvent(
  eventType: string,
  data: any,
  aiMsgId: string,
  set: (fn: (state: ChatState) => Partial<ChatState>) => void,
  get: () => ChatState
) {
  try {
    // 如果 data 是字符串（非 JSON），尝试解析
    const parsedData = typeof data === 'string' ? JSON.parse(data) : data

    switch (eventType) {
      case 'message_start':
        // 消息开始，不需特殊处理
        break

      case 'text_delta':
      case 'text':
        // 逐字追加内容
        set(state => ({
          messages: state.messages.map(msg =>
            msg.id === aiMsgId
              ? { ...msg, content: msg.content + (parsedData.content || parsedData.delta || '') }
              : msg
          ),
        }))
        break

      case 'loading':
        // 加载状态，不追加到内容
        break

      case 'tool_call':
      case 'tool_start': {
        const toolCall: ChatToolCall = {
          name: parsedData.tool_name || parsedData.tool || parsedData.name || '工具调用',
          input: parsedData.input || parsedData.args,
          status: 'running',
        }
        set(state => ({
          messages: state.messages.map(msg =>
            msg.id === aiMsgId
              ? { ...msg, tool_calls: [...(msg.tool_calls || []), toolCall] }
              : msg
          ),
        }))
        break
      }

      case 'tool_result': {
        set(state => ({
          messages: state.messages.map(msg => {
            if (msg.id !== aiMsgId) return msg
            const toolName = parsedData.tool_name || parsedData.tool || parsedData.name
            const toolCalls = (msg.tool_calls || []).map(tc =>
              tc.name === toolName && tc.status === 'running'
                ? { ...tc, result: parsedData.result, status: 'completed' as const }
                : tc
            )
            return { ...msg, tool_calls: toolCalls }
          }),
        }))
        break
      }

      case 'card': {
        // 卡片事件：将卡片数据附加到 AI 消息
        const card: ChatCard = {
          type: parsedData.type,
          data: parsedData.data || {},
        }
        set(state => ({
          messages: state.messages.map(msg =>
            msg.id === aiMsgId
              ? { ...msg, cards: [...(msg.cards || []), card] }
              : msg
          ),
        }))
        break
      }

      case 'suggestions': {
        const suggestions = parsedData.questions || []
        set(state => ({
          messages: state.messages.map(msg =>
            msg.id === aiMsgId
              ? { ...msg, suggestions }
              : msg
          ),
        }))
        break
      }

      case 'message_end':
      case 'done':
        set(state => ({
          isStreaming: false,
          messages: state.messages.map(msg =>
            msg.id === aiMsgId ? { ...msg, isStreaming: false } : msg
          ),
        }))
        break

      case 'error':
        set(state => ({
          isStreaming: false,
          messages: state.messages.map(msg =>
            msg.id === aiMsgId
              ? { ...msg, content: `错误: ${parsedData.message || '未知错误'}`, isStreaming: false }
              : msg
          ),
        }))
        break

      case 'message':
        // 兼容 { type: "text", content: "..." } 格式
        if (parsedData.type === 'text' || parsedData.content) {
          set(state => ({
            messages: state.messages.map(msg =>
              msg.id === aiMsgId
                ? { ...msg, content: msg.content + (parsedData.content || parsedData.delta || '') }
                : msg
            ),
          }))
        } else if (parsedData.type === 'loading') {
          // loading 状态，不追加到内容
        } else if (parsedData.type === 'error') {
          set(state => ({
            messages: state.messages.map(msg =>
              msg.id === aiMsgId
                ? { ...msg, content: `错误: ${parsedData.message || '未知错误'}`, isStreaming: false }
                : msg
            ),
          }))
        }
        break

      default:
        // 未知事件类型，尝试作为文本处理
        if (parsedData.content || parsedData.delta) {
          set(state => ({
            messages: state.messages.map(msg =>
              msg.id === aiMsgId
                ? { ...msg, content: msg.content + (parsedData.content || parsedData.delta || '') }
                : msg
            ),
          }))
        }
        break;
    }
  } catch {
    // 解析失败，如果是字符串直接追加
    if (typeof data === 'string' && data.trim()) {
      set(state => ({
        messages: state.messages.map(msg =>
          msg.id === aiMsgId
            ? { ...msg, content: msg.content + data }
            : msg
        ),
      }))
    }
  }
}

export default useChatStore
