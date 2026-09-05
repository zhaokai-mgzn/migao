import { create } from 'zustand'
import { chatApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'
import type { ChatSession, ChatMessage, ChatToolCall, ChatCard, QuickAction } from '@/types'
import { toast } from 'sonner'
import { SSEParser, type SSEEvent } from '@/lib/sse-parser'

// 生成唯一 ID
const generateId = () => Math.random().toString(36).substring(2, 15) + Date.now().toString(36)

/** 在途流：AI 回复累计缓冲 + 该流的 abort 控制器（多会话并发，key = 归属 session_id） */
interface ActiveStream {
  aiMsg: ChatMessage
  abortController: AbortController
}

interface ChatState {
  // 状态
  sessions: ChatSession[]
  currentSessionId: string | null
  // 每会话消息存储（快照）：切换会话即时渲染缓存；历史以服务端为准，切换时刷新
  messageStore: Record<string, ChatMessage[]>
  // 每会话在途流（多会话并发）：等待动画/增量/停止互不干扰（issue #2906）
  streams: Record<string, ActiveStream>
  // ── 以下为「当前视图」投影：由 withView() 从 messageStore+streams 推导，
  //    保持既有组件/存量测试的 messages/isStreaming/abortController 契约不变 ──
  messages: ChatMessage[]
  isStreaming: boolean
  abortController: AbortController | null
  isLoadingSessions: boolean
  isLoadingMessages: boolean
  searchKeyword: string
  quickActions: QuickAction[]
  isLoadingQuickActions: boolean
  error: string | null
  // choice 多选勾选（key = `${sessionId}:${tool}`，跨页保留）
  // 加工项选择场景：点击选项仅本地勾选累积，不触发 agent 回复，
  // 用户点「完成选择」后一次性提交；翻页后新卡片从 store 恢复已选（issue #2896）
  choiceSelections: Record<string, string[]>

  // 方法
  fetchSessions: () => Promise<void>
  createSession: () => Promise<void>
  selectSession: (id: string) => Promise<void>
  sendMessage: (content: string, images?: string[]) => Promise<void>
  closeSession: (id: string) => Promise<void>
  reopenSession: (id: string) => Promise<void>
  setSearchKeyword: (keyword: string) => void
  stopStreaming: () => void
  clearCurrentSession: () => void
  fetchQuickActions: () => Promise<void>
  toggleChoiceSelection: (sessionId: string, tool: string, label: string) => void
  clearChoiceSelections: (sessionId: string, tool: string) => void
}

const getToken = () => useAuthStore.getState().accessToken || ''

// 跨模式持久化：浮窗模式和全屏模式共享同一个 session ID
const PERSISTED_SESSION_KEY = 'mibao_current_session_id'

const persistSessionId = (id: string | null) => {
  try {
    if (id) localStorage.setItem(PERSISTED_SESSION_KEY, id)
    else localStorage.removeItem(PERSISTED_SESSION_KEY)
  } catch { /* ignore */ }
}

const restoreSessionId = (): string | null => {
  try { return localStorage.getItem(PERSISTED_SESSION_KEY) } catch { return null }
}

/** 检查是否有未完成的工具调用（阻断切换/新建，避免打断交互流程） */
function hasPendingTools(messages: ChatMessage[]): boolean {
  return messages.some(
    msg => msg.role === 'assistant' && msg.tool_calls && msg.tool_calls.some(tc => tc.status === 'running')
  )
}

/** 某会话的「有效」消息 = messageStore 快照 + 该会话在途流占位（如正在流式） */
function storeMessages(state: ChatState, key: string | null): ChatMessage[] {
  if (!key) return []
  const base = state.messageStore[key] ?? []
  const stream = state.streams[key]
  return stream ? [...base, stream.aiMsg] : base
}

/** 由单一事实源（messageStore + streams + currentSessionId）重算「当前视图」投影 */
function projectView(state: ChatState): Partial<ChatState> {
  const cur = state.currentSessionId
  if (!cur) return { messages: [], isStreaming: false, abortController: null }
  const base = state.messageStore[cur] ?? []
  const stream = state.streams[cur]
  return {
    messages: stream ? [...base, stream.aiMsg] : base,
    isStreaming: !!stream,
    abortController: stream?.abortController ?? null,
  }
}

/** 合并 patch 并重算投影：组件/存量测试仍读 messages/isStreaming，永不与底层脱节 */
function withView(prev: ChatState, patch: Partial<ChatState>): Partial<ChatState> {
  const next = { ...prev, ...patch }
  return { ...patch, ...projectView(next) }
}

/** 按占位 id 找到归属流（对 session 轮换后的 key 变更免疫） */
function findStreamKey(state: ChatState, aiMsgId: string): string | null {
  const keys = Object.keys(state.streams)
  for (let i = 0; i < keys.length; i++) {
    if (state.streams[keys[i]].aiMsg.id === aiMsgId) return keys[i]
  }
  return null
}

/** 更新指定流的占位消息（只写 streams，视图由 withView 重算） */
function patchStream(
  state: ChatState,
  aiMsgId: string,
  update: (msg: ChatMessage) => ChatMessage
): Partial<ChatState> {
  const key = findStreamKey(state, aiMsgId)
  if (key === null) return {}
  const stream = state.streams[key]
  return { streams: { ...state.streams, [key]: { ...stream, aiMsg: update(stream.aiMsg) } } }
}

function omitStream(streams: Record<string, ActiveStream>, key: string): Record<string, ActiveStream> {
  const next = { ...streams }
  delete next[key]
  return next
}

export const useChatStore = create<ChatState>()((set, get) => ({
  sessions: [],
  currentSessionId: null,
  messageStore: {},
  streams: {},
  messages: [],
  isStreaming: false,
  abortController: null,
  isLoadingSessions: false,
  isLoadingMessages: false,
  searchKeyword: '',
  quickActions: [],
  isLoadingQuickActions: false,
  error: null,
  choiceSelections: {},

  setSearchKeyword: (keyword: string) => set({ searchKeyword: keyword }),

  clearCurrentSession: () => set(state => withView(state, {
    currentSessionId: null,
    error: null,
    choiceSelections: {},
  })),

  toggleChoiceSelection: (sessionId: string, tool: string, label: string) => {
    const key = `${sessionId}:${tool}`
    set(state => {
      const current = state.choiceSelections[key] || []
      const next = current.includes(label)
        ? current.filter(l => l !== label)
        : [...current, label]
      return { choiceSelections: { ...state.choiceSelections, [key]: next } }
    })
  },

  clearChoiceSelections: (sessionId: string, tool: string) => {
    const key = `${sessionId}:${tool}`
    set(state => {
      const next = { ...state.choiceSelections }
      delete next[key]
      return { choiceSelections: next }
    })
  },

  fetchQuickActions: async () => {
    set({ isLoadingQuickActions: true })
    try {
      const token = getToken()
      const AI_SERVICE_URL = chatApi.AI_SERVICE_URL
      const res = await fetch(`${AI_SERVICE_URL}/api/chat/quick-actions`, {
        // P0-3 补齐：credentials include — 整页刷新后内存 token 丢失，
        // 需携带 HttpOnly cookie（.migaozn.com）让 ai-agent 恢复真实身份
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
      })
      if (!res.ok) throw new Error('获取快捷操作失败')
      const data = await res.json()
      const actions = data?.data?.actions || []
      set({ quickActions: actions })
    } catch (e) {
      // ai-agent 未启动时静默失败，页面已有空状态提示
    } finally {
      set({ isLoadingQuickActions: false })
    }
  },

  stopStreaming: () => {
    const { currentSessionId, streams } = get()
    if (!currentSessionId) return
    const stream = streams[currentSessionId]
    if (!stream) return
    // 只停当前会话这一条流；其他会话的并发流不受影响（issue #2906）
    stream.abortController.abort()
    const abortedMsg: ChatMessage = { ...stream.aiMsg, isStreaming: false, wasAborted: true }
    set(state => withView(state, {
      streams: omitStream(state.streams, currentSessionId),
      messageStore: {
        ...state.messageStore,
        [currentSessionId]: [...(state.messageStore[currentSessionId] ?? []), abortedMsg],
      },
    }))
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
      // 如果当前有选中会话但服务端列表里没有（刚新建的），补到最前面
      const currentId = get().currentSessionId
      let finalSessions = sessions
      if (currentId && !sessions.find(s => s.session_id === currentId)) {
        const currentSession = get().sessions.find(s => s.session_id === currentId)
        if (currentSession) {
          finalSessions = [currentSession, ...sessions]
        }
      }

      set({ sessions: finalSessions, error: null })

      // 如果没有选中会话且无未完成交互，自动选中第一个
      if (!get().currentSessionId && sessions.length > 0 && !hasPendingTools(get().messages)) {
        get().selectSession(sessions[0].session_id)
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : '获取会话列表失败'
      set({ error: message })
      // 不弹 toast 刷屏，在页面上友好提示
    } finally {
      set({ isLoadingSessions: false })
    }
  },

  createSession: async () => {
    // 检查是否有未完成的交互组件（form/choice/confirm 等待用户操作）
    if (hasPendingTools(get().messages)) {
      toast.warning('当前有未完成的交互操作，请先完成后再创建新对话')
      return
    }

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
      // 支持多会话并存，不再自动关闭其他活跃会话
      set(state => withView(state, {
        sessions: [newSession, ...state.sessions],
        currentSessionId: newSession.session_id,
        messageStore: { ...state.messageStore, [newSession.session_id]: [] },
      }))
      persistSessionId(newSession.session_id)
    } catch (error) {
      console.error('创建会话失败:', error)
      toast.error('创建会话失败，请稍后重试')
    }
  },

  selectSession: async (id: string) => {
    const { currentSessionId } = get()
    if (id === currentSessionId) return

    // 检查是否有未完成的交互组件，避免中断交互流程
    if (hasPendingTools(get().messages)) {
      toast.warning('当前有未完成的交互操作，请先完成后再切换会话')
      return
    }

    const requestId = generateId() // 请求去重标记
    // 先切视图：已缓存会话即时渲染（messageStore 快照 + 该会话在途流占位），再拉最新历史
    set(state => withView(state, { currentSessionId: id, isLoadingMessages: true, choiceSelections: {} }))
    persistSessionId(id)

    try {
      const data = await chatApi.getHistory(id, getToken())
      // 请求返回时确认未切到其他 session
      if (get().currentSessionId !== id) return
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
      // 仅当用户没有切换到其他会话时更新（历史为新会话权威，覆盖缓存快照；
      // 在途流在 streams 中独立持有，不受覆盖影响 —— issue #2906）
      if (get().currentSessionId === id) {
        set(state => withView(state, {
          messageStore: { ...state.messageStore, [id]: messages },
        }))
      }
    } catch (error) {
      console.error('获取历史消息失败:', error)
    } finally {
      set({ isLoadingMessages: false })
    }
  },

  closeSession: async (id: string) => {
    // 关闭的是当前会话时，检查是否有未完成的交互组件
    if (id === get().currentSessionId && hasPendingTools(get().messages)) {
      toast.warning('当前有未完成的交互操作，请先完成后再关闭会话')
      return
    }
    try {
      await chatApi.closeSession(id, getToken())
      // 仅更新状态为 closed，保留会话与历史消息
      set(state => ({
        sessions: state.sessions.map(s =>
          s.session_id === id ? { ...s, status: 'closed' as const } : s
        ),
      }))
      toast.success('会话已结束')
    } catch (error) {
      console.error('结束会话失败:', error)
      toast.error('结束会话失败')
    }
  },

  reopenSession: async (id: string) => {
    try {
      await chatApi.reopenSession(id, getToken())
      set(state => ({
        sessions: state.sessions.map(s =>
          s.session_id === id ? { ...s, status: 'active' as const } : s
        ),
      }))
      toast.success('会话已重新打开')
    } catch (error) {
      console.error('重新打开会话失败:', error)
      toast.error('重新打开会话失败')
    }
  },

  // 校验会话是否仍然活跃（浮窗/全屏模式切换时使用）
  validateSessionStatus: async (id: string): Promise<'active' | 'closed' | 'not_found'> => {
    try {
      // 先检查本地 sessions 列表
      const local = get().sessions.find(s => s.session_id === id)
      if (local) return local.status === 'active' ? 'active' : 'closed'
      // 不在本地列表中，刷新列表再查
      await get().fetchSessions()
      const refreshed = get().sessions.find(s => s.session_id === id)
      if (refreshed) return refreshed.status === 'active' ? 'active' : 'closed'
      return 'not_found'
    } catch {
      return 'not_found'
    }
  },

  sendMessage: async (content: string, images?: string[]) => {
    const { currentSessionId, isStreaming, sessions } = get()
    // 只挡当前会话正在回复；其他会话的并发流不受影响（issue #2906）
    if (!currentSessionId || isStreaming || !content.trim()) return

    // 拒绝向已关闭会话发送消息
    const currentSession = sessions.find(s => s.session_id === currentSessionId)
    if (currentSession?.status === 'closed') {
      toast.error('会话已结束，请创建新对话')
      return
    }

    const abortController = new AbortController()

    // 检查上一轮 AI 消息是否有未被采纳的建议（用于日志分析）—— 基于当前视图
    const lastAiMsg = [...get().messages].reverse().find(m => m.role === 'assistant')
    const ignoredSuggestions = lastAiMsg?.suggestions?.filter(
      s => s !== content.trim()
    ) || []

    // 添加用户消息
    const userMsg: ChatMessage = {
      id: generateId(),
      role: 'user',
      content: content.trim(),
      ...(images && images.length > 0 ? { content_type: 'mixed' as const, images } : {}),
      created_at: new Date().toISOString(),
    }

    // 清除上一轮 AI 消息的建议（已被消费）—— 写入归属会话的 messageStore
    set(state => withView(state, {
      messageStore: {
        ...state.messageStore,
        [currentSessionId]: (state.messageStore[currentSessionId] ?? []).map(msg =>
          msg.id === lastAiMsg?.id ? { ...msg, suggestions: undefined } : msg
        ),
      },
    }))

    // 添加空 AI 消息占位（存于本会话 streams，不入 messageStore）
    const aiMsgId = generateId()
    const aiMsg: ChatMessage = {
      id: aiMsgId,
      role: 'assistant',
      content: '',
      isStreaming: true,
      created_at: new Date().toISOString(),
    }

    set(state => withView(state, {
      messageStore: {
        ...state.messageStore,
        [currentSessionId]: [...(state.messageStore[currentSessionId] ?? []), userMsg],
      },
      streams: { ...state.streams, [currentSessionId]: { aiMsg, abortController } },
    }))

    try {
      const token = getToken()
      const AI_SERVICE_URL = chatApi.AI_SERVICE_URL

      const response = await fetch(`${AI_SERVICE_URL}/api/chat/send`, {
        method: 'POST',
        // P0-3 补齐：credentials include — 整页刷新后内存 token 丢失，
        // 需携带 HttpOnly cookie 让 ai-agent 恢复真实租户身份（否则空 Bearer → 401）
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          session_id: currentSessionId,
          message: content.trim(),
          ...(images && images.length > 0 ? { images } : {}),
          ...(ignoredSuggestions.length > 0 ? { ignored_suggestions: ignoredSuggestions } : {}),
        }),
        signal: abortController.signal,
      })

      if (!response.ok) {
        // 非 2xx 响应：解析错误信息
        let errorMsg = '请求失败'
        try {
          const errData = await response.json()
          errorMsg = errData?.detail?.error?.message || errData?.detail?.message || errorMsg
        } catch (e) { console.error("chat.ts", e); }
        throw { status: response.status, message: errorMsg, isSessionClosed: response.status === 409 }
      }

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

      // 检查是否是 409 SESSION_CLOSED
      const isSessionClosed = error?.isSessionClosed === true || error?.status === 409

      if (isSessionClosed) {
        // 会话已被后端关闭，提示用户手动创建新对话
        set(state => withView(state, {
          ...patchStream(state, aiMsgId, msg => ({
            ...msg,
            content: '会话已结束，请点击"新建对话"开始新会话。',
            isStreaming: false,
          })),
        }))
        toast.error('会话已结束，请创建新对话')
        return
      }

      set(state => withView(state, {
        ...patchStream(state, aiMsgId, msg => ({
          ...msg,
          content: '抱歉，发送消息时出现错误，请稍后重试。',
          isStreaming: false,
        })),
      }))
    } finally {
      // 流结束：终态消息落库到归属会话，删除该流（多会话互不影响，issue #2906）
      const aborted = abortController.signal.aborted
      const streamKey = findStreamKey(get(), aiMsgId)
      if (streamKey !== null) {
        const stream = get().streams[streamKey]
        const finalMsg: ChatMessage = { ...stream.aiMsg, isStreaming: false, wasAborted: aborted }
        set(state => withView(state, {
          streams: omitStream(state.streams, streamKey),
          messageStore: {
            ...state.messageStore,
            [streamKey]: [...(state.messageStore[streamKey] ?? []), finalMsg],
          },
        }))
      } else {
        // 已被 stopStreaming 提前落库（aborted 消息已在 messageStore）——仅重算投影
        set(state => withView(state, {}))
      }

      // 刷新会话列表以更新标题/最后消息
      get().fetchSessions()
    }
  },
}))

