import { useEffect, useCallback } from 'react'
import { View, Text } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useChatStore } from '../../../store/chatStore'
import { useAuthStore } from '../../../store/authStore'
import MessageList from '../../../components/chat/MessageList'
import MessageInput from '../../../components/chat/MessageInput'
import QuickActions from '../../../components/chat/QuickActions'
import './index.scss'

export default function ChatPage() {
  const {
    messages,
    isStreaming,
    currentSessionId,
    isLoadingMessages,
    error,
    createSession,
    sendMessage,
    stopStreaming,
  } = useChatStore()

  const { isLoggedIn, checkAuth, login } = useAuthStore()

  /** 初始化：检查登录 + 创建会话 */
  const initialize = useCallback(async () => {
    // 检查登录状态
    const authed = checkAuth()
    if (!authed) {
      // 尝试自动登录（微信小程序静默登录）
      const success = await login()
      if (!success) {
        Taro.showToast({ title: '请先登录', icon: 'none' })
        // 可以跳转登录页，但目前先静默处理
        return
      }
    }

    // 如果没有当前会话，创建一个
    if (!useChatStore.getState().currentSessionId) {
      await createSession()
    }
  }, [checkAuth, login, createSession])

  useEffect(() => {
    initialize()
  }, [initialize])

  // 页面显示时刷新状态
  useDidShow(() => {
    if (!useChatStore.getState().currentSessionId) {
      initialize()
    }
  })

  /** 发送消息 */
  const handleSend = useCallback(
    async (content: string, images?: string[]) => {
      if (!currentSessionId) {
        await createSession()
      }
      await sendMessage(content, images)
    },
    [currentSessionId, createSession, sendMessage],
  )

  /** 快捷操作 */
  const handleQuickAction = useCallback(
    (prompt: string) => {
      handleSend(prompt)
    },
    [handleSend],
  )

  /** 停止流式 */
  const handleStop = useCallback(() => {
    stopStreaming()
  }, [stopStreaming])

  // 是否显示快捷菜单：消息为空且不在加载中
  const showQuickActions = messages.length === 0 && !isStreaming && !isLoadingMessages

  return (
    <View className='chat-page'>
      {/* 错误提示 */}
      {error && (
        <View className='chat-page__error'>
          <Text className='chat-page__error-text'>{error}</Text>
        </View>
      )}

      {/* 主体区域 */}
      <View className='chat-page__body'>
        {isLoadingMessages && messages.length === 0 ? (
          <View className='chat-page__loading'>
            <Text className='chat-page__loading-text'>加载中...</Text>
          </View>
        ) : (
          <>
            <MessageList messages={messages} isStreaming={isStreaming} />
            {showQuickActions && <QuickActions onAction={handleQuickAction} />}
          </>
        )}
      </View>

      {/* 输入区域 */}
      <MessageInput
        onSend={handleSend}
        onStop={handleStop}
        isStreaming={isStreaming}
        disabled={!currentSessionId}
      />
    </View>
  )
}
