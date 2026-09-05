'use client'

/**
 * 会话简报 — 米宝（B端工作助手）会话的右侧业务简报抽屉
 *
 * 信息架构（UI-019 / issue #2897，从「工具台账」改为「业务简报」——
 * 商家用户不关心 agent 调用了哪些工具，只关心业务结果）：
 *   1. 会话结论   — 业务语言摘要：查询聚合 / 写操作完成 / 失败 / 待确认
 *   2. 需要你处理 — 待确认安全闸 + 失败操作（业务化原因）
 *   3. 办理结果   — 业务对象明细行（状态/金额/客户，点击跳详情或追问）
 *   4. 接下来可以问 — 复用 agent 已生成的后续建议，点击即发送
 *   5. 会话信息   — 消息数/历时 + 会话标识（调试用，弱化展示）
 * 不再展示工具调用时间线/领域计数等机器语言。
 */
import { useState, useMemo, useCallback, type ComponentType, type ReactNode } from 'react'
import {
  X,
  Bot,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  ShoppingBag,
  Package,
  Truck,
  RotateCcw,
  Users,
  Layers,
  ChevronRight,
  MessageSquare,
  Clock,
  Copy,
  Check,
} from 'lucide-react'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import { useChatStore } from '@/store/chat'
import {
  buildSessionBrief,
  detectPendingInteraction,
  extractFailedActions,
  extractLedgerRows,
  collectSuggestions,
  type BriefKind,
  type EntityType,
  type LedgerRow,
} from '@/lib/session-insight'

// ─── 业务对象展示元信息 ─────────────────────────────

