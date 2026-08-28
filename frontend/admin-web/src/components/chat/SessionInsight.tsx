'use client'

/**
 * 会话洞察 — 米宝（B端工作助手）会话的右侧工作台账抽屉
 *
 * 信息架构（依据米宝定位：面向商家的智能工作助手，
 * 「查询 → 校验 → confirm 确认 → 写操作 → 追问建议」的工具链工作范式）：
 *   1. 概览     — 米宝身份 + 会话状态 + 已触达业务域
 *   2. 待确认   — 米宝在等待用户确认的交互卡（写操作安全闸）
 *   3. 处理进度 — 工具调用时间线：做了什么、写到哪、哪里失败
 *   4. 业务对象 — 会话涉及的订单/商品/物流/售后/客户，点击可追问
 *   5. 会话信息 — 消息数/历时 + 会话标识（调试用，弱化展示）
 */
import { useState, useMemo, useCallback, type ComponentType, type ReactNode } from 'react'
import {
  X,
  Bot,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Loader2,
  ShoppingBag,
  Package,
  Truck,
  RotateCcw,
  Users,
  Layers,
  Boxes,
  BarChart3,
  UserCog,
  Settings,
  Zap,
  Hash,
  Copy,
  Check,
  MessageSquare,
  Clock,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import {
  extractToolEvents,
  detectPendingInteraction,
  extractEntities,
  groupEntities,
  DOMAIN_LABELS,
  type InsightDomain,
  type EntityType,
  type NormalizedToolCall,
} from '@/lib/session-insight'

type IconComponent = ComponentType<{ className?: string }>

// ─── 领域展示元信息 ─────────────────────────────────

const DOMAIN_ICONS: Record<InsightDomain, IconComponent> = {
  order: ShoppingBag,
  product: Package,
  logistics: Truck,
  aftersale: RotateCcw,
  customer: Users,
  inventory: Boxes,
  staff: UserCog,
  settings: Settings,
  data: BarChart3,
  workflow: Zap,
}

const DOMAIN_ICON_CLASSES: Record<InsightDomain, string> = {
  order: 'text-blue-500',
  product: 'text-amber-500',
  logistics: 'text-green-500',
  aftersale: 'text-red-500',
  customer: 'text-indigo-500',
  inventory: 'text-teal-500',
  staff: 'text-slate-500',
  settings: 'text-gray-400',
  data: 'text-violet-500',
  workflow: 'text-purple-500',
}

const DOMAIN_CHIP_CLASSES: Record<InsightDomain, string> = {
  order: 'bg-blue-50 text-blue-600 border-blue-200',
  product: 'bg-amber-50 text-amber-600 border-amber-200',
  logistics: 'bg-green-50 text-green-600 border-green-200',
  aftersale: 'bg-red-50 text-red-600 border-red-200',
  customer: 'bg-indigo-50 text-indigo-600 border-indigo-200',
  inventory: 'bg-teal-50 text-teal-600 border-teal-200',
  staff: 'bg-slate-100 text-slate-600 border-slate-200',
  settings: 'bg-gray-100 text-gray-600 border-gray-200',
  data: 'bg-violet-50 text-violet-600 border-violet-200',
  workflow: 'bg-purple-50 text-purple-600 border-purple-200',
}

// ─── 业务对象展示元信息 ─────────────────────────────

const ENTITY_ICONS: Record<EntityType, IconComponent> = {
  order: ShoppingBag,
  product: Package,
  logistics: Truck,
  aftersale: RotateCcw,
  customer: Users,
  processing: Layers,
}

const ENTITY_ICON_CLASSES: Record<EntityType, string> = {
  order: 'text-blue-500',
  product: 'text-amber-500',
  logistics: 'text-green-500',
  aftersale: 'text-red-500',
  customer: 'text-indigo-500',
  processing: 'text-purple-500',
}

const ENTITY_CHIP_CLASSES: Record<EntityType, string> = {
  order: 'bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100',
  product: 'bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-100',
  logistics: 'bg-green-50 text-green-700 border-green-200 hover:bg-green-100',
  aftersale: 'bg-red-50 text-red-700 border-red-200 hover:bg-red-100',
  customer: 'bg-indigo-50 text-indigo-700 border-indigo-200 hover:bg-indigo-100',
  processing: 'bg-purple-50 text-purple-700 border-purple-200 hover:bg-purple-100',
}

// ─── 失败工具的修复建议 ─────────────────────────────

function errorSuggestion(tool: NormalizedToolCall): string | null {
  const result = tool.result
  if (!result || typeof result !== 'object') return null
  const rec = result as Record<string, unknown>
  const value = rec.suggestion ?? rec.message ?? rec.error
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

// ═══════════════════════════════════════════════════

interface SessionInsightProps {
  /** 抽屉是否展开（默认收起） */
  isOpen?: boolean
  /** 关闭抽屉回调 */
  onClose?: () => void
}

export default function SessionInsight({ isOpen = false, onClose }: SessionInsightProps = {}) {
  const [sessionIdCopied, setSessionIdCopied] = useState(false)
  const { currentSessionId, sessions, messages, sendMessage } = useChatStore()

  const copySessionId = () => {
    if (!currentSessionId) return
    navigator.clipboard.writeText(currentSessionId).catch(() => {})
    setSessionIdCopied(true)
    setTimeout(() => setSessionIdCopied(false), 2000)
  }

  const currentSession = useMemo(
    () => sessions.find(s => s.session_id === currentSessionId),
    [sessions, currentSessionId],
  )

  // 工作台账：工具时间线（最新在前）
  const toolEvents = useMemo(() => extractToolEvents(messages), [messages])

  // 概览领域计数（保持工具调用顺序）
  const domainCounts = useMemo(() => {
    const counts = new Map<InsightDomain, number>()
    for (const event of toolEvents) {
      counts.set(event.meta.domain, (counts.get(event.meta.domain) || 0) + 1)
    }
    return Array.from(counts.entries())
  }, [toolEvents])

  // 待确认交互（写操作安全闸）
  const pendingInteraction = useMemo(() => detectPendingInteraction(messages), [messages])

  // 业务对象（跨来源去重）
  const entityGroups = useMemo(() => groupEntities(extractEntities(messages)), [messages])

  const handleEntityClick = useCallback(
    (followUp: string) => { sendMessage(followUp) },
    [sendMessage],
  )

  const messageCount = currentSession?.message_count ?? messages.length
  const sessionStatus = currentSession?.status || 'active'

  const duration = useMemo(() => {
    if (!currentSession?.created_at) return null
    const start = new Date(currentSession.created_at).getTime()
    const end = currentSession.updated_at ? new Date(currentSession.updated_at).getTime() : Date.now()
    const mins = Math.round((end - start) / 60000)
    if (mins < 1) return '刚刚'
    if (mins < 60) return `${mins} 分钟`
    const hours = Math.floor(mins / 60)
    const remainMins = mins % 60
    return remainMins > 0 ? `${hours} 小时 ${remainMins} 分钟` : `${hours} 小时`
  }, [currentSession?.created_at, currentSession?.updated_at])

  if (!currentSessionId) return null

  return (
    <>
      {/* 遮罩 — 仅展开时显示，点击关闭 */}
      {isOpen && (
        <div
          data-testid="session-insight-overlay"
          className="absolute inset-0 bg-black/20"
          onClick={onClose}
        />
      )}

      {/* 抽屉容器 — 从右侧滑入 */}
      <div
        data-testid="session-insight-drawer"
        className={cn(
          'absolute top-0 right-0 h-full w-[340px] bg-white shadow-2xl border-l border-gray-200 flex flex-col overflow-hidden',
          'transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]',
          isOpen ? 'translate-x-0 visible' : 'translate-x-full invisible'
        )}
        aria-hidden={!isOpen}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
          <h3 className="text-sm font-semibold text-gray-800">会话洞察</h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 transition-colors" title="关闭洞察">
            <X className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {/* ─── 概览：米宝身份 + 已触达业务域 ─── */}
          <div className="px-4 py-3 border-b border-gray-100">
            <div className="flex items-center gap-2.5">
              <span className="w-8 h-8 rounded-lg bg-primary-50 text-primary-600 flex items-center justify-center flex-shrink-0">
                <Bot className="w-[18px] h-[18px]" />
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-800 leading-tight">米宝 · B端工作助手</p>
                <p className="text-[10px] text-gray-400 mt-0.5">商品 · 订单 · 售后 · 客户 · 数据</p>
              </div>
              <span className={cn(
                'ml-auto inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium flex-shrink-0',
                sessionStatus === 'active'
                  ? 'bg-green-50 text-green-700 border border-green-200'
                  : 'bg-gray-50 text-gray-500 border border-gray-200',
              )}>
                {sessionStatus === 'active' ? '进行中' : '已结束'}
              </span>
            </div>

            {domainCounts.length > 0 && (
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {domainCounts.map(([domain, count]) => (
                  <span
                    key={domain}
                    className={cn(
                      'inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium border',
                      DOMAIN_CHIP_CLASSES[domain],
                    )}
                  >
                    {DOMAIN_LABELS[domain]} ×{count}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* ─── 待确认：写操作安全闸 ─── */}
          {pendingInteraction && (
            <div
              data-testid="insight-pending-confirm"
              className="mx-3 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 flex items-start gap-2"
            >
              <AlertTriangle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
              <div className="min-w-0">
                <p className="text-xs font-semibold text-amber-800">米宝在等你确认</p>
                {pendingInteraction.title && (
                  <p className="text-[11px] text-amber-700 mt-0.5 truncate">{pendingInteraction.title}</p>
                )}
                <p className="text-[10px] text-amber-600 mt-0.5">请回到对话中完成确认，米宝才会继续</p>
              </div>
            </div>
          )}

          {/* ─── 处理进度：工具调用时间线 ─── */}
          <div className="px-3 py-3 border-b border-gray-100">
            <h4 className="px-1 text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">处理进度</h4>

            {toolEvents.length === 0 ? (
              <div className="text-xs text-gray-400 text-center py-6 bg-gray-50 rounded-lg leading-relaxed">
                暂无处理记录
                <br />
                <span className="text-[11px]">向米宝提问后，这里会记录每一步操作</span>
              </div>
            ) : (
              <div className="space-y-1.5">
                {toolEvents.map((event, idx) => {
                  const DomainIcon = DOMAIN_ICONS[event.meta.domain]
                  const isError = event.tool.status === 'error'
                  const isRunning = event.tool.status === 'running'
                  const suggestion = isError ? errorSuggestion(event.tool) : null

                  return (
                    <div
                      key={`${event.messageId}-${event.tool.name}-${idx}`}
                      className={cn(
                        'flex items-start gap-2 rounded-lg border px-2.5 py-2',
                        isError ? 'border-red-100 bg-red-50/40' : 'border-gray-200 bg-white',
                      )}
                    >
                      <DomainIcon className={cn('w-3.5 h-3.5 mt-0.5 flex-shrink-0', DOMAIN_ICON_CLASSES[event.meta.domain])} />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className={cn('text-xs font-medium truncate', isError ? 'text-red-700' : 'text-gray-700')}>
                            {event.meta.label}
                          </span>
                          {event.meta.write && (
                            <span className="inline-flex items-center px-1 py-px rounded bg-orange-50 text-orange-600 border border-orange-200 text-[9px] font-medium flex-shrink-0">
                              写
                            </span>
                          )}
                        </div>
                        {suggestion && (
                          <p className="text-[11px] text-red-500 mt-0.5 leading-relaxed break-all">
                            ↳ <span>{suggestion}</span>
                          </p>
                        )}
                      </div>
                      {isRunning ? (
                        <Loader2 className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5 animate-spin" />
                      ) : isError ? (
                        <XCircle className="w-3.5 h-3.5 text-red-500 flex-shrink-0 mt-0.5" />
                      ) : (
                        <CheckCircle2 className="w-3.5 h-3.5 text-green-500 flex-shrink-0 mt-0.5" />
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* ─── 业务对象：实体收集 + 点击追问 ─── */}
          <div className="px-3 py-3">
            <h4 className="px-1 text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">业务对象</h4>

            {entityGroups.length === 0 ? (
              <div className="text-xs text-gray-400 text-center py-6 bg-gray-50 rounded-lg leading-relaxed">
                暂无业务对象
                <br />
                <span className="text-[11px]">查询订单、商品或物流后</span>
                <br />
                <span className="text-[11px]">会自动收集到这里，点击标签可快速追问</span>
              </div>
            ) : (
              <div>
                {entityGroups.map(group => {
                  const GroupIcon = ENTITY_ICONS[group.type]
                  return (
                    <div key={group.type} className="mb-3 last:mb-0">
                      <div className="flex items-center gap-1.5 mb-1.5">
                        <GroupIcon className={cn('w-3.5 h-3.5', ENTITY_ICON_CLASSES[group.type])} />
                        <span className="text-[11px] font-semibold text-gray-600">{group.label}</span>
                        <span className="text-[10px] text-gray-400">×{group.entities.length}</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {group.entities.map(entity => (
                          <button
                            key={`${entity.type}-${entity.value}`}
                            onClick={() => handleEntityClick(entity.followUp)}
                            className={cn(
                              'inline-flex items-center gap-1 px-2 py-1 rounded-full text-[11px] font-medium transition-colors cursor-pointer border',
                              ENTITY_CHIP_CLASSES[entity.type],
                            )}
                            title={`点击追问：${entity.followUp}`}
                          >
                            <Hash className="w-3 h-3" />
                            {entity.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        {/* ─── 会话信息（弱化展示，调试用） ─── */}
        <div className="px-4 py-3 border-t border-gray-100 bg-gray-50">
          <div className="grid grid-cols-2 gap-2">
            <StatBadge icon={<MessageSquare className="w-3.5 h-3.5" />} label="消息" value={String(messageCount)} />
            {duration && <StatBadge icon={<Clock className="w-3.5 h-3.5" />} label="历时" value={duration} />}
          </div>
          {currentSessionId && (
            <div className="mt-2 flex items-start gap-1">
              <p className="text-[10px] text-gray-400 font-mono break-all leading-relaxed flex-1">
                会话标识: {currentSessionId}
              </p>
              <button
                onClick={copySessionId}
                className="flex-shrink-0 p-0.5 rounded hover:bg-gray-100 transition-colors text-gray-400 hover:text-gray-600"
                title="复制会话标识"
              >
                {sessionIdCopied ? (
                  <Check className="w-3 h-3 text-green-500" />
                ) : (
                  <Copy className="w-3 h-3" />
                )}
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  )
}

function StatBadge({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-2 flex items-center gap-2">
      <span className="text-primary-500">{icon}</span>
      <div>
        <p className="text-sm font-semibold text-gray-800 leading-tight">{value}</p>
        <p className="text-[10px] text-gray-500">{label}</p>
      </div>
    </div>
  )
}
