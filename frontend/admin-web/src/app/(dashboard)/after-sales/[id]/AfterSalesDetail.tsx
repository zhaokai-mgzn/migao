'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import {
  ArrowLeft,
  User,
  Phone,
  Package,
  Clock,
  CheckCircle2,
  XCircle,
  AlertCircle,
  FileText,
  ExternalLink,
  MapPin,
} from 'lucide-react'
import Image from 'next/image'
import { toast } from 'sonner'
import { afterSalesApi, reworkOrderApi } from '@/lib/api'
import { loadErrorMessage } from '@/lib/api-error'
import { displayEnum } from '@/lib/enum-display'
import { Button, Card, Loading, Modal, Badge } from '@/components/ui'
import { useRouteId } from '@/lib/use-route-id'
import { usePermission } from '@/lib/permission'
import type { AfterSalesTicket, AfterSalesStatus } from '@/types'
import type { ReworkOrder, ReworkStatus } from '@/types/rework'
import {
  AfterSalesStatusLabels,
  AfterSalesTypeLabels,
  AfterSalesPriorityLabels,
} from '@/types'
import DateTimeCell from '@/components/common/DateTimeCell'
import { cn } from '@/lib/utils'

// 工单来源中文标签（issue #3686）：后端 source 表示工单**真实来源**
// customer=顾客发起 / agent=AI 建单 / merchant=人工建单。
// 取值集合与 AfterSalesTicketService 的 SOURCE_* 常量一一对应；
// 新增取值时必须同步此处，否则详情页会静默显示 '-'。
const TICKET_SOURCE_LABELS: Record<string, string> = {
  customer: '客户提交',
  agent: '客服创建',
  merchant: '商家创建',
}

// 状态操作配置：根据当前状态决定可用操作
// 注意：这里必须与后端 AfterSalesTicketService.STATUS_TRANSITIONS 保持一致，
// 否则会出现「后端允许但界面走不到」的断链（issue #3541/#3576：pending → closed 已由
// 后端放开，前端却只在 processing 提供「关闭工单」）。
const statusActions: Record<AfterSalesStatus, { label: string; targetStatus: AfterSalesStatus; variant?: 'danger' | 'secondary' }[]> = {
  pending: [
    { label: '接受处理', targetStatus: 'processing' },
    // 误建/线下已处理的工单允许直接关闭（#3541 裁定）；形态与 processing 的关闭项一致（同 label / 同 variant + 同确认弹窗收集 remark 作为关闭原因）
    { label: '关闭工单', targetStatus: 'closed', variant: 'secondary' },
    { label: '拒绝', targetStatus: 'rejected', variant: 'danger' },
  ],
  processing: [
    { label: '完成处理', targetStatus: 'resolved' },
    { label: '关闭工单', targetStatus: 'closed', variant: 'secondary' },
  ],
  resolved: [],
  rejected: [],
  closed: [],
}

/**
 * 售后单上「发起返工」这个入口的显隐/可用性（issue #7377 段 4）。
 *
 * 🔴 与后端 `ReworkState.canOpenFor` **同口径**：已闭环（closed / resolved / rejected）不许开；
 * 这张单已有未完结返工单也不许开（服务端同样拒，此处在入口上先讲清，避免点进去才报错）。
 * 这里只是**入口口径**，不是安全边界 —— 服务端仍然照拒。
 *
 * @returns `visible` 是否显示入口；`disabled` 显示但不可点（已有未完结返工单）；`reason` 为什么
 */
export function reworkEntry(
  ticketStatus: AfterSalesStatus | undefined,
  hasWrite: boolean,
  orders: ReworkOrder[],
): { visible: boolean; disabled: boolean; reason: string; openOrder: ReworkOrder | null } {
  const openOrder = orders.find((o) => o.status === 'draft' || o.status === 'in_progress') ?? null
  if (!ticketStatus) return { visible: false, disabled: false, reason: '', openOrder }
  const closed = ['closed', 'resolved', 'rejected'].includes(ticketStatus)
  const visible = hasWrite && !closed
  if (!visible) return { visible, disabled: false, reason: '', openOrder }
  if (openOrder) {
    return {
      visible,
      disabled: true,
      reason: `这张售后单已有未完结的返工单（${openOrder.reworkNo}），先完成或取消它`,
      openOrder,
    }
  }
  return { visible, disabled: false, reason: '', openOrder }
}

