import { View, Text } from '@tarojs/components'
import './TypingIndicator.scss'

interface TypingIndicatorProps {
  text?: string
}

export default function TypingIndicator({ text = 'AI 正在思考...' }: TypingIndicatorProps) {
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
