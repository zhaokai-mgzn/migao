'use client'

/**
 * 订单详情页「商品明细」—— **只读展示**（issue #4426 · 设计文档 §4.9 ②）。
 *
 * 用户 2026-09-19 口径：「新增订单有交互设计，而**订单详情页面只读展示**，可以另外设计」。
 * 本组件**不引入任何编辑入口**（订单行编辑是另一个议题，见 `processing-order-design.md` 决策 6）。
 *
 * ── 展示重构（issue #4426，用户「信息偏多，不能全部挤在一块区域」）──
 *
 * 外壳仍是可横向扫读的表（多行明细要对齐比价），改的是**单元格内的信息层次**：
 * ① **尺寸独立成行并加重**：宽 / 高是用料与加工单的复核依据（§5.9.3「不可推导的原始输入」），
 *    此前只是 12px 灰字行内的一项，现在单独一行、字号与字重都提上来；
 * ② **工艺规格 / 算料口径 分成两组**（§5.9.3 的「原始输入 vs 算料输出」）：一组 label/value 网格，
 *    不再 16 行竖排；
 * ③ **非工艺键的原始键值兜底行收进折叠区**：`edgeType` / `quantity` 这类**内部键名**
 *    不该摊在首屏给商家看；
 * ④ **小计带算式**：`5 × ¥100.00 + 加工 ¥50.00` —— 商家能对上报价单与加工单。
 *
 * 两条硬约束（§4.9，沿用未改）：
 * 1. **缺值不渲染**：键缺席 / `null` / 空串 ⇒ 该行不出现；绝不渲染 `undefined`/`null`/`NaN`；
 * 2. **只做展示**：不推导金额、不加价（展示映射的单一真值是 `lib/craft-display.ts`，不另写一份）。
 */

import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { craftSpecRows, isCraftSpecKey, type CraftSpecRow } from '@/lib/craft-display'
import type { OrderItem } from '@/types'

interface OrderItemListProps {
  items: OrderItem[]
  className?: string
}

