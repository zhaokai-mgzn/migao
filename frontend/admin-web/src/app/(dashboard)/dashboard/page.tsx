'use client'

import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { ClipboardList, DollarSign, TrendingUp, Package, Settings, ArrowRight, RefreshCw, ArrowUp, ArrowDown } from 'lucide-react'
import { dashboardApi } from '@/lib/api'
import { cn, formatFullDateTime } from '@/lib/utils'
import type { DashboardStats, OrderTrendPoint, Order, ProductRanking } from '@/types'
import TodayOverviewBar from '@/components/dashboard/TodayOverviewBar'
import TrendChart from '@/components/dashboard/TrendChart'
import RecentOrders from '@/components/dashboard/RecentOrders'

// ═══════════════════════════════════════════════════════
// 格式化
// ═══════════════════════════════════════════════════════

function fmtCurrency(n: number): string {
  if (n >= 10000) {
    const w = parseFloat((n / 10000).toFixed(2))
    return '¥' + w + '万'
  }
  return '¥' + n.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
}

function fmtNum(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toLocaleString('zh-CN')
}

/** 涨跌百分比带符号：+25.5% / -12.3% / 0% */
function fmtSigned(n: number): string {
  if (!Number.isFinite(n)) return '—'
  if (n === 0) return '0%'
  const sign = n > 0 ? '+' : '-'
  return `${sign}${Math.abs(n)}%`
}

function now(): string {
  return formatFullDateTime(new Date().toISOString())
}

// ═══════════════════════════════════════════════════════
// 迷你趋势图（SVG）
// ═══════════════════════════════════════════════════════

