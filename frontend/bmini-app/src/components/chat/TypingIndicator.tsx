import { View, Text } from '@tarojs/components'
import './TypingIndicator.scss'

interface TypingIndicatorProps {
  text?: string
}

/** 默认文案用 **B 端** agent 名（「米宝」；C 端才默认「小布」，见 `src/utils/brand.ts`）—— issue #5747 */
export default function TypingIndicator({ text = '米宝正在思考...' }: TypingIndicatorProps) {
  return (
    <View className='typing-indicator'>
      <View className='typing-indicator__bubble'>
        <View className='typing-indicator__dots'>
          <View className='typing-indicator__dot' />
          <View className='typing-indicator__dot' />
          <View className='typing-indicator__dot' />
        </View>
        <Text className='typing-indicator__text'>{text}</Text>
      </View>
    </View>
  )
}
