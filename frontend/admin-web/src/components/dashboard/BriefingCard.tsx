'use client'

import { useCallback, useEffect, useState } from 'react'
import Link from 'next/link'
import { Sparkles, AlertTriangle, Lightbulb, ListTodo, ArrowRight, RefreshCw, Newspaper, ShieldCheck } from 'lucide-react'
import { briefingApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import type { BriefingContent, BriefingItem, BriefingReviewItem } from '@/types'

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

function ReviewStrip({ items }: { items: BriefingReviewItem[] }) {
  if (!items || !items.length) return null
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {items.map((r, i) => (
        <div key={i} className="rounded-lg border border-neutral-100 bg-neutral-50/60 px-3 py-2">
          <p className="text-[11px] text-neutral-400">{r.label}</p>
          <p className="tnum mt-0.5 text-base font-bold text-neutral-900">
            {r.value?.toLocaleString('zh-CN')}{r.unit ? <span className="ml-0.5 text-[11px] font-normal text-neutral-400">{r.unit}</span> : null}
          </p>
          {r.change && <p className="mt-0.5 text-[11px] text-neutral-400">{r.change}</p>}
        </div>
      ))}
    </div>
  )
}

export default function BriefingCard({ enabled = true }: BriefingCardProps) {
  const [loading, setLoading] = useState(false)
  const [briefing, setBriefing] = useState<BriefingContent | null>(null)
  const [verifyStatus, setVerifyStatus] = useState<string | null>(null)
  const [generated, setGenerated] = useState(false)

  const fetchBriefing = useCallback(async () => {
    if (!enabled) return
    setLoading(true)
    try {
      const res = await briefingApi.getToday()
      const data = res.data.data
      setGenerated(!!data?.generated)
      setVerifyStatus(data?.verifyStatus ?? null)
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
    } finally {
      setLoading(false)
    }
  }, [enabled])

  useEffect(() => { fetchBriefing() }, [fetchBriefing])

  // 企业开关关闭 → 整卡不渲染（红线 3：菜单/首页同时隐藏）
  if (!enabled) return null

  return (
    <div className="mb-6 rounded-xl border border-neutral-200 bg-white shadow-card">
      {/* 头部 */}
      <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-4">
        <div className="flex items-center gap-2.5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-primary-50 to-indigo-50">
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
        <button
          onClick={fetchBriefing}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-lg border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-500 shadow-sm transition-colors hover:border-primary-200 hover:text-primary-600 disabled:opacity-50"
        >
          <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          刷新
        </button>
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
        ) : !generated ? (
          // 引导空态：未生成/生成失败（不展示假数据，红线 4）
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-primary-50 to-indigo-50">
              <Newspaper className="h-5 w-5 text-primary-400" />
            </div>
            <p className="text-sm font-medium text-neutral-600">今日简报尚未生成</p>
            <p className="mt-1 max-w-md text-xs text-neutral-400">
              开启「智能每日经营简报」后，系统将在每日生成时刻自动为您整理经营要点；生成失败时会显示此状态，不会展示不实数据。
            </p>
            <Link
              href="/settings?tab=basic"
              className="mt-4 inline-flex items-center gap-1.5 rounded-lg border border-primary-200 bg-primary-50 px-3.5 py-2 text-xs font-medium text-primary-600 transition-colors hover:bg-primary-100"
            >
              去开启 <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        ) : !briefing ? (
          <div className="flex items-center gap-2 py-6 text-sm text-neutral-500">
            <ShieldCheck className="h-4 w-4 text-neutral-400" />
            简报生成未通过数字校验，已安全丢弃不实条目（不会展示编造数据）。
          </div>
        ) : (
          <div className="space-y-5">
            {/* 一句话总览 */}
            {briefing.summary && (
              <p className="rounded-lg bg-neutral-50 px-4 py-3 text-sm text-neutral-700">{briefing.summary}</p>
            )}

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

            {/* 全部区块为空（如全部条目被校验丢弃但 summary 存在）→ 提示性兜底 */}
            {(briefing.todo?.length ?? 0) === 0 && (briefing.risks?.length ?? 0) === 0 && (briefing.suggestions?.length ?? 0) === 0 && (
              <p className="text-xs text-neutral-400">今日暂无待办事项与预警，经营平稳。</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
