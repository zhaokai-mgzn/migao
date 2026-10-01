'use client'

/**
 * 订单详情页「费用构成」（issue #5843）—— **只读展示**，数全部来自**落库快照**。
 *
 * 用户 2026-10-01 报障：`商品合计 ¥245.14` 与 `订单金额 ¥368.74` 之间那笔
 * **¥123.60 加工费在页面上任何位置都不出现** —— 详情页「金额 / 商品合计」两列只算商品金额，
 * 而页脚用的是订单级总额（含加工费）⇒ 商家看到两个数对不上、无从对账。
 *
 * 本组件的职责只有一件：把**服务端已算好**的构成摆成**页面上读得出来的等式**
 * ```
 * 商品合计 + 加工费 + 其它构成 = 订单金额
 * ```
 * 三条硬口径（与 `lib/order-fee-display.ts` 同源，判定全在那边）：
 * 1. **只展示、不重算**：加工费合计 = Σ 落库 `items[].processingFee`；行级算式只是复述
 *    服务端的 `processingFeeDetail`（`10.3 米 × ¥12.00/米 = ¥123.60`）—— 详情页是**落库快照**面，
 *    与新增订单页的**试算预览**是两回事（⛔ 不许按单价 × 米数重算出一套新数）；
 * 2. **未定价不渲染 `¥0.00`**：那半按 0 计 ⇒ 显式标「未定价」并**点名组合**（那格写文字，不写钱）；
 * 3. **布料单不出现空行 / `¥0.00` 行**：没有加工是正常、不是缺失 ⇒ 整块不渲染。
 *
 * ⚠️ 判定与渲染分离：所有「该不该显示、显示多少」都在 `buildOrderFeeComposition` 里，
 * 本文件只做 JSX（判据可脱离页面断言 —— #4434 同族拆法）。
 */

import { buildOrderFeeComposition, formatMoney, type OrderFeeLine } from '@/lib/order-fee-display'
import { cn } from '@/lib/utils'
import type { OrderItem } from '@/types'

interface OrderFeeBreakdownProps {
  items: OrderItem[]
  /** 商品合计（元）= 页面上「商品合计」列之和（调用方按**同一份**行金额口径算好传入） */
  goodsTotal: number
  /** 订单金额（服务端 `order.totalAmount`；未取到 ⇒ `null` ⇒ 不编差额） */
  orderTotal?: number | null
  className?: string
}

export default function OrderFeeBreakdown({
  items,
  goodsTotal,
  orderTotal,
  className,
}: OrderFeeBreakdownProps) {
  const composition = buildOrderFeeComposition(items, { goodsTotal, orderTotal })
  // 布料单（无加工费 / 无未定价 / 无差额）⇒ 整块不出现：没有加工是正常，不是缺失
  if (!composition.visible) return null

  // 等式（验收硬判据：「商品合计 + 加工费 + 其它构成 = 订单金额」必须在页面上看得见）
  const arithmetic = [
    `${formatMoney(composition.goodsTotal)}（商品合计）`,
    composition.showProcessingFee ? `${formatMoney(composition.processingFeeTotal)}（加工费）` : null,
    composition.showRemainder ? `${formatMoney(composition.remainder)}（其它构成）` : null,
  ].filter((part): part is string => part !== null)
  const orderTotalText =
    composition.orderTotal === null ? '订单金额未取到' : `${formatMoney(composition.orderTotal)}（订单金额）`
  const equation = `${arithmetic.join(' + ')} = ${orderTotalText}${
    composition.unpricedCount > 0 ? `，其中 ${composition.unpricedCount} 行未定价（见下）` : ''
  }`

  return (
    <div
      data-testid="order-fee-breakdown"
      className={cn(
        'mt-4 rounded-lg border border-neutral-200 bg-neutral-50/60 px-4 py-3',
        className
      )}
    >
      <div className="text-xs font-semibold text-neutral-500">费用构成</div>

      <div className="mt-2 space-y-1.5 text-sm">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-neutral-500">商品合计</span>
          <span data-testid="fee-breakdown-goods" className="text-neutral-900 tabular-nums">
            {formatMoney(composition.goodsTotal)}
          </span>
        </div>

        {composition.showProcessingFee && (
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-neutral-500">加工费</span>
            <span
              data-testid="fee-breakdown-processing"
              className="text-amber-700 font-medium tabular-nums"
            >
              {formatMoney(composition.processingFeeTotal)}
            </span>
          </div>
        )}

        {/* 逐行加工费（只列**有这笔钱**的行与**未定价**行）—— 商家据此对上加工单 */}
        {composition.lines.map((line) => (
          <FeeLine key={line.key} line={line} />
        ))}

        {composition.showRemainder && (
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-neutral-500">其它构成</span>
            <span data-testid="fee-breakdown-other" className="text-neutral-900 tabular-nums">
              {formatMoney(composition.remainder)}
            </span>
          </div>
        )}

        <div className="flex items-baseline justify-between gap-3 border-t border-neutral-200 pt-1.5">
          <span className="text-neutral-500">订单金额</span>
          <span
            data-testid="fee-breakdown-order-total"
            className="text-neutral-900 font-semibold tabular-nums"
          >
            {composition.orderTotal === null ? '—' : formatMoney(composition.orderTotal)}
          </span>
        </div>
      </div>

      <div data-testid="fee-breakdown-equation" className="mt-2 text-xs text-neutral-500 tabular-nums">
        {equation}
      </div>

      {composition.unpricedCount > 0 && (
        <div
          data-testid="fee-breakdown-unpriced"
          className="mt-2 rounded bg-amber-50 px-2.5 py-1.5 text-xs text-amber-700"
        >
          有 {composition.unpricedCount} 行加工费未定价（{composition.unpricedLabels.join('、')}）
          —— 这些行按 0 计入订单金额，请到「加工费组合」定价后再核对
        </div>
      )}
    </div>
  )
}

/**
 * 一行加工费。
 *
 * 🔴 **未定价那格写文字、不写钱**：`¥0.00` 与「这一行本来就不收加工费」长得一模一样
 * ⇒ 写「未定价 · 组合名」（组合名口径 = 新增订单页的 `unpricedCombinationLabel`）。
 */
function FeeLine({ line }: { line: OrderFeeLine }) {
  return (
    <div
      data-testid="fee-breakdown-line"
      className="flex items-baseline justify-between gap-3 pl-3 text-xs"
    >
      <span className="min-w-0 text-neutral-500">
        <span className="text-neutral-600">{line.label}</span>
        {line.unpriced && (
          <span className="ml-1.5 font-medium text-amber-600">
            未定价{line.unpricedLabel ? ` · ${line.unpricedLabel}` : ''}
          </span>
        )}
        {line.manual && <span className="ml-1.5 text-amber-600">人工改价</span>}
      </span>
      <span className="whitespace-nowrap text-neutral-700 tabular-nums">
        {/* 算式（缺单价 / 米数 ⇒ 不编）；未定价那半按 0 计 ⇒ **不写钱** */}
        {line.expr ?? (line.unpriced ? '' : formatMoney(line.amount))}
      </span>
    </div>
  )
}
