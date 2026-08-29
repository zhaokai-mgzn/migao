import { View, Text } from '@tarojs/components'
import type { InteractiveData } from '../../types'
import './ConfirmCard.scss'

interface ConfirmCardProps {
  data: InteractiveData
  onAction: (value: string) => void
}

/** 确认卡片：展示待确认信息 + 确认/取消按钮（interact confirm 组件） */
export default function ConfirmCard({ data, onAction }: ConfirmCardProps) {
  const fields = data.fields || []
  const confirmLabel = data.confirmLabel || '确认'
  const cancelLabel = data.cancelLabel || '取消'
  const confirmValue = data.confirmValue || '确认'
  const cancelValue = data.cancelValue || '取消'

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

      <View className='confirm-card__actions'>
        <View
          className='confirm-card__btn confirm-card__btn--cancel'
          onClick={() => onAction(cancelValue)}
        >
          <Text className='confirm-card__btn-text'>{cancelLabel}</Text>
        </View>
        <View
          className='confirm-card__btn confirm-card__btn--confirm'
          onClick={() => onAction(confirmValue)}
        >
          <Text className='confirm-card__btn-text confirm-card__btn-text--confirm'>
            {confirmLabel}
          </Text>
        </View>
      </View>
    </View>
  )
}
