import { useState } from 'react'
import { View, Text } from '@tarojs/components'
import { craftSpecRows } from '../../utils/craft-display'
import './QuotationCard.scss'

export interface QuoteBreakdown {
  name: string
  detail: string
  cost: number
}

export interface QuoteData {
  fabric_meters: number
  fabric_cost: number
  processing_cost: number
  accessory_cost: number
  install_cost: number
  total: number
  breakdown?: QuoteBreakdown[]
  formula_used?: string
  fullness?: number
  /**
   * 实际褶倍（= 折数法实际用料 ÷ 窗宽），与 `fullness`（档位/款式**理论**倍数）语义不同：
   * 顾客自报 48 折时理论 2 倍、实际 1.86 倍 ⇒ 展示必须取实际值（issue #4118 ④）。
   * 倍数法报价不含本字段（无「实际反算」这一项）。
   */
  fullness_actual?: number
  warning?: string
  /**
   * 工艺规格（设计文档 §4.9 ①）：**原样**来自 `curtain_calc` 输出对象，报价卡不做推导。
   * 键名 = 算料输出口径（snake_case，§4.5）；缺键/`null` ⇒ 该行不渲染。
   */
  curtain_type?: string | null
  craft?: string | null
  open_count?: number | null
  is_shaped?: boolean | null
  style?: string | null
  special_options?: string[] | null
  pleat_count?: number | null
  per_panel_pleats?: number | null
  pleat_spacing?: number | null
  panels?: number | null
  has_pattern?: boolean | null
  pattern_repeat?: number | null
  processing_meters?: number | null
}

interface QuotationCardProps {
  data: QuoteData
  onConfirm?: () => void
}

/**
 * 头部已展示的字段（issue #4118 ④）：规格块不重复渲染同一真值。
 * 「理论褶倍 / 实际褶倍 / 面料米数」三者已在 header-sub 一行里给出。
 */
const HEADER_LABELS = new Set(['理论褶倍', '实际褶倍', '面料米数'])

export default function QuotationCard({ data, onConfirm }: QuotationCardProps) {
  const breakdown = data.breakdown || []
  // 确认下单防连点锁：点击后锁卡（issue #3040 收尾 #3038，防重复下单）
  const [confirmed, setConfirmed] = useState(false)
  // 实际褶倍与理论值不同（客户自报折数 / 经济档）⇒ 一并标注实际值：
  // 只显示理论值会让顾客以为「2 倍褶皱」就是实际用料比，而实际可能只有 1.86 倍（issue #4118 ④）
  const showActualFullness = data.fullness_actual != null && data.fullness_actual !== data.fullness
  // 工艺规格（issue #4355 / 设计文档 §4.9 ①）：同一份定义（utils/craft-display）渲染，缺值行已丢弃
  const specRows = craftSpecRows(data).filter((row) => !HEADER_LABELS.has(row.label))

  return (
    <View className='quotation-card'>
      <View className='quotation-card__header'>
        <Text className='quotation-card__header-title'>📐 窗帘报价单</Text>
        {data.fullness != null && (
          <Text className='quotation-card__header-sub'>
            {data.fullness} 倍褶皱
            {showActualFullness ? `（实际 ${data.fullness_actual} 倍）` : ''} · {data.fabric_meters} 米面料
          </Text>
        )}
      </View>

      {/* 明细行 */}
      <View className='quotation-card__rows'>
        {breakdown.map((item, idx) => (
          <View key={`quote-${idx}`} className='quotation-card__row'>
            <Text className='quotation-card__row-name'>{item.name}</Text>
            <Text className='quotation-card__row-detail'>{item.detail}</Text>
            <Text className='quotation-card__row-cost'>¥{item.cost.toFixed(2)}</Text>
          </View>
        ))}
      </View>

      {/* 工艺规格（设计文档 §4.9 ①）：无任何工艺键时整块不出现 */}
      {specRows.length > 0 && (
        <View className='quotation-card__spec'>
          <Text className='quotation-card__spec-title'>工艺规格</Text>
          {specRows.map((row) => (
            <View key={row.label} className='quotation-card__spec-row'>
              <Text className='quotation-card__spec-label'>{row.label}</Text>
              <Text className='quotation-card__spec-value'>{row.value}</Text>
            </View>
          ))}
        </View>
      )}

      {/* 告警（窗高超定高上限等） */}
      {data.warning && (
        <View className='quotation-card__warning'>
          <Text className='quotation-card__warning-text'>⚠️ {data.warning}</Text>
        </View>
      )}

      {/* 合计 */}
      <View className='quotation-card__total'>
        <Text className='quotation-card__total-label'>合计</Text>
        <Text className='quotation-card__total-amount'>¥{data.total.toFixed(2)}</Text>
      </View>

      <Text className='quotation-card__note'>* 报价为估算值，最终以到店测量为准</Text>

      {onConfirm && (
        <View className='quotation-card__actions'>
          <View
            className={`quotation-card__btn quotation-card__btn--primary${confirmed ? ' quotation-card__btn--locked' : ''}`}
            onClick={() => {
              if (confirmed || !onConfirm) return
              setConfirmed(true)
              onConfirm()
            }}
          >
            <Text className='quotation-card__btn-text'>确认下单</Text>
          </View>
        </View>
      )}
    </View>
  )
}
