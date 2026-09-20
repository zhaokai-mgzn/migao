'use client'

import Link from 'next/link'
import { AlertCircle } from 'lucide-react'
import { operationDisplayName } from '@/lib/operation-display'
import type { UnpricedPiecework } from '@/types'

/**
 * 「未定价」显式可见块（V90，issue #4696，P1）。
 *
 * <p>为什么必须有它（缺陷原形）：矩阵格未定价此前在**实例化侧**被回落成「工序库行价」
 * （`NOT NULL DEFAULT 0`）⇒ 计件 **0 元**，而界面只把「未定价」画在**读面徽标**上
 * （`GET /operation-layers`）⇒ **界面说「未定价」、实际计件 0 元**：工人白干且无人知道，
 * 且「没定价」与「价本来就是 0」不可区分。</p>
 *
 * <p>本组件把三件事摆到**真正算钱的页面**上：① 未定价工序的合格数量（干了多少活）；
 * ② 逐条工序名（该给哪道定价）；③ **定价入口**（跳「工艺配置 → 工艺路线」的部位价目矩阵）。
 * 未定价的报工**不进**计件合计（后端 `unpriced` 块已排除）——本块只做「说不清的钱要显形」。</p>
 *
 * <p>零条未定价 ⇒ 不渲染任何东西（不制造噪音）。</p>
 */
interface UnpricedNoticeProps {
  /** 后端 `unpriced` 块（per-order 汇总 / 期间报表同形）；缺省/空 ⇒ 不渲染 */
  unpriced?: UnpricedPiecework | null
  className?: string
}

/** 定价入口（部位价目矩阵就在「工艺配置 → 工艺路线」页；URL 与后端 hint 同源） */
export const PRICING_ENTRY_HREF = '/production/routings'

export default function UnpricedNotice({ unpriced, className }: UnpricedNoticeProps) {
  const rows = unpriced?.operations ?? []
  if (rows.length === 0) {
    return null
  }
  const qty = unpriced?.qty ?? 0

  return (
    <div
      className={`rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800 ${className ?? ''}`}
      data-testid="piecework-unpriced"
    >
      <p className="flex items-center gap-2 font-medium">
        <AlertCircle className="w-4 h-4" />
        <span data-testid="piecework-unpriced-title">有 {rows.length} 道工序未定价</span>
      </p>
      <p className="mt-1 text-xs opacity-90" data-testid="piecework-unpriced-detail">
        合计 {qty} 件（合格数量）<b>未计入</b>计件金额 —— 未定价 ≠ ¥0.00，
        这些活工人照做了但拿不到钱，请先定价。
      </p>
      <ul className="mt-2 space-y-0.5 text-xs" data-testid="piecework-unpriced-list">
        {rows.map((row, index) => (
          <li key={`${operationDisplayName(row)}-${index}`} data-testid={`piecework-unpriced-${index}`}>
            <span data-testid={`piecework-unpriced-name-${index}`}>{operationDisplayName(row)}</span>
            {' · 未定价（'}
            {row.qty ?? 0}
            {'）'}
          </li>
        ))}
      </ul>
      <Link
        href={PRICING_ENTRY_HREF}
        data-testid="piecework-unpriced-pricing-link"
        className="mt-2 inline-block rounded border border-amber-400 bg-white px-2 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100"
      >
        去定价（工艺配置 → 工艺路线 · 部位价目矩阵）
      </Link>
    </div>
  )
}
