'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { X, Minus, Send, Loader2, Plus } from 'lucide-react'
import { MibaoLogo } from '@/components/icons/MibaoLogo'
import { cn } from '@/lib/utils'
import { chatApi } from '@/lib/api'
import { useAuthStore } from '@/store/auth'

// ========== 类型定义 ==========
interface AssistantMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: string
  isStreaming?: boolean
  suggestions?: string[]
}

// ========== 常量 ==========
const STORAGE_KEY_SESSION = 'ai_assistant_session_id'
const STORAGE_KEY_TIMESTAMP = 'ai_assistant_last_active'
const SESSION_TIMEOUT_MS = 30 * 60 * 1000 // 30 分钟

// ========== 工具函数 ==========
const generateId = () =>
  Math.random().toString(36).substring(2, 15) + Date.now().toString(36)

/** 从 localStorage 读取持久化的 sessionId（含超时检测） */
const loadPersistedSession = (): string | null => {
  try {
    const sid = localStorage.getItem(STORAGE_KEY_SESSION)
    if (!sid) return null
    const lastActive = localStorage.getItem(STORAGE_KEY_TIMESTAMP)
    if (lastActive) {
      const elapsed = Date.now() - Number(lastActive)
      if (elapsed > SESSION_TIMEOUT_MS) {
        // 会话超时，清除
        localStorage.removeItem(STORAGE_KEY_SESSION)
        localStorage.removeItem(STORAGE_KEY_TIMESTAMP)
        return null
      }
    }
    return sid
  } catch {
    return null
  }
}

/** 持久化 sessionId 到 localStorage */
const persistSession = (sid: string | null) => {
  try {
    if (sid) {
      localStorage.setItem(STORAGE_KEY_SESSION, sid)
      localStorage.setItem(STORAGE_KEY_TIMESTAMP, String(Date.now()))
    } else {
      localStorage.removeItem(STORAGE_KEY_SESSION)
      localStorage.removeItem(STORAGE_KEY_TIMESTAMP)
    }
  } catch {
    // 忽略 localStorage 不可用的情况
  }
}

/** 更新最后活跃时间 */
const touchSession = () => {
  try {
    localStorage.setItem(STORAGE_KEY_TIMESTAMP, String(Date.now()))
  } catch {
    // ignore
  }
}

