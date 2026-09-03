'use client'

/**
 * 人工客服工作台
 *
 * 处理 C 端用户转人工后的会话：
 *   - 左侧：转人工会话列表（waiting/active）
 *   - 右侧：会话详情对话区（消息列表 + 客服回复）
 *   - 轮询刷新（POC 简单版，WebSocket 后置）
 *
 * 数据源：agentSessionApi（/api/admin/agent-sessions，人工客服会话）
 * 区别于「会话管理」页（AI 会话 /chat），本页是真正的人工客服接待。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Bot, MessageSquare, Send } from 'lucide-react'
import { agentSessionApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { AgentMessageItem, AgentSession, AgentSessionDetail } from '@/lib/api'

const STATUS_LABEL: Record<string, string> = {
  waiting: '待接待',
  active: '接待中',
  ended: '已结束',
  transferred: '已转接',
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export default function HumanAgentSessionsPage() {
  const [sessions, setSessions] = useState<AgentSession[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<AgentSessionDetail | null>(null)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  /** 加载会话列表 */
  const loadSessions = useCallback(async () => {
    try {
      const res = await agentSessionApi.getSessions({ page: 1, size: 50 })
      if (res.data?.success) {
        setSessions(res.data.data?.items ?? [])
      }
    } catch (e) {
      console.error('加载会话列表失败:', e)
    }
  }, [])

  /** 加载选中会话详情（含消息） */
  const loadDetail = useCallback(async (id: string) => {
    try {
      const res = await agentSessionApi.getSession(id)
      if (res.data?.success && res.data.data) {
        setDetail(res.data.data)
      }
    } catch (e) {
      console.error('加载会话详情失败:', e)
    }
  }, [])

  /** 选中会话 */
  const handleSelect = useCallback(
    (id: string) => {
      setSelectedId(id)
      loadDetail(id)
    },
    [loadDetail],
  )

  /** 发送客服消息 */
  const handleSend = useCallback(async () => {
    const content = input.trim()
    if (!content || !selectedId || loading) return
    setLoading(true)
    try {
      const res = await agentSessionApi.sendMessage(selectedId, content)
      if (res.data?.success) {
        setInput('')
        await loadDetail(selectedId)
        await loadSessions()
      }
    } catch (e) {
      console.error('发送消息失败:', e)
    } finally {
      setLoading(false)
    }
  }, [input, selectedId, loading, loadDetail, loadSessions])

  // 初始加载 + 轮询刷新（POC 简单版）
  useEffect(() => {
    loadSessions()
    const timer = setInterval(() => {
      loadSessions()
      if (selectedId) loadDetail(selectedId)
    }, 5000)
    return () => clearInterval(timer)
  }, [loadSessions, loadDetail, selectedId])

  // 新消息自动滚动到底部
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [detail?.messages?.length])

  return (
    <div className="h-[calc(100vh-180px)] flex flex-col">
      {/* 顶部 */}
      <div className="flex items-center justify-between flex-shrink-0 px-5 h-14 border-b border-neutral-200/80">
        <h1 className="text-base font-semibold text-neutral-900">人工客服工作台</h1>
        <div className="flex items-center gap-4 text-xs text-neutral-500">
          <span>待接待 {sessions.filter(s => s.status === 'waiting').length}</span>
          <span>接待中 {sessions.filter(s => s.status === 'active').length}</span>
        </div>
      </div>

      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* 左侧：会话列表 */}
        <div className="w-72 flex-shrink-0 border-r border-neutral-200/80 overflow-y-auto">
          {sessions.length === 0 && (
            <div className="p-6 text-center text-sm text-neutral-400">
              暂无转人工会话
              <br />
              <span className="text-xs">（C 端用户触发转人工后在此显示）</span>
            </div>
          )}
          {sessions.map(s => (
            <button
              key={s.id}
              onClick={() => handleSelect(s.id)}
              className={cn(
                'w-full text-left px-4 py-3 border-b border-neutral-100 hover:bg-neutral-50 transition-colors',
                selectedId === s.id && 'bg-primary-50 hover:bg-primary-50',
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-neutral-800">
                  {s.customerName || '顾客'}
                </span>
                <span
                  className={cn(
                    'text-xs px-1.5 py-0.5 rounded',
                    s.status === 'waiting' && 'bg-amber-50 text-amber-600',
                    s.status === 'active' && 'bg-emerald-50 text-emerald-600',
                    s.status === 'ended' && 'bg-neutral-100 text-neutral-400',
                  )}
                >
                  {STATUS_LABEL[s.status] ?? s.status}
                </span>
              </div>
              <div className="mt-1 text-xs text-neutral-500 truncate">
                {s.reason || '客户请求转人工'}
              </div>
              <div className="mt-0.5 text-[11px] text-neutral-400">
                {formatTime(s.createdAt)} {s.messageCount ? `· ${s.messageCount}条` : ''}
              </div>
            </button>
          ))}
        </div>

        {/* 右侧：对话区 */}
        <div className="flex-1 flex flex-col min-w-0">
          {!detail ? (
            <div className="flex-1 flex items-center justify-center text-sm text-neutral-400">
              <MessageSquare className="w-5 h-5 mr-2" />
              选择左侧会话开始接待
            </div>
          ) : (
            <>
              {/* 会话头部 */}
              <div className="flex items-center justify-between flex-shrink-0 px-5 h-12 border-b border-neutral-200/80">
                <div className="text-sm font-medium text-neutral-800">
                  {detail.customerName || '顾客'}
                  {detail.customerPhone && (
                    <span className="ml-2 text-xs text-neutral-400">{detail.customerPhone}</span>
                  )}
                </div>
                <div className="text-xs text-neutral-400">{STATUS_LABEL[detail.status] ?? detail.status}</div>
              </div>

              {/* 消息区 */}
              <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-3 bg-neutral-50/50">
                {/* GB-01（GB/T 47746-2026）：转人工前 AI 对话上下文——人工客服无需顾客重复复述 */}
                {(detail.aiContextSummary || (detail.aiContext && detail.aiContext.length > 0)) && (
                  <div className="rounded-xl border border-blue-200/70 bg-blue-50/60 p-3 space-y-2">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-blue-700">
                      <Bot className="w-3.5 h-3.5" />
                      <span>顾客与 AI 客服（小布）的对话 · 转人工前</span>
                    </div>
                    {detail.aiContextSummary && (
                      <div className="text-xs text-neutral-600 bg-white/80 border border-blue-100 rounded-lg px-2.5 py-1.5">
                        📋 对话摘要：{detail.aiContextSummary}
                      </div>
                    )}
                    {detail.aiContext?.map((turn, idx) => (
                      <div key={`ai-ctx-${idx}`} className="flex justify-start">
                        <div
                          className={cn(
                            'max-w-[85%] px-2.5 py-1.5 rounded-lg text-xs shadow-sm',
                            turn.role === 'assistant'
                              ? 'bg-indigo-50 border border-indigo-100 text-neutral-700'
                              : 'bg-white border border-neutral-200 text-neutral-700',
                          )}
                        >
                          <div
                            className={cn(
                              'mb-0.5 text-[10px] font-medium',
                              turn.role === 'assistant' ? 'text-indigo-500' : 'text-neutral-400',
                            )}
                          >
                            {turn.role === 'assistant' ? '小布 · AI' : '顾客'}
                          </div>
                          <div className="whitespace-pre-wrap break-words">{turn.content}</div>
                        </div>
                      </div>
                    ))}
                    <div className="text-center text-[10px] text-neutral-400 pt-0.5">
                      ———— 以下为人工接待记录 ————
                    </div>
                  </div>
                )}
                {detail.messages?.map(m => (
                  <div
                    key={m.id}
                    className={cn(
                      'flex',
                      m.senderType === 'agent' ? 'justify-end' : 'justify-start',
                    )}
                  >
                    <div
                      className={cn(
                        'max-w-[70%] px-3 py-2 rounded-lg text-sm shadow-sm',
                        m.senderType === 'agent' && 'bg-primary-500 text-white',
                        m.senderType === 'customer' && 'bg-white text-neutral-800 border border-neutral-200',
                        m.senderType === 'system' && 'bg-neutral-100 text-neutral-400 text-xs mx-auto',
                      )}
                    >
                      {m.senderType === 'system' && <div className="text-center">{m.content}</div>}
                      {m.senderType !== 'system' && (
                        <>
                          <div className="whitespace-pre-wrap break-words">{m.content}</div>
                          <div
                            className={cn(
                              'mt-1 text-[10px]',
                              m.senderType === 'agent' ? 'text-white/70' : 'text-neutral-400',
                            )}
                          >
                            {m.senderType === 'agent' ? '客服' : '顾客'} · {formatTime(m.createdAt)}
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              {/* 输入区 */}
              <div className="flex-shrink-0 px-4 py-3 border-t border-neutral-200/80 bg-white">
                <div className="flex items-center gap-2">
                  <textarea
                    className="flex-1 h-10 px-3 py-2 text-sm border border-neutral-200 rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-primary-200"
                    placeholder="输入回复内容，Enter 发送，Shift+Enter 换行"
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault()
                        handleSend()
                      }
                    }}
                  />
                  <button
                    onClick={handleSend}
                    disabled={!input.trim() || loading}
                    className="h-10 px-4 rounded-lg bg-primary-500 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                  >
                    <Send className="w-4 h-4" />
                    发送
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
