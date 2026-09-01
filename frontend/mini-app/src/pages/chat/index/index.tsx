import { useEffect, useCallback, useState } from 'react'
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
    handedOff,
    ensureLatestSession,
    createSession,
    sendMessage,
    stopStreaming,
  } = useChatStore()

  const { isLoggedIn, checkAuth, login } = useAuthStore()

  // 状态栏高度（自定义导航栏需要）
  const [statusBarHeight, setStatusBarHeight] = useState(20)

  useEffect(() => {
    try {
      const info = Taro.getSystemInfoSync()
      setStatusBarHeight(info.statusBarHeight || 20)
    } catch {}
  }, [])

  /** 初始化：检查登录 + 续聊/新建会话（无会话 UX，前端无感） */
  const initialize = useCallback(async () => {
    // 检查登录状态
    const authed = checkAuth()
    if (!authed) {
      // 尝试自动登录（微信小程序静默登录）
      const success = await login()
      if (!success) {
        Taro.showToast({ title: '请先登录', icon: 'none' })
        return
      }
    }

    // 无会话 UX：续聊最近一次，无则静默新建
    await ensureLatestSession()
  }, [checkAuth, login, ensureLatestSession])

  useEffect(() => {
    initialize()
  }, [initialize])

  // 页面显示时刷新状态
  useDidShow(() => {
    if (!useChatStore.getState().currentSessionId) {
      initialize()
    }
    // 消费「我的」页订单/售后入口的待发提示（唤起对话追问进度）
    const pending = Taro.getStorageSync('pendingOrderPrompt') as string | ''
    if (pending) {
      Taro.removeStorageSync('pendingOrderPrompt')
      setTimeout(() => handleSend(pending), 300)
    }
  })

  /** 发送消息 */
  const handleSend = useCallback(
    async (content: string, images?: string[]) => {
      if (!currentSessionId) {
        await ensureLatestSession()
      }
      await sendMessage(content, images)
    },
    [currentSessionId, ensureLatestSession, sendMessage],
  )

  /** 新对话（清空当前会话工作状态，不展示会话列表） */
  const handleNewChat = useCallback(async () => {
    await createSession()
  }, [createSession])

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
    <View className='chat-page' style={{ paddingTop: statusBarHeight }}>
      {/* 自定义导航栏：深蓝渐变品牌头 */}
      <View className='chat-page__navbar'>
        <View className='chat-page__navbar-title'>
          <View className='chat-page__navbar-logo' />
          <Text className='chat-page__navbar-name'>小布</Text>
          <View className='chat-page__navbar-badge'>
            <Text className='chat-page__navbar-badge-text'>AI</Text>
          </View>
        </View>
        <View className='chat-page__navbar-right'>
          <Text className='chat-page__navbar-sub'>米高窗帘 · 智能购物助手</Text>
          {/* 新对话（清空工作状态，不展示会话列表） */}
          <View className='chat-page__new-chat' onClick={handleNewChat} hoverClass='chat-page__new-chat--hover'>
            <Text className='chat-page__new-chat-text'>🔄 新对话</Text>
          </View>
        </View>
      </View>

      {/* 错误提示 */}
      {error && (
        <View className='chat-page__error'>
          <Text className='chat-page__error-text'>{error}</Text>
        </View>
      )}

      {/* 已转人工横幅 */}
      {handedOff && (
        <View className='chat-page__handoff'>
          <Text className='chat-page__handoff-text'>👩‍💼 已为您转接人工客服，请稍候，可直接在这里和客服沟通</Text>
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
            <MessageList messages={messages} isStreaming={isStreaming} onInteract={handleSend} />
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
