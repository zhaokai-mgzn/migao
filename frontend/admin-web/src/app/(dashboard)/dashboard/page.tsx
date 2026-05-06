'use client'

import { useState, useEffect, useCallback } from 'react'
import {
  ClipboardList,
  Users,
  MessageSquare,
  DollarSign,
  Plus,
  FileUp,
  CalendarDays,
} from 'lucide-react'
import Link from 'next/link'
import { toast } from 'sonner'
import { useAuthStore } from '@/store/auth'
import { dashboardApi } from '@/lib/api'
import StatCard from '@/components/dashboard/StatCard'
import OrderTrendChart from '@/components/dashboard/OrderTrendChart'
import OrderStatusChart from '@/components/dashboard/OrderStatusChart'
import RecentOrders from '@/components/dashboard/RecentOrders'
import ActiveSessions from '@/components/dashboard/ActiveSessions'
import type {
  DashboardStats,
  OrderTrendPoint,
  OrderStatusDistribution,
  Order,
  ActiveSession,
} from '@/types'

// ========== 格式化工具 ==========

function formatCurrency(amount: number): string {
  if (amount >= 10000) {
    return '¥' + (amount / 10000).toFixed(1) + '万'
  }
  return '¥' + amount.toLocaleString('zh-CN')
}

function formatDate(): string {
  const now = new Date()
  const weekdays = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六']
  return `${now.getFullYear()}年${now.getMonth() + 1}月${now.getDate()}日 ${weekdays[now.getDay()]}`
}

// ========== Dashboard 页面 ==========

export default function DashboardPage() {
  const { user } = useAuthStore()
  const [loading, setLoading] = useState(true)
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [trendData, setTrendData] = useState<OrderTrendPoint[]>([])
  const [statusData, setStatusData] = useState<OrderStatusDistribution[]>([])
  const [recentOrders, setRecentOrders] = useState<Order[]>([])
  const [activeSessions, setActiveSessions] = useState<ActiveSession[]>([])

  // 获取仪表盘数据
  const fetchDashboardData = useCallback(async () => {
    setLoading(true)
    try {
      const [statsRes, trendRes, statusRes, ordersRes, sessionsRes] = await Promise.all([
        dashboardApi.getStats(),
        dashboardApi.getOrderTrend(7),
        dashboardApi.getOrderStatusDistribution(),
        dashboardApi.getRecentOrders(5),
        dashboardApi.getActiveSessions(5),
      ])
      setStats(statsRes.data.data)
      setTrendData(trendRes.data.data)
      setStatusData(statusRes.data.data)
      setRecentOrders(ordersRes.data.data)
      setActiveSessions(sessionsRes.data.data)
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error)
      toast.error('加载仪表盘数据失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDashboardData()
  }, [fetchDashboardData])

  const handleTrendRangeChange = async (days: number) => {
    try {
      const res = await dashboardApi.getOrderTrend(days)
      setTrendData(res.data.data)
    } catch (error) {
      console.error('Failed to fetch trend data:', error)
      toast.error('加载订单趋势数据失败')
    }
  }

  const statCards = stats
    ? [
        {
          title: '今日订单',
          value: stats.todayOrders.toLocaleString(),
          change: {
            value: `${stats.todayOrdersChange > 0 ? '+' : ''}${stats.todayOrdersChange}% 较昨日`,
            isPositive: stats.todayOrdersChange > 0,
          },
          icon: <ClipboardList className="w-5 h-5 text-blue-600" />,
          iconBgColor: 'bg-blue-50',
        },
        {
          title: '客户总数',
          value: stats.totalCustomers.toLocaleString(),
          change: {
            value: `+${stats.newCustomersToday} 今日新增`,
            isPositive: true,
          },
          icon: <Users className="w-5 h-5 text-purple-600" />,
          iconBgColor: 'bg-purple-50',
        },
        {
          title: '活跃会话',
          value: stats.activeSessions.toLocaleString(),
          description: `AI 处理 ${stats.aiSessionRate}%`,
          icon: <MessageSquare className="w-5 h-5 text-green-600" />,
          iconBgColor: 'bg-green-50',
        },
        {
          title: '本月收入',
          value: formatCurrency(stats.monthRevenue),
          change: {
            value: `${stats.monthRevenueChange > 0 ? '+' : ''}${stats.monthRevenueChange}% 较上月`,
            isPositive: stats.monthRevenueChange > 0,
          },
          icon: <DollarSign className="w-5 h-5 text-orange-600" />,
          iconBgColor: 'bg-orange-50',
        },
      ]
    : []

  return (
    <div className="p-6 -m-0">
      {/* 顶部欢迎区 */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-6 gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">
            欢迎回来，{user?.name || user?.nickname || user?.username || '管理员'} 👋
          </h1>
          <p className="text-sm text-gray-500 mt-1 flex items-center gap-1.5">
            <CalendarDays className="w-3.5 h-3.5" />
            {formatDate()}
          </p>
        </div>
        <div className="flex gap-2">
          <Link
            href="/orders"
            className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-primary-600 text-white text-sm font-medium rounded-lg hover:bg-primary-700 transition-colors"
          >
            <Plus className="w-4 h-4" />
            新建订单
          </Link>
          <Link
            href="/knowledge"
            className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-white text-gray-700 text-sm font-medium rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors"
          >
            <FileUp className="w-4 h-4" />
            上传文档
          </Link>
        </div>
      </div>

      {/* 统计卡片 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {loading
          ? Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="bg-white rounded-xl border border-gray-100 p-5 animate-pulse">
                <div className="h-4 bg-gray-100 rounded w-20 mb-3" />
                <div className="h-7 bg-gray-100 rounded w-24 mb-2" />
                <div className="h-3 bg-gray-100 rounded w-28" />
              </div>
            ))
          : statCards.map((card, index) => <StatCard key={index} {...card} />)}
      </div>

      {/* 图表区 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        <OrderTrendChart data={trendData} loading={loading} onRangeChange={handleTrendRangeChange} />
        <OrderStatusChart data={statusData} loading={loading} />
      </div>

      {/* 列表区 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <RecentOrders orders={recentOrders} loading={loading} />
        <ActiveSessions sessions={activeSessions} loading={loading} />
      </div>
    </div>
  )
}
