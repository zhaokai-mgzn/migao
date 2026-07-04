'use client'

import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { ClipboardList, DollarSign, TrendingUp, Package, Settings, ArrowRight, RefreshCw, ArrowUp, ArrowDown } from 'lucide-react'
import request from '@/lib/request'
import { dashboardApi } from '@/lib/api'
import { cn, formatFullDateTime } from '@/lib/utils'
import type { DashboardStats, OrderTrendPoint, Order, ProductRanking } from '@/types'
import { normalizeOrderStatus, OrderStatusLabels } from '@/types'

// ═══════════════════════════════════════════════════════
// 格式化
// ═══════════════════════════════════════════════════════

function fmtCurrency(n: number): string {
  if (n >= 10000) return '¥' + (n / 10000).toFixed(1) + '万'
  return '¥' + n.toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })
}

function fmtNum(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  return n.toLocaleString('zh-CN')
}

function now(): string {
  return formatFullDateTime(new Date().toISOString())
}

// ═══════════════════════════════════════════════════════
// 迷你趋势图（SVG）
// ═══════════════════════════════════════════════════════

// Y 轴坐标计算器 — 带 10% padding，防止数据点被压扁
function makeYScale(values: number[], chartH: number, padTop: number, padBottom: number) {
  const plotH = chartH - padTop - padBottom
  const dMax = Math.max(...values, 0)
  const dMin = Math.min(...values, 0)
  const dRange = dMax - dMin || 10
  const pad = dRange * 0.1
  const yMin = Math.max(0, dMin - pad)
  const yMax = dMax + pad
  const yRange = yMax - yMin || 1
  return (v: number) => padTop + plotH * (1 - (v - yMin) / yRange)
}

