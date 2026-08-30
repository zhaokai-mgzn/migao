import { useEffect, useRef, useCallback } from 'react'
import { View, ScrollView, Text } from '@tarojs/components'
import type { Message } from '../../types'
import MessageBubble from './MessageBubble'
import TypingIndicator from './TypingIndicator'
import './MessageList.scss'

interface MessageListProps {
  messages: Message[]
  isStreaming: boolean
  onInteract?: (value: string) => void
}

export default function MessageList({ messages, isStreaming, onInteract }: MessageListProps) {
  const scrollAnchorId = 'msg-anchor'
  const scrollTopRef = useRef(0)
  const scrollIntoViewRef = useRef(scrollAnchorId)
  // 使用一个计数器强制 scrollIntoView 更新
  const counterRef = useRef(0)

  // 检查是否需要显示思考中动画：正在流式但最后一条 AI 消息还没有内容
  const showTyping = isStreaming && (() => {
    const lastMsg = messages[messages.length - 1]
    return lastMsg?.role === 'assistant' && !lastMsg.content && !(lastMsg.tool_calls?.length)
  })()

  const scrollToBottom = useCallback(() => {
    counterRef.current += 1
    // 通过改变 scrollIntoView 的值触发滚动
    scrollIntoViewRef.current = scrollAnchorId
  }, [])

  // 消息变化时滚动到底部
  useEffect(() => {
    scrollToBottom()
  }, [messages.length, isStreaming, scrollToBottom])

  // 流式内容更新时也滚动（通过监听最后一条消息的内容长度）
  const lastMsgContentLen = messages.length > 0 ? messages[messages.length - 1]?.content?.length || 0 : 0
  useEffect(() => {
    if (isStreaming) {
      scrollToBottom()
    }
  }, [lastMsgContentLen, isStreaming, scrollToBottom])

  if (messages.length === 0 && !isStreaming) {
    return (
      <View className='message-list'>
        <View className='message-list__empty'>
          <View className='message-list__empty-brand'>
            <Text className='message-list__empty-brand-text'>布</Text>
          </View>
          <Text className='message-list__empty-title'>你好，我是小布</Text>
          <Text className='message-list__empty-text'>
            你的专属智能购物助手{'\n'}查订单、找产品、了解窗帘知识，都可以问我
          </Text>
        </View>
      </View>
    )
  }

  return (
    <View className='message-list'>
      <ScrollView
        className='message-list__scroll'
        scrollY
        scrollIntoView={scrollAnchorId}
        scrollWithAnimation
        enhanced
        showScrollbar={false}
      >
        <View className='message-list__content'>
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} onInteract={onInteract} />
          ))}

          {/* 思考中动画 */}
          {showTyping && <TypingIndicator />}

          {/* 滚动锚点 */}
          <View id={scrollAnchorId} className='message-list__anchor' />
        </View>
      </ScrollView>
    </View>
  )
}
