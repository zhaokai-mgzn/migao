'use client'

import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { ClipboardList, DollarSign, TrendingUp, Package, Settings, ArrowRight, RefreshCw, ArrowUp, ArrowDown, AlertTriangle, Headphones } from 'lucide-react'
import { dashboardApi } from '@/lib/api'
// issue #5792：可插拔指标卡的**注册表**（能力位判定收敛在 lib 里，组件不散落 if）
import { visiblePluggableCards } from '@/lib/dashboard-cards'
import { useAuthStore } from '@/store/auth'
import { cn, formatFullDateTime } from '@/lib/utils'
import type { DashboardStats, OrderTrendPoint, Order, ProductRanking, OrderStatusDistribution } from '@/types'
import TodayOverviewBar from '@/components/dashboard/TodayOverviewBar'
import TrendChart from '@/components/dashboard/TrendChart'
import RecentOrders from '@/components/dashboard/RecentOrders'
import BriefingCard from '@/components/dashboard/BriefingCard'
// issue #5792 第二阶段：订单状态分布（端点与组件此前都已写好，但**从未接线** —— 本次接上）
import OrderStatusChart from '@/components/dashboard/OrderStatusChart'

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

/** 分块失败告警里显示的**人话块名**（键 = Promise.allSettled 的四块） */
const BLOCK_LABELS: Record<string, string> = {
  stats: '经营数据与待处理',
  trend: '趋势图',
  orders: '近期订单',
  ranking: '商品销量排行',
  orderStatus: '订单状态分布',
}

/**
 * 环比徽章（issue #5792 口径整改）：`null` = **无上期可比** ⇒ 文案「—」+ 悬停说明。
 *
 * 为什么不是 0%：0% 的语义是「与上期**持平**」，与「上期为 0、根本没有可比基数」是两件事；
 * 折叠成 0% 会被读成「没有变化」⇒ 误导（加了这个悬停说明，才让「—」可解释）。
 */
