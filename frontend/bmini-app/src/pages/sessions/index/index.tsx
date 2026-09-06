import { useCallback, useEffect, useState } from 'react'
import { View, Text, ScrollView, Input, Button } from '@tarojs/components'
import Taro from '@tarojs/taro'
import {
  getAgentSessions,
  getAgentMonitor,
  type AgentSessionItem,
  type AgentMonitor,
} from '../../../services/agentSessionService'
import './index.scss'

/**
 * 移动坐席（米宝商家端，issue #2977）
 *
 * P0 核心：客服不在电脑前也能接人工。
 * - 队列页：待接管（waiting）+ 进行中（active）会话列表 + 排队统计
 * - 点击会话 → 进入详情页接管/回复（pages/sessions/detail）
 */
export default function SessionsPage() {
  const [waiting, setWaiting] = useState<AgentSessionItem[]>([])
  const [active, setActive] = useState<AgentSessionItem[]>([])
  const [monitor, setMonitor] = useState<AgentMonitor | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const [w, a, m] = await Promise.all([
      getAgentSessions('waiting', 1, 20),
      getAgentSessions('active', 1, 20),
      getAgentMonitor(),
    ])
    setWaiting(w.items || [])
    setActive(a.items || [])
    setMonitor(m)
    setLoading(false)
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
          {item.createdAt ? item.createdAt.slice(5, 16).replace('T', ' ') : ''}
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

  return (
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
        {!loading && waiting.length === 0 ? (
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
  )
}