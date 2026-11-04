/**
 * AI 生成内容**常驻**提示（微信「深度合成 → AI问答」类目备注 + 《人工智能生成合成内容标识办法》2025-09-01）
 *
 * 为什么单独一个组件：这句话必须**常驻**在对话页（不随消息滚动消失），
 * 且要和气泡上的逐条角标分开承载 —— 气泡角标证明「这条是 AI 说的」，
 * 这句证明「本页内容由 AI 生成，仅供参考」。两处口径都来自同一处实现，避免各写一份文案。
 *
 * 判据：frontend/bmini-app/tests/chat-ai-generated-label.test.tsx
 */
import { View, Text } from '@tarojs/components'
import './AiGeneratedNote.scss'

export default function AiGeneratedNote() {
  return (
    <View className='ai-generated-note' data-testid='ai-generated-disclaimer'>
      <Text className='ai-generated-note__text'>内容由人工智能生成，仅供参考</Text>
    </View>
  )
}
