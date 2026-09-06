import { useCallback } from 'react'
import { View, Text, Button } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import './index.scss'

/**
 * B 端员工小程序登录页（米宝商家端，issue #2977）
 *
 * 登录流程：
 * 1. 点击「授权手机号登录」触发 <Button open-type="getPhoneNumber"> 微信手机号授权
 * 2. onGetPhoneNumber 拿到动态 code → bminiLoginAction(phoneCode)
 * 3. 后端：wx.login code 换 openid → 查 bmini_app 绑定 → 未绑定则用手机号跨租户匹配
 *    员工（role∉customer/agent）→ 绑定并签发员工 JWT；匹配不到即时拒绝
 * 4. 登录成功 → switchTab 到「问米宝」（首页 Tab）
 */
export default function LoginPage() {
  const { isLoading, bminiLoginAction } = useAuthStore()

  /**
   * getPhoneNumber 授权回调：拿到动态 code 后发起 B 端登录。
   * - e.detail.code：授权成功返回的动态令牌（后端换真实手机号）
   * - e.detail.errMsg 以 getUserProfile:fail/deny 结尾 = 用户拒绝授权
   */
  const handleGetPhoneNumber = useCallback(
    async (e: any) => {
      const detail = e?.detail || {}
      if (detail.errMsg && detail.errMsg.includes('deny')) {
        Taro.showToast({ title: '需要授权手机号才能登录', icon: 'none' })
        return
      }
      if (!detail.code) {
        Taro.showToast({ title: '未获取到手机号授权，请重试', icon: 'none' })
        return
      }
      if (isLoading) return

      const success = await bminiLoginAction(detail.code)
      if (success) {
        Taro.switchTab({ url: '/pages/chat/index/index' })
      }
      // 失败原因由 authStore 内部 showToast（如「手机号未匹配员工账号」）
    },
    [isLoading, bminiLoginAction],
  )

  // 服务条款
  const handleTerms = useCallback(() => {
    Taro.showModal({
      title: '服务条款',
      content: '本应用面向米高平台商家员工，使用即表示同意平台服务条款。',
      showCancel: false,
      confirmText: '我知道了',
    })
  }, [])

  // 隐私协议
  const handlePrivacy = useCallback(() => {
    Taro.showModal({
      title: '隐私协议',
      content: '登录仅用于绑定您的员工账号，手机号信息将严格保密。',
      showCancel: false,
      confirmText: '我知道了',
    })
  }, [])

  return (
    <View className='login-page'>
      {/* 顶部品牌区域 */}
      <View className='login-brand'>
        <View className='login-brand__icon'>
          <Text className='login-brand__icon-text'>米</Text>
        </View>
        <Text className='login-brand__title'>米宝 · 商家助手</Text>
        <Text className='login-brand__subtitle'>经营数据 · AI 客服 · 移动坐席</Text>
      </View>

      {/* 中间欢迎文案 */}
      <View className='login-welcome'>
        <Text className='login-welcome__title'>欢迎回来</Text>
        <Text className='login-welcome__desc'>
          授权手机号即可登录{'\n'}随时随地查看经营数据、处理紧急事务
        </Text>
      </View>

      {/* 底部操作区域 */}
      <View className='login-actions'>
        <Button
          className={`login-btn ${isLoading ? 'login-btn--loading' : ''}`}
          openType='getPhoneNumber'
          onGetPhoneNumber={handleGetPhoneNumber}
          loading={isLoading}
          disabled={isLoading}
        >
          {isLoading ? '登录中...' : '微信授权手机号登录'}
        </Button>

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