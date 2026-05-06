import { useCallback, useEffect, useState } from 'react'
import Taro, { useDidShow } from '@tarojs/taro'
import { View, Text, Image } from '@tarojs/components'
import { useAuthStore } from '../../../store/authStore'
import { useChatStore } from '../../../store/chatStore'
import { getUserInfo } from '../../../services/userService'
import './index.scss'

/** 判断日期是否属于当月 */
function isCurrentMonth(dateStr: string): boolean {
  const now = new Date()
  const d = new Date(dateStr)
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth()
}

export default function ProfilePage() {
  const { user, isLoggedIn, setUser, logout } = useAuthStore()
  const { sessions } = useChatStore()
  const [loading, setLoading] = useState(false)

  // 拉取用户信息（store 没有时走接口）
  const fetchUser = useCallback(async () => {
    if (user) return
    setLoading(true)
    try {
      const info = await getUserInfo()
      setUser(info)
    } catch {
      // ignore – 页面会显示占位
    } finally {
      setLoading(false)
    }
  }, [user, setUser])

  useEffect(() => {
    if (isLoggedIn && !user) {
      fetchUser()
    }
  }, [isLoggedIn, user, fetchUser])

  useDidShow(() => {
    if (isLoggedIn && !user) {
      fetchUser()
    }
  })

  // ========== 统计 ==========
  const totalSessions = sessions.length || 0
  const monthSessions = sessions.filter((s) => isCurrentMonth(s.created_at)).length

  // ========== 设置列表点击 ==========
  const handleAccountInfo = () => {
    Taro.showToast({ title: '功能开发中', icon: 'none' })
  }

  const handleAbout = () => {
    Taro.showModal({
      title: '关于我们',
      content: '小布 v1.0.0\n您的专属智能购物助手',
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

  return (
    <View className='profile-page'>
      {/* ===== 顶部用户信息 ===== */}
      <View className='profile-header'>
        <View className='avatar-wrapper'>
          {user?.avatar ? (
            <Image className='avatar-image' src={user.avatar} mode='aspectFill' />
          ) : (
            <View className='avatar-placeholder'>
              <Text className='avatar-letter'>{initial}</Text>
            </View>
          )}
        </View>
        <View className='user-info'>
          <Text className='user-nickname'>{loading ? '加载中…' : user?.nickname || '用户'}</Text>
          <Text className='user-id'>ID: {user?.id || '--'}</Text>
        </View>
      </View>

      {/* ===== 统计卡片 ===== */}
      <View className='stats-card'>
        <View className='stat-item'>
          <Text className='stat-value'>{totalSessions > 0 ? totalSessions : '--'}</Text>
          <Text className='stat-label'>总会话数</Text>
        </View>
        <View className='stat-item'>
          <Text className='stat-value'>{totalSessions > 0 ? monthSessions : '--'}</Text>
          <Text className='stat-label'>本月对话</Text>
        </View>
      </View>

      {/* ===== 设置列表 ===== */}
      <View className='settings-card'>
        <View className='setting-item' onClick={handleAccountInfo}>
          <Text className='setting-label'>账号信息</Text>
          <Text className='setting-arrow'>›</Text>
        </View>
        <View className='setting-item' onClick={handleAbout}>
          <Text className='setting-label'>关于我们</Text>
          <Text className='setting-arrow'>›</Text>
        </View>
        <View className='setting-item' onClick={handlePrivacy}>
          <Text className='setting-label'>隐私协议</Text>
          <Text className='setting-arrow'>›</Text>
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
