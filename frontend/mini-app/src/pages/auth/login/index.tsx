import { useEffect, useCallback } from 'react'
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import { DEFAULT_TENANT_ID } from '../../../utils/constants'
import './index.scss'

export default function LoginPage() {
  const { isLoading, checkAuth, login } = useAuthStore()

  // 页面加载时检查是否已登录
  useEffect(() => {
    const isValid = checkAuth()
    if (isValid) {
      Taro.switchTab({ url: '/pages/chat/index/index' })
    }
  }, [])

  // 点击登录
  const handleLogin = useCallback(async () => {
    if (isLoading) return

    const success = await login(DEFAULT_TENANT_ID)
    if (success) {
      Taro.switchTab({ url: '/pages/chat/index/index' })
    }
    // 失败时 authStore.login 内部已经 showToast
  }, [isLoading, login])

  // 服务条款
  const handleTerms = useCallback(() => {
    Taro.showModal({
      title: '服务条款',
      content: '本应用服务条款内容将在后续版本中完善，感谢您的理解与支持。',
      showCancel: false,
      confirmText: '我知道了',
    })
  }, [])

  // 隐私协议
  const handlePrivacy = useCallback(() => {
    Taro.showModal({
      title: '隐私协议',
      content: '我们重视您的隐私保护，隐私协议详细内容将在后续版本中完善。',
      showCancel: false,
      confirmText: '我知道了',
    })
  }, [])

  return (
    <View className='login-page'>
      {/* 顶部品牌区域 */}
      <View className='login-brand'>
        <View className='login-brand__icon'>
          <Text className='login-brand__icon-text'>AI</Text>
        </View>
        {/* AI 角色标签口径见 frontend/admin-web/src/config/ai-roles.ts（issue #6330/#6333）；
            本 App 是独立工程，不跨 App 引共享模块（#6306 教训：落在发布集外 ⇒ 白屏）⇒ 本地字面量 + 测试钉值。
            注意：buildBrandSubtitle 的「{企业名} · 智能购物助手」是**店铺描述**，不是 AI 角色，不动。 */}
        <Text className='login-brand__title'>元元 · 企业智能客服</Text>
        <Text className='login-brand__subtitle'>您的专属智能购物助手</Text>
      </View>

      {/* 中间欢迎文案 */}
      <View className='login-welcome'>
        <Text className='login-welcome__title'>欢迎使用</Text>
        <Text className='login-welcome__desc'>
          元元为您提供 7×24 小时在线服务{'\n'}随时解答您的购物疑问
        </Text>
      </View>

      {/* 底部操作区域 */}
      <View className='login-actions'>
        <View
          className={`login-btn ${isLoading ? 'login-btn--loading' : ''}`}
          onClick={handleLogin}
        >
          {isLoading ? (
            <Text className='login-btn__text'>登录中...</Text>
          ) : (
            <Text className='login-btn__text'>微信一键登录</Text>
          )}
        </View>

        <View className='login-agreement'>
          <Text className='login-agreement__text'>
            登录即表示您同意
          </Text>
          <Text className='login-agreement__link' onClick={handleTerms}>
            《服务条款》
          </Text>
          <Text className='login-agreement__text'>和</Text>
          <Text className='login-agreement__link' onClick={handlePrivacy}>
            《隐私协议》
          </Text>
        </View>
      </View>
    </View>
  )
}
