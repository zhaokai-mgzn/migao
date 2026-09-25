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
 *
 * 多选模式（`data.multiSelect === true`，批量建品/批量改商品勾选，issue #3947）：
 * 点击选项只**本地勾选累积**（不提交、不锁卡），「完成选择（N）」一次性回传
 * `${multiSelectSubmitPrefix}${已选名称、拼接}` —— 与 admin-web
 * `frontend/admin-web/src/components/chat/InteractiveMessage.tsx` 同一协议
 * （前端单一事实源），AI 侧 `backend/ai-agent-service/app/graph/nodes.py` 的
 * `_card_accepts_answer` 正是按 `multiSelectSubmitPrefix` 前缀识别这张卡的答卡轮。
 * 跳过按钮**只在卡自带 `multiSelectSkipLabel` 时渲染**（AI 侧的跳过文案取自**卡自身**
 * 的该字段，凭空发默认文案会让答卡轮失配）。
 * 单选模式（无 `multiSelect`）：点击即提交 `opt.value` 并锁卡（原行为，CH-030 不回归）。
 */
export default function ChoiceCard({ data, onAction, disabled }: ChoiceCardProps) {
  const options = data.options || []
  const pageMeta = data.pageMeta
  const hasPaging = !!pageMeta && (pageMeta.total || 0) > 0
  // 提交锁：点击选项/翻页后锁卡，防重复提交（issue #3038 CH-030）
  const [submitted, setSubmitted] = useState(false)
  // 多选勾选态（issue #3947）：只本地累积，点「完成选择」才一次性提交
  const [selected, setSelected] = useState<string[]>([])
  const locked = disabled || submitted

  const isMultiSelect = data.multiSelect === true
  const submitPrefix = data.multiSelectSubmitPrefix || '已选加工项：'
  const submitLabel = data.multiSelectSubmitLabel || '完成选择'
  const skipLabel = data.multiSelectSkipLabel

  /** 多选回传文本：人话 label 优先（与 admin-web 多选提交口径一致，AI 侧期望「名称列表」） */
  const optionText = (opt: { label?: string; value: string }) => opt.label || opt.value

  const clickOption = (opt: { label?: string; value: string }) => {
    if (locked) return
    if (isMultiSelect) {
      // 多选：仅本地勾选/取消，不触发 onAction（不惊动 agent 逐条回复）
      const text = optionText(opt)
      setSelected(prev => (prev.includes(text) ? prev.filter(x => x !== text) : [...prev, text]))
      return
    }
    setSubmitted(true)
    onAction(opt.value)
  }

  const submitSelections = () => {
    if (locked || selected.length === 0) return
    setSubmitted(true)
    onAction(`${submitPrefix}${selected.join('、')}`)
  }

  const skipSelections = () => {
    if (locked || !skipLabel) return
    setSubmitted(true)
    onAction(skipLabel)
  }

  // 翻页：构造下一/上一页指令文本回传（多选卡同样保留翻页控件）
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
        {options.map((opt, idx) => {
          const isSelected = isMultiSelect && selected.includes(optionText(opt))
          return (
            <View
              key={`co-${idx}`}
              className={`choice-card__option${locked ? ' choice-card__option--locked' : ''}${isSelected ? ' choice-card__option--selected' : ''}`}
              onClick={() => clickOption(opt)}
              hoverClass={locked ? undefined : 'choice-card__option--hover'}
            >
              <View className='choice-card__option-main'>
                <Text className='choice-card__option-label'>{opt.label}</Text>
                {opt.description && (
                  <Text className='choice-card__option-desc'>{opt.description}</Text>
                )}
              </View>
              <Text className='choice-card__option-arrow'>{isSelected ? '✓' : '›'}</Text>
            </View>
          )
        })}
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

      {/* 多选提交/跳过（issue #3947）：未勾选任何项时不渲染提交按钮（不给空的提交） */}
      {isMultiSelect && !locked && (selected.length > 0 || !!skipLabel) && (
        <View className='choice-card__actions'>
          {selected.length > 0 && (
            <View className='choice-card__submit' onClick={submitSelections}>
              <Text className='choice-card__submit-text'>{`${submitLabel}（${selected.length}）`}</Text>
            </View>
          )}
          {!!skipLabel && (
            <View className='choice-card__skip' onClick={skipSelections}>
              <Text className='choice-card__skip-text'>{skipLabel}</Text>
            </View>
          )}
        </View>
      )}
    </View>
  )
}