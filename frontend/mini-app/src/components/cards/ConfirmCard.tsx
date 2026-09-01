import { useMemo, useState } from 'react'
import { View, Text } from '@tarojs/components'
import type { InteractiveData } from '../../types'
import './ConfirmCard.scss'

interface ConfirmCardProps {
  data: InteractiveData
  onAction: (value: string) => void
}

/** 确认卡片：展示待确认信息 + 确认/取消按钮（interact confirm 组件）
 *
 * orderConfirm=true 时（订单确认）额外渲染瑞幸式配送方式(自提/外送)分段开关 +
 * 支付方式选择 + 应付金额；确认时把选中值拼到 confirmValue 一并回传，
 * 供 LLM 带入下单流程。
 */
export default function ConfirmCard({ data, onAction }: ConfirmCardProps) {
  const fields = data.fields || []
  const confirmLabel = data.confirmLabel || '确认'
  const cancelLabel = data.cancelLabel || '取消'
  const confirmValue = data.confirmValue || '确认'
  const cancelValue = data.cancelValue || '取消'

  const deliveryOptions = data.deliveryOptions || []
  const paymentOptions = data.paymentOptions || []

  // 默认选中第一项
  const [delivery, setDelivery] = useState<string>(deliveryOptions[0]?.value || '')
  const [payment, setPayment] = useState<string>(paymentOptions[0]?.value || '')

  const isOrderConfirm = data.orderConfirm === true

  const handleConfirm = () => {
    let value = confirmValue
    if (isOrderConfirm) {
      const extras: string[] = []
      if (delivery) extras.push(delivery)
      if (payment) extras.push(payment)
      if (extras.length > 0) value = `${confirmValue}（${extras.join('·')}）`
    }
    onAction(value)
  }

  const handleCancel = () => {
    onAction(cancelValue)
  }

  const renderOrderMeta = useMemo(() => {
    if (!isOrderConfirm) return null
    return (
      <View className='confirm-card__order-meta'>
        {deliveryOptions.length > 0 && (
          <View className='confirm-card__seg'>
            <Text className='confirm-card__meta-label'>取餐方式</Text>
            <View className='confirm-card__seg-row'>
              {deliveryOptions.map(opt => (
                <View
                  key={opt.value}
                  className={`confirm-card__seg-item${delivery === opt.value ? ' confirm-card__seg-item--active' : ''}`}
                  onClick={() => setDelivery(opt.value)}
                >
                  <Text className='confirm-card__seg-text'>{opt.label}</Text>
                </View>
              ))}
            </View>
          </View>
        )}

        {paymentOptions.length > 0 && (
          <View className='confirm-card__payment'>
            <Text className='confirm-card__meta-label'>支付方式</Text>
            <View className='confirm-card__payment-row'>
              {paymentOptions.map(opt => (
                <View
                  key={opt.value}
                  className={`confirm-card__payment-item${payment === opt.value ? ' confirm-card__payment-item--active' : ''}`}
                  onClick={() => setPayment(opt.value)}
                >
                  <Text className='confirm-card__payment-text'>{opt.label}</Text>
                </View>
              ))}
            </View>
          </View>
        )}

        {data.amount && (
          <View className='confirm-card__amount-row'>
            <Text className='confirm-card__amount-label'>应付</Text>
            <Text className='confirm-card__amount-value'>{data.amount}</Text>
          </View>
        )}
      </View>
    )
  }, [isOrderConfirm, deliveryOptions, paymentOptions, delivery, payment, data.amount])

  return (
    <View className='confirm-card'>
      <Text className='confirm-card__title'>{data.title}</Text>

      <View className='confirm-card__fields'>
        {fields.map((field, idx) => (
          <View key={`cf-${idx}`} className='confirm-card__field'>
            <Text className='confirm-card__field-label'>{field.label}</Text>
            <Text className='confirm-card__field-value'>{field.value}</Text>
          </View>
        ))}
      </View>

      {renderOrderMeta}

      <View className='confirm-card__actions'>
        <View
          className='confirm-card__btn confirm-card__btn--cancel'
          onClick={handleCancel}
        >
          <Text className='confirm-card__btn-text'>{cancelLabel}</Text>
        </View>
        <View
          className='confirm-card__btn confirm-card__btn--confirm'
          onClick={handleConfirm}
        >
          <Text className='confirm-card__btn-text confirm-card__btn-text--confirm'>
            {confirmLabel}
          </Text>
        </View>
      </View>
    </View>
  )
}
