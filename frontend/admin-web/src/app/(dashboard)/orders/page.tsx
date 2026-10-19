'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { toastRequestError } from '@/lib/api-error'
import { cn } from '@/lib/utils'
import { orderApi } from '@/lib/api'
import { OrderTable, CloseOrderModal, RemarkModal, RefundOrderModal } from '@/components/orders'
import { Button, Modal, PageHeader, SearchPanel } from '@/components/ui'
import type { SearchFieldSpec } from '@/components/ui'
import ListLoadError from '@/components/common/ListLoadError'
import { usePermission } from '@/lib/permission'
import type { OrderBrief, OrderStatus, OrderStatusTab } from '@/types'
import { FrontendToBackendStatus, OrderStatusTabs, ORDER_CATEGORIES, OrderStatusLabels, toBackendStatusParam } from '@/types'

interface SearchState {
  orderId: string
  receiver: string
  creator: string
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
  creator: '',
  startDate: DEFAULT_DATE_RANGE.startDate,
  endDate: DEFAULT_DATE_RANGE.endDate,
  productCode: '',
  productTitle: '',
  hasProcessing: '',
}



/** 将 URL 参数中的中文标签映射为内部 tab key */
function resolveCategoryParam(raw: string | null): OrderStatusTab | null {
  if (!raw) return null
  // 直接匹配 tab key
  if (raw === 'processing' || raw === 'all') return raw as OrderStatusTab
  if (raw === 'has_processing') return 'processing'
  // 按 ORDER_CATEGORIES label 匹配
  const cat = ORDER_CATEGORIES.find(c => c.label === raw)
  if (cat) {
    return cat.key === 'has_processing' ? 'processing' : (cat.key as OrderStatusTab)
  }
  return null
}

/** 将 URL 中的状态标签（中文或英文）映射为内部 OrderStatus */
function resolveStatusParam(raw: string | null): OrderStatus | null {
  if (!raw) return null
  // 直接匹配 OrderStatus 枚举值
  const allStatuses: OrderStatus[] = ['pending_payment', 'pending_shipment', 'shipped', 'completed', 'closed', 'refund']
  if (allStatuses.includes(raw as OrderStatus)) return raw as OrderStatus
  // 按 OrderStatusLabels label 匹配
  const entry = Object.entries(OrderStatusLabels).find(([, label]) => label === raw)
  if (entry) return entry[0] as OrderStatus
  return null
}

/** 筛选控件统一形态：与 `SearchPanel` 的 `CONTROL_CLASS` 同口径（h-9 / 暖色描边 / 聚焦环） */
const SEARCH_CONTROL =
  'flex-1 min-w-0 w-full h-9 px-3 rounded border border-neutral-300 bg-white text-sm text-neutral-900 ' +
  'focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ' +
  'placeholder:text-neutral-400'