function formatAmount(amount: number): string {
  return `¥${amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

const sellingMethodLabel: Record<string, string> = {
  bulk_cut: '散剪',
  full_roll: '整卷',
  per_meter: '按米',
  per_piece: '按件',
}

/**
 * **算料输出**行的标签（§5.9.3 表右列）—— 与「原始输入」分开展示。
 *
 * 为什么分两组：输入丢了永远拿不回来、输出可重算；商家核对时看的是两组不同的东西
 * （「我报的宽高对不对」vs「系统算的折数用料对不对」）。混在一列 16 行里两组都读不出来。
 */
const CALC_OUTPUT_LABELS = new Set([
  '总褶数',
  '折数（每片）',
  '幅数',
  '理论褶倍',
  '实际褶倍',
  '面料米数',
  '加工费米数',
])

/**
 * 加工费构成（后端 #4406 落库 → 本组件**只展示**，不重算）。
 *
 * 键名是 **snake_case**（设计文档 §4.5：算料/计价输出键与 `CALC_INFO_KEYS` 同口径）。
 * `fee_source` 三态：`matched` 命中组合 / `unpriced` 未定价 / `manual` 人工改价。
 */
export interface ProcessingFeeDetail {
  /** 参与计价的选配特征集合（组合键） */
  composition?: string
  unit_price?: number
  meters?: number
  meters_source?: string
  fee_source?: string
  amount?: number
  /** 未定价时的可行动提示（后端给） */
  hint?: string
}

/** 取有限数值（容忍 JSON 里以字符串承载的数字）；其余 ⇒ `null` */
function numericOrNull(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

/** 从 `processingInfo` 取加工费构成；缺席 / 形态不对 ⇒ `null`（存量单：接线前生成，无该键） */
export function readFeeDetail(info: unknown): ProcessingFeeDetail | null {
  if (info === null || typeof info !== 'object' || Array.isArray(info)) return null
  const raw = (info as Record<string, unknown>).processingFeeDetail
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return null
  return raw as ProcessingFeeDetail
}

/**
 * 加工费算式（用户口径：「**窗帘米数 × 组合加工费 = 具体费用**」）。
 *
 * **缺单价或米数 ⇒ 不编算式**（返回 `null`）：宁可只显示金额，
 * 也不给商家一个对不上的算式（那比不显示更糟 —— 商家会照着它去核账）。
 */
export function feeFormula(detail: ProcessingFeeDetail | null): string | null {
  if (!detail) return null
  const meters = numericOrNull(detail.meters)
  const unit = numericOrNull(detail.unit_price)
  if (meters === null || unit === null) return null
  const amount = numericOrNull(detail.amount)
  const left = `${meters} 米 × ${formatAmount(unit)}/米`
  return amount === null ? left : `${left} = ${formatAmount(amount)}`
}

/**
 * 未定价（`fee_source=unpriced`）。
 *
 * 为什么单独判它：未定价时后端按用户裁定给 **0 元**，而 `¥0.00` 与「这一行本来就不收加工费」
 * **长得一模一样** ⇒ 必须显式标「未定价」，否则就是静默改钱的外观。
 */
export function isUnpriced(detail: ProcessingFeeDetail | null): boolean {
  return detail?.fee_source === 'unpriced'
}

/** 一组 label/value 网格（缺值行已由 `craftSpecRows` 丢弃 ⇒ 空组不渲染） */
function SpecGroup({ title, rows }: { title: string; rows: CraftSpecRow[] }) {
  if (rows.length === 0) return null
  return (
    <div>
      <div className="text-xs font-medium text-neutral-500 mb-1.5">{title}</div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1.5">
        {rows.map((row) => (
          <div key={row.label} className="min-w-0">
            <div className="text-xs text-neutral-400">{row.label}</div>
            <div className="text-sm text-neutral-800 break-words">{row.value}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function OrderItemList({ items, className }: OrderItemListProps) {
  const subtotalSum = items.reduce((sum, item) => sum + item.subtotal, 0)
  const processingFeeSum = items.reduce((sum, item) => sum + (item.processingFee || 0), 0)
  const totalAmount = subtotalSum + processingFeeSum
  // 未定价行数（#4406：未定价按用户裁定计 0）—— 合计区必须显式提示，不能让它藏在 0 里
  const unpricedCount = items.filter((it) => isUnpriced(readFeeDetail(it.processingInfo))).length

  return (
    <div className={className}>
      {/* 表头 */}
      <div className="grid grid-cols-12 gap-2 px-4 py-2.5 bg-neutral-50 rounded-t-lg text-xs font-semibold text-neutral-500 uppercase">
        <div className="col-span-4">商品信息</div>
        <div className="col-span-2 text-center">数量</div>
        <div className="col-span-2 text-right">单价</div>
        <div className="col-span-2 text-right">加工费</div>
        <div className="col-span-2 text-right">小计</div>
      </div>

      {/* 明细行 */}
      <div className="divide-y divide-neutral-100">
        {items.map((item, index) => (
          <ItemRow key={item.id || index} item={item} />
        ))}
      </div>

      {/* 合计 */}
      <div className="border-t border-neutral-200 px-4 py-3 space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-neutral-500">商品金额</span>
          <span className="text-neutral-700">{formatAmount(subtotalSum)}</span>
        </div>
        {processingFeeSum > 0 && (
          <div className="flex justify-between text-sm">
            <span className="text-neutral-500">加工费合计</span>
            <span className="text-amber-600">{formatAmount(processingFeeSum)}</span>
          </div>
        )}
        {unpricedCount > 0 && (
          <div className="rounded bg-amber-50 px-2.5 py-1.5 text-xs text-amber-700">
            有 {unpricedCount} 行加工费未定价 —— 这些行按 0 计入订单金额，
            请到「加工费组合」定价后再核对
          </div>
        )}
        <div className="flex justify-between text-base font-semibold pt-2 border-t border-neutral-100">
          <span className="text-neutral-900">订单总金额</span>
          <span className="text-primary-600">{formatAmount(totalAmount)}</span>
        </div>
      </div>
    </div>
  )
}

function ItemRow({ item }: { item: OrderItem }) {
  // 非工艺键的原始键值兜底行（内部键名）默认收起 —— issue #4426
  const [otherOpen, setOtherOpen] = useState(false)

  const specRows = craftSpecRows(item.processingInfo)
  // 工艺键已由规格块按标签展示 ⇒ 兜底行只留非工艺键（同一真值不重复展示）
  const otherEntries = Object.entries(item.processingInfo ?? {}).filter(
    ([key]) => !isCraftSpecKey(key)
  )
  const craftRows = specRows.filter((row) => !CALC_OUTPUT_LABELS.has(row.label))
  const calcRows = specRows.filter((row) => CALC_OUTPUT_LABELS.has(row.label))

  const info = (item.processingInfo ?? {}) as Record<string, unknown>
  const colorName = typeof info.colorName === 'string' ? info.colorName : undefined
  const sellingMethod =
    typeof info.sellingMethod === 'string'
      ? sellingMethodLabel[info.sellingMethod] || info.sellingMethod
      : undefined
  const doorWidth = typeof info.doorWidth === 'string' ? info.doorWidth : undefined

  const processingFee = item.processingFee || 0
  // 加工费构成（#4406）：只展示服务端已算好的数，**不重算**
  const feeDetail = readFeeDetail(item.processingInfo)
  const feeExpr = feeFormula(feeDetail)
  const unpriced = isUnpriced(feeDetail)

  return (
    <div className="grid grid-cols-12 gap-2 px-4 py-3 items-start">
      <div className="col-span-4">
        <div className="font-medium text-neutral-900 text-sm">{item.productName}</div>

        {/* 尺寸：独立成行 + 加重（issue #4426）—— 用料与加工单的复核依据 */}
        {(item.width || item.height) && (
          <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            {item.width ? (
              <span className="text-sm font-semibold text-neutral-900 tabular-nums">
                宽: {item.width}m
              </span>
            ) : null}
            {item.height ? (
              <span className="text-sm font-semibold text-neutral-900 tabular-nums">
                高: {item.height}m
              </span>
            ) : null}
          </div>
        )}

        <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1">
          {item.sku && <span className="text-xs text-neutral-400">SKU: {item.sku}</span>}
          {/* 销售信息：颜色、销售方式、门幅 */}
          {colorName && (
            <span className="text-xs text-primary-600 font-medium">{colorName}</span>
          )}
          {sellingMethod && <span className="text-xs text-neutral-400">{sellingMethod}</span>}
          {doorWidth && <span className="text-xs text-neutral-400">门幅: {doorWidth}</span>}
          {item.specification && (
            <span className="text-xs text-neutral-400">规格: {item.specification}</span>
          )}
        </div>

        {/* 工艺规格 + 算料口径：分两组（§5.9.3 输入 / 输出）—— 无任何工艺键时整块不出现 */}
        {specRows.length > 0 && (
          <div className="mt-2.5 space-y-2.5 rounded-lg bg-neutral-50/70 px-3 py-2.5">
            <SpecGroup title="工艺规格" rows={craftRows} />
            <SpecGroup title="算料口径" rows={calcRows} />
          </div>
        )}

        {/* 其它字段（非工艺键的原始键值）—— 内部键名不该占首屏，默认收起 */}
        {otherEntries.length > 0 && (
          <div className="mt-2">
            <button
              type="button"
              onClick={() => setOtherOpen((v) => !v)}
              aria-expanded={otherOpen}
              className="inline-flex items-center gap-1 text-xs text-neutral-400 hover:text-neutral-600 transition-colors"
            >
              {otherOpen ? (
                <ChevronDown className="w-3.5 h-3.5" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5" />
              )}
              其它字段（{otherEntries.length}）
            </button>
            {otherOpen && (
              <div className="mt-1 text-xs text-amber-600">
                加工: {otherEntries.map(([k, v]) => `${k}: ${v}`).join(', ')}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="col-span-2 text-center text-sm text-neutral-700">×{item.quantity}</div>
      <div className="col-span-2 text-right text-sm text-neutral-700">
        {formatAmount(item.unitPrice)}
      </div>
      <div className="col-span-2 text-right">
        {unpriced ? (
          <>
            {/* 未定价必须显式：`¥0.00` 与「本来就不收加工费」长得一样 ⇒ 不标就是静默改钱的外观 */}
            <div className="text-sm font-medium text-amber-600">未定价</div>
            {feeDetail?.hint && (
              <div className="mt-0.5 text-xs text-amber-600 break-words">{feeDetail.hint}</div>
            )}
          </>
        ) : (
          <>
            <div className="text-sm text-neutral-500">
              {processingFee ? formatAmount(processingFee) : '-'}
            </div>
            {/* 算式（issue #4444，用户口径「米数 × 组合加工费 = 具体费用」）—— 缺值不编 */}
            {feeExpr && (
              <div className="mt-0.5 text-xs text-neutral-400 tabular-nums break-words">
                {feeExpr}
              </div>
            )}
            {feeDetail?.fee_source === 'manual' && (
              <div className="mt-0.5 text-xs text-amber-600">人工改价</div>
            )}
          </>
        )}
      </div>
      <div className="col-span-2 text-right">
        <div className="text-sm font-medium text-neutral-900">
          {formatAmount(item.subtotal + processingFee)}
        </div>
        {/* 算式（issue #4426）：商家据此对上报价单与加工单 */}
        <div className="mt-0.5 text-xs text-neutral-400 tabular-nums">
          {item.quantity} × {formatAmount(item.unitPrice)}
          {processingFee > 0 ? ` + 加工 ${formatAmount(processingFee)}` : ''}
        </div>
      </div>
    </div>
  )
}
