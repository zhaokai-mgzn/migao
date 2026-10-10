'use client'

import { Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'

/** 读不到 / 无有效值时的占位（口径同 `formatOrderChange` 的「—」，也同 bmini 侧 `DASHBOARD_EMPTY_VALUE`） */
const DASHBOARD_EMPTY_VALUE = '—'

/** 今日经营速览洞察条 props（数值均由页面从 API 返回值派生传入，组件内无硬编码） */
export interface TodayOverviewBarProps {
  /** 今日订单数；`null` = **读不到**（不是 0 —— 见 issue #6701） */
  todayOrders: number | null
  /** 今日销售额；`null` = **读不到**（不是 0 —— 见 issue #6701） */
  todaySales: number | null
  /** 订单环比（百分比，正=较昨日上涨）；`null` = 无上期可比 / 读不到 */
  orderChange: number | null
  /** 销售额环比（百分比，正=较昨日上涨）；`null` = 无上期可比 / 读不到 */
  salesChange: number | null
  /** 含加工待发货数 */
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
export function formatOrderChange(orderChange: number | null | null | undefined): string {
  // 🔴 null = **无上期可比**（上期为 0）⇒ 显示「—」，**不是** 0%：
  //    0% 会被读成「与上期持平」，那是另一个意思（口径整改见 issue #5792）。
  if (orderChange == null) return '—'
  if (!Number.isFinite(orderChange)) return '—'
  if (orderChange === 0) return '0%'
  const sign = orderChange > 0 ? '+' : '-'
  return `${sign}${Math.abs(orderChange)}%`
}

/** 金额格式化：≥ 1 万转「万」（最多 2 位小数，去尾零），否则千分位（最多 2 位小数） */
function fmtCurrency(n: number): string {
  if (!Number.isFinite(n)) return '¥0'
  if (n >= 10000) {
    const w = parseFloat((n / 10000).toFixed(2))
    return '¥' + w + '万'
  }
  return '¥' + n.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
}

export interface InsightParams {
  /** `null` = **读不到**（与「真 0」不同：真 0 才说「今日暂无新订单」—— issue #6701） */
  todayOrders: number | null
  /** `null` = **读不到**（同上） */
  todaySales: number | null
  orderChange: number | null
  salesChange: number | null
  /** 含加工占比百分比（0-100） */
  processingRatioPct: number
  lowStockCount: number
}

/**
 * 生成一句话经营解读：把今日订单/销售额/环比/提醒串联成一句人话。
 * 全部由 API 派生数值生成，无硬编码假数据；非有限值一律规避。
 *
 * 🔴 issue #6701：`todayOrders` / `todaySales` 为 `null` = **读不到**（不是 0）——
 * 改前页面传 `?? 0` 进来，这句话就变成「今日暂无新订单，销售额 ¥0」，
 * 与同屏的「数据加载失败」**互相打架**，且会把商家读成「今天没卖出去」。
 * 现在读不到 ⇒ `—`（与金额卡同一占位），**真 0 仍走原分支**（那是事实）。
 */
export function buildInsightSentence(p: InsightParams): string {
  const { todayOrders, todaySales, orderChange, salesChange, processingRatioPct, lowStockCount } = p

  // 读不到（任一侧为 `null`）⇒ 说「没取到」，**不说**「¥0 / 0 单」—— 那是编造的经营事实
  if (todayOrders === null || todaySales === null) {
    return `今日订单数 ${todayOrders === null ? DASHBOARD_EMPTY_VALUE : todayOrders}、销售额 ${todaySales === null ? DASHBOARD_EMPTY_VALUE : fmtCurrency(todaySales)}（经营数据没读到，详见上方提示）`
  }

  // 真 0 是**事实**（今天确实没卖出去）—— 与「读不到」是两件事，不走上一条分支
  if (todayOrders <= 0 && todaySales <= 0) {
    return '今日暂无新订单，销售额 ¥0'
  }

  const parts: string[] = []
  parts.push(`今日订单 ${Math.max(todayOrders, 0)} 单、销售额 ${fmtCurrency(todaySales)}`)
  parts.push(`较昨日订单 ${formatOrderChange(orderChange)}、销售额 ${formatOrderChange(salesChange)}`)
  if (processingRatioPct > 0) parts.push(`含加工订单占 ${Math.round(processingRatioPct)}%`)
  if (lowStockCount > 0) parts.push(`${Math.max(lowStockCount, 0)} 款商品库存偏低`)

  return parts.join('，')
}

/**
 * 黄金策「今日经营速览」洞察条（经营看板顶部 AI 洞察一等公民）。
 * 以「一句话经营解读」形式呈现：数字串联成句，客户一眼读懂业务含义。
 */
export default function TodayOverviewBar({
  todayOrders,
  todaySales,
  orderChange,
  salesChange,
  processingCount,
  pendingCount,
  lowStockCount,
}: TodayOverviewBarProps) {
  const ratioPct = Math.round(processingRatio(processingCount, pendingCount) * 100)
  const sentence = buildInsightSentence({
    todayOrders,
    todaySales,
    orderChange,
    salesChange,
    processingRatioPct: ratioPct,
    lowStockCount,
  })

  return (
    <section
      data-testid="today-overview-bar"
      className="relative mb-6 overflow-hidden rounded-xl border border-primary-200/70 bg-white shadow-card"
    >
      {/* 顶部品牌渐变细条 */}
      <div className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-primary-500 via-accent-500 to-primary-500" />

      <div className="px-5 py-4">
        <div className="mb-2.5 flex items-center gap-2">
          <span className="inline-flex items-center gap-1 rounded-full bg-gradient-to-r from-primary-600 to-primary-500 px-2.5 py-1 text-xs font-semibold text-white shadow-sm">
            <Sparkles className="h-3 w-3" />
            黄金策 · 今日经营速览
          </span>
          <span className="text-[11px] text-neutral-400">AI 生成内容仅供参考</span>
        </div>
        <p data-testid="today-overview-sentence" className={cn('text-sm leading-relaxed text-neutral-700')}>{sentence}</p>
      </div>
    </section>
  )
}
