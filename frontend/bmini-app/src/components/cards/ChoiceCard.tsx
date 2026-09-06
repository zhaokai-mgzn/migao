import { View, Text } from '@tarojs/components'
import type { InteractiveData } from '../../types'
import './ChoiceCard.scss'

interface ChoiceCardProps {
  data: InteractiveData
  onAction: (value: string) => void
}

/**
 * 选择卡片：展示可选项列表 + 翻页控件（interact choice 组件）
 *
 * 用于翻页查询场景（查订单/商品列表）：用户点击选项或翻页按钮，
 * 以可读文本形式回传给 AI 继续处理。
 */
export default function ChoiceCard({ data, onAction }: ChoiceCardProps) {
  const options = data.options || []
  const pageMeta = data.pageMeta
  const hasPaging = !!pageMeta && (pageMeta.total || 0) > 0

  // 翻页：构造下一/上一页指令文本回传
  const handlePrev = () => {
    if (!pageMeta || pageMeta.current <= 1) return
    onAction(`上一页（${pageMeta.current - 1}）`)
  }

  const handleNext = () => {
    if (!pageMeta || pageMeta.current >= pageMeta.total) return
    onAction(`下一页（${pageMeta.current + 1}）`)
  }

  const isLastPage = pageMeta ? pageMeta.current >= pageMeta.total : true

  return (
    <View className='choice-card'>
      <Text className='choice-card__title'>{data.title}</Text>

      <View className='choice-card__options'>
        {options.map((opt, idx) => (
          <View
            key={`co-${idx}`}
            className='choice-card__option'
            onClick={() => onAction(opt.value)}
            hoverClass='choice-card__option--hover'
          >
            <View className='choice-card__option-main'>
              <Text className='choice-card__option-label'>{opt.label}</Text>
              {opt.description && (
                <Text className='choice-card__option-desc'>{opt.description}</Text>
              )}
            </View>
            <Text className='choice-card__option-arrow'>›</Text>
          </View>
        ))}
      </View>

      {hasPaging && (
        <View className='choice-card__paging'>
          <View
            className={`choice-card__page-btn${pageMeta.current <= 1 ? ' choice-card__page-btn--disabled' : ''}`}
            onClick={handlePrev}
          >
            <Text className='choice-card__page-btn-text'>上一页</Text>
          </View>
          <Text className='choice-card__page-indicator'>
            {pageMeta.current}/{pageMeta.total}
          </Text>
          <View
            className={`choice-card__page-btn${isLastPage ? ' choice-card__page-btn--disabled' : ''}`}
            onClick={handleNext}
          >
            <Text className='choice-card__page-btn-text'>下一页</Text>
          </View>
        </View>
      )}
    </View>
  )
}