const REWORK_STATUS_LABEL: Record<ReworkStatus, string> = {
  draft: '待开工',
  in_progress: '返工中',
  done: '已完成',
  cancelled: '已取消',
}

// 时间线图标
const statusTimelineIcon: Record<AfterSalesStatus, typeof CheckCircle2> = {
  pending: AlertCircle,
  processing: Clock,
  resolved: CheckCircle2,
  rejected: XCircle,
  closed: XCircle,
}

// 时间线颜色
const statusTimelineColor: Record<AfterSalesStatus, string> = {
  pending: 'text-amber-500 bg-amber-50 border-amber-200',
  processing: 'text-primary-500 bg-primary-50 border-primary-200',
  resolved: 'text-green-500 bg-green-50 border-green-200',
  rejected: 'text-red-500 bg-red-50 border-red-200',
  closed: 'text-neutral-500 bg-neutral-50 border-neutral-200',
}

export default function AfterSalesDetailPage() {
  const router = useRouter()
  const ticketId = useRouteId('id')
  // issue #5913（由类级元守卫 `tests/unit/cross-domain-nav-permission-guard.test.ts` 抓出的
  // **同族第二处**）：本页守卫码是 `after_sales:view`，而「订单号」跳的 `/orders/{id}` 守卫码是
  // `order:list`。默认岗位里两者总同时持有（客服/运营），但岗位权限页可以只给前者
  // ⇒ 那就是一个「看得见、点进去 403」的入口。⇒ 无 `order:list` 时订单号**照显、只是不再是入口**。
  const { has } = usePermission()
  const canViewOrder = has('order:list')

  const [ticket, setTicket] = useState<AfterSalesTicket | null>(null)
  const [loading, setLoading] = useState(true)

  // 返工单（issue #7377 段 4）：本页是**发起返工**的入口，返工本身的推进在 `/rework-orders`
  const [reworkOrders, setReworkOrders] = useState<ReworkOrder[]>([])
  const [reworkLoadFailed, setReworkLoadFailed] = useState(false)
  const [reworkOpen, setReworkOpen] = useState(false)
  const [reworkReason, setReworkReason] = useState('')
  const [reworkProcessing, setReworkProcessing] = useState('')
  const [reworkError, setReworkError] = useState('')
  const [reworkBusy, setReworkBusy] = useState(false)
  const canWriteRework = has('order:refund')

  // 状态更新
  const [statusConfirmOpen, setStatusConfirmOpen] = useState(false)
  const [pendingAction, setPendingAction] = useState<{ label: string; targetStatus: AfterSalesStatus } | null>(null)
  const [statusUpdating, setStatusUpdating] = useState(false)
  const [statusRemark, setStatusRemark] = useState('')

  // 加载工单
  const loadTicket = useCallback(async () => {
    if (!ticketId) return
    setLoading(true)
    try {
      const res = await afterSalesApi.getTicket(ticketId)
      const data = res.data?.data
      if (data) setTicket(data)
    } catch (error) {
      console.error('加载售后工单失败:', error)
      toast.error('加载工单详情失败')
    } finally {
      setLoading(false)
    }
  }, [ticketId])

  /**
   * 读这张售后单的返工单（issue #7377 段 4）。
   *
   * ⚠️ **失败不拖垮整页**：返工接口读不到时工单本身仍然可看可操作，只在返工区块写一行失败提示
   * （把「售后详情」这块主业务挡住去换一个附属读数，是本末倒置）。
   */
  const loadRework = useCallback(async () => {
    if (!ticketId) return
    try {
      const res = await reworkOrderApi.list(ticketId)
      setReworkOrders((res.data?.data ?? []) as ReworkOrder[])
      setReworkLoadFailed(false)
    } catch (error) {
      console.error('加载返工单失败:', error)
      setReworkLoadFailed(true)
    }
  }, [ticketId])

  useEffect(() => {
    loadTicket()
    loadRework()
  }, [loadTicket, loadRework])

  async function submitRework() {
    if (!ticket) return
    setReworkError('')
    const reason = reworkReason.trim()
    if (!reason) {
      setReworkError('写一句返工原因 —— 师傅要知道返哪一步')
      return
    }
    setReworkBusy(true)
    try {
      await reworkOrderApi.create({
        afterSalesTicketId: ticket.id,
        reason,
        processingOrderId: reworkProcessing.trim() || undefined,
      })
      toast.success('返工单已开，去「返工单」页开工/完工')
      setReworkOpen(false)
      setReworkReason('')
      setReworkProcessing('')
      await Promise.all([loadTicket(), loadRework()])
    } catch (e) {
      // 🔴 服务端拒绝原话上屏（已闭环 / 已有未完结返工单 / 并发撞索引）
      setReworkError(loadErrorMessage(e, '开返工单'))
    } finally {
      setReworkBusy(false)
    }
  }

  // 打开状态确认弹窗
  const handleStatusAction = (action: { label: string; targetStatus: AfterSalesStatus }) => {
    setPendingAction(action)
    setStatusRemark('')
    setStatusConfirmOpen(true)
  }

  // 确认状态更新
  const confirmStatusUpdate = async () => {
    if (!ticket || !pendingAction) return
    setStatusUpdating(true)
    try {
      await afterSalesApi.updateTicketStatus(ticket.id, {
        status: pendingAction.targetStatus,
        remark: statusRemark || undefined,
      })
      toast.success('状态更新成功')
      setStatusConfirmOpen(false)
      setPendingAction(null)
      setStatusRemark('')
      loadTicket()
    } catch (e) {
      toast.error('状态更新失败')
    } finally {
      setStatusUpdating(false)
    }
  }

  // 状态 Badge 变体
  const getStatusVariant = (status: AfterSalesStatus): 'success' | 'warning' | 'error' | 'default' | 'info' => {
    const map: Record<AfterSalesStatus, 'success' | 'warning' | 'error' | 'default' | 'info'> = {
      pending: 'warning',
      processing: 'info',
      resolved: 'success',
      rejected: 'error',
      closed: 'default',
    }
    return map[status] || 'default'
  }

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <Loading size="lg" text="加载工单详情..." />
      </div>
    )
  }

  if (!ticket) {
    return (
      <div className="p-6 text-center py-12">
        <p className="text-neutral-500 mb-4">工单不存在或已被删除</p>
        <Button onClick={() => router.push('/after-sales')}>返回工单列表</Button>
      </div>
    )
  }

  const actions = statusActions[ticket.status] || []

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push('/after-sales')}
            className="p-2 hover:bg-neutral-100 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-neutral-600" />
          </button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-neutral-900">工单详情</h1>
              <Badge variant={getStatusVariant(ticket.status)}>
                {AfterSalesStatusLabels[ticket.status]}
              </Badge>
              {ticket.priority && (
                <Badge variant={ticket.priority === 'critical' ? 'error' : ticket.priority === 'urgent' ? 'warning' : 'default'}>
                  {AfterSalesPriorityLabels[ticket.priority]}
                </Badge>
              )}
            </div>
            <p className="text-sm text-neutral-500 mt-1 font-mono">工单号: {ticket.ticketNo}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {/*
            🔴 发起返工（issue #7377 段 4）：售后判定要返工 ⇒ 就在这里开单，不必再手抄单号去返工单页。
            显隐/可用性由 `reworkEntry()` 一处判定（已闭环不显示；已有未完结返工单显示但不可点）。
          */}
          {reworkEntry(ticket.status, canWriteRework, reworkOrders).visible && (
            <Button
              variant="secondary"
              disabled={reworkEntry(ticket.status, canWriteRework, reworkOrders).disabled}
              title={reworkEntry(ticket.status, canWriteRework, reworkOrders).reason || undefined}
              onClick={() => {
                setReworkError('')
                setReworkOpen(true)
              }}
              data-testid="after-sales-rework-create"
            >
              发起返工
            </Button>
          )}
          {actions.map((action) => (
            <Button
              key={action.targetStatus}
              variant={action.variant as any}
              onClick={() => handleStatusAction(action)}
            >
              {action.label}
            </Button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧 */}
        <div className="lg:col-span-2 space-y-6">
          {/* 工单信息卡片 */}
          <Card>
            <div className="p-6">
              <div className="flex items-center gap-2 mb-4">
                <FileText className="w-5 h-5 text-neutral-500" />
                <h2 className="text-lg font-semibold text-neutral-900">工单信息</h2>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-neutral-500 mb-1">售后类型</p>
                  <p className="text-sm font-medium text-neutral-900">
                    {AfterSalesTypeLabels[ticket.ticketType] || ticket.ticketType}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-neutral-500 mb-1">创建时间</p>
                  {/* issue #6799：DateTimeCell 渲染的是 `<div>`（两行 YYYY-MM-DD / HH:mm），
                      不能再挂在 `<p>` 里 —— `<p>` 只允许短语内容，浏览器解析时会把 `<p>` 就地闭合，
                      于是服务端 HTML 与 React 树的形状不一致 ⇒ hydration 报
                      「In HTML, <div> cannot be a descendant of <p>」并**整页 hydration 失败**。
                      换 `<div>` 而非把 DateTimeCell 改成 `<span>`：两行布局（leading-snug + 第二行
                      弱化色）依赖块级子元素，改成内联会动版式（截图对照见 PR）。 */}
                  <div className="text-sm font-medium text-neutral-900">
                    {<DateTimeCell value={ticket.createdAt} />}
                  </div>
                </div>
                {ticket.refundAmount !== undefined && ticket.refundAmount !== null && (
                  <div>
                    <p className="text-xs text-neutral-500 mb-1">退款金额</p>
                    <p className="text-sm font-medium text-red-600">
                      ¥{ticket.refundAmount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </p>
                  </div>
                )}
                {ticket.deadline && (
                  <div>
                    <p className="text-xs text-neutral-500 mb-1">处理截止时间</p>
                    <div className="text-sm font-medium text-neutral-900">
                      {<DateTimeCell value={ticket.deadline} />}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </Card>

          {/* 售后原因和描述 */}
          <Card>
            <div className="p-6">
              <h2 className="text-lg font-semibold text-neutral-900 mb-3">售后原因</h2>
              <p className="text-neutral-600 bg-neutral-50 p-4 rounded-lg whitespace-pre-wrap">
                {ticket.description || '无描述'}
              </p>
              {ticket.images && ticket.images.length > 0 && (
                <div className="mt-4">
                  <p className="text-sm text-neutral-500 mb-2">相关图片</p>
                  <div className="flex flex-wrap gap-2">
                    {ticket.images.map((img, i) => (
                      <a
                        key={i}
                        href={img}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="w-20 h-20 rounded-lg border border-neutral-200 overflow-hidden hover:border-primary-400 transition-colors"
                      >
                        <Image src={img} alt={`图片${i + 1}`} width={80} height={80} className="w-full h-full object-cover" unoptimized />
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Card>

          {/* 返工单（issue #7377 段 4）：只在有读数或读失败时出现 —— 没返工的空区块只是噪音 */}
          {(reworkOrders.length > 0 || reworkLoadFailed) && (
            <Card>
              <div className="p-6">
                <div className="flex items-center gap-2 mb-3">
                  <Package className="w-5 h-5 text-neutral-500" />
                  <h2 className="text-lg font-semibold text-neutral-900">返工单</h2>
                  <span className="text-xs text-neutral-500">返工的推进在「返工单」页</span>
                </div>
                {reworkLoadFailed ? (
                  <p className="text-sm text-neutral-500" data-testid="after-sales-rework-load-error">
                    返工单没读到 —— 不影响这张工单本身的操作，可稍后刷新。
                  </p>
                ) : (
                  <div className="space-y-2" data-testid="after-sales-rework-list">
                    {reworkOrders.map((order) => (
                      <div
                        key={order.id}
                        className="flex flex-wrap items-center justify-between gap-2 text-sm"
                        data-testid={`after-sales-rework-row-${order.id}`}
                      >
                        <span className="font-mono text-neutral-800">{order.reworkNo}</span>
                        <span className="text-neutral-600">{displayEnum(REWORK_STATUS_LABEL, order.status)}</span>
                        <span className="text-neutral-500">{order.reason || '—'}</span>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => router.push('/rework-orders')}
                          data-testid={`after-sales-rework-goto-${order.id}`}
                        >
                          查看返工单
                        </Button>
                      </div>
                    ))}
                  </div>
                )}
                {reworkEntry(ticket.status, canWriteRework, reworkOrders).reason && (
                  <p className="mt-2 text-xs text-amber-600" data-testid="after-sales-rework-hint">
                    {reworkEntry(ticket.status, canWriteRework, reworkOrders).reason}
                  </p>
                )}
              </div>
            </Card>
          )}

          {/* 处理时间线 */}
          <Card>
            <div className="p-6">
              <div className="flex items-center gap-2 mb-4">
                <Clock className="w-5 h-5 text-neutral-500" />
                <h2 className="text-lg font-semibold text-neutral-900">处理时间线</h2>
              </div>
              {ticket.statusHistory && ticket.statusHistory.length > 0 ? (
                <div className="relative">
                  {/* 竖线 */}
                  <div className="absolute left-4 top-6 bottom-6 w-px bg-neutral-200" />
                  <div className="space-y-6">
                    {ticket.statusHistory.map((history, index) => {
                      const Icon = statusTimelineIcon[history.status] || AlertCircle
                      const colorClass = statusTimelineColor[history.status] || statusTimelineColor.pending
                      return (
                        <div key={index} className="flex items-start gap-4 relative">
                          <div className={cn('w-8 h-8 rounded-full flex items-center justify-center border flex-shrink-0 z-10', colorClass)}>
                            <Icon className="w-4 h-4" />
                          </div>
                          <div className="flex-1 min-w-0 pt-1">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium text-neutral-900">
                                {AfterSalesStatusLabels[history.status]}
                              </span>
                              <span className="text-xs text-neutral-400">
                                {<DateTimeCell value={history.time} />}
                              </span>
                            </div>
                            {history.operator && (
                              <p className="text-xs text-neutral-500 mt-0.5">操作人: {history.operator}</p>
                            )}
                            {history.remark && (
                              <p className="text-sm text-neutral-600 mt-1 bg-neutral-50 px-3 py-2 rounded">
                                {history.remark}
                              </p>
                            )}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              ) : (
                <p className="text-neutral-400 text-center py-8">暂无处理记录</p>
              )}
            </div>
          </Card>

          {/* 内部备注 */}
          {ticket.internalNotes && (
            <Card>
              <div className="p-6">
                <h2 className="text-lg font-semibold text-neutral-900 mb-3">内部备注</h2>
                <p className="text-neutral-600 bg-amber-50 p-4 rounded-lg border border-amber-100 whitespace-pre-wrap">
                  {ticket.internalNotes}
                </p>
              </div>
            </Card>
          )}
        </div>

        {/* 右侧 */}
        <div className="space-y-6">
          {/* 关联订单 */}
          <Card>
            <div className="p-6">
              <h2 className="text-lg font-semibold text-neutral-900 mb-4">关联订单</h2>
              <div className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-neutral-500">订单号</span>
                  {canViewOrder ? (
                    <button
                      onClick={() => router.push(`/orders/${ticket.orderId}`)}
                      className="font-mono text-primary-600 hover:text-primary-700 flex items-center gap-1"
                    >
                      {ticket.orderNo || ticket.orderId}
                      <ExternalLink className="w-3 h-3" />
                    </button>
                  ) : (
                    <span className="font-mono text-neutral-700">{ticket.orderNo || ticket.orderId}</span>
                  )}
                </div>
              </div>
            </div>
          </Card>

          {/* 客户信息 */}
          <Card>
            <div className="p-6">
              <h2 className="text-lg font-semibold text-neutral-900 mb-4">客户信息</h2>
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <User className="w-5 h-5 text-neutral-400 mt-0.5" />
                  <div>
                    <p className="text-xs text-neutral-500">客户姓名</p>
                    <p className="font-medium text-neutral-900">{ticket.customerName || '-'}</p>
                  </div>
                </div>
                {ticket.customerPhone && (
                  <div className="flex items-start gap-3">
                    <Phone className="w-5 h-5 text-neutral-400 mt-0.5" />
                    <div>
                      <p className="text-xs text-neutral-500">联系电话</p>
                      <p className="font-medium text-neutral-900">{ticket.customerPhone}</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </Card>

          {/* 工单详细信息 */}
          <Card>
            <div className="p-6">
              <h2 className="text-lg font-semibold text-neutral-900 mb-4">工单信息</h2>
              <div className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-neutral-500">工单ID</span>
                  <span className="font-mono text-neutral-600 text-xs">{ticket.id}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-neutral-500">来源</span>
                  <span className="text-neutral-700">
                    {TICKET_SOURCE_LABELS[ticket.source ?? ''] ?? '-'}
                  </span>
                </div>
                {ticket.handlerName && (
                  <div className="flex justify-between text-sm">
                    <span className="text-neutral-500">处理人</span>
                    <span className="text-neutral-700">{ticket.handlerName}</span>
                  </div>
                )}
                {ticket.assignedAt && (
                  <div className="flex justify-between text-sm">
                    <span className="text-neutral-500">分配时间</span>
                    <span className="text-neutral-700">
                      {<DateTimeCell value={ticket.assignedAt} />}
                    </span>
                  </div>
                )}
                <div className="flex justify-between text-sm">
                  <span className="text-neutral-500">创建时间</span>
                  <span className="text-neutral-700">
                    {<DateTimeCell value={ticket.createdAt} />}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-neutral-500">更新时间</span>
                  <span className="text-neutral-700">
                    {<DateTimeCell value={ticket.updatedAt} />}
                  </span>
                </div>
                {ticket.closedAt && (
                  <div className="flex justify-between text-sm">
                    <span className="text-neutral-500">关闭时间</span>
                    <span className="text-neutral-700">
                      {<DateTimeCell value={ticket.closedAt} />}
                    </span>
                  </div>
                )}
                {ticket.closeReason && (
                  <div className="flex justify-between text-sm">
                    <span className="text-neutral-500">关闭原因</span>
                    <span className="text-neutral-700">{ticket.closeReason}</span>
                  </div>
                )}
              </div>
            </div>
          </Card>
        </div>
      </div>

      {/* 开返工弹窗（issue #7377 段 4）：原因必填（师傅要知道返哪一步），加工单号可留空 */}
      <Modal
        open={reworkOpen}
        onClose={() => setReworkOpen(false)}
        title="发起返工"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setReworkOpen(false)}>
              取消
            </Button>
            <Button loading={reworkBusy} onClick={() => void submitRework()} data-testid="after-sales-rework-submit">
              开单
            </Button>
          </div>
        }
      >
        <div className="space-y-3">
          <p className="text-sm text-neutral-600">
            开出来是「待开工」；师傅在「返工单」页开工、完工，完工后这张售后单才会推进到「已解决」。
          </p>
          <label className="block text-sm font-medium text-neutral-700">
            返工原因
            <input
              data-testid="after-sales-rework-reason"
              value={reworkReason}
              onChange={(e) => setReworkReason(e.target.value)}
              placeholder="例如：帘头褶皱不齐，需重做帘头"
              className="mt-1.5 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
            />
          </label>
          <label className="block text-sm font-medium text-neutral-700">
            关联加工单号（可留空）
            <input
              data-testid="after-sales-rework-processing"
              value={reworkProcessing}
              onChange={(e) => setReworkProcessing(e.target.value)}
              placeholder="例如：JG-20261023-0008"
              className="mt-1.5 w-full rounded-lg border border-neutral-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none"
            />
          </label>
          {reworkError && (
            <p className="text-sm text-red-600" data-testid="after-sales-rework-error">
              {reworkError}
            </p>
          )}
        </div>
      </Modal>

      {/* 状态确认弹窗 */}
      <Modal
        open={statusConfirmOpen}
        onClose={() => setStatusConfirmOpen(false)}
        title="确认操作"
        footer={
          <>
            <Button variant="secondary" onClick={() => setStatusConfirmOpen(false)} disabled={statusUpdating}>
              取消
            </Button>
            <Button
              variant={pendingAction?.targetStatus === 'rejected' ? 'danger' : undefined}
              onClick={confirmStatusUpdate}
              loading={statusUpdating}
            >
              确认{pendingAction?.label}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-neutral-600">
            确定要将工单 <span className="font-medium text-neutral-900">{ticket.ticketNo}</span> 的状态更新为{' '}
            <span className="font-medium text-primary-600">
              {pendingAction ? AfterSalesStatusLabels[pendingAction.targetStatus] : ''}
            </span>{' '}
            吗？
          </p>
          <div>
            <label className="block text-sm font-medium text-neutral-700 mb-1.5">处理备注（可选）</label>
            <textarea
              value={statusRemark}
              onChange={(e) => setStatusRemark(e.target.value)}
              placeholder="请输入处理备注..."
              rows={3}
              className="w-full px-3 py-2 rounded border border-neutral-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}
