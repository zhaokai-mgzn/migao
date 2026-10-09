import { useEffect, useCallback, useState } from 'react'
import { View, Text } from '@tarojs/components'
import Taro, { useDidShow } from '@tarojs/taro'
import { useChatStore } from '../../../store/chatStore'
import { useAuthStore } from '../../../store/authStore'
import { buildBrandSubtitle, buildBotName } from '../../../utils/brand'
import { currentLandingCode } from '../../../utils/inbound/deepLink'
// 商家面身份护栏（issue #6567）：纯工人设备打开本页 ⇒ 送回工人工作台
import { useMerchantSurfaceGuard } from '../../../utils/roleGuard'
import MessageList from '../../../components/chat/MessageList'
import MessageInput from '../../../components/chat/MessageInput'
import QuickActions from '../../../components/chat/QuickActions'
// 黄金策唤出授权门 + 能力位来源（issue #5642 功能⑤）
import MibaoAccessGate from '../../../components/chat/MibaoAccessGate'
// 底栏（issue #6574）：按岗位权限裁剪，端侧自绘 + 收起原生条
import MerchantTabBar from '../../../components/MerchantTabBar'
import { getUserInfo } from '../../../services/userService'
import './index.scss'

export default function ChatPage() {
  useMerchantSurfaceGuard()
  const {
    messages,
    isStreaming,
    currentSessionId,
    isLoadingMessages,
    error,
    handedOff,
    quickActions,
    loadQuickActions,
    ensureLatestSession,
    createSession,
    sendMessage,
    stopStreaming,
  } = useChatStore()

  const { isLoggedIn, checkAuth, user } = useAuthStore()

  // 状态栏高度（自定义导航栏需要）
  const [statusBarHeight, setStatusBarHeight] = useState(20)

  // 黄金策唤出能力位（issue #5642 功能⑤）：**只**取服务端 `capabilities.mibaoChat`
  // —— 前端不判任何权限码（哪些码算管理员是服务端单一真值，改一处即 h5 与 admin-web 同步）。
  // `null` = 尚未取到 ⇒ 门不渲染任何一侧（避免把「还没拿到」误报成「没权限」）。
  const [mibaoAllowed, setMibaoAllowed] = useState<boolean | null>(null)

  useEffect(() => {
    try {
      const info = Taro.getSystemInfoSync()
      setStatusBarHeight(info.statusBarHeight || 20)
    } catch {}
  }, [])

  /** 初始化：检查登录 + 续聊/新建会话（B 端：未登录引导去登录页，不做 C 端静默登录） */
  const initialize = useCallback(async () => {
    // 🔴 **落地页深链优先**（issue #5052 实现 PR）：URL 上带着 `?code=` 时**不抢路由** ——
    // 本页「未登录 ⇒ 600ms 后去商家登录页」的定时器**在页面卸载后照样触发**，
    // 会把工人从他的补打落地页一脚踢到商家登录页，而这一步**没有任何东西会变红**
    // （跳转成功、无异常、无日志 —— 正是本单要治的"静默失败"形态）。
    // 深链的接手方是 `src/app.tsx`（把码交给补打页）。
    if (currentLandingCode().present) return

    // 检查登录状态（B 端首次登录需账号密码，无微信静默登录）
    if (!checkAuth()) {
      Taro.showToast({ title: '请先登录', icon: 'none' })
      setTimeout(() => Taro.redirectTo({ url: '/pages/auth/login/index' }), 600)
      return
    }

    // 🔴 黄金策唤出授权门前置（issue #5642 功能⑤）：未授权 ⇒ **不创建会话、不改路由**
    // （入口保持可见，页内由 `<MibaoAccessGate>` 给「需要管理员授权」+ 可行动引导
    //  —— 不是静默隐藏、不是 403 白屏）。
    let allowed = false
    try {
      const me = await getUserInfo()
      allowed = me?.capabilities?.mibaoChat === true
    } catch {
      // 取不到能力位 ⇒ fail-closed（**不**静默放行）
      allowed = false
    }
    setMibaoAllowed(allowed)
    if (!allowed) {
      return
    }

    // 无会话 UX：续聊最近一次，无则静默新建；
    // 同批拉空态快捷入口（issue #6468）：内容 = 服务端**单一真值**（`/api/chat/quick-actions`），
    // H5 不再自带一份（旧形态正是抄 C 端的硬编码六条）。
    await Promise.all([ensureLatestSession(), loadQuickActions()])
  }, [checkAuth, ensureLatestSession, loadQuickActions])

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
      // 授权门兜底（授权缺失态下输入区本就不渲染；此处防「我的」页待发提示等旁路）
      if (mibaoAllowed !== true) {
        return
      }
      if (!currentSessionId) {
        await ensureLatestSession()
      }
      await sendMessage(content, images)
    },
    [currentSessionId, ensureLatestSession, sendMessage, mibaoAllowed],
  )

  /** 新对话（清空当前会话工作状态，不展示会话列表） */
  const handleNewChat = useCallback(async () => {
    // 导航栏的「新对话」在授权缺失态下仍可见（入口不隐藏）⇒ 这里兜底：未授权不发请求
    if (mibaoAllowed !== true) {
      return
    }
    await createSession()
  }, [createSession, mibaoAllowed])

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
          <Text className='chat-page__navbar-name'>{buildBotName(user?.botName)}</Text>
          <View className='chat-page__navbar-badge'>
            <Text className='chat-page__navbar-badge-text'>AI</Text>
          </View>
        </View>
        <View className='chat-page__navbar-right'>
          <Text className='chat-page__navbar-sub'>{buildBrandSubtitle(user?.tenantName)}</Text>
          {/* 新对话（清空工作状态，不展示会话列表） */}
          <View className='chat-page__new-chat' onClick={handleNewChat} hoverClass='chat-page__new-chat--hover'>
            <Text className='chat-page__new-chat-text'>🔄 新对话</Text>
          </View>
        </View>
      </View>

      {/* 🔴 黄金策唤出授权门（issue #5642 功能⑤）：未授权 ⇒ 明确「需要管理员授权」+ 可行动引导 */}
      <MibaoAccessGate allowed={mibaoAllowed}>
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
            {showQuickActions && <QuickActions actions={quickActions} onAction={handleQuickAction} />}
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
      </MibaoAccessGate>

      {/* 底栏（issue #6574）：按岗位权限裁剪（服务端下发 `mobileTabs`），原生的静态 4 项被收起 */}
      <MerchantTabBar current='chat' />
    </View>
  )
}
