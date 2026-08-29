import { View, ScrollView, Text } from '@tarojs/components'
import './SuggestionChips.scss'

interface SuggestionChipsProps {
  questions: string[]
  onAction: (question: string) => void
}

/** 建议追问 chips：AI 回复后出现的后续问题建议 */
export default function SuggestionChips({ questions, onAction }: SuggestionChipsProps) {
  if (!questions || questions.length === 0) return null

  return (
    <ScrollView
      className='suggestion-chips'
      scrollX
      enhanced
      showScrollbar={false}
    >
      <View className='suggestion-chips__inner'>
        {questions.slice(0, 3).map((q, idx) => (
          <View
            key={`sug-${idx}`}
            className='suggestion-chips__item'
            onClick={() => onAction(q)}
          >
            <Text className='suggestion-chips__text'>{q}</Text>
          </View>
        ))}
      </View>
    </ScrollView>
  )
}