export default function OrdersPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  // issue #5983：列表页**写按钮随权限显隐** —— 与员工页同范式（`canWrite = hasPermission('employee:create')`）。
  // 路由守卫取的是**读**码 `order:list`（页面可进），而建单入口 `/orders/new` 的提交要 `order:create`
  // ⇒ 无码时若把按钮渲染出来，用户点进去、填完表单才吃 403（"白点一下"）。
  const { has: hasPermission } = usePermission()
  const canWrite = hasPermission('order:create')

  // 从 URL 读取初始参数（#387: Dashboard 卡片跳转）
  const urlCategory = searchParams.get('category')
  const urlStatus = searchParams.get('status')
  const urlHasProcessing = searchParams.get('has_processing')

  // 当 category 和 status 同时出现：tab = category, 叠加 status 过滤
  const initialCategory = resolveCategoryParam(urlCategory)
  const initialStatus = resolveStatusParam(urlStatus)
  const initialTab: OrderStatusTab = initialCategory || initialStatus || 'all'
  // extraStatusFilter: 当同时有 category + status 时，status 作为叠加过滤
  const initialExtraStatus: OrderStatus | null =
    (initialCategory && initialStatus) ? initialStatus : null

  // 表单输入状态（未提交）
  const [orderId, setOrderId] = useState('')
  const [receiver, setReceiver] = useState('')
  /**
   * 制单人（issue #5835）：文本框**模糊**匹配 —— 只走独立查询参数 `creator`，
   * **不并入**下面那个 `keyword`（keyword 后端匹配的是客户姓名 / 电话 / 订单号，
   * 塞进去会把「制单人姓张」变成「客户姓张」⇒ 筛错对象）。
   */
  const [creator, setCreator] = useState('')
  const [startDate, setStartDate] = useState(DEFAULT_DATE_RANGE.startDate)
  const [endDate, setEndDate] = useState(DEFAULT_DATE_RANGE.endDate)
  const [productCode, setProductCode] = useState('')
  const [productTitle, setProductTitle] = useState('')
  const [hasProcessing, setHasProcessing] = useState<'' | 'true' | 'false'>(
    urlHasProcessing === 'true' ? 'true' : urlHasProcessing === 'false' ? 'false' : ''
  )

  // 实际提交的搜索参数
  const initialSearch: SearchState = {
    ...EMPTY_SEARCH,
    hasProcessing: urlHasProcessing === 'true' ? 'true' : urlHasProcessing === 'false' ? 'false' : '',
  }
  const [search, setSearch] = useState<SearchState>(initialSearch)

  // Tab
  const [activeTab, setActiveTab] = useState<OrderStatusTab>(initialTab)

  // 当 category + status 同时指定时，叠加 status 过滤（#387）
  const [extraStatusFilter, setExtraStatusFilter] = useState<OrderStatus | null>(initialExtraStatus)

  // 分页
  const [current, setCurrent] = useState(1)
  const pageSize = 20
  const [total, setTotal] = useState(0)
  /**
   * 读面失败标记（issue #6703）：`total` 初值 0，读失败时若照旧印「共 0 条」，
   * 商家回到屏幕会把它读成「今天没有订单」—— 与 #6691「读面故障不得画成空态」同族。
   * 失败 ⇒ 计数位印 `—` + 常驻失败锚点（`orders-load-error`）+ 真重发出口。
   */
  const [loadError, setLoadError] = useState(false)

  // 列表（🔴 issue #6882：**列表形态**，不是详情形态 —— `orderApi.getOrders` 回的是 brief）
  const [orders, setOrders] = useState<OrderBrief[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  // 弹窗
  const [closeModalOpen, setCloseModalOpen] = useState(false)
  const [remarkModalOpen, setRemarkModalOpen] = useState(false)
  const [refundModalOpen, setRefundModalOpen] = useState(false)
  const [selectedOrder, setSelectedOrder] = useState<OrderBrief | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  /**
   * 确认动作弹框（issue #6664 第 4 条）：改前这两个动作走 `window.confirm` ——
   * 与仓内自研 `Modal`（UI-048 家族）**同一个动作两个世界观**，且**没有在飞行态**。
   * 现在统一走 Modal，弹框就是**闸门**（取消 ⇒ 一个请求都不发）。
   */
  const [confirmAction, setConfirmAction] = useState<{ kind: 'payment' | 'receive'; order: OrderBrief } | null>(null)
  const [confirming, setConfirming] = useState(false)

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
      // 制单人（issue #5835）：独立参数，后端按 `created_by_name` 快照列模糊匹配
      if (search.creator) apiParams.creator = search.creator

      // 状态映射：前端枚举 → 后端枚举。
      // 'all' / 'processing' 不传 status，'processing' tab 传 hasProcessing=true 给后端过滤
      if (activeTab !== 'all' && activeTab !== 'processing') {
        apiParams.status = toBackendStatusParam(activeTab as OrderStatus)
      } else if (activeTab === 'processing') {
        apiParams.hasProcessing = true
        // #387: 当 category + status 同时指定时，叠加 status 过滤
        if (extraStatusFilter) {
          apiParams.status = toBackendStatusParam(extraStatusFilter)
        }
      }

      // 搜索表单的「是否加工」筛选项（修复 P0-1：之前该字段未传给 API）
      // 仅当非「加工项订单」tab 时，表单的 hasProcessing 才生效（tab 优先）
      if (activeTab !== 'processing') {
        if (search.hasProcessing === 'true') {
          apiParams.hasProcessing = true
        } else if (search.hasProcessing === 'false') {
          apiParams.hasProcessing = false
        }
      }

      const res = await orderApi.getOrders(apiParams as Parameters<typeof orderApi.getOrders>[0])
      const pageData = res.data?.data
      const items = pageData?.items || []

      setOrders(items)
      setTotal(pageData?.total || 0)
      setLoadError(false)
    } catch (e) {
      console.error(e)
      // 读不到 ⇒ 屏上必须留一处**常驻**的失败面（toast 约 4s 就没了）
      setLoadError(true)
      toastRequestError(e, '加载订单失败')
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, search, activeTab, extraStatusFilter])

  useEffect(() => {
    loadOrders()
  }, [loadOrders])

  const handleSearch = () => {
    setCurrent(1)
    setSearch({
      orderId: orderId.trim(),
      receiver: receiver.trim(),
      creator: creator.trim(),
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
    setCreator('')
    setStartDate(DEFAULT_DATE_RANGE.startDate)
    setEndDate(DEFAULT_DATE_RANGE.endDate)
    setProductCode('')
    setProductTitle('')
    setHasProcessing('')
    setCurrent(1)
    setSearch(EMPTY_SEARCH)
  }

  const handleTabChange = (tab: OrderStatusTab) => {
    setActiveTab(tab)
    setExtraStatusFilter(null) // 手动切 tab 时清除叠加状态过滤
    setCurrent(1)
    // #387: 同步 URL 参数
    const url = new URLSearchParams()
    if (tab === 'processing') url.set('category', '含加工订单')
    else if (tab !== 'all') url.set('status', tab)
    router.replace(`/orders?${url.toString()}`, { scroll: false })
  }

  const handleView = (order: OrderBrief) => {
    router.push(`/orders/${order.id}`)
  }

  const handleOpenRemark = (order: OrderBrief) => {
    setSelectedOrder(order)
    setRemarkModalOpen(true)
  }

  const handleOpenClose = (order: OrderBrief) => {
    setSelectedOrder(order)
    setCloseModalOpen(true)
  }

  const handleOpenRefund = (order: OrderBrief) => {
    setSelectedOrder(order)
    setRefundModalOpen(true)
  }

  const handleShip = (order: OrderBrief) => {
    router.push(`/orders/${order.id}/ship`)
  }

  const handleConfirmPayment = (order: OrderBrief) => {
    setConfirmAction({ kind: 'payment', order })
  }

  const handleConfirmReceive = (order: OrderBrief) => {
    setConfirmAction({ kind: 'receive', order })
  }

  /** 弹框里点「确认」才真发请求（在飞时按钮 disabled，防连点重复请求） */
  const runConfirmAction = async () => {
    if (!confirmAction || confirming) return
    const { kind, order } = confirmAction
    setConfirming(true)
    const toastId = toast.loading('操作中…')
    try {
      if (kind === 'payment') {
        await orderApi.confirmPayment(order.id)
        toast.success('付款已确认', { id: toastId })
      } else {
        await orderApi.updateOrderStatus(order.id, { status: 'completed' })
        toast.success('订单已完成', { id: toastId })
      }
      setConfirmAction(null)
      loadOrders()
    } catch (e) {
      console.error(e)
      toastRequestError(e, kind === 'payment' ? '确认付款失败' : '确认收货失败', { id: toastId })
    } finally {
      setConfirming(false)
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
      toastRequestError(e, '关闭订单失败')
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
      toastRequestError(e, '添加备注失败')
    } finally {
      setActionLoading(false)
    }
  }

  // 提交退款（后端 PUT /api/admin/orders/{id}/refund，退款不改变订单状态）
  const handleConfirmRefund = async (data: { refundAmount: number; refundReason: string }) => {
    if (!selectedOrder) return
    setActionLoading(true)
    try {
      await orderApi.refundOrder(selectedOrder.id, data)
      toast.success('退款成功')
      setRefundModalOpen(false)
      setSelectedOrder(null)
      loadOrders()
    } catch (e) {
      console.error(e)
      toastRequestError(e, '退款失败')
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

  const searchPanelFields: SearchFieldSpec[] = [
    {
      key: 'dateRange',
      label: '下单时间',
      span: 2,
      control: (
        <div className="flex items-center gap-1.5 min-w-0">
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            placeholder="开始日期"
            className={SEARCH_CONTROL}
          />
          <span className="shrink-0 text-neutral-400 text-sm">至</span>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            placeholder="结束日期"
            className={SEARCH_CONTROL}
          />
        </div>
      ),
    },
    {
      key: 'orderId',
      label: '订单ID',
      control: (
        <input type="text" placeholder="请输入订单ID" value={orderId}
          onChange={(e) => setOrderId(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()} className={SEARCH_CONTROL} />
      ),
    },
    {
      key: 'receiver',
      label: '收货人',
      control: (
        <input type="text" placeholder="请输入收货人姓名或手机号" value={receiver}
          onChange={(e) => setReceiver(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()} className={SEARCH_CONTROL} />
      ),
    },
    {
      // 制单人（issue #5835）：文本框模糊匹配（与同区其它输入一致，回车即搜）
      key: 'creator',
      label: '制单人',
      control: (
        <input type="text" placeholder="请输入制单人姓名" value={creator}
          onChange={(e) => setCreator(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()} className={SEARCH_CONTROL} />
      ),
    },
    {
      key: 'productCode',
      label: '商品货号',
      control: (
        <input type="text" placeholder="请输入商品货号" value={productCode}
          onChange={(e) => setProductCode(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()} className={SEARCH_CONTROL} />
      ),
    },
    {
      key: 'productTitle',
      label: '商品标题',
      control: (
        <input type="text" placeholder="请输入商品标题" value={productTitle}
          onChange={(e) => setProductTitle(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()} className={SEARCH_CONTROL} />
      ),
    },
    {
      key: 'hasProcessing',
      label: '是否加工',
      control: (
        <select value={hasProcessing}
          onChange={(e) => setHasProcessing(e.target.value as '' | 'true' | 'false')}
          className={SEARCH_CONTROL}>
          <option value="">全部</option>
          <option value="true">是</option>
          <option value="false">否</option>
        </select>
      ),
    },
  ]


  return (
    <div className="p-6 space-y-4">
      {/* 标题 */}
      <PageHeader
        title="销售订单"
        actions={
          canWrite && (
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
          )
        }
      />

      {/* 查询区域（issue #5880：**纯版式重构、零行为变更**）——
          **单一响应式 grid**：列由轨道定义 ⇒ 行与行**天然对齐**。改前是**两行各自一个 flex 容器**
          （`flex-1` vs `flex-[1.5]` + 各格**不同的** `min-w-[…]`）⇒ 换行点与格宽都随视口漂移、列不对齐。
          列梯 1 / 2 / 4（<768 一列、≥768 两列、≥1536 四列）：大轨道数只放在 ≥1536 —— #5850 的病根就是
          窄屏轨道太多、只能把控件**压扁**。每格 `min-w-0`：宽度由**轨道**给，不再靠 `min-w-[…]` 撑（#5841 的溢出）。
          排布：第 1 行 = 下单时间（跨 2 轨）· 订单ID · 收货人；第 2 行 = 制单人 · 商品货号 · 商品标题 · 是否加工；
          第 3 行 = 按钮行（`col-span-full` 独占一行 + `justify-end` 右对齐）—— 主操作不再埋在第 2 行末尾。 */}
      <SearchPanel
        fields={searchPanelFields}
        onSearch={handleSearch}
        onReset={handleReset}
        onRefresh={() => loadOrders()}
        loading={loading}
      />

      {/* 表格 + Tab */}
      <div className="bg-white rounded-lg border border-neutral-200 shadow-card">
        {loadError && (
          // 失败态 ≠ 空态（issue #6703 / #6691）：说清「不是今天没有订单，是没读到」+ 真重发出口
          <div className="p-4 pb-0">
            <ListLoadError
              testId="orders-load-error"
              message="订单加载失败 —— 没读到数据，下面的条数与列表都不可信。请检查网络后重试。"
              onRetry={() => void loadOrders()}
              retrying={loading}
            />
          </div>
        )}
        {/* Tab 栏 */}
        <div className="flex items-center gap-6 px-5 pt-3 border-b border-neutral-200 overflow-x-auto">
          {OrderStatusTabs.map((tab) => {
            const active = activeTab === tab.key
            return (
              <button
                key={tab.key}
                type="button"
                onClick={() => handleTabChange(tab.key)}
                className={cn(
                  'relative pb-3 text-sm whitespace-nowrap transition-colors',
                  active ? 'text-primary-600 font-medium' : 'text-neutral-600 hover:text-neutral-900'
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
          onRefund={handleOpenRefund}
          onConfirmPayment={handleConfirmPayment}
          onConfirmReceive={handleConfirmReceive}
          /* 🔴 issue #6733：读失败 ⇒ 表体**不得**印「暂无数据」（那是「今天没有订单」的事实性断言，
             而真相是**没读到** —— 上面那行「共 — 条」已经在诚实地说"不可知"，横幅也说了读失败；
             三处说法不能打架）。读成功才回落到默认的「暂无数据」。 */
          emptyText={loadError ? '' : '暂无数据'}
        />

        {/* 分页 */}
        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-neutral-100">
          <span className="text-sm text-neutral-500 mr-2">共 {loadError ? '—' : total} 条</span>
          <button
            type="button"
            onClick={() => setCurrent(Math.max(1, current - 1))}
            disabled={current <= 1}
            className="h-8 w-8 inline-flex items-center justify-center rounded border border-neutral-300 text-neutral-500 text-sm hover:bg-neutral-50 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ‹
          </button>
          {pageList.map((p, idx) =>
            p === '...' ? (
              <span key={`dots-${idx}`} className="px-1 text-neutral-400 text-sm">
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
                    : 'text-neutral-600 hover:bg-neutral-50 border border-neutral-300'
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
            className="h-8 w-8 inline-flex items-center justify-center rounded border border-neutral-300 text-neutral-500 text-sm hover:bg-neutral-50 disabled:opacity-40 disabled:cursor-not-allowed"
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
      <RefundOrderModal
        open={refundModalOpen}
        order={selectedOrder}
        onClose={() => {
          if (!actionLoading) {
            setRefundModalOpen(false)
            setSelectedOrder(null)
          }
        }}
        onConfirm={handleConfirmRefund}
        loading={actionLoading}
      />

      {/* 确认动作弹框（issue #6664 第 4 条）：与仓内自研 Modal 同一世界观；
          取消 ⇒ 不发请求；在飞 ⇒ 按钮 disabled（防连点重复请求） */}
      <Modal
        open={confirmAction !== null}
        onClose={() => {
          if (!confirming) setConfirmAction(null)
        }}
        title={confirmAction?.kind === 'payment' ? '确认已收到客户付款' : '确认客户已收到货物'}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmAction(null)} disabled={confirming}>
              取消
            </Button>
            <Button onClick={() => void runConfirmAction()} loading={confirming}>
              确认
            </Button>
          </>
        }
      >
        <p className="text-sm text-neutral-600">
          {confirmAction?.kind === 'payment'
            ? `将订单 ${confirmAction?.order.orderNo ?? ''} 标记为「已付款」，并进入待发货。`
            : `将订单 ${confirmAction?.order.orderNo ?? ''} 标记为「已完成」。`}
        </p>
        <p className="mt-2 text-sm text-neutral-500">
          该动作会写入订单状态、不可撤销，请确认后再提交。
        </p>
      </Modal>
    </div>
  )
}