function changeBadge(
  prefix: string,
  v: number | null | undefined,
): { text: string; up: boolean; title: string; neutral: boolean } {
  if (v == null) {
    // ⚠️ `neutral` 必须显式带上：否则徽章会落到「非上涨 = 红色 + 向下箭头」那一支，
    //    把「没有可比基数」画成**下跌** —— 又是一种误导。
    return { text: `${prefix} —`, up: false, neutral: true, title: '无上期可比（上期为 0）—— 这不是「与上期持平」' }
  }
  return { text: `${prefix} ${fmtSigned(v)}`, up: v > 0, neutral: false, title: '' }
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
  title: string; value: string; change?: { text: string; up: boolean; title?: string; neutral?: boolean }; hint?: string; icon: React.ReactNode; sparkline?: number[]; chartType?: 'line' | 'bar'; metric?: keyof typeof METRIC_STYLES
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
          <span
            title={change.title || undefined}
            className={cn(
              'inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-medium',
              change.neutral
                ? 'bg-neutral-100 text-neutral-500'
                : change.up
                  ? 'bg-emerald-50 text-emerald-600'
                  : 'bg-red-50 text-red-600'
            )}
          >
            {/* 中性态**不画箭头**：没有可比基数时，任何方向箭头都是编造 */}
            {!change.neutral && (change.up ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)}
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
  // issue #5792 第二阶段：待支付订单（钱还没到）
  const [pendingPayment, setPendingPayment] = useState(0)
  // issue #5792：超时工单（口径与简报快照、工单列表筛选同源）
  const [overdueTickets, setOverdueTickets] = useState(0)
  const [processingShipment, setProcessingShipment] = useState(0)
  const [lowStockCount, setLowStockCount] = useState(0)
  const [trendDays, setTrendDays] = useState(7)
  const [updateTime, setUpdateTime] = useState('--')
  // 🔴 issue #5792（客观缺陷 ④）：**失败态与空数据必须可区分**。
  // 改前：4 个接口任一失败只 `console.error` ⇒ UI 退化成「空态」或「0」，
  // 商家无法区分「今天没单」与「接口挂了」—— 加了指标之后这会直接影响决策。
  // 口径：① 失败**不清零**（保留上次成功值，避免把故障画成业务事实）；② 显式告警 + 分块列出；
  //       ③ 重试**只重发失败的那一块**（已成功的块不重复打后端）。
  const [blockErrors, setBlockErrors] = useState<Record<string, string>>({})
  // 服务端下发的能力位（issue #5792）：端侧**不判权限码**，只消费布尔位
  const capabilities = useAuthStore((st) => st.user?.capabilities)
  const pluggableCards = visiblePluggableCards(capabilities)
  // ⚠️ 标记的读/清一律**就地内联**成 `setBlockErrors(...)`，不抽组件内小函数：
  //    `fetchData`（useCallback）声明的更早，抽函数会形成前向引用，ESLint `react-hooks/immutability`
  //    判 **error**（本地 `tsc` 看不见，CI 的 eslint 步会红 —— 已实跑踩过）。
  // 智能每日经营简报：企业开关状态（默认关，关闭不渲染简报卡，红线 3）
  const [briefingEnabled, setBriefingEnabled] = useState(false)
  const [orderStatus, setOrderStatus] = useState<OrderStatusDistribution[]>([])

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      // #2886: 4 个接口一次并发（原 3 波串行 → 1 波，整页接口等待从 ~640ms 降到单波 max）
      //   pendingShipOrders / processingPendingOrders / lowStockItems 均由 stats 聚合返回，
      //   不再单独请求 pending-shipment-count / processing-shipment-count 两个重复计数接口
      const [statsRes, trendRes, ordersRes, rkRes, osRes] = await Promise.allSettled([
        dashboardApi.getStats(),
        dashboardApi.getOrderTrend(trendDays),
        dashboardApi.getRecentOrders(5),
        dashboardApi.getProductRanking('day', 10),
        dashboardApi.getOrderStatusDistribution(),
      ])

      // 每块：成功 ⇒ 清掉自己的失败标记；失败 ⇒ 记标记 + **不动**上次成功值（不清零）
      if (statsRes.status === 'fulfilled') {
        const s = statsRes.value.data.data
        setStats(s)
        setLowStockCount(s.lowStockItems ?? 0)
        setPendingShipment(s.pendingShipOrders ?? 0)
        setPendingPayment(s.pendingPaymentOrders ?? 0)
        setOverdueTickets(s.overdueTickets ?? 0)
        setProcessingShipment(s.processingPendingOrders ?? 0)
        setBlockErrors((prev) => {
          if (!('stats' in prev)) return prev
          const next = { ...prev }
          delete next.stats
          return next
        })
      } else {
        console.error('Dashboard stats:', statsRes.reason)
        setBlockErrors((prev) => ({ ...prev, stats: BLOCK_LABELS.stats }))
      }
      if (trendRes.status === 'fulfilled') {
        setTrendData(Array.isArray(trendRes.value.data.data) ? trendRes.value.data.data : [])
        setBlockErrors((prev) => {
          if (!('trend' in prev)) return prev
          const next = { ...prev }
          delete next.trend
          return next
        })
      } else {
        console.error('Dashboard trend:', trendRes.reason)
        setBlockErrors((prev) => ({ ...prev, trend: BLOCK_LABELS.trend }))
      }
      if (ordersRes.status === 'fulfilled') {
        setRecentOrders(ordersRes.value.data.data || [])
        setBlockErrors((prev) => {
          if (!('orders' in prev)) return prev
          const next = { ...prev }
          delete next.orders
          return next
        })
      } else {
        console.error('Dashboard recent orders:', ordersRes.reason)
        setBlockErrors((prev) => ({ ...prev, orders: BLOCK_LABELS.orders }))
      }
      if (rkRes.status === 'fulfilled') {
        setRanking((rkRes.value.data as any)?.data || [])
        setBlockErrors((prev) => {
          if (!('ranking' in prev)) return prev
          const next = { ...prev }
          delete next.ranking
          return next
        })
      } else {
        console.error('Dashboard ranking:', rkRes.reason)
        setBlockErrors((prev) => ({ ...prev, ranking: BLOCK_LABELS.ranking }))
      }
      if (osRes.status === 'fulfilled') {
        setOrderStatus(Array.isArray(osRes.value.data.data) ? osRes.value.data.data : [])
        setBlockErrors((prev) => {
          if (!('orderStatus' in prev)) return prev
          const next = { ...prev }
          delete next.orderStatus
          return next
        })
      } else {
        console.error('Dashboard order status:', osRes.reason)
        setBlockErrors((prev) => ({ ...prev, orderStatus: BLOCK_LABELS.orderStatus }))
      }
      setUpdateTime(now())
    } catch (error) {
      // Promise.allSettled 不会整体 reject，此分支仅兜底
      console.error('Dashboard load:', error)
    } finally {
      setLoading(false)
    }
  }, [trendDays])

  /**
   * 只重试**失败的那一块**（issue #5792 ④）—— 已成功的块不重复打后端。
   * 与整页「刷新」的区别：刷新会重发 4 个接口；重试只补缺口。
   */
  const retryBlock = useCallback(async (key: string) => {
    try {
      if (key === 'stats') {
        const r = await dashboardApi.getStats()
        const s = r.data.data
        setStats(s)
        setLowStockCount(s.lowStockItems ?? 0)
        setPendingShipment(s.pendingShipOrders ?? 0)
        setPendingPayment(s.pendingPaymentOrders ?? 0)
        setProcessingShipment(s.processingPendingOrders ?? 0)
      } else if (key === 'trend') {
        const r = await dashboardApi.getOrderTrend(trendDays)
        setTrendData(Array.isArray(r.data.data) ? r.data.data : [])
      } else if (key === 'orders') {
        const r = await dashboardApi.getRecentOrders(5)
        setRecentOrders(r.data.data || [])
      } else if (key === 'ranking') {
        const r = await dashboardApi.getProductRanking('day', 10)
        setRanking((r.data as any)?.data || [])
      } else if (key === 'orderStatus') {
        const r = await dashboardApi.getOrderStatusDistribution()
        setOrderStatus(Array.isArray(r.data.data) ? r.data.data : [])
      }
      setBlockErrors((prev) => {
        if (!(key in prev)) return prev
        const next = { ...prev }
        delete next[key]
        return next
      })
    } catch (error) {
      console.error('Dashboard retry:', key, error)
      setBlockErrors((prev) => ({ ...prev, [key]: BLOCK_LABELS[key] ?? key }))
    }
  }, [trendDays])

  // 拉取简报企业开关（开关关闭时不渲染简报卡；失败默认关闭，不影响看板主体）
  useEffect(() => {
    import('@/lib/api').then(({ briefingApi }) =>
      briefingApi.getConfig()
        .then((res) => setBriefingEnabled(!!res.data.data?.enabled))
        .catch(() => setBriefingEnabled(false))
    )
  }, [])

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

  // 失败块（按 BLOCK_LABELS 的声明顺序稳定输出，便于判据断言与用户扫读）
  const failedBlocks = Object.keys(BLOCK_LABELS).filter((k) => k in blockErrors).map((k) => BLOCK_LABELS[k])
  const errorKeyOfLabel = (label: string) =>
    Object.keys(BLOCK_LABELS).find((k) => BLOCK_LABELS[k] === label) ?? label

  return (
    <div className="p-5 sm:p-6">
      {/* 顶部 */}
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-neutral-900">经营看板</h1>
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

      {/* 🔴 失败态显式告警（issue #5792 ④）：与空态**可区分** —— 空态说「暂无数据」，
          这里说「加载失败 + 是哪几块 + 上次成功值仍在」。不清零是关键：把故障画成 0 = 误导决策。 */}
      {failedBlocks.length > 0 && (
        <div
          data-testid="dashboard-load-failed"
          role="alert"
          className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800"
        >
          <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
          <span className="font-medium">数据加载失败：{failedBlocks.join('、')}</span>
          <span className="text-amber-700">下方显示的仍是上次成功取到的值（不是 0，也不是「暂无数据」）</span>
          <button
            type="button"
            data-testid="dashboard-retry-block"
            onClick={() => failedBlocks.forEach((b) => retryBlock(errorKeyOfLabel(b)))}
            className="ml-auto rounded border border-amber-300 bg-white/70 px-2 py-0.5 font-medium text-amber-800 transition-colors hover:bg-white"
          >
            只重试失败项
          </button>
        </div>
      )}

      {/* 米宝「今日经营速览」洞察条 — 一句话经营解读，置于页面顶部 */}
      <TodayOverviewBar
        todayOrders={stats?.todayOrders ?? 0}
        todaySales={stats?.todaySales ?? 0}
        orderChange={stats?.todayOrdersChange ?? null}
        salesChange={stats?.todaySalesChange ?? null}
        processingCount={processingShipment}
        pendingCount={pendingShipment}
        lowStockCount={lowStockCount}
      />

      {/* 智能每日经营简报（企业开关开启才渲染，红线 3） */}
      <BriefingCard enabled={briefingEnabled} />

      {/* ① 待处理任务 */}
      <div className="mb-6">
        <SectionHeading icon={<Package className="h-3.5 w-3.5 text-amber-600" />} colorClass="bg-amber-50">待处理</SectionHeading>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {/* issue #5792 第二阶段：待支付订单（钱还没到）。下钻用**端点枚举值**
              （`resolveStatusParam` 直接匹配 `pending_payment`），不依赖中文标签映射。 */}
          <Link href="/orders?status=pending_payment"><PendingCard title="待支付订单" count={pendingPayment} icon={<DollarSign className="w-4 h-4 text-amber-600" />} color="amber" /></Link>
          <Link href="/orders?status=待发货"><PendingCard title="待发货订单" count={pendingShipment} icon={<Package className="w-4 h-4 text-primary-600" />} color="blue" /></Link>
          <Link href="/orders?category=含加工订单&status=待发货"><PendingCard title="含加工待发货订单" count={processingShipment} icon={<Settings className="w-4 h-4 text-accent-600" />} color="purple" /></Link>
          {/* issue #5792：超时工单卡 —— 下钻 `?overdue=1` 与计数**同源**
              （`AfterSalesTicketMapper.applyOverdue`）：列表页会真的筛（已实装可见指示 + 可清除），
              不会出现「卡说 3 条、点进去一屏」。 */}
          <Link href="/after-sales?overdue=1"><PendingCard title="超时工单" count={overdueTickets} icon={<ClipboardList className="w-4 h-4 text-red-600" />} color="red" /></Link>
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
                change={changeBadge('较昨日', stats?.todayOrdersChange)}
                icon={<ClipboardList className="w-4 h-4 text-primary-600" />}
                sparkline={sparkline}
                chartType="line"
              />
              <BizStatCard
                metric="sales"
                title="今日销售额"
                value={fmtCurrency(stats?.todaySales || 0)}
                change={changeBadge('较昨日', stats?.todaySalesChange)}
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
                change={changeBadge('较上月', stats?.monthRevenueChange)}
                icon={<DollarSign className="w-4 h-4 text-accent-600" />}
              />
            </>
          )}
        </div>
      </div>

      {/* ②′ 可插拔指标区（issue #5792）：**只在企业启用对应能力时出现**
          —— 未购买/未下发 ⇒ 整块**不渲染**（不是渲染成 0、不是空白占位）。
          当前只有「AI 接待占比」一张；新增卡片只改 `@/lib/dashboard-cards` 的注册表。 */}
      {pluggableCards.length > 0 && (
        <div className="mb-6">
          <SectionHeading icon={<Headphones className="h-3.5 w-3.5 text-accent-600" />} colorClass="bg-accent-50">
            客户服务
          </SectionHeading>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {pluggableCards.map((card) => (
              <div
                key={card.key}
                data-testid={`dashboard-card-${card.key}`}
                className="rounded-xl border border-neutral-200 bg-white p-5 shadow-card"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-xs text-neutral-400">{card.title}</p>
                    <p className="mt-1 text-2xl font-semibold text-neutral-900">
                      {stats ? `${stats.aiSessionRate ?? 0}%` : '—'}
                    </p>
                  </div>
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-50">
                    <Headphones className="h-4 w-4 text-accent-600" />
                  </div>
                </div>
                <p className="mt-2 text-xs text-neutral-400">
                  AI 自动接待占活跃会话的比例（活跃会话 {(stats?.activeSessions ?? 0)} 个）
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

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
            {/* 🔴 issue #5792：`updateTime` 是 `formatFullDateTime()` 的**已格式化**结果
                （`2026年9月29日 15:30`）—— 它**不是** ISO 串，再 `.slice(11, 19)` 切出来的是
                `日 15:3` 这种下标碎片（页头同一字段显示正常 ⇒ 同页两处不一致）。
                ⇒ 两处**同源同格式**，不再二次加工。 */}
            <span className="text-xs text-neutral-400">数据更新时间：{updateTime}</span>
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

      {/* ③′ 订单状态分布（issue #5792 第二阶段）：端点与组件此前都已写好、从未接线 */}

      <div className="mb-6">

        <OrderStatusChart data={orderStatus} loading={loading} />

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
            <Link href="/products?sortBy=salesCount&sortOrder=desc" className="flex items-center gap-1 text-xs text-primary-600 hover:underline">查看更多 <ArrowRight className="w-3 h-3" /></Link>
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
            <>
              <table className="w-full text-xs">
                <thead><tr className="border-b border-neutral-100 text-neutral-400"><th className="w-10 py-2 text-left font-medium whitespace-nowrap">#</th><th className="py-2 text-left font-medium whitespace-nowrap">商品</th><th className="py-2 text-right font-medium whitespace-nowrap" title="近7天累计成交量（不含未付款/已取消订单）">成交量</th><th className="py-2 text-right font-medium whitespace-nowrap" title="环比：本期(近7天)销量较上一统计周期(前7天)的涨跌幅">环比</th></tr></thead>
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
              {/* #3000: 环比概念可见化 —— 讲明比较周期，避免用户不理解「环比」与哪个时间比 */}
              <p className="mt-2 text-[11px] leading-relaxed text-neutral-400">
                环比 = 本期销量（近7天）对比上一期（前7天）的涨跌幅
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
