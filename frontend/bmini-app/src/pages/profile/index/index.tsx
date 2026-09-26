import { useCallback } from 'react'
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import { useChatStore } from '../../../store/chatStore'
import { visibleAdminSurfaces } from '../../../utils/adminPermission'
import { useAdminPermissions } from '../../../components/admin/useAdminPermissions'
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
  // 服务端下发的权限集合（`GET /api/auth/me`）；`null` = 未知 ⇒ 入口照显（fail-open）
  const permissions = useAdminPermissions()
  const adminSurfaces = visibleAdminSurfaces(permissions)

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

  /** 工人扫码报工入口（issue #3997，M4-G-3） */
  const handleProduction = () => {
    Taro.navigateTo({ url: '/pages/production/index/index' })
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

  // 角色展示（面向低学历用户可读性：**未登记的角色一律回退中文**，
  // 原先 `|| user.role` 会把后端角色码原样印在页面上——如 `warehouse_keeper`，
  // 这是「页面上出现英文」的同类泄漏。新增角色请登记到下表。）
  const roleLabel = user?.role
    ? ({ operator: '运营经理', admin: '企业管理员', product_manager: '商品管理员', knowledge_editor: '知识编辑' } as Record<string, string>)[user.role] || '商家员工'
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
        <View className='menu-item' onClick={handleProduction}>
          <Text className='menu-item__text'>扫码报工</Text>
          <Text className='menu-item__arrow'>›</Text>
        </View>

        {/* ── 管理面 4 项（issue #5654）──
            管理员离店后仍要能办的事：排产/派单 · 入库过账 · 售后处理 · 计件工资报表。
            🔴 可见性 = 「能读这一页」的**端点码**（`src/utils/adminPermission.ts` 台账），
            权限集合来自服务端 `GET /api/auth/me`；**集合未知 ⇒ 照显**（fail-open：
            判定权威在服务端 403 + 显式文案，静默隐藏入口是 #5642 明令禁止的形态）。 */}
        {adminSurfaces.map((surface) => (
          <View
            key={surface.key}
            className='menu-item'
            data-testid={`profile-admin-${surface.key}`}
            onClick={() => Taro.navigateTo({ url: surface.route })}
          >
            <Text className='menu-item__text'>{surface.label}</Text>
            <Text className='menu-item__arrow'>›</Text>
          </View>
        ))}

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