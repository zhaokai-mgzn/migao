import { useCallback, useEffect, useState } from 'react'
import { View, Text, ScrollView, Input, Button } from '@tarojs/components'
import Taro from '@tarojs/taro'
import {
  getAgentSessions,
  getAgentMonitor,
  type AgentSessionItem,
  type AgentMonitor,
} from '../../../services/agentSessionService'
// 商家面身份护栏（issue #6567）：纯工人设备打开本页 ⇒ 送回工人工作台
import { useMerchantSurfaceGuard } from '../../../utils/roleGuard'
// 底栏（issue #6574）：端侧自绘 + 收起原生条；4 项**常驻**（用户 2026-10-18 裁定）
import MerchantTabBar from '../../../components/MerchantTabBar'
// 「没权限」= 与「问黄金策」同一做法（用户 2026-10-18 裁定）：授权缺失态的唯一呈现实现
import AdminGrantGate, { surfaceGrantGuide } from '../../../components/admin/SurfaceAccessGate'
import { useMobileMenu } from '../../../components/admin/useMobileMenu'
// 时间口径单一真值（issue #6666 判据 8）
import { formatMessageTime } from '../../../utils/datetime'
import './index.scss'

/**
 * 移动坐席（黄金策商家端，issue #2977）
 *
 * P0 核心：客服不在电脑前也能接人工。
 * - 队列页：待接管（waiting）+ 进行中（active）会话列表 + 排队统计
 * - 点击会话 → 进入详情页接管/回复（pages/sessions/detail）
 */
export default function SessionsPage() {
  useMerchantSurfaceGuard()
  const [waiting, setWaiting] = useState<AgentSessionItem[]>([])
  const [active, setActive] = useState<AgentSessionItem[]>([])
  const [monitor, setMonitor] = useState<AgentMonitor | null>(null)
  const [loading, setLoading] = useState(true)
  /**
   * 三态（用户 2026-10-18 裁定「底栏 4 项一律可见」之后**必须**有）：
   * 底栏不再按权限删格 ⇒ 没有 `agent:session` 的员工也能进本页。改前 `load()` 没有 catch
   * ⇒ 403 会变成「加载坐席队列…」永远转圈，或把「看不到」画成「队列空闲，AI 正在处理中」
   * （= 把没权限说成没数据）。这里显式分开：`forbidden` / `error` 各自有话说。
   */
  const [status, setStatus] = useState<'loading' | 'ok' | 'forbidden' | 'error'>('loading')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [w, a, m] = await Promise.all([
        getAgentSessions('waiting', 1, 20),
        getAgentSessions('active', 1, 20),
        getAgentMonitor(),
      ])
      setWaiting(w.items || [])
      setActive(a.items || [])
      setMonitor(m)
      setStatus('ok')
    } catch (e: any) {
      // 403 = 本岗位没有「移动坐席」权限（数据面仍由服务端拦）：显式说，不画成空态
      setStatus(e?.statusCode === 403 ? 'forbidden' : 'error')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    // 30s 轮询一次（移动坐席需要较新的队列状态）
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [load])

  // 进入会话详情
  const openSession = useCallback((id: string) => {
    Taro.navigateTo({ url: `/pages/sessions/detail/index?id=${id}` })
  }, [])

  const renderCount = (n: number | undefined) => n ?? '--'

  const SessionItem = ({ item }: { item: AgentSessionItem }) => (
    <View className='session-item' onClick={() => openSession(item.id)}>
      <View className={`session-item__avatar ${item.priority === 1 ? 'session-item__avatar--urgent' : ''}`}>
        <Text className='session-item__avatar-text'>
          {(item.customerName || '客')[0]}
        </Text>
      </View>
      <View className='session-item__body'>
        <Text className='session-item__name'>
          {item.customerName || '匿名客户'}
          {item.priority === 1 && <Text className='session-item__badge'>紧急</Text>}
        </Text>
        <Text className='session-item__reason' numberOfLines={1}>
          {item.reason || '转人工会话'}
        </Text>
        <Text className='session-item__time'>
          {formatMessageTime(item.createdAt)}
          {item.queuePosition != null && item.status === 'waiting' ? ` · 排位 ${item.queuePosition}` : ''}
        </Text>
      </View>
      <View className='session-item__action'>
        <Text className={`session-item__status session-item__status--${item.status}`}>
          {item.status === 'waiting' ? '待接管' : '进行中'}
        </Text>
      </View>
    </View>
  )

  // 🔴 底栏常驻（用户 2026-10-18 裁定）⇒ 没有 `agent:session` 的岗位**也能点进本页**。
  // 做法与「问黄金策」一致：整页给授权缺失态（逐字「需要管理员授权」+ 去哪开通），
  // **不白屏、不静默隐藏、不画成「队列空闲」**。判定一律来自服务端：
  // ① `mobileTabs` 里没有 `sessions`；② 接口 403（= status==='forbidden'，权限漂移时的兜底）。
  const menu = useMobileMenu()
  const tabDenied = menu.state === 'ok' && !menu.tabs.some((tab) => tab.key === 'sessions')
  if (tabDenied || status === 'forbidden') {
    return (
      <>
        <ScrollView scrollY className='sessions-page'>
          <AdminGrantGate testid='sessions-gate-denied' guide={surfaceGrantGuide('移动坐席')} />
        </ScrollView>
        <MerchantTabBar current='sessions' />
      </>
    )
  }

  // 加载失败（非权限原因）：显式错误 + 可点重试（不许画成「队列空闲」）
  if (status === 'error') {
    return (
      <>
        <ScrollView scrollY className='sessions-page'>
          <View className='sessions-empty' data-testid='sessions-error' onClick={load}>
            <Text>坐席队列加载失败，点此重试</Text>
          </View>
        </ScrollView>
        <MerchantTabBar current='sessions' />
      </>
    )
  }

  return (
    <>
    <ScrollView scrollY className='sessions-page'>
      {/* 队列统计卡 */}
      <View className='sessions-stats'>
        <View className='sessions-stats__item'>
          <Text className='sessions-stats__num sessions-stats__num--danger'>{renderCount(monitor?.waiting)}</Text>
          <Text className='sessions-stats__label'>待接管</Text>
        </View>
        <View className='sessions-stats__item'>
          <Text className='sessions-stats__num'>{renderCount(monitor?.active)}</Text>
          <Text className='sessions-stats__label'>进行中</Text>
        </View>
        <View className='sessions-stats__item'>
          <Text className='sessions-stats__num'>{renderCount(waiting.length)}</Text>
          <Text className='sessions-stats__label'>队列</Text>
        </View>
      </View>

      {/* 待接管队列 */}
      <View className='sessions-section'>
        <Text className='sessions-section__title'>待接管</Text>
        {status === 'ok' && !loading && waiting.length === 0 ? (
          <View className='sessions-empty'>
            <Text>队列空闲，AI 正在处理中</Text>
          </View>
        ) : (
          waiting.map(item => <SessionItem key={item.id} item={item} />)
        )}
      </View>

      {/* 进行中 */}
      {active.length > 0 && (
        <View className='sessions-section'>
          <Text className='sessions-section__title'>进行中</Text>
          {active.map(item => <SessionItem key={item.id} item={item} />)}
        </View>
      )}

      {loading && (
        <View className='sessions-loading'>
          <Text>加载坐席队列...</Text>
        </View>
      )}
    </ScrollView>
      {/* 底栏：4 项一律可见（用户 2026-10-18 裁定，「跟问黄金策一样」）；本页权限由上面的三态兜住 */}
      <MerchantTabBar current='sessions' />
    </>
  )
}