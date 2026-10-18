import { View, ScrollView, Text } from '@tarojs/components'
import type { Message } from '../../types'
import MessageBubble from './MessageBubble'
import TypingIndicator from './TypingIndicator'
import { useAuthStore } from '../../store/authStore'
import { buildBotName } from '../../utils/brand'
import { ANCHORS, useChatFollow } from '../../hooks/use-chat-follow'
import './MessageList.scss'

interface MessageListProps {
  messages: Message[]
  isStreaming: boolean
  onInteract?: (value: string) => void
  /** 对话区滚动位置（issue #7265：页面据此折叠顶部品牌层） */
  onScrollOffset?: (scrollTop: number) => void
}

export default function MessageList({ messages, isStreaming, onInteract, onScrollOffset }: MessageListProps) {
  // UI-018：智能客服名称取自租户配置 botName（B 端未配置默认「黄金策」）
  const botName = buildBotName(useAuthStore((s) => s.user)?.botName)
  // issue #7263：贴底跟随（打字机逐字上屏时自动往下滑；用户上滑即停、回底恢复）
  const { anchorId, followIfSticky, handleScroll, handleScrollToLower } = useChatFollow(
    messages.length,
    isStreaming,
    onScrollOffset,
  )

  // 检查是否需要显示思考中动画：正在流式但最后一条 AI 消息还没有内容
  const showTyping = isStreaming && (() => {
    const lastMsg = messages[messages.length - 1]
    return lastMsg?.role === 'assistant' && !lastMsg.content && !(lastMsg.tool_calls?.length)
  })()

  if (messages.length === 0 && !isStreaming) {
    return (
      <View className='message-list'>
        <View className='message-list__empty'>
          <View className='message-list__empty-brand'>
            <Text className='message-list__empty-brand-text'>布</Text>
          </View>
          <Text className='message-list__empty-title'>你好，我是{botName}</Text>
          <Text className='message-list__empty-text'>
            你的商家经营助手{'\n'}经营、订单交付、库存、商品、售后、客户，都可以问我
          </Text>
          {/* 🔴 B 端空态**不铺商品**（issue #5747）：C 端旧版的商品推荐卡（拉
              `/api/chat/products/new-arrivals`、提示「点一下问问元元」）已整块删除 ——
              商家端不该出现顾客端的商品展示，更不该出现**顾客端 agent 名**。 */}
        </View>
      </View>
    )
  }

  return (
    <View className='message-list'>
      <ScrollView
        className='message-list__scroll'
        scrollY
        scrollIntoView={anchorId}
        scrollWithAnimation={false}
        lowerThreshold={60}
        enhanced
        showScrollbar={false}
        onScroll={handleScroll}
        onScrollToLower={handleScrollToLower}
      >
        <View className='message-list__content'>
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              onInteract={onInteract}
              onContentGrow={followIfSticky}
            />
          ))}

          {/* 思考中动画（UI-018：显示租户 botName，B 端默认「黄金策正在思考...」） */}
          {showTyping && <TypingIndicator text={`${botName}正在思考...`} />}

          {/* 两个底部锚点轮换（issue #7263）：Taro 只在 scrollIntoView 值变化时滚动 */}
          {ANCHORS.map((id) => (
            <View key={id} id={id} className='message-list__anchor' />
          ))}
        </View>
      </ScrollView>
    </View>
  )
}
