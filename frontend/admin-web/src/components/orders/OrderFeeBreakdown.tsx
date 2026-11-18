'use client'

/**
 * 订单详情页「费用明细」（issue #5843 → issue #8896 改版）—— **只读展示**，数全部来自**落库快照**。
 *
 * 2026-10-01 用户报障：`商品合计 ¥245.14` 与 `订单金额 ¥368.74` 之间那笔 **¥123.60 加工费**
 * 在页面上任何位置都不出现 ⇒ 商家看到两个数对不上。当时的修法是补一块「费用构成」等式。
 *
 * 2026-11-11 用户追加口径（issue #8896）：
 * > 商品信息顶部有「订单实付款」，商品明细下面又有「费用构成」，底部又有「订单金额」「优惠金额」
 * > 「实收款」，这个地方信息重复排版混乱，你把商品费用明细相关的这些字段整理一下重新排版展示，
 * > 要求简单清晰明了，一眼可以看出商品费用明细。
 *
 * ⇒ 本组件现在是商品信息里**唯一**的金额面：卡头「订单实收款」与底部横向汇总行都撤掉，
 * 合成一张「费用明细」：
 * ```
 * 商品合计 → 加工费（含逐行算式 / 未定价）→ 其它构成
 * ─────────────────────────────
 * 订单金额
 * 优惠金额（>0 才出现） / 已退款（>0 才出现，带退款时间）
 * ─────────────────────────────
 * 实收款
 * ```
 * 硬口径不变（与 `lib/order-fee-display.ts` 同源）：
 * 1. **只展示、不重算**：加工费合计 = Σ 落库 `items[].processingFee`；行级算式只是复述
 *    服务端的 `processingFeeDetail` —— 详情页是**落库快照**面，与新增订单页的试算预览是两回事；
 * 2. **未定价不渲染 `¥0.00`**：那半按 0 计 ⇒ 显式标「未定价」并点名组合（那格写文字，不写钱）；
 * 3. **布料单不出现加工费空行 / `¥0.00` 行**：没有加工是正常、不是缺失；但商品合计 /
 *    订单金额 / 实收款仍要显示（费用明细是唯一金额面）；
 * 4. **零值不占行**：优惠金额 / 已退款为 0 时不渲染（与既有「已退款」口径一致）。
 *
 * ⚠️ 判定与渲染分离：所有「该不该显示、显示多少」都在 `buildOrderFeeComposition` 里，
 * 本文件只做 JSX。
 */

import DateTimeCell from '@/components/common/DateTimeCell'
import { buildOrderFeeComposition, formatMoney, type OrderFeeLine } from '@/lib/order-fee-display'
import { cn } from '@/lib/utils'
import type { OrderItem } from '@/types'

interface OrderFeeBreakdownProps {
  items: OrderItem[]
  /** 商品合计（元）= 页面上「商品合计」列之和（调用方按**同一份**行金额口径算好传入） */
  goodsTotal: number
  /** 订单金额（服务端 `order.totalAmount`；未取到 ⇒ `null` ⇒ 不编差额） */
  orderTotal?: number | null
  /** 优惠金额（服务端 `order.discountAmount`；缺省 0；>0 才占行） */
  discountAmount?: number
  /** 已退款（服务端 `order.refundAmount`；>0 才占行） */
  refundAmount?: number
  refundAt?: string
  /** 实收款（服务端 `order.actualAmount`；页面必须传，组件缺省时不渲染该行） */
  actualAmount?: number | null
  className?: string
}

export default function OrderFeeBreakdown({
  items,
  goodsTotal,
  orderTotal,
  discountAmount,
  refundAmount,
  refundAt,
  actualAmount,
  className,
}: OrderFeeBreakdownProps) {
  const composition = buildOrderFeeComposition(items, { goodsTotal, orderTotal })
  // 没有商品也没有订单金额 ⇒ 没有费用可读（页面另有「暂无商品」空态）
  if (items.length === 0 && orderTotal == null) return null

  const discount = discountAmount ?? 0
  const refunded = (refundAmount ?? 0) > 0
  // 等式只在「有构成可解释」时出现：布料单只有商品合计=订单金额，再印一行等式就是噪音
  const showCompositionEquation =
    composition.showProcessingFee || composition.showRemainder || composition.unpricedCount > 0

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
        'mt-4 rounded-lg border border-neutral-200 bg-neutral-50/60 px-4 py-3.5',
        className
      )}
    >
      <div className="text-sm font-semibold text-neutral-700">费用明细</div>

      <div className="mt-2 text-sm">
        <FeeRow
          label="商品合计"
          testId="fee-breakdown-goods"
          value={formatMoney(composition.goodsTotal)}
        />

        {composition.showProcessingFee && (
          <FeeRow
            label="加工费"
            testId="fee-breakdown-processing"
            value={formatMoney(composition.processingFeeTotal)}
            valueClass="font-medium text-amber-700"
          />
        )}

        {/* 逐行加工费（只列**有这笔钱**的行与**未定价**行）—— 商家据此对上加工单 */}
        {composition.lines.map((line) => (
          <FeeLine key={line.key} line={line} />
        ))}

        {composition.showRemainder && (
          <FeeRow
            label="其它构成"
            testId="fee-breakdown-other"
            value={formatMoney(composition.remainder)}
          />
        )}

        <div className="my-1.5 border-t border-neutral-200" />
        <FeeRow
          label="订单金额"
          testId="fee-breakdown-order-total"
          strong
          value={composition.orderTotal === null ? '—' : formatMoney(composition.orderTotal)}
        />

        {discount > 0 && (
          <FeeRow
            label="优惠金额"
            testId="fee-breakdown-discount"
            value={`-${formatMoney(discount)}`}
            valueClass="text-green-600"
          />
        )}

        {refunded && (
          <FeeRow
            label="已退款"
            testId="fee-breakdown-refund"
            value={
              <>
                {formatMoney(refundAmount ?? 0)}
                {refundAt && (
                  <span className="ml-1.5 text-xs font-normal text-neutral-400">
                    (<DateTimeCell value={refundAt} inline />)
                  </span>
                )}
              </>
            }
            valueClass="text-red-600"
          />
        )}

        {actualAmount != null && (
          <>
            <div className="my-1.5 border-t border-neutral-200" />
            <FeeRow
              label="实收款"
              testId="fee-breakdown-actual"
              labelClass="font-medium text-neutral-700"
              value={formatMoney(actualAmount)}
              valueClass="text-base font-semibold text-primary-600"
            />
          </>
        )}
      </div>

      {showCompositionEquation && (
        <div
          data-testid="fee-breakdown-equation"
          className="mt-2 text-xs text-neutral-500 tabular-nums"
        >
          {equation}
        </div>
      )}

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

/** 一行费用读数：左标签 / 右金额（金额列 nowrap，避免折行）。 */
function FeeRow({
  label,
  value,
  testId,
  labelClass,
  valueClass,
  strong,
}: {
  label: string
  value: React.ReactNode
  testId: string
  labelClass?: string
  valueClass?: string
  strong?: boolean
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5">
      <span className={cn('text-neutral-500', labelClass)}>{label}</span>
      <span
        data-testid={testId}
        className={cn(
          'whitespace-nowrap text-right tabular-nums text-neutral-900',
          strong && 'font-semibold',
          valueClass
        )}
      >
        {value}
      </span>
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
      className="flex items-baseline justify-between gap-3 py-1 pl-3 text-xs"
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