function MiniSparkline({ data, color, width = 80, height = 28 }: { data: number[]; color: string; width?: number; height?: number }) {
  if (!data.length) return <div className="h-7 w-20" />
  const max = Math.max(...data, 1)
  const min = Math.min(...data, 0)
  const range = max - min || 1
  const points = data.map((v, i) => `${(i / (data.length - 1)) * width},${height - ((v - min) / range) * (height - 4) - 2}`).join(' ')
  return (
    <svg width={width} height={height} className="flex-shrink-0">
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function MiniBarChart({ data, color, width = 80, height = 28 }: { data: number[]; color: string; width?: number; height?: number }) {
  if (!data.length) return <div className="h-7 w-20" />
  const barW = Math.max(2, width / data.length - 2)
  const max = Math.max(...data, 1)
  return (
    <svg width={width} height={height} className="flex-shrink-0">
      {data.map((v, i) => (
        <rect key={i} x={i * (barW + 2)} y={height - (v / max) * (height - 2)} width={barW} height={(v / max) * (height - 2)} fill={color} rx="1" opacity="0.7" />
      ))}
    </svg>
  )
}

// ═══════════════════════════════════════════════════════
// 子组件
// ═══════════════════════════════════════════════════════

function BizStatCard({ title, value, change, icon, sparkline, chartType }: {
  title: string; value: string; change?: { val: string; up: boolean }; icon: React.ReactNode; sparkline?: number[]; chartType?: 'line' | 'bar'
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 p-5 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <span className="text-sm text-gray-500">{title}</span>
        <span className="p-1.5 rounded-lg bg-gray-50">{icon}</span>
      </div>
      <div className="flex items-end justify-between">
        <div>
          <p className="text-2xl font-bold text-gray-900">{value}</p>
          {change && (
            <p className={cn('text-xs mt-1 flex items-center gap-0.5', change.up ? 'text-red-500' : 'text-green-500')}>
              {change.up ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />}
              较昨天 {change.val}
            </p>
          )}
        </div>
        {sparkline && (chartType === 'bar'
          ? <MiniBarChart data={sparkline} color="#3B82F6" />
          : <MiniSparkline data={sparkline} color="#3B82F6" />
        )}
      </div>
    </div>
  )
}

const PENDING_COLORS: Record<string, string> = {
  blue: 'bg-blue-50', purple: 'bg-purple-50', red: 'bg-red-50', amber: 'bg-amber-50', green: 'bg-green-50',
}

function PendingCard({ title, count, icon, color }: { title: string; count: number; icon: React.ReactNode; color: string }) {
  return (
    <div className="flex items-center gap-3 p-4 rounded-lg border border-gray-100 bg-white">
      <span className={cn('p-2 rounded-lg', PENDING_COLORS[color] || 'bg-gray-50')}>{icon}</span>
      <div className="flex-1">
        <p className="text-xs text-gray-500">{title}</p>
        <p className="text-xl font-bold text-gray-900">{fmtNum(count)}<ArrowUp className="w-3 h-3 text-red-500 inline ml-1" /></p>
      </div>
    </div>
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
  const [updateTime, setUpdateTime] = useState(now())

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [statsRes, trendRes, ordersRes] = await Promise.all([
        dashboardApi.getStats(),
        dashboardApi.getOrderTrend(trendDays),
        dashboardApi.getRecentOrders(5),
      ])
      const s = statsRes.data.data
      setStats(s)
      setTrendData(trendRes.data.data)
      setRecentOrders(ordersRes.data.data || [])

      // 商品排行
      try {
        const rkResp = await dashboardApi.getProductRanking('day', 10)
        setRanking((rkResp.data as any)?.data || [])
      } catch (e) { console.error("page.tsx", e); }

      // 待发货订单数（status = 待发货）
      try {
        const resp = await request.get('/api/admin/dashboard/pending-shipment-count')
        setPendingShipment(resp.data?.data ?? 0)
      } catch (e) { console.error("page.tsx", e); }
      // 含加工待发货订单数（status = 待发货 AND has_processing = true）
      try {
        const resp = await request.get('/api/admin/dashboard/processing-shipment-count')
        setProcessingShipment(resp.data?.data ?? 0)
      } catch (e) { console.error("page.tsx", e); }
      // 待补库存 = 低库存 SKU 数（按颜色规格维度，库存 ≤ 100）
      try {
        const resp = await request.get('/api/admin/products/low-stock-by-color', { params: { threshold: 100, limit: 200 } })
        const items = resp?.data?.data
        setLowStockCount(Array.isArray(items) ? items.length : 0)
      } catch (e) { console.error("page.tsx", e); }
      setUpdateTime(now())
    } catch (error) {
      console.error('Dashboard load:', error)
    } finally {
      setLoading(false)
    }
  }, [trendDays])

  useEffect(() => { fetchData() }, [fetchData])

  // 从 trend 数据提取迷你图
  const sparkline = trendData.map(d => d.orders || 0).slice(-14)

  return (
    <div className="p-6">
      {/* 顶部 */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">数据看板</h1>
          <p className="text-xs text-gray-400 mt-1">数据更新时间：{updateTime}</p>
        </div>
        <button onClick={fetchData} className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100">
          <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
        </button>
      </div>

      {/* ① 待处理任务 */}
      <div className="mb-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
          <Package className="w-4 h-4 text-amber-500" />待处理
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <Link href="/orders?status=待发货"><PendingCard title="待发货订单" count={pendingShipment} icon={<Package className="w-4 h-4 text-blue-600" />} color="blue" /></Link>
          <Link href="/orders?category=含加工订单&status=待发货"><PendingCard title="含加工待发货订单" count={processingShipment} icon={<Settings className="w-4 h-4 text-purple-600" />} color="purple" /></Link>
          <Link href="/products?low_stock=true"><PendingCard title="待补库存商品" count={lowStockCount} icon={<Package className="w-4 h-4 text-red-600" />} color="red" /></Link>
        </div>
      </div>

      {/* ② 经营数据卡片 */}
      <div className="mb-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-primary-500" />经营数据
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {loading ? (
            Array.from({ length: 3 }).map((_, i) => <div key={i} className="bg-white rounded-xl border border-gray-100 p-5 animate-pulse h-[120px]" />)
          ) : (
            <>
              <BizStatCard
                title="今日订单数"
                value={stats?.todayOrders?.toLocaleString() || '0'}
                change={{ val: `${stats?.todayOrdersChange || 0}`, up: (stats?.todayOrdersChange || 0) > 0 }}
                icon={<ClipboardList className="w-4 h-4 text-blue-600" />}
                sparkline={sparkline}
                chartType="line"
              />
              <BizStatCard
                title="今日销售额"
                value={fmtCurrency(stats?.todaySales || 0)}
                change={{ val: `${stats?.todaySalesChange || 0}`, up: (stats?.todaySalesChange || 0) > 0 }}
                icon={<DollarSign className="w-4 h-4 text-green-600" />}
                sparkline={sparkline.map(v => v * 23.8)}
                chartType="bar"
              />
              <BizStatCard
                title="本月销售额"
                value={fmtCurrency(stats?.monthRevenue || 0)}
                change={{ val: `${stats?.monthRevenueChange || 0}% 较上月`, up: (stats?.monthRevenueChange || 0) > 0 }}
                icon={<DollarSign className="w-4 h-4 text-orange-600" />}
              />
            </>
          )}
        </div>
      </div>

      {/* ③ 趋势图 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-5">
        {/* 订单趋势 */}
        <div className="bg-white rounded-xl border border-gray-100 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-800">订单趋势</h3>
            <div className="flex gap-1 bg-gray-100 rounded-lg p-0.5">
              {[7, 30].map(d => (
                <button key={d} onClick={() => setTrendDays(d)}
                  className={cn('px-3 py-1 text-xs rounded-md', trendDays === d ? 'bg-white shadow text-gray-900' : 'text-gray-500')}>
                  近{d}天
                </button>
              ))}
            </div>
          </div>
          <div className="h-48">
            {trendData.length > 0 ? (
              (() => {
                const chartW = Math.max(trendData.length * 40, 300)
                const CHART_H = 240
                const PAD_TOP = 15, PAD_BOTTOM = 35
                const toY = makeYScale(trendData.map(d => d.orders || 0), CHART_H, PAD_TOP, PAD_BOTTOM)
                const step = Math.ceil(trendData.length / 7)
                return (
                  <svg width="100%" height="100%" viewBox={`0 0 ${chartW} ${CHART_H}`} preserveAspectRatio="xMidYMid meet">
                    <polyline fill="none" stroke="#3B82F6" strokeWidth="2"
                      points={trendData.map((d, i) => `${i * 40 + 20},${toY(d.orders || 0)}`).join(' ')} />
                    {trendData.map((d, i) => (
                      <circle key={i} cx={i * 40 + 20} cy={toY(d.orders || 0)} r="3" fill="#3B82F6" />
                    ))}
                    {trendData.filter((_, i) => i % step === 0).map((d, i) => (
                      <text key={i} x={i * 40 * step + 20} y={CHART_H - 5} textAnchor="middle" fontSize="11" fill="#6B7280">
                        {d.date?.slice(5)}
                      </text>
                    ))}
                  </svg>
                )
              })()
            ) : <div className="h-full flex items-center justify-center text-gray-400 text-sm">暂无数据</div>}
          </div>
        </div>

        {/* 销售额趋势 */}
        <div className="bg-white rounded-xl border border-gray-100 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-800">销售额数据</h3>
            <span className="text-xs text-gray-400">数据更新时间：{updateTime.slice(11, 19)}</span>
          </div>
          <div className="h-48">
            {trendData.length > 0 ? (
              (() => {
                const chartW = Math.max(trendData.length * 40, 300)
                const CHART_H = 240
                const PAD_TOP = 15, PAD_BOTTOM = 10
                const toY = makeYScale(trendData.map(d => d.totalAmount || d.orders * 23.8 || 0), CHART_H, PAD_TOP, PAD_BOTTOM)
                return (
                  <svg width="100%" height="100%" viewBox={`0 0 ${chartW} ${CHART_H}`} preserveAspectRatio="xMidYMid meet">
                    <defs><linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#3B82F6" stopOpacity="0.3" /><stop offset="100%" stopColor="#3B82F6" stopOpacity="0" /></linearGradient></defs>
                    <path fill="url(#areaGrad)"
                      d={`M 20 ${CHART_H - PAD_BOTTOM} ${trendData.map((d, i) => `L ${i * 40 + 20} ${toY(d.totalAmount || d.orders * 23.8 || 0)}`).join(' ')} L ${(trendData.length - 1) * 40 + 20} ${CHART_H - PAD_BOTTOM} Z`} />
                    <polyline fill="none" stroke="#3B82F6" strokeWidth="2"
                      points={trendData.map((d, i) => `${i * 40 + 20},${toY(d.totalAmount || d.orders * 23.8 || 0)}`).join(' ')} />
                  </svg>
                )
              })()
            ) : <div className="h-full flex items-center justify-center text-gray-400 text-sm">暂无数据</div>}
          </div>
        </div>
      </div>

      {/* ④ 列表 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 近期订单 */}
        <div className="bg-white rounded-xl border border-gray-100 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-800">近期订单</h3>
            <a href="/orders" className="text-xs text-primary-600 hover:underline flex items-center gap-1">查看全部 <ArrowRight className="w-3 h-3" /></a>
          </div>
          <table className="w-full text-xs">
            <thead><tr className="text-gray-500 border-b"><th className="text-left py-2 font-medium">订单号</th><th className="text-left py-2 font-medium">客户</th><th className="text-right py-2 font-medium">金额</th><th className="text-right py-2 font-medium">状态</th><th className="text-right py-2 font-medium">时间</th></tr></thead>
            <tbody>
              {recentOrders.slice(0, 5).map(o => (
                <tr key={o.id} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="py-2"><a href={`/orders/${o.id}`} className="text-blue-600 font-mono text-[11px] hover:underline">{o.orderNo?.slice(0, 16)}</a></td>
                  <td className="py-2 text-gray-700">{o.customerName}</td>
                  <td className="py-2 text-right text-gray-900 font-mono">{fmtCurrency(o.totalAmount)}</td>
                  <td className="py-2 text-right"><StatusBadge status={o.status as string} /></td>
                  <td className="py-2 text-right text-gray-400 text-[11px]">{o.createdAt?.slice(5, 16)?.replace('T', ' ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!loading && recentOrders.length === 0 && <p className="text-center text-gray-400 py-4 text-sm">暂无订单</p>}
        </div>

        {/* 商品销量排行 */}
        <div className="bg-white rounded-xl border border-gray-100 p-5">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-800">商品销量排行</h3>
            <a href="/products?sortBy=salesCount&sortOrder=desc" className="text-xs text-primary-600 hover:underline flex items-center gap-1">查看更多 <ArrowRight className="w-3 h-3" /></a>
          </div>
          {loading ? (
            <div className="space-y-2">{Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-8 bg-gray-100 rounded animate-pulse" />)}</div>
          ) : ranking.length === 0 ? (
            <p className="text-center text-gray-400 py-4 text-sm">暂无数据</p>
          ) : (
            <table className="w-full text-xs">
              <thead><tr className="text-gray-500 border-b"><th className="text-left py-2 font-medium w-8">#</th><th className="text-left py-2 font-medium">商品</th><th className="text-right py-2 font-medium">成交量</th><th className="text-right py-2 font-medium">日涨</th></tr></thead>
              <tbody>
                {ranking.slice(0, 10).map(r => (
                  <tr key={r.productId} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-2 text-gray-400">{r.rank}</td>
                    <td className="py-2 text-gray-700 truncate max-w-[160px]" title={r.productName}>{r.productName}</td>
                    <td className="py-2 text-right font-mono text-gray-900">{r.qtyDisplay}</td>
                    <td className={cn('py-2 text-right', r.dailyChange > 0 ? 'text-red-500' : 'text-green-500')}>
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

// ========== 订单状态徽章（中文） ==========

function StatusBadge({ status }: { status: string }) {
  const s = normalizeOrderStatus(status)
  const label = OrderStatusLabels[s]
  const colorClass =
    s === 'completed' ? 'bg-green-100 text-green-700' :
    s === 'pending_shipment' || s === 'shipped' ? 'bg-blue-100 text-blue-700' :
    s === 'pending_payment' ? 'bg-amber-100 text-amber-700' :
    s === 'closed' ? 'bg-gray-100 text-gray-500' :
    'bg-gray-100 text-gray-600'
  return (
    <span className={cn('inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium', colorClass)}>
      {label}
    </span>
  )
}
