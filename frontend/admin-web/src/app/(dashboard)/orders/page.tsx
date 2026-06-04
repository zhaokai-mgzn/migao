'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import dayjs from 'dayjs'
import { RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { orderApi } from '@/lib/api'
import { OrderTable, CloseOrderModal, RemarkModal } from '@/components/orders'
import type { Order, OrderStatus, OrderStatusTab } from '@/types'
import { FrontendToBackendStatus, OrderStatusTabs } from '@/types'

interface SearchState {
  orderId: string
  receiver: string
  startDate: string
  endDate: string
  productCode: string
  productTitle: string
  hasProcessing: '' | 'true' | 'false'
}

// 将 Date 格式化为 YYYY-MM-DD（与 <input type="date"> 及后端 OrderListParams 一致）
function formatDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// 默认下单时间范围：最近一个月（开始日期 = 今天往前推一个月，结束日期 = 今天）
function getDefaultDateRange(): { startDate: string; endDate: string } {
  const end = new Date()
  const start = new Date()
  start.setMonth(start.getMonth() - 1)
  return { startDate: formatDate(start), endDate: formatDate(end) }
}

const DEFAULT_DATE_RANGE = getDefaultDateRange()

const EMPTY_SEARCH: SearchState = {
  orderId: '',
  receiver: '',
  startDate: DEFAULT_DATE_RANGE.startDate,
  endDate: DEFAULT_DATE_RANGE.endDate,
  productCode: '',
  productTitle: '',
  hasProcessing: '',
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="text-sm text-gray-600 whitespace-nowrap shrink-0 w-20 text-right">
      {children}
    </label>
  )
}

function FieldInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cn(
        'flex-1 min-w-0 h-9 px-3 rounded border border-gray-300 bg-white text-sm',
        'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15',
        'placeholder:text-gray-400',
        props.className
      )}
    />
  )
}