const ENTITY_ICONS: Record<EntityType, ComponentType<{ className?: string }>> = {
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

/** 订单状态 → 业务文案与配色（办理结果行） */
const ORDER_STATUS_META: Record<string, { label: string; className: string }> = {
  pending: { label: '待确认', className: 'bg-amber-50 text-amber-700 border-amber-200' },
  confirmed: { label: '已确认', className: 'bg-blue-50 text-blue-700 border-blue-200' },
  producing: { label: '生产中', className: 'bg-purple-50 text-purple-700 border-purple-200' },
  shipped: { label: '已发货', className: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
  completed: { label: '已完成', className: 'bg-green-50 text-green-700 border-green-200' },
  cancelled: { label: '已取消', className: 'bg-neutral-50 text-neutral-600 border-neutral-200' },
}

function statusBadge(type: EntityType, status?: string) {
  if (!status) return null
  if (type === 'order' && ORDER_STATUS_META[status]) {
    const meta = ORDER_STATUS_META[status]
    return (
      <span className={cn('inline-flex items-center px-1.5 py-px rounded text-[10px] font-medium border', meta.className)}>
        {meta.label}
      </span>
    )
  }
  // 非订单域状态直接展示业务原文（如物流「运输中」）
  return (
    <span className="inline-flex items-center px-1.5 py-px rounded text-[10px] font-medium border bg-neutral-50 text-neutral-600 border-neutral-200">
      {status}
    </span>
  )
}

function fmtAmount(n: number): string {
  return `¥${n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

// ─── 会话结论行图标（按 kind 着色） ─────────────────────

const BRIEF_ICONS: Record<BriefKind, { icon: ComponentType<{ className?: string }>; className: string }> = {
  done: { icon: CheckCircle2, className: 'text-green-500' },
  failed: { icon: XCircle, className: 'text-red-500' },
  pending: { icon: AlertTriangle, className: 'text-amber-500' },
}

// ═══════════════════════════════════════════════════════════

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

  // 会话结论（业务语言，确定性推导）
  const brief = useMemo(() => buildSessionBrief(messages), [messages])
  // 待确认交互（写操作安全闸）
  const pendingInteraction = useMemo(() => detectPendingInteraction(messages), [messages])
  // 失败操作（需要你处理）
  const failedActions = useMemo(() => extractFailedActions(messages), [messages])
  // 办理结果明细
  const ledgerRows = useMemo(() => extractLedgerRows(messages), [messages])
  // 接下来可以问
  const suggestions = useMemo(() => collectSuggestions(messages), [messages])

  const handleSend = useCallback(
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

  const hasBrief = brief.lines.length > 0 || brief.totals.orders > 0
  const hasActions = Boolean(pendingInteraction) || failedActions.length > 0
  const isEmpty = !hasBrief && !hasActions && ledgerRows.length === 0

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
          <h3 className="text-sm font-semibold text-gray-800">会话简报</h3>
          <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 transition-colors" title="关闭会话简报">
            <X className="w-4 h-4 text-gray-400" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {/* ─── 概览：米宝身份 + 会话状态 ─── */}
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
          </div>

          {isEmpty ? (
            /* ─── 空态：友好引导 ─── */
            <div className="px-4 py-10 text-center">
              <p className="text-xs text-gray-400 leading-relaxed">
                本会话还没有记录
                <br />
                <span className="text-[11px]">向米宝提问后，这里会汇总本次会话的成果与待办</span>
              </p>
            </div>
          ) : (
            <>
              {/* ─── 会话结论 ─── */}
              <div className="px-3 py-3 border-b border-gray-100" data-testid="brief-conclusion">
                <h4 className="px-1 text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">会话结论</h4>
                <div className="space-y-1.5">
                  {brief.lines.map((line, idx) => {
                    const meta = BRIEF_ICONS[line.kind]
                    const Icon = meta.icon
                    return (
                      <div key={`${line.kind}-${idx}`} className="flex items-start gap-2 rounded-lg border border-gray-200 bg-white px-2.5 py-2">
                        <Icon className={cn('w-3.5 h-3.5 mt-0.5 flex-shrink-0', meta.className)} />
                        <span className="text-xs text-gray-700 leading-relaxed break-all">{line.text}</span>
                      </div>
                    )
                  })}
                  {brief.totals.orders > 0 && (
                    <div className="flex items-center gap-2 rounded-lg bg-primary-50/60 border border-primary-100 px-2.5 py-2">
                      <span className="text-xs font-medium text-primary-700 leading-relaxed">
                        涉及订单 {brief.totals.orders} 笔
                        {brief.totals.amount !== null && ` · 合计 ¥${Math.round(brief.totals.amount).toLocaleString('zh-CN')}`}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* ─── 需要你处理 ─── */}
              <div className="px-3 py-3 border-b border-gray-100" data-testid="brief-actions">
                <h4 className="px-1 text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">需要你处理</h4>

                {hasActions ? (
                  <div className="space-y-1.5">
                    {/* 待确认：写操作安全闸 */}
                    {pendingInteraction && (
                      <div
                        data-testid="insight-pending-confirm"
                        className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 flex items-start gap-2"
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
                    {/* 失败操作：业务化原因 */}
                    {failedActions.map((action, idx) => (
                      <div key={`failed-${idx}`} className="flex items-start gap-2 rounded-lg border border-red-100 bg-red-50/40 px-2.5 py-2">
                        <XCircle className="w-3.5 h-3.5 text-red-500 flex-shrink-0 mt-0.5" />
                        <div className="min-w-0">
                          <p className="text-xs font-medium text-red-700">{action.label}失败</p>
                          {action.reason && (
                            <p className="text-[11px] text-red-500 mt-0.5 leading-relaxed break-all">{action.reason}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-[11px] text-gray-400 text-center py-4 bg-gray-50 rounded-lg">暂无待办</div>
                )}
              </div>

              {/* ─── 办理结果 ─── */}
              <div className="px-3 py-3 border-b border-gray-100" data-testid="brief-ledger">
                <h4 className="px-1 text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">办理结果</h4>
                {ledgerRows.length === 0 ? (
                  <div className="text-[11px] text-gray-400 text-center py-4 bg-gray-50 rounded-lg">
                    查询订单、商品或物流后，会自动汇总到这里
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {ledgerRows.map(row => (
                      <LedgerRowItem key={`${row.type}-${row.label}`} row={row} onSend={handleSend} />
                    ))}
                  </div>
                )}
              </div>

              {/* ─── 接下来可以问 ─── */}
              {suggestions.length > 0 && (
                <div className="px-3 py-3" data-testid="brief-questions">
                  <h4 className="px-1 text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">接下来可以问</h4>
                  <div className="flex flex-wrap gap-1.5">
                    {suggestions.map(suggestion => (
                      <button
                        key={suggestion}
                        onClick={() => handleSend(suggestion)}
                        className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-full text-[11px] font-medium text-primary-700 bg-primary-50 border border-primary-200 hover:bg-primary-100 transition-colors cursor-pointer"
                      >
                        {suggestion}
                        <ChevronRight className="w-3 h-3" />
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
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

// ─── 办理结果明细行 ──────────────────────────────────

function LedgerRowItem({ row, onSend }: { row: LedgerRow; onSend: (followUp: string) => void }) {
  const Icon = ENTITY_ICONS[row.type]
  const content = (
    <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-2.5 py-2 w-full text-left">
      <Icon className={cn('w-3.5 h-3.5 flex-shrink-0', ENTITY_ICON_CLASSES[row.type])} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-medium text-gray-700 truncate">{row.label}</span>
          {statusBadge(row.type, row.status)}
        </div>
        {(row.amount !== undefined || row.customer) && (
          <p className="text-[11px] text-gray-500 mt-0.5 truncate">
            {row.amount !== undefined && <span className="font-semibold text-red-500">{fmtAmount(row.amount)}</span>}
            {row.amount !== undefined && row.customer && <span> · </span>}
            {row.customer}
          </p>
        )}
      </div>
      <ChevronRight className="w-3.5 h-3.5 text-gray-300 flex-shrink-0" />
    </div>
  )

  if (row.href) {
    return (
      <Link
        href={row.href}
        className="block hover:opacity-90 transition-opacity"
        title={`查看${row.label} 详情`}
      >
        {content}
      </Link>
    )
  }
  return (
    <button onClick={() => onSend(row.followUp)} className="block w-full hover:opacity-90 transition-opacity cursor-pointer" title={row.followUp}>
      {content}
    </button>
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