// ========== 主组件 ==========
export default function FloatingAssistant() {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState<AssistantMessage[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(() => loadPersistedSession())
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const historyLoadedRef = useRef<string | null>(null)
  const historyLoadingSessionRef = useRef<string | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  // 自动滚动到底部
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  // 面板打开时：恢复会话历史 + 聚焦输入框
  useEffect(() => {
    if (isOpen) {
      setTimeout(() => inputRef.current?.focus(), 300)

      // 如果有持久化的 sessionId 且尚未加载过该会话的历史
      if (sessionId && historyLoadedRef.current !== sessionId) {
        loadHistory(sessionId)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen])

  // 加载会话历史消息
  const loadHistory = async (sid: string) => {
    historyLoadingSessionRef.current = sid
    setIsLoadingHistory(true)
    try {
      const token = getToken()
      const data = await chatApi.getHistory(sid, token)
      const rawMessages = data?.data?.messages || data?.messages || []
      const history: AssistantMessage[] = rawMessages.map((msg: any) => ({
        id: msg.id || generateId(),
        role: msg.role as 'user' | 'assistant',
        content: msg.content || '',
        createdAt: msg.created_at || new Date().toISOString(),
      }))
      if (historyLoadingSessionRef.current === sid) {
        setMessages(history)
        historyLoadedRef.current = sid
      }
    } catch (err) {
      console.error('加载会话历史失败:', err)
      // 如果加载失败（如会话已被删除），清除持久化并重置
      if (historyLoadingSessionRef.current === sid) {
        setSessionId(null)
        persistSession(null)
        historyLoadedRef.current = null
      }
    } finally {
      if (historyLoadingSessionRef.current === sid) {
        setIsLoadingHistory(false)
      }
    }
  }

  // 获取 token
  const getToken = () => useAuthStore.getState().accessToken || ''

  // 确保有 session（lazy creation）
  const ensureSession = async (): Promise<string> => {
    if (sessionId) {
      touchSession()
      return sessionId
    }
    const token = getToken()
    const data = await chatApi.createSession(token)
    const newId = data?.data?.id || data?.data?.session_id || data?.id || data?.session_id
    setSessionId(newId)
    persistSession(newId)
    historyLoadedRef.current = newId
    return newId
  }

  // 新建对话
  const handleNewChat = () => {
    if (isStreaming) return
    setSessionId(null)
    setMessages([])
    persistSession(null)
    historyLoadedRef.current = null
    historyLoadingSessionRef.current = null
    setTimeout(() => inputRef.current?.focus(), 100)
  }

  // 解析 SSE 流
  const processSSEStream = async (
    response: Response,
    aiMsgId: string
  ) => {
    if (!response.body) return

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let currentEventType = ''
    let hasReceivedText = false
    let inactivityTimer: ReturnType<typeof setTimeout> | null = null

    const resetInactivityTimer = () => {
      if (inactivityTimer) clearTimeout(inactivityTimer)
      // 收到文本后，如果 15 秒无新数据则自动结束流
      if (hasReceivedText) {
        inactivityTimer = setTimeout(() => {
          try { reader.cancel() } catch {}
        }, 15000)
      }
    }

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        resetInactivityTimer()
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed) {
            currentEventType = ''
            continue
          }

          if (trimmed.startsWith('event:')) {
            currentEventType = trimmed.slice(6).trim()
            continue
          }

          if (trimmed.startsWith('data:')) {
            const dataStr = trimmed.slice(5).trim()
            if (!dataStr) continue

            try {
              const data = JSON.parse(dataStr)

              if (currentEventType === 'loading') {
                // loading 事件：仅作为状态指示，不追加到消息内容
                // 前端通过 isStreaming + 空 content 显示加载动画
                continue
              } else if (currentEventType === 'text' || currentEventType === 'delta') {
                hasReceivedText = true
                const delta = data.content || data.delta || ''
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === aiMsgId
                      ? { ...msg, content: msg.content + delta }
                      : msg
                  )
                )
              } else if (currentEventType === 'suggestions') {
                const questions = data.questions || []
                if (questions.length > 0) {
                  setMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === aiMsgId
                        ? { ...msg, suggestions: questions }
                        : msg
                    )
                  )
                }
              } else if (currentEventType === 'done') {
                // 流结束
              } else if (currentEventType === 'error') {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === aiMsgId
                      ? {
                          ...msg,
                          content: `错误: ${data.message || '未知错误'}`,
                          isStreaming: false,
                        }
                      : msg
                  )
                )
              } else if (currentEventType === 'message') {
                if (data.type === 'text' || data.content) {
                  const delta = data.content || data.delta || ''
                  setMessages((prev) =>
                    prev.map((msg) =>
                      msg.id === aiMsgId
                        ? { ...msg, content: msg.content + delta }
                        : msg
                    )
                  )
                }
              } else if (data.content || data.delta) {
                // 兜底：未知事件类型但有内容
                const delta = data.content || data.delta || ''
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === aiMsgId
                      ? { ...msg, content: msg.content + delta }
                      : msg
                  )
                )
              }
            } catch {
              // 非 JSON，直接追加
              if (dataStr.trim()) {
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === aiMsgId
                      ? { ...msg, content: msg.content + dataStr }
                      : msg
                  )
                )
              }
            }
          }
        }
      }
    } finally {
      if (inactivityTimer) clearTimeout(inactivityTimer)
      reader.releaseLock()
    }
  }

  // 发送消息
  const handleSend = async (directText?: string) => {
    const text = (directText ?? input).trim()
    if (!text || isStreaming) return

    setInput('')

    const userMsg: AssistantMessage = {
      id: generateId(),
      role: 'user',
      content: text,
      createdAt: new Date().toISOString(),
    }

    const aiMsgId = generateId()
    const aiMsg: AssistantMessage = {
      id: aiMsgId,
      role: 'assistant',
      content: '',
      createdAt: new Date().toISOString(),
      isStreaming: true,
    }

    setMessages((prev) => [...prev, userMsg, aiMsg])
    setIsStreaming(true)

    const abortController = new AbortController()
    abortRef.current = abortController

    try {
      const sid = await ensureSession()
      touchSession()
      const token = getToken()
      const AI_SERVICE_URL = chatApi.AI_SERVICE_URL

      const response = await fetch(`${AI_SERVICE_URL}/api/chat/send`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          session_id: sid,
          message: text,
        }),
        signal: abortController.signal,
      })

      if (!response.ok) {
        throw new Error(`请求失败: ${response.status}`)
      }

      await processSSEStream(response, aiMsgId)
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      const errorMsg = err instanceof Error ? err.message : '发送失败'
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === aiMsgId
            ? { ...msg, content: `错误: ${errorMsg}`, isStreaming: false }
            : msg
        )
      )
    } finally {
      setIsStreaming(false)
      abortRef.current = null
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === aiMsgId ? { ...msg, isStreaming: false } : msg
        )
      )
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const togglePanel = () => setIsOpen((prev) => !prev)

  return (
    <>
      {/* 聊天面板 */}
      <div
        className={cn(
          'fixed bottom-24 right-6 z-50 w-[400px] h-[560px] flex flex-col',
          'bg-white rounded-2xl shadow-2xl border border-gray-200',
          'transition-all duration-300 ease-in-out origin-bottom-right',
          isOpen
            ? 'opacity-100 scale-100 translate-y-0 pointer-events-auto'
            : 'opacity-0 scale-95 translate-y-4 pointer-events-none'
        )}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between h-12 px-4 border-b border-gray-100 bg-gradient-to-r from-primary-600 to-primary-500 rounded-t-2xl">
          <div className="flex items-center gap-2">
            <MibaoLogo size={22} className="flex-shrink-0" />
            <span className="text-sm font-semibold text-white">米宝 · 智能工作助手</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={handleNewChat}
              disabled={isStreaming}
              className="p-1 rounded-md hover:bg-white/20 transition-colors disabled:opacity-50"
              title="新对话"
            >
              <Plus className="w-4 h-4 text-white" />
            </button>
            <button
              onClick={togglePanel}
              className="p-1 rounded-md hover:bg-white/20 transition-colors"
              title="最小化"
            >
              <Minus className="w-4 h-4 text-white" />
            </button>
          </div>
        </div>

        {/* 消息区域 */}
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
          {isLoadingHistory ? (
            <div className="flex items-center justify-center h-full">
              <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
            </div>
          ) : messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-400 gap-2">
              <MibaoLogo size={48} className="opacity-60" />
              <p className="text-sm">你好，我是米宝！有什么可以帮助你的？</p>
            </div>
          ) : null}

          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn(
                'flex',
                msg.role === 'user' ? 'justify-end' : 'justify-start'
              )}
            >
              <div className="flex flex-col items-start max-w-[80%]">
                <div
                  className={cn(
                    'px-3 py-2 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap break-words',
                    msg.role === 'user'
                      ? 'bg-primary-600 text-white rounded-br-md'
                      : 'bg-gray-100 text-gray-800 rounded-bl-md'
                  )}
                >
                  {msg.content || (msg.isStreaming && (
                    <span className="inline-flex items-center gap-1 text-gray-400">
                      <Loader2 className="w-3 h-3 animate-spin" />
                      正在输入...
                    </span>
                  ))}
                </div>
                {msg.role === 'assistant' && msg.suggestions && msg.suggestions.length > 0 && (
                  <div className="mt-2 w-full">
                    <span className="text-xs text-gray-400">推荐提问：</span>
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {msg.suggestions.map((q, idx) => (
                        <button
                          key={idx}
                          onClick={() => handleSend(q)}
                          disabled={isStreaming}
                          className="text-xs px-2.5 py-1 rounded-full bg-gradient-to-r from-primary-50 to-primary-100 border border-primary-200 text-primary-700 hover:from-primary-100 hover:to-primary-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          {q}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* 输入区域 */}
        <div className="px-4 py-3 border-t border-gray-100">
          <div className="flex items-center gap-2">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入消息..."
              disabled={isStreaming}
              className="flex-1 px-3 py-2 text-sm bg-gray-50 border border-gray-200 rounded-xl focus:outline-none focus:border-primary-400 focus:ring-1 focus:ring-primary-400/20 disabled:opacity-50 placeholder:text-gray-400 transition-colors"
            />
            <button
              onClick={() => handleSend()}
              disabled={!input.trim() || isStreaming}
              className={cn(
                'p-2 rounded-xl transition-colors flex-shrink-0',
                input.trim() && !isStreaming
                  ? 'bg-primary-600 text-white hover:bg-primary-700'
                  : 'bg-gray-200 text-gray-400 cursor-not-allowed'
              )}
            >
              <Send className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* FAB 悬浮按钮 */}
      <button
        onClick={togglePanel}
        className={cn(
          'fixed bottom-6 right-6 z-50 w-14 h-14 rounded-full',
          'flex items-center justify-center',
          'bg-primary-600 text-white shadow-lg',
          'hover:bg-primary-700 hover:shadow-xl hover:scale-110',
          'active:scale-95',
          'transition-all duration-200 ease-in-out'
        )}
        title={isOpen ? '关闭米宝' : '打开米宝'}
      >
        <div
          className={cn(
            'transition-transform duration-300',
            isOpen ? 'rotate-0' : 'rotate-0'
          )}
        >
          {isOpen ? <X className="w-6 h-6" /> : <MibaoLogo size={32} />}
        </div>
      </button>
    </>
  )
}