/** 处理 SSE 事件（写归属流的缓冲，视图由 withView 重算） */
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
        // 逐字追加内容（写归属流，issue #2906 多会话并发互不串流）
        set(state => withView(state, patchStream(state, aiMsgId, msg => ({
          ...msg,
          content: msg.content + (parsedData.content || parsedData.delta || ''),
        }))))
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
        set(state => withView(state, patchStream(state, aiMsgId, msg => ({
          ...msg,
          tool_calls: [...(msg.tool_calls || []), toolCall],
        }))))
        break
      }

      case 'tool_result': {
        set(state => withView(state, patchStream(state, aiMsgId, msg => {
          const toolName = parsedData.tool_name || parsedData.tool || parsedData.name
          const toolCalls = (msg.tool_calls || []).map(tc =>
            tc.name === toolName && tc.status === 'running'
              ? { ...tc, result: parsedData.result, status: 'completed' as const }
              : tc
          )
          return { ...msg, tool_calls: toolCalls }
        })))
        break
      }

      case 'card': {
        // 卡片事件：将卡片数据附加到 AI 消息
        const card: ChatCard = {
          type: parsedData.type,
          data: parsedData.data || {},
        }
        set(state => withView(state, patchStream(state, aiMsgId, msg => ({
          ...msg,
          cards: [...(msg.cards || []), card],
        }))))
        break
      }

      case 'suggestions': {
        const suggestions = parsedData.questions || []
        set(state => withView(state, patchStream(state, aiMsgId, msg => ({ ...msg, suggestions }))))
        break
      }

      case 'message_end':
      case 'done':
        set(state => {
          // 后端可能因空闲超时轮换到新 session_id，需同步前端状态
          // 但如果有未完成的交互组件，不执行轮换（防止打断交互流程）
          const newSessionId =
            typeof parsedData?.session_id === 'string' ? parsedData.session_id : null
          const key = findStreamKey(state, aiMsgId)
          // 交互守卫：正在看该会话时以投影（含在途 tool_calls）为准，否则用该会话 store
          const pendingT = key !== null
            ? hasPendingTools(key === state.currentSessionId ? state.messages : storeMessages(state, key))
            : false
          const shouldRotate = !!newSessionId && newSessionId !== key && !pendingT
          const patch = key !== null
            ? patchStream(state, aiMsgId, msg => ({ ...msg, isStreaming: false }))
            : {}
          if (shouldRotate && key !== null) {
            persistSessionId(newSessionId)
            // 流与消息快照随会话迁移到新 id（后端续聊轮换）；仅当用户正看该会话时切换视图
            return withView(state, {
              ...patch,
              streams: {
                ...omitStream(state.streams, key),
                [newSessionId]: state.streams[key],
              },
              messageStore: {
                ...state.messageStore,
                [newSessionId]: [...(state.messageStore[newSessionId] ?? []), ...(state.messageStore[key] ?? [])],
              },
              ...(state.currentSessionId === key ? { currentSessionId: newSessionId } : {}),
            })
          }
          return withView(state, patch)
        })
        break

      case 'error':
        set(state => withView(state, {
          ...patchStream(state, aiMsgId, msg => ({
            ...msg,
            content: `错误: ${parsedData.message || '未知错误'}`,
            isStreaming: false,
          })),
        }))
        break

      case 'message':
        // 兼容 { type: "text", content: "..." } 格式
        if (parsedData.type === 'text' || parsedData.content) {
          set(state => withView(state, patchStream(state, aiMsgId, msg => ({
            ...msg,
            content: msg.content + (parsedData.content || parsedData.delta || ''),
          }))))
        } else if (parsedData.type === 'loading') {
          // loading 状态，不追加到内容
        } else if (parsedData.type === 'error') {
          set(state => withView(state, {
            ...patchStream(state, aiMsgId, msg => ({
              ...msg,
              content: `错误: ${parsedData.message || '未知错误'}`,
              isStreaming: false,
            })),
          }))
        }
        break

      case 'interactive':
        if (parsedData.type && parsedData.component) {
          set(state => withView(state, patchStream(state, aiMsgId, msg => ({
            ...msg,
            interactive: {
              type: parsedData.type,
              component: parsedData.component,
              title: parsedData.title || '',
              options: parsedData.options,
              fields: parsedData.fields,
              formFields: parsedData.formFields,
              submitLabel: parsedData.submitLabel,
              // 完整透传 confirm/form/分页字段：confirmValue 携带上下文
              // （后端依赖其路由后续消息），pageMeta 驱动 ChoiceCard 翻页，
              // multiSelect 驱动多选不锁死（加工项选择，issue #2894）
              confirmLabel: parsedData.confirmLabel,
              confirmValue: parsedData.confirmValue,
              cancelLabel: parsedData.cancelLabel,
              cancelValue: parsedData.cancelValue,
              pageMeta: parsedData.pageMeta,
              multiSelect: parsedData.multiSelect,
            },
          }))))
        }
        break

      default:
        // 未知事件类型，尝试作为文本处理
        if (parsedData.content || parsedData.delta) {
          set(state => withView(state, patchStream(state, aiMsgId, msg => ({
            ...msg,
            content: msg.content + (parsedData.content || parsedData.delta || ''),
          }))))
        }
        break;
    }
  } catch (e) {
    // 解析失败，如果是字符串直接追加
    if (typeof data === 'string' && data.trim()) {
      set(state => withView(state, patchStream(state, aiMsgId, msg => ({
        ...msg,
        content: msg.content + data,
      }))))
    }
  }
}

export default useChatStore