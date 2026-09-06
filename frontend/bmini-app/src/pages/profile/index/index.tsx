import { useCallback } from 'react'
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import { useChatStore } from '../../../store/chatStore'
import './index.scss'

/**
 * 「我的」（B 端商家版，issue #2977）
 *
 * 员工信息（昵称/角色/租户）+ 快捷入口 + 退出登录。
 * 与 C 端消费者 profile 不同：不展示订单/售后/手机号绑定（B 端员工管理他人的订单，
 * 个人消费数据无意义），聚焦员工身份与安全退出。
 */
export default function ProfilePage() {
  const { user, isLoggedIn, logout } = useAuthStore()

  const handleAbout = () => {
    Taro.showModal({
      title: '关于我们',
      content: '米宝商家助手 v1.0.0\n面向商家员工的 AI 经营助手',
      showCancel: false,
    })
  }

  const handlePrivacy = () => {
    Taro.showModal({
      title: '隐私协议',
      content:
        '我们重视您的隐私。我们仅收集提供服务所必需的信息，并严格保护您的数据安全。未经您的同意，我们不会向第三方分享您的个人信息。',
      showCancel: false,
    })
  }

  const handleLogout = () => {
    Taro.showModal({
      title: '提示',
      content: '确定要退出登录吗？',
      success: (res) => {
        if (res.confirm) {
          logout()
          // 清空对话状态
          useChatStore.getState().clearMessages()
          Taro.redirectTo({ url: '/pages/auth/login/index' })
        }
      },
    })
  }

  const handleGoLogin = () => {
    Taro.redirectTo({ url: '/pages/auth/login/index' })
  }

  // ========== 未登录 ==========
  if (!isLoggedIn) {
    return (
      <View className='not-logged-in'>
        <View className='not-logged-icon'>
          <Text className='not-logged-icon-text'>👤</Text>
        </View>
        <Text className='not-logged-text'>请先登录</Text>
        <View className='login-btn' onClick={handleGoLogin}>
          <Text className='login-btn-text'>去登录</Text>
        </View>
      </View>
    )
  }

  // 头像首字母
  const initial = user?.nickname?.charAt(0) || '?'

  // 角色展示
  const roleLabel = user?.role
    ? ({ operator: '运营经理', admin: '企业管理员', product_manager: '商品管理员', knowledge_editor: '知识编辑' } as Record<string, string>)[user.role] || user.role
    : '商家员工'

  return (
    <View className='profile-page'>
      {/* ===== 顶部用户信息 ===== */}
      <View className='profile-header'>
        <View className='profile-avatar'>
          <Text className='profile-avatar-text'>{initial}</Text>
        </View>
        <View className='profile-info'>
          <Text className='profile-name'>{user?.nickname || '商家员工'}</Text>
          <Text className='profile-role'>{roleLabel}</Text>
          {user?.tenantName && <Text className='profile-tenant'>{user.tenantName}</Text>}
        </View>
      </View>

      {/* ===== 功能入口 ===== */}
      <View className='profile-menu'>
        <View className='menu-item' onClick={handleAbout}>
          <Text className='menu-item__text'>关于我们</Text>
          <Text className='menu-item__arrow'>›</Text>
        </View>
        <View className='menu-item' onClick={handlePrivacy}>
          <Text className='menu-item__text'>隐私协议</Text>
          <Text className='menu-item__arrow'>›</Text>
        </View>
      </View>

      {/* ===== 退出登录 ===== */}
      <View className='logout-section'>
        <View className='logout-btn' onClick={handleLogout}>
          <Text className='logout-text'>退出登录</Text>
        </View>
      </View>
    </View>
  )
}