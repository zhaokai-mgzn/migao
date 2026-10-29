'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { Sparkles, AlertTriangle, Lightbulb, ListTodo, ArrowRight, RefreshCw, Newspaper, ShieldCheck, ChevronDown, ChevronUp } from 'lucide-react'
import { briefingApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import ProactiveStatusPanel from '@/components/dashboard/ProactiveStatusPanel'
import type { BriefingContent, BriefingItem, BriefingReviewItem, ProactiveStatus } from '@/types'

/**
 * 智能每日经营简报卡（issue #3468，设计文档 docs/design/daily-briefing-design.md v0.2）
 *
 * 四区块：昨日回顾（review）/ 今日必办（todo）/ 风险预警（risks）/ 优化建议（suggestions）。
 * 数据安全：内容来自后端（LLM 输出已经数字回填校验，verifyStatus=verified/partial 才展示条目）；
 * 未生成/生成失败 → 引导空态（不展示假数据，红线 4）。
 *
 * 使用方：经营看板首页（dashboard）顶部。
 */
export interface BriefingCardProps {
  /** 是否启用简报（企业开关）。关闭时不渲染整卡（菜单/首页同时隐藏，红线 3） */
  enabled?: boolean
  /** `page` = 日报页（逐规则原因全展开）；`dashboard` = 看板首页（紧凑，绿行收起） */
  variant?: 'page' | 'dashboard'
  /**
   * 默认收起为**一行**（issue #8105）：看板首页传 `true`，第一眼留给「待处理」；
   * 点「展开」才渲染完整卡片（摘要 + 主动检查 + 昨日回顾 + 今日必办）。
   * 不持久化 —— 刷新回默认收起。空态（未开启 / 未生成）不受本开关影响，走 #8012 的 `briefing-collapsed-hint`。
   */
  defaultCollapsed?: boolean
}

const PRIORITY_STYLES: Record<string, string> = {
  high: 'bg-red-50 text-red-600',
  medium: 'bg-amber-50 text-amber-600',
  low: 'bg-neutral-100 text-neutral-500',
}

const PRIORITY_LABELS: Record<string, string> = {
  high: '紧急',
  medium: '高',
  low: '普通',
}

/** 数字校验未通过时的事实（收起态一行 / 展开态完整句**共用同一句**，不造第二套说法） */
const VERIFY_FAILED = '简报生成未通过数字校验，已安全丢弃不实条目'

/** 收起态那一行摘要（issue #8105）：优先当日摘要首句；无摘要 ⇒ 关键读数；未过校验 ⇒ 说清已丢弃 */
function collapsedSummary({ loading, briefing }: { loading: boolean; briefing: BriefingContent | null }): string {
  if (loading) return '正在读取今日简报…'
  if (!briefing) return VERIFY_FAILED
  const first = briefing.summary?.split('。')[0]?.trim()
  if (first) return first
  const todo = briefing.todo?.length ?? 0
  const risks = briefing.risks?.length ?? 0
  if (todo || risks) return `今日必办 ${todo} 项 · 风险预警 ${risks} 项`
  return '今日没有待办与预警条目'
}

function SeverityBadge({ item }: { item: BriefingItem }) {
  const level = item.priority || item.severity || 'medium'
  return (
    <span className={cn('inline-flex h-5 items-center rounded-full px-1.5 text-[11px] font-medium', PRIORITY_STYLES[level] || PRIORITY_STYLES.medium)}>
      {PRIORITY_LABELS[level] || '高'}
    </span>
  )
}

/** 单条目行：标题 + 理由 + 一键直达（link 由后端 LLM 生成，仅允许站内路由） */
function ItemRow({ item, tone }: { item: BriefingItem; tone: 'todo' | 'risk' | 'suggestion' }) {
  const icon = tone === 'todo' ? <ListTodo className="h-3.5 w-3.5 text-primary-600" />
    : tone === 'risk' ? <AlertTriangle className="h-3.5 w-3.5 text-red-500" />
    : <Lightbulb className="h-3.5 w-3.5 text-amber-500" />
  const inner = (
    <div className="group flex items-start gap-2.5 rounded-lg px-3 py-2.5 transition-colors hover:bg-neutral-50">
      <span className="mt-0.5 flex-shrink-0">{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm text-neutral-800">{item.title}</span>
          <SeverityBadge item={item} />
        </div>
        {(item.reason || item.detail) && (
          <p className="mt-0.5 text-xs text-neutral-500">{item.reason || item.detail}</p>
        )}
      </div>
      {item.link && (
        <span className="mt-0.5 flex-shrink-0 text-neutral-300 transition-transform group-hover:translate-x-0.5 group-hover:text-primary-500">
          <ArrowRight className="h-4 w-4" />
        </span>
      )}
    </div>
  )
  // 一键直达：link 是后端生成的白名单站内路由，用 <Link> 跳转
  if (item.link && item.link.startsWith('/')) {
    return <Link href={item.link}>{inner}</Link>
  }
  return inner
}

/** 环比涨跌方向：↑/+ 与 升/增/涨 → 涨（绿）；↓/- 与 降/减/跌 → 跌（红）；其余（如「持平」）中性。口径与 StatCard 一致。 */
function changeDirection(change: string): 'up' | 'down' | 'flat' {
  if (/[↑+]|上升|增长|增加|上涨|提升/.test(change)) return 'up'
  if (/[↓-]|下降|减少|降低|下跌|回落/.test(change)) return 'down'
  return 'flat'
}

function ReviewStrip({ items }: { items: BriefingReviewItem[] }) {
  if (!items || !items.length) return null
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {items.map((r, i) => {
        // #3888：回顾区弱化绝对值 —— 有环比时主展示环比（带涨跌色），不再重复绝对值；
        // 无环比时保留原值兜底（避免丢信息）。label 恒保留，unit 随原值兜底展示。
        const dir = r.change ? changeDirection(r.change) : 'flat'
        const tone = dir === 'up' ? 'text-green-600' : dir === 'down' ? 'text-red-600' : 'text-neutral-900'
        return (
          <div key={i} className="rounded-lg border border-neutral-100 bg-neutral-50/60 px-3 py-2">
            <p className="text-[11px] text-neutral-400">{r.label}</p>
            {r.change ? (
              <p className={cn('tnum mt-0.5 text-base font-bold', tone)}>{r.change}</p>
            ) : (
              <p className="tnum mt-0.5 text-base font-bold text-neutral-900">
                {r.value?.toLocaleString('zh-CN')}{r.unit ? <span className="ml-0.5 text-[11px] font-normal text-neutral-400">{r.unit}</span> : null}
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default function BriefingCard({ enabled = true, variant = 'dashboard', defaultCollapsed = false }: BriefingCardProps) {
  // 开启时首帧就是「加载中」（issue #8012）：否则会先闪一下「尚未生成」摘要再变回卡片
  const [loading, setLoading] = useState(enabled)
  /**
   * 展开态（issue #8105）：看板首页默认收起一行，点「展开」才渲染完整卡片。
   * **不持久化** —— 刷新回默认收起（看板第一职责是「今天该处理什么」，不是日报全文）。
   */
  const [expanded, setExpanded] = useState(!defaultCollapsed)
  const [briefing, setBriefing] = useState<BriefingContent | null>(null)
  const [verifyStatus, setVerifyStatus] = useState<string | null>(null)
  const [generated, setGenerated] = useState(false)
  // 逐规则接线状态（issue #5955）：后端原样透传的引擎四态；null = 未采集（不渲染面板）
  const [proactiveStatus, setProactiveStatus] = useState<ProactiveStatus | null>(null)

  const fetchBriefing = useCallback(async () => {
    if (!enabled) return
    setLoading(true)
    try {
      const res = await briefingApi.getToday()
      const data = res.data.data
      setGenerated(!!data?.generated)
      setVerifyStatus(data?.verifyStatus ?? null)
      setProactiveStatus(data?.proactive_status ?? null)
      // 后端 failed 状态返回 content={}（空对象）：归一化为 null，
      // 避免渲染期 briefing.review.length 等对 undefined 取属性崩溃（UI 旅程实证）
      const content = data?.content
      if (content && typeof content === 'object' && Array.isArray(content.review)) {
        setBriefing(content as BriefingContent)
      } else {
        setBriefing(null)
      }
    } catch (e) {
      console.error('Briefing load:', e)
      setGenerated(false)
      setBriefing(null)
      setProactiveStatus(null)
    } finally {
      setLoading(false)
    }
  }, [enabled])

  useEffect(() => { fetchBriefing() }, [fetchBriefing])

  // ── 空态压缩（issue #8012）──────────────────────────────────────────────
  // 改前：开关关闭 ⇒ 整块不渲染；开关开启但今日未生成 ⇒ 一个约 300px 的常驻盒子
  //       （图标 + 「今日简报尚未生成」+ 三行长说明 + 「去开启」）⇒ 把「待处理」推到 1440×900
  //       折叠线以下（2026-10-24 真栈截图 03-briefing.png 即此现象）。
  // 改后：两种空态都降级为**一行摘要**（`migao-dev-flow` §31 P1 常驻面克制）：
  //       一句话说清状态 + 一个可行动入口；有数据时仍是原来的完整卡片（不压缩）。
  if (!enabled || (!loading && !generated)) {
    return (
      <div className="mb-6 space-y-2">
        <div
          data-testid="briefing-collapsed-hint"
          className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border border-neutral-200 bg-white px-4 py-2.5 text-xs text-neutral-500 shadow-card"
        >
          <Newspaper className="h-3.5 w-3.5 flex-shrink-0 text-neutral-400" />
          <span className="font-medium text-neutral-700">
            {enabled ? '今日简报尚未生成' : '每日经营简报未开启'}
          </span>
          <span className="text-neutral-400">
            {enabled
              ? '每日生成时刻自动整理经营要点；生成失败时不会展示不实数据'
              : '开启后每日自动整理经营要点'}
          </span>
          <Link
            href="/settings?tab=basic"
            className="ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium text-primary-600 transition-colors hover:bg-primary-50 hover:text-primary-700"
          >
            {enabled ? '查看设置' : '开启'} <ArrowRight className="h-3 w-3" />
          </Link>
        </div>
        {/* 简报没生成 ≠ 没有主动检查结论：有采集到就说清楚「哪些方面本次没有数据」 */}
        {enabled && <ProactiveStatusPanel status={proactiveStatus} variant={variant} />}
      </div>
    )
  }

  // ── 收起态（issue #8105）────────────────────────────────────────────────
  // 有数据时也默认一行（图标 + 标题 + 一句关键摘要 + 「展开」）。改前完整卡片约 400px 高，
  // 把「待处理」推到 1440×900 首屏之外 663px（2026-10-29 真栈实测 y=1563）。
  // 🔴 空态（未开启 / 未生成）**不**走这里 —— 它沿用上面 #8012 的 `briefing-collapsed-hint`（别造第二套）。
  if (!expanded) {
    return (
      <div className="mb-6">
        <button
          type="button"
          data-testid="briefing-toggle"
          aria-expanded={false}
          onClick={() => setExpanded(true)}
          className="flex w-full items-center gap-2.5 rounded-xl border border-neutral-200 bg-white px-4 py-2.5 text-left shadow-card transition-colors hover:border-primary-200"
        >
          <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary-50 to-accent-50">
            <Newspaper className="h-3.5 w-3.5 text-primary-600" />
          </span>
          <span className="flex-shrink-0 text-sm font-semibold text-neutral-900">每日经营简报</span>
          <span className="min-w-0 flex-1 truncate text-xs text-neutral-500">
            {collapsedSummary({ loading, briefing })}
          </span>
          <span className="flex flex-shrink-0 items-center gap-1 text-xs font-medium text-primary-600">
            展开
            <ChevronDown className="h-3.5 w-3.5" />
          </span>
        </button>
      </div>
    )
  }

  return (
    <div className="mb-6 rounded-xl border border-neutral-200 bg-white shadow-card">
      {/* 头部 */}
      <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-4">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-primary-50 to-accent-50">
            <Newspaper className="h-4 w-4 text-primary-600" />
          </span>
          <div>
            <h2 className="flex items-center gap-1.5 text-sm font-semibold text-neutral-900">
              每日经营简报
              <span className="inline-flex items-center gap-0.5 rounded-full bg-primary-50 px-1.5 py-0.5 text-[10px] font-medium text-primary-600">
                <Sparkles className="h-2.5 w-2.5" /> AI 生成
              </span>
            </h2>
            <p className="mt-0.5 text-[11px] text-neutral-400">昨日回顾 · 今日必办 · 风险预警 · 优化建议</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={fetchBriefing}
            disabled={loading}
            className="flex items-center gap-1.5 rounded-lg border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-500 shadow-sm transition-colors hover:border-primary-200 hover:text-primary-600 disabled:opacity-50"
          >
            <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
            刷新
          </button>
          {/* 收起（issue #8105）：只有「默认可收起」的调用方才给这个入口 —— 其它调用面行为不变 */}
          {defaultCollapsed && (
            <button
              type="button"
              data-testid="briefing-toggle"
              aria-expanded={true}
              onClick={() => setExpanded(false)}
              className="flex items-center gap-1 rounded-lg border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-500 shadow-sm transition-colors hover:border-primary-200 hover:text-primary-600"
            >
              收起
              <ChevronUp className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      <div className="p-5">
        {loading ? (
          <div className="space-y-3">
            <div className="h-4 w-2/3 animate-pulse rounded bg-neutral-100" />
            <div className="grid grid-cols-3 gap-3">
              {Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-14 animate-pulse rounded-lg bg-neutral-100" />)}
            </div>
            <div className="h-10 animate-pulse rounded-lg bg-neutral-100" />
          </div>
        ) : !briefing ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2 py-2 text-sm text-neutral-500">
              <ShieldCheck className="h-4 w-4 text-neutral-400" />
              {VERIFY_FAILED}（不会展示编造数据）。
            </div>
            <ProactiveStatusPanel status={proactiveStatus} variant={variant} />
          </div>
        ) : (
          <div className="space-y-5">
            {/* 一句话总览 */}
            {briefing.summary && (
              <p className="rounded-lg bg-neutral-50 px-4 py-3 text-sm text-neutral-700">{briefing.summary}</p>
            )}

            {/* 主动检查 · 逐规则四态（issue #5955）：让「今天为什么没有提示」可解释 */}
            <ProactiveStatusPanel status={proactiveStatus} variant={variant} />

            {/* 昨日回顾 */}
            {briefing.review?.length > 0 && (
              <div>
                <h3 className="mb-2 text-xs font-semibold text-neutral-500">昨日回顾</h3>
                <ReviewStrip items={briefing.review} />
              </div>
            )}

            {/* 今日必办 */}
            {briefing.todo?.length > 0 && (
              <div>
                <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-neutral-500">
                  <ListTodo className="h-3.5 w-3.5 text-primary-500" /> 今日必办
                </h3>
                <div className="space-y-1">
                  {briefing.todo.map((item, i) => <ItemRow key={i} item={item} tone="todo" />)}
                </div>
              </div>
            )}

            {/* 风险预警 */}
            {briefing.risks?.length > 0 && (
              <div>
                <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-neutral-500">
                  <AlertTriangle className="h-3.5 w-3.5 text-red-500" /> 风险预警
                </h3>
                <div className="space-y-1">
                  {briefing.risks.map((item, i) => <ItemRow key={i} item={item} tone="risk" />)}
                </div>
              </div>
            )}

            {/* 优化建议 */}
            {briefing.suggestions?.length > 0 && (
              <div>
                <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-neutral-500">
                  <Lightbulb className="h-3.5 w-3.5 text-amber-500" /> 优化建议
                </h3>
                <div className="space-y-1">
                  {briefing.suggestions.map((item, i) => <ItemRow key={i} item={item} tone="suggestion" />)}
                </div>
              </div>
            )}

            {/* 全部区块为空（如全部条目被校验丢弃但 summary 存在）→ 提示性兜底。
                🔴 措辞只说「简报没有可执行条目」，**不**说「经营平稳 / 一切正常」：
                「没命中」到底等于「没问题」还是「本次没检查」，只有上面的主动检查面板说得清。 */}
            {(briefing.todo?.length ?? 0) === 0 && (briefing.risks?.length ?? 0) === 0 && (briefing.suggestions?.length ?? 0) === 0 && (
              <p className="text-xs text-neutral-400">
                今日简报没有待办与预警条目（是否代表「没问题」请看上方「主动检查」的逐规则结论）。
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