export default function OrdersPage() {
  const router = useRouter()

  // 表单输入状态（未提交）
  const [orderId, setOrderId] = useState('')
  const [receiver, setReceiver] = useState('')
  const [startDate, setStartDate] = useState(DEFAULT_DATE_RANGE.startDate)
  const [endDate, setEndDate] = useState(DEFAULT_DATE_RANGE.endDate)
  const [productCode, setProductCode] = useState('')
  const [productTitle, setProductTitle] = useState('')
  const [hasProcessing, setHasProcessing] = useState<'' | 'true' | 'false'>('')

  // 实际提交的搜索参数
  const [search, setSearch] = useState<SearchState>(EMPTY_SEARCH)

  // Tab
  const [activeTab, setActiveTab] = useState<OrderStatusTab>('all')

  // 分页
  const [current, setCurrent] = useState(1)
  const pageSize = 20
  const [total, setTotal] = useState(0)

  // 列表
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  // 弹窗
  const [closeModalOpen, setCloseModalOpen] = useState(false)
  const [remarkModalOpen, setRemarkModalOpen] = useState(false)
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null)
  const [actionLoading, setActionLoading] = useState(false)

  const loadOrders = useCallback(async (pageOverride?: number) => {
    const pageNum = pageOverride ?? current
    if (pageOverride !== undefined) setCurrent(pageOverride)
    setLoading(true)
    try {
      // 后端列表接口仅支持 page/size/status/keyword/followStatus。
      // 前端 6 字段搜索合并为 keyword（取第一个非空值）。
      const apiParams: Record<string, unknown> = {
        page: pageNum,
        size: pageSize,
      }

      // 下单时间范围（YYYY-MM-DD）
      if (search.startDate) apiParams.startDate = search.startDate
      if (search.endDate) apiParams.endDate = search.endDate

      // 多字段搜索：分别传递各字段，后端支持 keyword 模糊匹配
      // 优先使用第一个非空字段作为 keyword（后端当前限制），后续可升级为多字段
      const keywordCandidates = [
        search.orderId,
        search.receiver,
        search.productCode,
        search.productTitle,
      ].filter(Boolean)
      if (keywordCandidates.length > 0) {
        apiParams.keyword = keywordCandidates[0]
      }
      // 同时传递各字段供后端精确匹配（后端如支持则优先使用）
      if (search.orderId) apiParams.orderId = search.orderId
      if (search.receiver) apiParams.receiver = search.receiver
      if (search.productCode) apiParams.productCode = search.productCode
      if (search.productTitle) apiParams.productTitle = search.productTitle

      // 状态映射：前端枚举 → 后端枚举。
      // 'all' / 'processing' 不传 status，'processing' tab 传 hasProcessing=true 给后端过滤
      if (activeTab !== 'all' && activeTab !== 'processing') {
        apiParams.status = FrontendToBackendStatus[activeTab as OrderStatus]
      } else if (activeTab === 'processing') {
        apiParams.hasProcessing = true
      }

      const res = await orderApi.getOrders(apiParams as Parameters<typeof orderApi.getOrders>[0])
      const pageData = res.data?.data
      const items = pageData?.items || []

      setOrders(items)
      setTotal(pageData?.total || 0)
    } catch (e) {
      console.error(e)
      toast.error('加载订单失败')
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, search, activeTab])

  useEffect(() => {
    loadOrders()
  }, [loadOrders])

  const handleSearch = () => {
    setCurrent(1)
    setSearch({
      orderId: orderId.trim(),
      receiver: receiver.trim(),
      startDate,
      endDate,
      productCode: productCode.trim(),
      productTitle: productTitle.trim(),
      hasProcessing,
    })
  }

  const handleReset = () => {
    setOrderId('')
    setReceiver('')
    setStartDate(DEFAULT_DATE_RANGE.startDate)
    setEndDate(DEFAULT_DATE_RANGE.endDate)
    setProductCode('')
    setProductTitle('')
    setHasProcessing('')
    setCurrent(1)
    setSearch(EMPTY_SEARCH)
  }

  const handleDateQuickSelect = (preset: 'today' | '7days' | '30days') => {
    const today = dayjs().format('YYYY-MM-DD')
    if (preset === 'today') {
      setStartDate(today)
      setEndDate(today)
    } else if (preset === '7days') {
      setStartDate(dayjs().subtract(6, 'day').format('YYYY-MM-DD'))
      setEndDate(today)
    } else {
      setStartDate(dayjs().subtract(29, 'day').format('YYYY-MM-DD'))
      setEndDate(today)
    }
  }

  const handleTabChange = (tab: OrderStatusTab) => {
    setActiveTab(tab)
    setCurrent(1)
  }

  const handleView = (order: Order) => {
    router.push(`/orders/${order.id}`)
  }

  const handleOpenRemark = (order: Order) => {
    setSelectedOrder(order)
    setRemarkModalOpen(true)
  }

  const handleOpenClose = (order: Order) => {
    setSelectedOrder(order)
    setCloseModalOpen(true)
  }

  const handleShip = (order: Order) => {
    router.push(`/orders/${order.id}?action=ship`)
  }

  const handleConfirmPayment = async (order: Order) => {
    if (!window.confirm('确认已收到客户付款？')) return
    const toastId = toast.loading('操作中…')
    try {
      await orderApi.confirmPayment(order.id)
      toast.success('付款已确认', { id: toastId })
      loadOrders()
    } catch (e) {
      console.error(e)
      toast.error('确认付款失败', { id: toastId })
    }
  }

  const handleConfirmReceive = async (order: Order) => {
    if (!window.confirm('确认客户已收到货物？')) return
    const toastId = toast.loading('操作中…')
    try {
      await orderApi.updateOrderStatus(order.id, { status: 'completed' })
      toast.success('订单已完成', { id: toastId })
      loadOrders()
    } catch (e) {
      console.error(e)
      toast.error('确认收货失败', { id: toastId })
    }
  }

  const handleConfirmClose = async (reason: string) => {
    if (!selectedOrder) return
    setActionLoading(true)
    try {
      await orderApi.closeOrder(selectedOrder.id, { reason })
      toast.success('订单已关闭')
      setCloseModalOpen(false)
      setSelectedOrder(null)
      loadOrders()
    } catch (e) {
      console.error(e)
      toast.error('关闭订单失败')
    } finally {
      setActionLoading(false)
    }
  }

  const handleConfirmRemark = async (content: string) => {
    if (!selectedOrder) return
    setActionLoading(true)
    try {
      await orderApi.addRemark(selectedOrder.id, content)
      toast.success('备注添加成功')
      setRemarkModalOpen(false)
      setSelectedOrder(null)
      loadOrders()
    } catch (e) {
      console.error(e)
      toast.error('添加备注失败')
    } finally {
      setActionLoading(false)
    }
  }

  // 简易分页器
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const pageList: (number | '...')[] = (() => {
    const list: (number | '...')[] = []
    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i++) list.push(i)
    } else {
      const left = Math.max(2, current - 1)
      const right = Math.min(totalPages - 1, current + 1)
      list.push(1)
      if (left > 2) list.push('...')
      for (let i = left; i <= right; i++) list.push(i)
      if (right < totalPages - 1) list.push('...')
      list.push(totalPages)
    }
    return list
  })()

  return (
    <div className="p-6 space-y-4">
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">订单列表</h1>
        <button
          type="button"
          onClick={() => router.push('/orders/new')}
          className="h-9 px-4 rounded bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 active:bg-primary-800 transition-colors inline-flex items-center gap-1.5 shadow-sm"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          新增订单
        </button>
      </div>

      {/* 查询区域 */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_1.5fr] gap-x-6 gap-y-4 mb-4">
          {/* 订单ID */}
          <div className="flex items-center gap-2">
            <FieldLabel>订单ID</FieldLabel>
            <FieldInput
              placeholder="请输入订单ID"
              value={orderId}
              onChange={(e) => setOrderId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          {/* 收货人 */}
          <div className="flex items-center gap-2">
            <FieldLabel>收货人</FieldLabel>
            <FieldInput
              placeholder="请输入收货人姓名或手机号"
              value={receiver}
              onChange={(e) => setReceiver(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          {/* 下单时间 */}
          <div className="flex items-center gap-2">
            <FieldLabel>下单时间</FieldLabel>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              placeholder="开始日期"
              className="flex-1 min-w-[130px] h-9 px-3 rounded border border-gray-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
            <span className="text-gray-400 text-sm">至</span>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              placeholder="结束日期"
              className="flex-1 min-w-[130px] h-9 px-3 rounded border border-gray-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
            <div className="flex gap-1 bg-gray-100 rounded-lg p-0.5">
              {(['today', '7days', '30days'] as const).map((preset) => {
                const label = preset === 'today' ? '今天' : preset === '7days' ? '近7天' : '近30天'
                const isActive = (() => {
                  const today = dayjs().format('YYYY-MM-DD')
                  if (preset === 'today') return startDate === today && endDate === today
                  if (preset === '7days') return startDate === dayjs().subtract(6, 'day').format('YYYY-MM-DD') && endDate === today
                  return startDate === dayjs().subtract(29, 'day').format('YYYY-MM-DD') && endDate === today
                })()
                return (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => handleDateQuickSelect(preset)}
                    className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                      isActive ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-[repeat(3,1fr)_auto] gap-x-6 gap-y-4 items-center">
          {/* 商品货号 */}
          <div className="flex items-center gap-2">
            <FieldLabel>商品货号</FieldLabel>
            <FieldInput
              placeholder="请输入商品货号"
              value={productCode}
              onChange={(e) => setProductCode(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          {/* 商品标题 */}
          <div className="flex items-center gap-2">
            <FieldLabel>商品标题</FieldLabel>
            <FieldInput
              placeholder="请输入商品标题"
              value={productTitle}
              onChange={(e) => setProductTitle(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          {/* 是否加工 */}
          <div className="flex items-center gap-2">
            <FieldLabel>是否加工</FieldLabel>
            <select
              value={hasProcessing}
              onChange={(e) => setHasProcessing(e.target.value as '' | 'true' | 'false')}
              className="flex-1 min-w-0 h-9 px-3 rounded border border-gray-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            >
              <option value="">全部</option>
              <option value="true">是</option>
              <option value="false">否</option>
            </select>
          </div>
          {/* 按钮 */}
          <div className="flex items-center gap-2 justify-end">
            <button
              type="button"
              onClick={handleSearch}
              disabled={loading}
              className="h-9 px-5 rounded bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 active:bg-primary-800 disabled:opacity-50 transition-colors"
            >
              查询
            </button>
            <button
              type="button"
              onClick={handleReset}
              disabled={loading}
              className="h-9 px-5 rounded bg-white text-gray-700 text-sm font-medium border border-gray-300 hover:bg-gray-50 active:bg-gray-100 disabled:opacity-50 transition-colors inline-flex items-center gap-1"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M3 12a9 9 0 1 0 3-6.7L3 8" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M3 3v5h5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              重置
            </button>
            <button
              type="button"
              onClick={() => loadOrders(1)}
              className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
              title="刷新"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* 表格 + Tab */}
      <div className="bg-white rounded-lg border border-gray-200">
        {/* Tab 栏 */}
        <div className="flex items-center gap-6 px-5 pt-3 border-b border-gray-200 overflow-x-auto">
          {OrderStatusTabs.map((tab) => {
            const active = activeTab === tab.key
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => handleTabChange(tab.key)}
                className={cn(
                  'relative pb-3 text-sm whitespace-nowrap transition-colors',
                  active ? 'text-primary-600 font-medium' : 'text-gray-600 hover:text-gray-900'
                )}
              >
                {tab.label}
                {active && (
                  <span className="absolute left-0 right-0 -bottom-px h-0.5 bg-primary-600 rounded-full" />
                )}
              </button>
            )
          })}
        </div>

        {/* 表格 */}
        <OrderTable
          orders={orders}
          loading={loading}
          selectedIds={selectedIds}
          onSelectChange={setSelectedIds}
          onView={handleView}
          onRemark={handleOpenRemark}
          onClose={handleOpenClose}
          onShip={handleShip}
          onRefund={handleView}
          onConfirmPayment={handleConfirmPayment}
          onConfirmReceive={handleConfirmReceive}
        />

        {/* 分页 */}
        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-gray-100">
          <span className="text-sm text-gray-500 mr-2">共 {total} 条</span>
          <button
            type="button"
            onClick={() => setCurrent(Math.max(1, current - 1))}
            disabled={current <= 1}
            className="h-8 w-8 inline-flex items-center justify-center rounded border border-gray-300 text-gray-500 text-sm hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ‹
          </button>
          {pageList.map((p, idx) =>
            p === '...' ? (
              <span key={`dots-${idx}`} className="px-1 text-gray-400 text-sm">
                …
              </span>
            ) : (
              <button
                key={p}
                type="button"
                onClick={() => setCurrent(p)}
                className={cn(
                  'min-w-[32px] h-8 px-2 rounded text-sm transition-colors',
                  p === current
                    ? 'bg-primary-600 text-white'
                    : 'text-gray-600 hover:bg-gray-50 border border-gray-300'
                )}
              >
                {p}
              </button>
            )
          )}
          <button
            type="button"
            onClick={() => setCurrent(Math.min(totalPages, current + 1))}
            disabled={current >= totalPages}
            className="h-8 w-8 inline-flex items-center justify-center rounded border border-gray-300 text-gray-500 text-sm hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ›
          </button>
        </div>
      </div>

      {/* 弹窗 */}
      <CloseOrderModal
        open={closeModalOpen}
        onClose={() => {
          if (!actionLoading) {
            setCloseModalOpen(false)
            setSelectedOrder(null)
          }
        }}
        onConfirm={handleConfirmClose}
        loading={actionLoading}
      />
      <RemarkModal
        open={remarkModalOpen}
        onClose={() => {
          if (!actionLoading) {
            setRemarkModalOpen(false)
            setSelectedOrder(null)
          }
        }}
        onConfirm={handleConfirmRemark}
        loading={actionLoading}
      />
    </div>
  )
}
