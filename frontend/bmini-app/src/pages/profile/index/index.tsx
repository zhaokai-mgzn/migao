import { useCallback } from 'react'
import { View, Text } from '@tarojs/components'
import Taro from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import { useChatStore } from '../../../store/chatStore'
// 手机端菜单（issue #6570）：**服务端按岗位投影**，端侧不再自己判权限码
import { useMobileMenu } from '../../../components/admin/useMobileMenu'
// 商家面身份护栏（issue #6567）：纯工人设备打开本页 ⇒ 送回工人工作台
import { useMerchantSurfaceGuard } from '../../../utils/roleGuard'
import './index.scss'

/**
 * 「我的」（B 端商家版，issue #2977）
 *
 * 员工信息（昵称/角色/租户）+ 快捷入口 + 退出登录。
 * 与 C 端消费者 profile 不同：不展示订单/售后/手机号绑定（B 端员工管理他人的订单，
 * 个人消费数据无意义），聚焦员工身份与安全退出。
 *
 * issue #6563（用户 2026-10-08 裁定）：**工人三件功能（扫码报工 / 拍照入库 / 补打入库标签）不在本页** ——
 * 它们是工人动作（各自页内还会再要求工人身份），已归位到工人登录后的工作台
 * （`src/pages/worker/home/index.tsx`）。#5747 时代把它们铺进商家菜单，是为了补「`/b/` 内两页零入口」
 * 的可达性；工人工作台落地（#6467 切片 1）后这条理由不再成立 ⇒ 从商家面撤掉，
 * 免得商家员工点进去只被身份分流挡住（反向判据见 tests/profile-page.test.tsx）。
 */
export default function ProfilePage() {
  useMerchantSurfaceGuard()
  const { user, isLoggedIn, logout } = useAuthStore()
  // 服务端下发的**手机端菜单**（`GET /api/auth/me` 的 `mobileSurfaces`，issue #6570）：
  // 端侧**只渲染服务端给的面**（旧口径 = 端侧拿 permissions 自己判码 + 未知照显 ⇒ 员工点进去逐项 403）
  const menu = useMobileMenu()
  const navSurfaces = menu.surfaces.filter((surface) => !!surface.route)

  const handleAbout = () => {
    Taro.showModal({
      title: '关于我们',
      content: '黄金策商家助手 v1.0.0\n面向商家员工的 AI 经营助手',
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
        {/* 🔴 本页**没有**工人三件功能（扫码报工 / 拍照入库 / 补打入库标签，issue #6563）：
            它们是工人动作，归位在工人登录后的工作台 `src/pages/worker/home/index.tsx`。
            判据 = tests/profile-page.test.tsx 的两条反向断言（渲染面取不到 + 源码面无工人面路由记号）。 */}

        {/* ── 管理面（issue #5654；菜单改为**服务端下发** issue #6570）──
            管理员离店后仍要能办的事：排产/派单 · 入库过账 · 售后处理 · 计件工资报表。
            🔴 可见性 = **服务端按岗位投影**（`GET /api/auth/me` 的 `mobileSurfaces`，服务端
            `MobileSurfaces.visibleFor` 按生效权限集合过滤）—— 端侧**不再自己判权限码**。
            🔴 没拿到菜单（`error`）⇒ **显式说 + 可重试**：既不静默隐藏（#5642 禁止的形态），
            也不退回「照显全部」（那会让员工点进去逐项 403 —— issue #6570 的现状读数）。 */}
        {navSurfaces.map((surface) => (
          <View
            key={surface.key}
            className='menu-item'
            data-testid={`profile-admin-${surface.key}`}
            onClick={() => surface.route && Taro.navigateTo({ url: surface.route })}
          >
            <Text className='menu-item__text'>{surface.title}</Text>
            <Text className='menu-item__arrow'>›</Text>
          </View>
        ))}
        {menu.state === 'error' && (
          <View className='menu-item' data-testid='profile-menu-error' onClick={menu.reload}>
            <Text className='menu-item__text'>菜单没加载出来，点这里重试</Text>
            <Text className='menu-item__arrow'>↻</Text>
          </View>
        )}

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