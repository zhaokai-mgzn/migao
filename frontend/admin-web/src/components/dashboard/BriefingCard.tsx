'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { Sparkles, AlertTriangle, Lightbulb, ListTodo, ArrowRight, RefreshCw, Newspaper, ShieldCheck } from 'lucide-react'
import { briefingApi } from '@/lib/api'
import { useChatStore } from '@/store/chat'
import { cn } from '@/lib/utils'
import ProactiveStatusPanel from '@/components/dashboard/ProactiveStatusPanel'
import type { BriefingContent, BriefingItem, BriefingReviewItem, ProactiveStatus } from '@/types'

/**
 * 智能每日经营简报（issue #3468，设计文档 docs/design/daily-briefing-design.md v0.2）
 *
 * 四区块：昨日回顾（review）/ 今日必办（todo）/ 风险预警（risks）/ 优化建议（suggestions）。
 * 数据安全：内容来自后端（LLM 输出已经数字回填校验，verifyStatus=verified/partial 才展示条目）；
 * 未生成/生成失败 → 引导空态（不展示假数据，红线 4）。
 *
 * 使用方（issue #8114）：
 * ① 经营看板「黄金策 · 今日经营」合并卡 `DailyBusinessCard` —— `embedded` 形态：
 *    不渲染自己的卡片外壳与头部，由合并卡统一「展开 / 收起」（收起态 = 速览那一句话）；
 * ② 独立卡片形态（`variant='page'`）—— 组件保留给 /briefing 深链与既有单测。
 */
