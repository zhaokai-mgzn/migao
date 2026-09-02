import { useCallback, useEffect, useState } from 'react'
import Taro, { useDidShow } from '@tarojs/taro'
import { View, Text, Image, Button } from '@tarojs/components'
import { useAuthStore } from '../../../store/authStore'
import { useChatStore } from '../../../store/chatStore'
import { getUserInfo, bindMiniPhone } from '../../../services/userService'
import { getMyOrders, getMyTickets } from '../../../services/productService'
import type { MiniOrder, MiniTicket } from '../../../services/productService'
import './index.scss'

/** 订单/售后状态中文标签 */
const ORDER_STATUS_TEXT: Record<string, string> = {
  pending: '待付款',
  confirmed: '已确认',
  producing: '生产中',
  shipped: '已发货',
  completed: '已完成',
  cancelled: '已取消',
}

const TICKET_TYPE_TEXT: Record<string, string> = {
  refund: '退款',
  exchange: '换货',
  repair: '维修',
  complaint: '投诉',
  other: '其他',
}

export default function ProfilePage() {
  const { user, isLoggedIn, setUser, logout } = useAuthStore()
  const [loading, setLoading] = useState(false)
  const [orders, setOrders] = useState<MiniOrder[]>([])
  const [tickets, setTickets] = useState<MiniTicket[]>([])

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

  // 拉取我的订单 + 售后工单（C 端数据隔离端点）
  const fetchMyData = useCallback(async () => {
    const [orderList, ticketList] = await Promise.allSettled([
      getMyOrders(3),
      getMyTickets(3),
    ])
    if (orderList.status === 'fulfilled') setOrders(orderList.value)
    if (ticketList.status === 'fulfilled') setTickets(ticketList.value)
  }, [])

  useEffect(() => {
    if (isLoggedIn) {
      if (!user) fetchUser()
      fetchMyData()
    }
  }, [isLoggedIn, user, fetchUser, fetchMyData])

  useDidShow(() => {
    if (isLoggedIn) {
      if (!user) fetchUser()
      fetchMyData()
    }
  })

  // ========== 入口点击 ==========
  const handleOrderDetail = (order: MiniOrder) => {
    // 唤起对话追问订单（闭环在对话里，不另造详情页）
    Taro.switchTab({ url: '/pages/chat/index/index' })
    // 通过事件总线把订单号注入对话（chatStore 在页面 show 后消费）
    Taro.setStorageSync('pendingOrderPrompt', `帮我查一下订单 ${order.order_no} 的进度`)
  }

  const handleTicketDetail = (ticket: MiniTicket) => {
    Taro.switchTab({ url: '/pages/chat/index/index' })
    Taro.setStorageSync('pendingOrderPrompt', `帮我查一下售后工单 ${ticket.ticket_no} 的进度`)
  }

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

  // ========== 手机号绑定（关联名下商户代录订单） ==========
  const [bindingPhone, setBindingPhone] = useState(false)

  /** 微信 getPhoneNumber 授权回调：拿动态 code → 后端换号 + 回填名下订单 */
  const handleGetPhoneNumber = async (e: any) => {
    if (bindingPhone) return
    const detail = e?.detail || {}
    // 用户拒绝授权：errMsg 以 "fail" 开头（如 cancel）
    const errMsg: string = detail.errMsg || ''
    if (errMsg.startsWith('fail') || errMsg.includes('cancel')) {
      Taro.showToast({ title: '已取消授权', icon: 'none' })
      return
    }
    const code: string = detail.code || ''
    if (!code) {
      Taro.showToast({ title: '未获取到授权凭证，请重试', icon: 'none' })
      return
    }
    setBindingPhone(true)
    try {
      const result = await bindMiniPhone(code)
      // 更新 store 中的 user.phone
      if (user) {
        setUser({ ...user, phone: result.phone })
      }
      const boundMsg = result.boundOrders > 0
        ? `绑定成功，已关联 ${result.boundOrders} 笔历史订单`
        : '绑定成功'
      Taro.showToast({ title: boundMsg, icon: 'none' })
    } catch (err: any) {
      Taro.showToast({ title: err?.message || '绑定失败，请重试', icon: 'none' })
    } finally {
      setBindingPhone(false)
    }
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
          {user?.phone ? (
            <Text className='user-phone'>📱 {user.phone.replace(/^(\d{3})\d{4}(\d{4})$/, '$1****$2')}</Text>
          ) : (
            <Button
              className='bind-phone-btn'
              openType='getPhoneNumber'
              onGetPhoneNumber={handleGetPhoneNumber}
              loading={bindingPhone}
            >
              绑定手机号，查看名下订单
            </Button>
          )}
        </View>
      </View>

      {/* ===== 我的订单 ===== */}
      <View className='section-card'>
        <View className='section-card__header'>
          <Text className='section-card__title'>📦 我的订单</Text>
        </View>
        {orders.length === 0 ? (
          <Text className='section-card__empty'>暂无订单</Text>
        ) : (
          orders.map((o) => (
            <View key={o.id} className='entry-row' hoverClass='entry-row--hover' onClick={() => handleOrderDetail(o)}>
              <View className='entry-row__main'>
                <Text className='entry-row__title'>{o.order_no}</Text>
                <Text className='entry-row__sub'>{ORDER_STATUS_TEXT[o.status] || o.status_text || o.status}</Text>
              </View>
              <Text className='entry-row__value'>¥{Number(o.total_amount || 0).toFixed(2)}</Text>
            </View>
          ))
        )}
      </View>

      {/* ===== 我的售后 ===== */}
      <View className='section-card'>
        <View className='section-card__header'>
          <Text className='section-card__title'>🔄 我的售后</Text>
        </View>
        {tickets.length === 0 ? (
          <Text className='section-card__empty'>暂无售后工单</Text>
        ) : (
          tickets.map((t) => (
            <View key={t.id} className='entry-row' hoverClass='entry-row--hover' onClick={() => handleTicketDetail(t)}>
              <View className='entry-row__main'>
                <Text className='entry-row__title'>{t.ticket_no}</Text>
                <Text className='entry-row__sub'>{TICKET_TYPE_TEXT[t.ticket_type] || t.ticket_type} · {t.status}</Text>
              </View>
              <Text className='entry-row__arrow'>›</Text>
            </View>
          ))
        )}
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
