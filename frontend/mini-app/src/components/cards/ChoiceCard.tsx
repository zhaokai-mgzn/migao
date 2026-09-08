import { useState } from 'react'
import { View, Text } from '@tarojs/components'
import type { InteractiveData } from '../../types'
import './ChoiceCard.scss'

interface ChoiceCardProps {
  data: InteractiveData
  onAction: (value: string) => void
  /** 只读（已答复/历史回放）：选项不可点，防重复提交（issue #3038 CH-030） */
  disabled?: boolean
}

/**
 * 选择卡片：展示可选项列表 + 翻页控件（interact choice 组件）
 *
 * 用于翻页查询场景（查订单/商品列表）：用户点击选项或翻页按钮，
 * 以可读文本形式回传给 AI 继续处理。
 */
export default function ChoiceCard({ data, onAction, disabled }: ChoiceCardProps) {
  const options = data.options || []
  const pageMeta = data.pageMeta
  const hasPaging = !!pageMeta && (pageMeta.total || 0) > 0
  // 提交锁：点击选项/翻页后锁卡，防重复提交（issue #3038 CH-030）
  const [submitted, setSubmitted] = useState(false)
  const locked = disabled || submitted

  // 翻页：构造下一/上一页指令文本回传
  const handlePrev = () => {
    if (locked || !pageMeta || pageMeta.current <= 1) return
    setSubmitted(true)
    onAction(`上一页（${pageMeta.current - 1}）`)
  }

  const handleNext = () => {
    if (locked || !pageMeta || pageMeta.current >= pageMeta.total) return
    setSubmitted(true)
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
            className={`choice-card__option${locked ? ' choice-card__option--locked' : ''}`}
            onClick={() => {
              if (locked) return
              setSubmitted(true)
              onAction(opt.value)
            }}
            hoverClass={locked ? undefined : 'choice-card__option--hover'}
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