function MiniSparkline({ data, color, width = 88, height = 30 }: { data: number[]; color: string; width?: number; height?: number }) {
  if (!data.length) return (
    <svg width={width} height={height} className="flex-shrink-0">
      <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="#E6DFD3" strokeWidth="1" strokeDasharray="3 3" />
    </svg>
  )
  const max = Math.max(...data, 1)
  const min = Math.min(...data, 0)
  const range = max - min || 1
  const points = data.map((v, i) => `${(i / (data.length - 1)) * width},${height - ((v - min) / range) * (height - 6) - 3}`).join(' ')
  const gradId = `spark-${color.replace('#', '')}`
  return (
    <svg width={width} height={height} className="flex-shrink-0">
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.22" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`0,${height} ${points} ${width},${height}`} fill={`url(#${gradId})`} />
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function MiniBarChart({ data, color, width = 88, height = 30 }: { data: number[]; color: string; width?: number; height?: number }) {
  if (!data.length) return (
    <svg width={width} height={height} className="flex-shrink-0">
      <line x1="0" y1={height / 2} x2={width} y2={height / 2} stroke="#E6DFD3" strokeWidth="1" strokeDasharray="3 3" />
    </svg>
  )
  const barW = Math.max(2, width / data.length - 2)
  const max = Math.max(...data, 1)
  return (
    <svg width={width} height={height} className="flex-shrink-0">
      {data.map((v, i) => (
        <rect key={i} x={i * (barW + 2)} y={height - (v / max) * (height - 4)} width={barW} height={(v / max) * (height - 4)} fill={color} rx="2" opacity="0.78" />
      ))}
    </svg>
  )
}

function ChartSkeleton({ bars = 7, heights }: { bars?: number; heights?: number[] }) {
  const h = heights || [35, 55, 28, 62, 42, 50, 38]
  return (
    <div className="h-full flex flex-col justify-end relative">
      <svg className="absolute inset-0 w-full h-full" viewBox="0 0 400 200" preserveAspectRatio="none">
        <line x1="40" y1="10" x2="40" y2="170" stroke="#F2EDE5" strokeWidth="1" />
        <line x1="40" y1="170" x2="380" y2="170" stroke="#F2EDE5" strokeWidth="1" />
        {[30, 65, 100, 135].map((y, i) => (
          <line key={i} x1="40" y1={y} x2="380" y2={y} stroke="#F2EDE5" strokeWidth="1" strokeDasharray="4 4" />
        ))}
      </svg>
      <div className="relative z-10 flex items-end gap-2 px-[10%] pb-5">
        {h.slice(0, bars).map((pct, i) => (
          <div key={i} className="flex-1 bg-neutral-100 rounded-sm animate-pulse" style={{ height: `${Math.min(pct, 85)}%` }} />
        ))}
      </div>
    </div>
  )
}

// ═══════════════════════════════════════════════════════
// 子组件
// ═══════════════════════════════════════════════════════

const METRIC_STYLES: Record<string, { tile: string; icon: string; spark: string }> = {
  orders:  { tile: 'bg-primary-50',  icon: 'text-primary-600',  spark: '#48618f' },
  sales:   { tile: 'bg-accent-50',   icon: 'text-accent-600',   spark: '#c06a3e' },
  month:   { tile: 'bg-amber-50',    icon: 'text-amber-600',    spark: '#b8933d' },
}

function BizStatCard({ title, value, change, hint, icon, sparkline, chartType, metric = 'orders' }: {
  title: string; value: string; change?: { text: string; up: boolean }; hint?: string; icon: React.ReactNode; sparkline?: number[]; chartType?: 'line' | 'bar'; metric?: keyof typeof METRIC_STYLES
}) {
  const style = METRIC_STYLES[metric] || METRIC_STYLES.orders
  return (
    <div className="group bg-white rounded-xl border border-neutral-200 shadow-card p-5 transition-all hover:-translate-y-0.5 hover:shadow-card-hover animate-fade-in-up">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <span className={cn('p-2 rounded-lg', style.tile)}>{icon}</span>
          <span className="text-sm text-neutral-500">{title}</span>
        </div>
        {change && (
          <span className={cn(
            'inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-medium',
            change.up ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'
          )}>
            {change.up ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
            {change.text}
          </span>
        )}
      </div>
      <div className="flex items-end justify-between">
        <div>
          <p className="tnum text-[26px] font-bold leading-none text-neutral-900">{value}</p>
          {hint && <p className="mt-1.5 text-xs text-neutral-400">{hint}</p>}
        </div>
        {sparkline && (chartType === 'bar'
          ? <MiniBarChart data={sparkline} color={style.spark} />
          : <MiniSparkline data={sparkline} color={style.spark} />
        )}
      </div>
    </div>
  )
}

const PENDING_COLORS: Record<string, { tile: string; icon: string }> = {
  blue:   { tile: 'bg-primary-50',  icon: 'text-primary-600' },
  purple: { tile: 'bg-accent-50',   icon: 'text-accent-600' },
  red:    { tile: 'bg-red-50',      icon: 'text-red-600' },
  amber:  { tile: 'bg-amber-50',    icon: 'text-amber-600' },
  green:  { tile: 'bg-emerald-50',  icon: 'text-emerald-600' },
}

function PendingCard({ title, count, icon, color }: { title: string; count: number; icon: React.ReactNode; color: string }) {
  const c = PENDING_COLORS[color] || PENDING_COLORS.blue
  return (
    <div className="group flex items-center gap-3.5 rounded-xl border border-neutral-200 bg-white p-4 shadow-card transition-all hover:-translate-y-0.5 hover:shadow-card-hover">
      <span className={cn('p-2.5 rounded-lg transition-transform group-hover:scale-105', c.tile)}>{icon}</span>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-neutral-500">{title}</p>
        <p className="tnum text-2xl font-bold leading-tight text-neutral-900">{fmtNum(count)}</p>
      </div>
      <ArrowRight className="w-4 h-4 text-neutral-300 transition-all group-hover:translate-x-0.5 group-hover:text-primary-500" />
    </div>
  )
}

/** 区块标题：左侧色点 + 标题（与洞察条/卡片同源的主色体系） */
function SectionHeading({ icon, colorClass, children }: { icon: React.ReactNode; colorClass: string; children: React.ReactNode }) {
  return (
    <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-neutral-700">
      <span className={cn('flex h-6 w-6 items-center justify-center rounded-md', colorClass)}>{icon}</span>
      {children}
    </h2>
  )
}

// ═══════════════════════════════════════════════════════
// 主页面
// ═══════════════════════════════════════════════════════

export default function DashboardPage() {
  const [loading, setLoading] = useState(true)
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [trendData, setTrendData] = useState<OrderTrendPoint[]>([])
  const [recentOrders, setRecentOrders] = useState<Order[]>([])
  const [ranking, setRanking] = useState<ProductRanking[]>([])
  const [pendingShipment, setPendingShipment] = useState(0)
  const [processingShipment, setProcessingShipment] = useState(0)
  const [lowStockCount, setLowStockCount] = useState(0)
  const [trendDays, setTrendDays] = useState(7)
  const [updateTime, setUpdateTime] = useState('--')

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      // #2886: 4 个接口一次并发（原 3 波串行 → 1 波，整页接口等待从 ~640ms 降到单波 max）
      //   pendingShipOrders / processingPendingOrders / lowStockItems 均由 stats 聚合返回，
      //   不再单独请求 pending-shipment-count / processing-shipment-count 两个重复计数接口
      const [statsRes, trendRes, ordersRes, rkRes] = await Promise.allSettled([
        dashboardApi.getStats(),
        dashboardApi.getOrderTrend(trendDays),
        dashboardApi.getRecentOrders(5),
        dashboardApi.getProductRanking('day', 10),
      ])

      if (statsRes.status === 'fulfilled') {
        const s = statsRes.value.data.data
        setStats(s)
        setLowStockCount(s.lowStockItems ?? 0)
        setPendingShipment(s.pendingShipOrders ?? 0)
        setProcessingShipment(s.processingPendingOrders ?? 0)
      } else {
        console.error('Dashboard stats:', statsRes.reason)
      }
      if (trendRes.status === 'fulfilled') {
        setTrendData(Array.isArray(trendRes.value.data.data) ? trendRes.value.data.data : [])
      } else {
        console.error('Dashboard trend:', trendRes.reason)
      }
      if (ordersRes.status === 'fulfilled') {
        setRecentOrders(ordersRes.value.data.data || [])
      } else {
        console.error('Dashboard recent orders:', ordersRes.reason)
      }
      if (rkRes.status === 'fulfilled') {
        setRanking((rkRes.value.data as any)?.data || [])
      } else {
        console.error('Dashboard ranking:', rkRes.reason)
      }
      setUpdateTime(now())
    } catch (error) {
      // Promise.allSettled 不会整体 reject，此分支仅兜底
      console.error('Dashboard load:', error)
    } finally {
      setLoading(false)
    }
  }, [trendDays])

  useEffect(() => { fetchData() }, [fetchData])

  // 从 trend 数据提取迷你图
  const sparkline = trendData.map(d => d.orders || 0).slice(-14)

  // 销售额序列（真实 amount 字段，单位分；不再用 23.8 假乘数估算）
  const salesSeries = trendData.map(d => d.amount || 0)

  // 客单价 = 今日销售额 ÷ 今日订单数（数字自洽：订单数 × 客单价 ≈ 销售额）
  const avgOrderValue = (stats?.todayOrders ?? 0) > 0
    ? Math.round((stats?.todaySales ?? 0) / (stats?.todayOrders ?? 1))
    : 0

  // 销量排行最大值（进度条基准）
  const maxSalesQty = Math.max(...ranking.map(r => r.salesQty || 0), 1)

  return (
    <div className="p-5 sm:p-6">
      {/* 顶部 */}
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-neutral-900">经营看板</h1>
          <p className="mt-0.5 text-xs text-neutral-400">数据更新时间：{updateTime}</p>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-1.5 rounded-lg border border-neutral-200 bg-white px-3 py-1.5 text-xs font-medium text-neutral-500 shadow-card transition-colors hover:border-primary-200 hover:text-primary-600"
        >
          <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
          刷新
        </button>
      </div>

      {/* 米宝「今日经营速览」洞察条 — 一句话经营解读，置于页面顶部 */}
      <TodayOverviewBar
        todayOrders={stats?.todayOrders ?? 0}
        todaySales={stats?.todaySales ?? 0}
        orderChange={stats?.todayOrdersChange ?? 0}
        salesChange={stats?.todaySalesChange ?? 0}
        processingCount={processingShipment}
        pendingCount={pendingShipment}
        lowStockCount={lowStockCount}
      />

      {/* ① 待处理任务 */}
      <div className="mb-6">
        <SectionHeading icon={<Package className="h-3.5 w-3.5 text-amber-600" />} colorClass="bg-amber-50">待处理</SectionHeading>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <Link href="/orders?status=待发货"><PendingCard title="待发货订单" count={pendingShipment} icon={<Package className="w-4 h-4 text-primary-600" />} color="blue" /></Link>
          <Link href="/orders?category=含加工订单&status=待发货"><PendingCard title="含加工待发货订单" count={processingShipment} icon={<Settings className="w-4 h-4 text-accent-600" />} color="purple" /></Link>
          <Link href="/products?low_stock=true"><PendingCard title="待补库存商品" count={lowStockCount} icon={<Package className="w-4 h-4 text-red-600" />} color="red" /></Link>
        </div>
      </div>

      {/* ② 经营数据卡片（4 卡自洽：订单数 × 客单价 ≈ 销售额） */}
      <div className="mb-6">
        <SectionHeading icon={<TrendingUp className="h-3.5 w-3.5 text-primary-600" />} colorClass="bg-primary-50">经营数据</SectionHeading>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {loading ? (
            Array.from({ length: 4 }).map((_, i) => <div key={i} className="bg-white rounded-xl border border-neutral-200 shadow-card h-[120px] animate-pulse p-5" />)
          ) : (
            <>
              <BizStatCard
                metric="orders"
                title="今日订单数"
                value={stats?.todayOrders?.toLocaleString() || '0'}
                change={{ text: `较昨日 ${fmtSigned(stats?.todayOrdersChange ?? 0)}`, up: (stats?.todayOrdersChange ?? 0) > 0 }}
                icon={<ClipboardList className="w-4 h-4 text-primary-600" />}
                sparkline={sparkline}
                chartType="line"
              />
              <BizStatCard
                metric="sales"
                title="今日销售额"
                value={fmtCurrency(stats?.todaySales || 0)}
                change={{ text: `较昨日 ${fmtSigned(stats?.todaySalesChange ?? 0)}`, up: (stats?.todaySalesChange ?? 0) > 0 }}
                icon={<DollarSign className="w-4 h-4 text-emerald-600" />}
                sparkline={salesSeries.slice(-14)}
                chartType="bar"
              />
              <BizStatCard
                metric="month"
                title="客单价"
                value={avgOrderValue > 0 ? fmtCurrency(avgOrderValue) : '—'}
                hint={avgOrderValue > 0 ? '今日每单平均消费' : '暂无订单'}
                icon={<TrendingUp className="w-4 h-4 text-accent-600" />}
              />
              <BizStatCard
                metric="month"
                title="本月销售额"
                value={fmtCurrency(stats?.monthRevenue || 0)}
                change={{ text: `较上月 ${fmtSigned(stats?.monthRevenueChange ?? 0)}`, up: (stats?.monthRevenueChange ?? 0) > 0 }}
                icon={<DollarSign className="w-4 h-4 text-accent-600" />}
              />
            </>
          )}
        </div>
      </div>

      {/* ③ 趋势图 */}
      <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* 订单趋势 */}
        <div className="bg-white rounded-xl border border-neutral-200 shadow-card p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-neutral-800">订单趋势</h3>
            <div className="flex gap-1 rounded-lg bg-neutral-100 p-0.5">
              {[7, 30].map(d => (
                <button key={d} onClick={() => setTrendDays(d)}
                  className={cn(
                    'rounded-md px-3 py-1 text-xs font-medium transition-all',
                    trendDays === d ? 'bg-white text-primary-700 shadow-sm' : 'text-neutral-500 hover:text-neutral-700'
                  )}>
                  近{d}天
                </button>
              ))}
            </div>
          </div>
          <div className="h-[240px]">
            {loading ? (
              <ChartSkeleton bars={7} />
            ) : trendData.length > 0 ? (
              <TrendChart
                data={trendData}
                series={[{ key: 'orders', name: '订单数', color: '#48618f', dots: true }]}
                formatValue={fmtNum}
              />
            ) : (
              <div className="h-full flex flex-col items-center justify-center">
                <div className="flex flex-col items-center">
                  <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-50 to-indigo-50">
                    <TrendingUp className="w-6 h-6 text-primary-400" />
                  </div>
                  <p className="text-sm font-medium text-neutral-500">暂无订单数据</p>
                  <p className="mt-1 mb-4 text-xs text-neutral-400">创建订单后，趋势图将在此展示</p>
                  <Link href="/orders/new" className="inline-flex items-center gap-1.5 rounded-lg bg-primary-500 px-3.5 py-2 text-xs font-medium text-white shadow-sm transition-colors hover:bg-primary-600">
                    创建订单 <ArrowRight className="w-3 h-3" />
                  </Link>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* 销售额趋势 */}
        <div className="bg-white rounded-xl border border-neutral-200 shadow-card p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-neutral-800">销售额数据</h3>
            <span className="text-xs text-neutral-400">数据更新时间：{updateTime === '--' ? updateTime : updateTime.slice(11, 19)}</span>
          </div>
          <div className="h-[240px]">
            {loading ? (
              <ChartSkeleton bars={7} heights={[45, 32, 58, 25, 52, 38, 48]} />
            ) : trendData.length > 0 ? (
              <TrendChart
                data={trendData}
                series={[{ key: 'amount', name: '销售额', color: '#c06a3e', area: true, dots: true }]}
                formatValue={fmtCurrency}
              />
            ) : (
              <div className="h-full flex flex-col items-center justify-center">
                <div className="flex flex-col items-center">
                  <div className="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-accent-50 to-orange-50">
                    <DollarSign className="w-6 h-6 text-accent-400" />
                  </div>
                  <p className="text-sm font-medium text-neutral-500">暂无销售额数据</p>
                  <p className="mt-1 mb-4 text-xs text-neutral-400">产生订单后，销售趋势将在此展示</p>
                  <Link href="/orders/new" className="inline-flex items-center gap-1.5 rounded-lg bg-accent-500 px-3.5 py-2 text-xs font-medium text-white shadow-sm transition-colors hover:bg-accent-600">
                    创建订单 <ArrowRight className="w-3 h-3" />
                  </Link>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ④ 列表 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* 近期订单 — #2544: 复用 RecentOrders 组件（语义色 chips + 空态治理） */}
        <RecentOrders
          orders={recentOrders}
          loading={loading}
          emptyText="暂无近期订单"
          emptyHint="新订单将在此展示"
        />

        {/* 商品销量排行 */}
        <div className="bg-white rounded-xl border border-neutral-200 shadow-card p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-neutral-800">商品销量排行</h3>
            <a href="/products?sortBy=salesCount&sortOrder=desc" className="flex items-center gap-1 text-xs text-primary-600 hover:underline">查看更多 <ArrowRight className="w-3 h-3" /></a>
          </div>
          {loading ? (
            <div className="space-y-2">{Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-9 animate-pulse rounded bg-neutral-100" />)}</div>
          ) : ranking.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-10">
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-amber-50 to-orange-50">
                <Package className="w-5 h-5 text-amber-400" />
              </div>
              <p className="text-sm font-medium text-neutral-500">暂无排行数据</p>
              <p className="mt-1 text-xs text-neutral-400">产生订单后，销量排行将在此展示</p>
            </div>
          ) : (
            <table className="w-full text-xs">
              <thead><tr className="border-b border-neutral-100 text-neutral-400"><th className="w-10 py-2 text-left font-medium whitespace-nowrap">#</th><th className="py-2 text-left font-medium whitespace-nowrap">商品</th><th className="py-2 text-right font-medium whitespace-nowrap">成交量</th><th className="py-2 text-right font-medium whitespace-nowrap" title="较昨日销量涨跌幅">日涨</th></tr></thead>
              <tbody>
                {ranking.slice(0, 10).map(r => (
                  <tr key={r.productId} className="border-b border-neutral-50 transition-colors hover:bg-neutral-50/70">
                    <td className="py-2.5">
                      <span className={cn(
                        'inline-flex h-5 w-5 items-center justify-center rounded-md text-[11px] font-semibold',
                        r.rank === 1 ? 'bg-amber-100 text-amber-700' :
                        r.rank === 2 ? 'bg-neutral-200 text-neutral-600' :
                        r.rank === 3 ? 'bg-accent-100 text-accent-700' :
                        'text-neutral-400'
                      )}>
                        {r.rank}
                      </span>
                    </td>
                    <td className="max-w-[160px] py-2.5">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-neutral-700" title={r.productName}>{r.productName}</span>
                      </div>
                      {/* 销量进度条 — 相对当日冠军的占比 */}
                      <div className="mt-1 h-1 w-full max-w-[140px] overflow-hidden rounded-full bg-neutral-100">
                        <div className="h-full rounded-full bg-gradient-to-r from-primary-400 to-primary-500" style={{ width: `${Math.min(100, (r.salesQty || 0) / maxSalesQty * 100)}%` }} />
                      </div>
                    </td>
                    <td className="tnum py-2.5 text-right font-mono text-neutral-900 whitespace-nowrap">{r.qtyDisplay}</td>
                    <td className={cn('py-2.5 text-right whitespace-nowrap', r.dailyChange > 0 ? 'text-emerald-600' : 'text-red-500')}>
                      {r.dailyChange > 0 ? '▲' : '▼'} {Math.abs(r.dailyChange)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