export interface BriefingCardProps {
  /**
   * 企业开关（issue #8114 四态之一）：
   * `true` = 开启；`false` = **未开启**（卡片仍在，段内说「未开启」+ 去开启入口）；
   * `null` = **开关还没回来** ⇒ 按「加载中」处理（改前若先渲染「未开启」会闪一句错话 —— #8012）。
   */
  enabled?: boolean | null
  /** `page` = 日报页（逐规则原因全展开）；`dashboard` = 看板首页（紧凑，绿行收起） */
  variant?: 'page' | 'dashboard'
  /** 嵌进合并卡（issue #8114）：只出**内容**，不渲染卡片外壳 / 头部（展开收起由调用方持有） */
  embedded?: boolean
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

/** 数字校验未通过时的事实（简报没有可展示内容时**共用同一句**，不造第二套说法） */
const VERIFY_FAILED = '简报生成未通过数字校验，已安全丢弃不实条目'

function SeverityBadge({ item }: { item: BriefingItem }) {
  const level = item.priority || item.severity || 'medium'
  return (
    <span className={cn('inline-flex h-5 items-center rounded-full px-1.5 text-[11px] font-medium', PRIORITY_STYLES[level] || PRIORITY_STYLES.medium)}>
      {PRIORITY_LABELS[level] || '高'}
    </span>
  )
}

/** 条目 → 预置给黄金策的问题：带上下文，不是空泛的「帮我看看」（issue #8236） */
function askPrompt(item: BriefingItem): string {
  const detail = item.reason || item.detail
  return `日报里这条：${item.title}${detail ? `（${detail}）` : ''}`
    + ' —— 帮我查一下相关数据，给出处理建议；能批量处理的话给我确认卡。'
}

/** 单条目行：标题 + 理由 + 一键直达（link）+ 问黄金策（issue #8236） */
function ItemRow({ item, tone, bizDate }: { item: BriefingItem; tone: 'todo' | 'risk' | 'suggestion'; bizDate: string | null }) {
  // 外部入口：把这条建议**直接交给**黄金策，而不是只给一个跳页面的箭头。
  // 无 link 的条目（建议/风险类）同样有它 —— 恰恰是这些条目没有「页面可去」。
  const openAssistant = useChatStore((s) => s.openAssistant)
  // 上报「点开问了」（issue #8260）：**fire-and-forget** —— 不 await、不 catch 弹错。
  // `opened_agent` 只表示「点开问了」，**不表示**「照着做了」（报表文案必须区分）。
  const reportAsked = () => {
    if (!bizDate) return
    void briefingApi
      .recordAction({ bizDate, itemKind: tone, title: item.title, action: 'opened_agent' })
      .catch(() => {})
  }
  const icon = tone === 'todo' ? <ListTodo className="h-3.5 w-3.5 text-primary-600" />
    : tone === 'risk' ? <AlertTriangle className="h-3.5 w-3.5 text-red-500" />
    : <Lightbulb className="h-3.5 w-3.5 text-amber-500" />
  const link = item.link && item.link.startsWith('/') ? item.link : null
  const content = (
    <div className="flex min-w-0 flex-1 items-start gap-2.5">
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
    </div>
  )
  return (
    <div className="group flex items-start gap-2 rounded-lg px-3 py-2.5 transition-colors hover:bg-neutral-50">
      {/* 一键直达：link 是后端生成的白名单站内路由，用 <Link> 跳转 */}
      {link ? (
        <Link href={link} className="min-w-0 flex-1">{content}</Link>
      ) : (
        <div className="min-w-0 flex-1">{content}</div>
      )}
      {link && (
        <span className="mt-0.5 flex-shrink-0 text-neutral-300 transition-transform group-hover:translate-x-0.5 group-hover:text-primary-500">
          <ArrowRight className="h-4 w-4" />
        </span>
      )}
      <button
        type="button"
        onClick={() => {
                reportAsked()
                openAssistant(askPrompt(item))
              }}
        className="mt-0.5 flex flex-shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-neutral-400 transition-colors hover:bg-primary-50 hover:text-primary-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-400"
        aria-label={`问黄金策：${item.title}`}
      >
        <Sparkles className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">问黄金策</span>
      </button>
    </div>
  )
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

export default function BriefingCard({ enabled = true, variant = 'dashboard', embedded = false }: BriefingCardProps) {
  // 开启时首帧就是「加载中」（issue #8012）：否则会先闪一下「尚未生成」摘要再变回卡片
  const [loading, setLoading] = useState(enabled !== false)
  const [briefing, setBriefing] = useState<BriefingContent | null>(null)
  const [verifyStatus, setVerifyStatus] = useState<string | null>(null)
  // 上报需要业务日期（issue #8260）：简报条目的「哪一天的」由它钉住
  const [bizDate, setBizDate] = useState<string | null>(null)
  const [generated, setGenerated] = useState(false)
  // 逐规则接线状态（issue #5955）：后端原样透传的引擎四态；null = 未采集（不渲染面板）
  const [proactiveStatus, setProactiveStatus] = useState<ProactiveStatus | null>(null)

  const fetchBriefing = useCallback(async () => {
    if (enabled !== true) return
    setLoading(true)
    try {
      const res = await briefingApi.getToday()
      const data = res.data.data
      setGenerated(!!data?.generated)
      setVerifyStatus(data?.verifyStatus ?? null)
      setBizDate(data?.bizDate ?? null)
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

  // ── 空态（issue #8012 常驻面克制 / issue #8114 四态）──────────────────────
  // 两种空态都只有**一行**（一句话说清状态 + 一个可行动入口）：
  //   未开启（enabled=false）⇒ 「每日经营简报未开启」+ 去开启入口；
  //   已开启但今日未生成   ⇒ 「今日简报尚未生成」+ 查看设置入口。
  // 🔴 合并进「今日经营」卡后，空态由**展开态**承载（收起态就是速览那一句话），
  //    但形态与 testid（`briefing-collapsed-hint`）沿用同一套语义 —— 不造第二套空态。
  const hint = (
    <div
      data-testid="briefing-collapsed-hint"
      className={cn(
        'flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg text-xs text-neutral-500',
        embedded ? 'bg-neutral-50 px-3 py-2' : 'border border-neutral-200 bg-white px-4 py-2.5 shadow-card',
      )}
    >
      <Newspaper className="h-3.5 w-3.5 flex-shrink-0 text-neutral-400" />
      <span className="font-medium text-neutral-700">
        {enabled === false ? '每日经营简报未开启' : '今日简报尚未生成'}
      </span>
      <span className="text-neutral-400">
        {enabled === false
          ? '开启后每日自动整理经营要点'
          : '每日生成时刻自动整理经营要点；生成失败时不会展示不实数据'}
      </span>
      <Link
        href="/settings?tab=basic"
        className="ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium text-primary-600 transition-colors hover:bg-primary-50 hover:text-primary-700"
      >
        {enabled === false ? '开启' : '查看设置'} <ArrowRight className="h-3 w-3" />
      </Link>
    </div>
  )
  const emptyState = (
    <div className={cn('space-y-2', !embedded && 'mb-6')}>
      {hint}
      {/* 简报没生成 ≠ 没有主动检查结论：有采集到就说清楚「哪些方面本次没有数据」 */}
      {enabled === true && <ProactiveStatusPanel status={proactiveStatus} variant={variant} />}
    </div>
  )

  if (enabled === false) return emptyState

  // 加载中（issue #8114 四态之四）：配置开关还没回来（null）或 getToday 未落定 ⇒ 简报骨架。
  const skeleton = (
    <div data-testid="briefing-skeleton" className="space-y-3">
      <div className="h-4 w-2/3 animate-pulse rounded bg-neutral-100" />
      <div className="grid grid-cols-3 gap-3">
        {Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-14 animate-pulse rounded-lg bg-neutral-100" />)}
      </div>
      <div className="h-10 animate-pulse rounded-lg bg-neutral-100" />
    </div>
  )

  if (enabled === null || loading) {
    if (embedded) return skeleton
    return (
      <div className="mb-6 rounded-xl border border-neutral-200 bg-white shadow-card">
        {headerNode()}
        <div className="p-5">{skeleton}</div>
      </div>
    )
  }

  if (!generated) return emptyState

  const content = !briefing ? (
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
            {briefing.todo.map((item, i) => <ItemRow key={i} item={item} tone="todo" bizDate={bizDate} />)}
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
            {briefing.risks.map((item, i) => <ItemRow key={i} item={item} tone="risk" bizDate={bizDate} />)}
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
            {briefing.suggestions.map((item, i) => <ItemRow key={i} item={item} tone="suggestion" bizDate={bizDate} />)}
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
  )

  // 合并卡（issue #8114）：只出内容，外壳与展开/收起由调用方持有
  if (embedded) return content

  return (
    <div className="mb-6 rounded-xl border border-neutral-200 bg-white shadow-card">
      {headerNode()}
      <div className="p-5">{content}</div>
    </div>
  )

  /** 独立卡片形态的头部（refresh + AI 标记）；embedded 形态不渲染它 */
  function headerNode() {
    return (
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
        </div>
      </div>
    )
  }
}
