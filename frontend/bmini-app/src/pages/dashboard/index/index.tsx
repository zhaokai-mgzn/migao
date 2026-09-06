import { useCallback, useEffect, useState } from 'react'
import { View, Text, ScrollView } from '@tarojs/components'
import Taro, { usePullDownRefresh } from '@tarojs/taro'
import { useAuthStore } from '../../../store/authStore'
import {
  getDashboardStats,
  getPendingTasks,
  formatYuan,
  formatPercent,
  type DashboardStats,
  type PendingTask,
} from '../../../services/dashboardService'
import './index.scss'

/**
 * 数据一屏（米宝商家端，issue #2977）
 *
 * P0 核心：「老板扫一眼」的 5 个数字 + 待办。
 * 全部复用 admin-api /api/admin/dashboard/* 现成接口，权限 dashboard:view 后端门禁。
 */
export default function DashboardPage() {
  const { user } = useAuthStore()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [tasks, setTasks] = useState<PendingTask[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    const [s, t] = await Promise.all([getDashboardStats(), getPendingTasks()])
    setStats(s)
    setTasks(t)
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // 下拉刷新（页面配置 enablePullDownRefresh 触发 onPullDownRefresh）
  usePullDownRefresh(async () => {
    await load()
    Taro.stopPullDownRefresh()
  })

  // 数字卡片
  const MetricCard = ({ label, value, change, sign, unit }: {
    label: string
    value: string
    change?: string
    sign?: string
    unit?: string
  }) => (
    <View className='metric-card'>
      <Text className='metric-card__label'>{label}</Text>
      <View className='metric-card__value-row'>
        <Text className='metric-card__value'>{value}</Text>
        {unit && <Text className='metric-card__unit'>{unit}</Text>}
      </View>
      {change && (
        <Text className={`metric-card__change ${sign === '+' ? 'metric-card__change--up' : sign === '-' ? 'metric-card__change--down' : ''}`}>
          {change}
        </Text>
      )}
    </View>
  )

  const totalSalesYuan = stats ? formatYuan(stats.todaySales) : '--'

  const renderLoading = () => (
    <View className='dashboard-loading'>
      <Text>加载经营数据中...</Text>
    </View>
  )

  if (loading && !stats) return renderLoading()

  return (
    <ScrollView scrollY className='dashboard-page'>
        {/* 头部问候 */}
        <View className='dashboard-header'>
          <Text className='dashboard-header__greet'>
            {user?.nickname ? `${user.nickname}，` : ''}今日经营一览
          </Text>
          <Text className='dashboard-header__sub'>数据来自米宝 · 每 30 分钟自动刷新</Text>
        </View>

        {/* 核心 5 数字（老板一屏） */}
        <View className='metric-grid'>
          <MetricCard
            label='今日销售额'
            value={totalSalesYuan}
            unit='元'
            change={formatPercent(stats?.todaySalesChange ?? 0)}
            sign={(stats?.todaySalesChange ?? 0) >= 0 ? '+' : '-'}
          />
          <MetricCard
            label='今日订单'
            value={String(stats?.todayOrders ?? '--')}
            change={formatPercent(stats?.todayOrdersChange ?? 0)}
            sign={(stats?.todayOrdersChange ?? 0) >= 0 ? '+' : '-'}
          />
          <MetricCard
            label='本月营收'
            value={stats ? formatYuan(stats.monthRevenue) : '--'}
            unit='元'
            change={formatPercent(stats?.monthRevenueChange ?? 0)}
            sign={(stats?.monthRevenueChange ?? 0) >= 0 ? '+' : '-'}
          />
          <MetricCard
            label='AI 接管率'
            value={`${stats?.aiSessionRate ?? '--'}%`}
          />
          <MetricCard
            label='活跃会话'
            value={String(stats?.activeSessions ?? '--')}
          />
        </View>

        {/* 第二行：客户/商品/售后 */}
        <View className='metric-grid metric-grid--secondary'>
          <MetricCard label='客户总数' value={String(stats?.totalCustomers ?? '--')} />
          <MetricCard label='今日新增客户' value={String(stats?.newCustomersToday ?? '--')} />
          <MetricCard label='在售商品' value={String(stats?.totalProducts ?? '--')} />
          <MetricCard label='待处理售后' value={String(stats?.totalTickets ?? '--')} />
          <MetricCard label='待发货' value={String(stats?.pendingShipOrders ?? '--')} />
        </View>

        {/* 待办（数字 → 一个动作） */}
        <View className='dashboard-section'>
          <Text className='dashboard-section__title'>待办事项</Text>
          {tasks.length === 0 ? (
            <View className='dashboard-empty'>
              <Text>暂无待办，AI 正在处理中</Text>
            </View>
          ) : (
            tasks.slice(0, 5).map(task => (
              <View key={`${task.type}-${task.id}`} className='task-item'>
                <View className='task-item__tag'>
                  <Text className={`task-item__tag-text task-item__tag-text--${task.type}`}>
                    {task.type === 'order' ? '订单' : '售后'}
                  </Text>
                </View>
                <View className='task-item__body'>
                  <Text className='task-item__title'>{task.title}</Text>
                  <Text className='task-item__time'>{task.createdAt ? task.createdAt.slice(0, 16).replace('T', ' ') : ''}</Text>
                </View>
                {task.priority === 'high' && (
                  <View className='task-item__urgent'>
                    <Text className='task-item__urgent-text'>紧急</Text>
                  </View>
                )}
              </View>
            ))
          )}
        </View>
      </ScrollView>
  )
}