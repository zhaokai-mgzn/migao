import { View, Text } from '@tarojs/components'
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
  warning?: string
}

interface QuotationCardProps {
  data: QuoteData
  onConfirm?: () => void
}

export default function QuotationCard({ data, onConfirm }: QuotationCardProps) {
  const breakdown = data.breakdown || []

  return (
    <View className='quotation-card'>
      <View className='quotation-card__header'>
        <Text className='quotation-card__header-title'>📐 窗帘报价单</Text>
        {data.fullness != null && (
          <Text className='quotation-card__header-sub'>
            {data.fullness} 倍褶皱 · {data.fabric_meters} 米面料
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
          <View className='quotation-card__btn quotation-card__btn--primary' onClick={onConfirm}>
            <Text className='quotation-card__btn-text'>确认下单</Text>
          </View>
        </View>
      )}
    </View>
  )
}
