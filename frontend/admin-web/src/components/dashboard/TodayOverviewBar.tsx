'use client'

import { ArrowDown, ArrowUp, Package, Settings, Sparkles, TrendingUp } from 'lucide-react'
import { cn } from '@/lib/utils'

/** 今日经营速览洞察条 props（三个数值均由页面从 API 返回值派生传入，组件内无硬编码） */
export interface TodayOverviewBarProps {
  /** 订单环比（百分比，正=较昨日上涨） */
  orderChange: number
  /** 含加工待发货订单数 */
  processingCount: number
  /** 待发货订单数 */
  pendingCount: number
  /** 低库存预警 SKU 数（库存 ≤ 100） */
  lowStockCount: number
}

/**
 * 含加工占比 = processingCount / pendingCount，范围 [0,1]。
 * pendingCount <= 0（或非有限值）时返回 0，避免渲染 NaN/Infinity。
 */
export function processingRatio(processingCount: number, pendingCount: number): number {
  if (!Number.isFinite(pendingCount) || pendingCount <= 0) return 0
  const ratio = processingCount / pendingCount
  if (!Number.isFinite(ratio)) return 0
  return Math.min(1, Math.max(0, ratio))
}

/**
 * 订单环比格式化：正数带加号、负数带负号、0 渲染 0%、非有限值渲染 —。
 * 不做任何写死百分比，数值完全来自入参（API 派生）。
 */
export function formatOrderChange(orderChange: number): string {
  if (!Number.isFinite(orderChange)) return '—'
  if (orderChange === 0) return '0%'
  const sign = orderChange > 0 ? '+' : '-'
  return `${sign}${Math.abs(orderChange)}%`
}

/**
 * 米宝「今日经营速览」洞察条（经营看板顶部 AI 洞察一等公民）。
 * 展示三项：订单环比 / 含加工占比 / 低库存预警。
 */
export default function TodayOverviewBar({
  orderChange,
  processingCount,
  pendingCount,
  lowStockCount,
}: TodayOverviewBarProps) {
  const ratioPct = Math.round(processingRatio(processingCount, pendingCount) * 100)
  const up = orderChange > 0
  const down = orderChange < 0

  return (
    <section
      data-testid="today-overview-bar"
      className="relative mb-6 overflow-hidden rounded-xl border border-primary-200/70 bg-white shadow-card"
    >
      {/* 顶部品牌渐变细条 */}
      <div className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-primary-500 via-accent-500 to-primary-500" />

      <div className="px-5 pt-4">
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1 rounded-full bg-gradient-to-r from-primary-600 to-primary-500 px-2.5 py-1 text-xs font-semibold text-white shadow-sm">
            <Sparkles className="h-3 w-3" />
            米宝 · 今日经营速览
          </span>
          <span className="text-[11px] text-neutral-400">AI 生成内容仅供参考</span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-3">
        {/* 订单环比 */}
        <div className="flex items-center gap-3 rounded-lg bg-neutral-50/80 p-3 transition-colors hover:bg-primary-50/60">
          <span className="rounded-lg bg-primary-100 p-2">
            <TrendingUp className="h-4 w-4 text-primary-600" />
          </span>
          <div className="min-w-0">
            <p className="text-xs text-neutral-500">订单环比</p>
            <p className="tnum flex items-center gap-1 text-lg font-semibold text-neutral-900">
              {formatOrderChange(orderChange)}
              {up && <ArrowUp className="h-3.5 w-3.5 text-red-500" />}
              {down && <ArrowDown className="h-3.5 w-3.5 text-emerald-500" />}
            </p>
          </div>
        </div>

        {/* 含加工占比 */}
        <div className="flex items-center gap-3 rounded-lg bg-neutral-50/80 p-3 transition-colors hover:bg-primary-50/60">
          <span className="rounded-lg bg-accent-100 p-2">
            <Settings className="h-4 w-4 text-accent-600" />
          </span>
          <div className="min-w-0">
            <p className="text-xs text-neutral-500">含加工占比</p>
            <p className="tnum text-lg font-semibold text-neutral-900">{ratioPct}%</p>
          </div>
        </div>

        {/* 低库存预警 */}
        <div className="flex items-center gap-3 rounded-lg bg-neutral-50/80 p-3 transition-colors hover:bg-primary-50/60">
          <span className="rounded-lg bg-red-50 p-2">
            <Package className="h-4 w-4 text-red-500" />
          </span>
          <div className="min-w-0">
            <p className="text-xs text-neutral-500">低库存预警</p>
            <p className="tnum text-lg font-semibold text-neutral-900">{lowStockCount} 款</p>
          </div>
        </div>
      </div>
    </section>
  )
}
