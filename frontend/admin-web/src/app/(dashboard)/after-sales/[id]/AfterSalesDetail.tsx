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
import { afterSalesApi } from '@/lib/api'
import { Button, Card, Loading, Modal, Badge } from '@/components/ui'
import { useRouteId } from '@/lib/use-route-id'
import type { AfterSalesTicket, AfterSalesStatus } from '@/types'
import {
  AfterSalesStatusLabels,
  AfterSalesTypeLabels,
  AfterSalesPriorityLabels,
} from '@/types'
import dayjs from 'dayjs'
import { cn } from '@/lib/utils'

// 状态操作配置：根据当前状态决定可用操作
const statusActions: Record<AfterSalesStatus, { label: string; targetStatus: AfterSalesStatus; variant?: 'danger' | 'secondary' }[]> = {
  pending: [
    { label: '接受处理', targetStatus: 'processing' },
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
  processing: 'text-blue-500 bg-blue-50 border-blue-200',
  resolved: 'text-green-500 bg-green-50 border-green-200',
  rejected: 'text-red-500 bg-red-50 border-red-200',
  closed: 'text-gray-500 bg-gray-50 border-gray-200',
}

export default function AfterSalesDetailPage() {
  const router = useRouter()
  const ticketId = useRouteId('id')

  const [ticket, setTicket] = useState<AfterSalesTicket | null>(null)
  const [loading, setLoading] = useState(true)

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

  useEffect(() => {
    loadTicket()
  }, [loadTicket])

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
        <p className="text-gray-500 mb-4">工单不存在或已被删除</p>
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
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-gray-600" />
          </button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-gray-900">工单详情</h1>
              <Badge variant={getStatusVariant(ticket.status)}>
                {AfterSalesStatusLabels[ticket.status]}
              </Badge>
              {ticket.priority && (
                <Badge variant={ticket.priority === 'critical' ? 'error' : ticket.priority === 'urgent' ? 'warning' : 'default'}>
                  {AfterSalesPriorityLabels[ticket.priority]}
                </Badge>
              )}
            </div>
            <p className="text-sm text-gray-500 mt-1 font-mono">工单号: {ticket.ticketNo}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
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
                <FileText className="w-5 h-5 text-gray-500" />
                <h2 className="text-lg font-semibold text-gray-900">工单信息</h2>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-gray-500 mb-1">售后类型</p>
                  <p className="text-sm font-medium text-gray-900">
                    {AfterSalesTypeLabels[ticket.ticketType] || ticket.ticketType}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 mb-1">创建时间</p>
                  <p className="text-sm font-medium text-gray-900">
                    {ticket.createdAt ? dayjs(ticket.createdAt).format('YYYY-MM-DD HH:mm') : '-'}
                  </p>
                </div>
                {ticket.refundAmount !== undefined && ticket.refundAmount !== null && (
                  <div>
                    <p className="text-xs text-gray-500 mb-1">退款金额</p>
                    <p className="text-sm font-medium text-red-600">
                      ¥{ticket.refundAmount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </p>
                  </div>
                )}
                {ticket.deadline && (
                  <div>
                    <p className="text-xs text-gray-500 mb-1">处理截止时间</p>
                    <p className="text-sm font-medium text-gray-900">
                      {dayjs(ticket.deadline).format('YYYY-MM-DD HH:mm')}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </Card>

          {/* 售后原因和描述 */}
          <Card>
            <div className="p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-3">售后原因</h2>
              <p className="text-gray-600 bg-gray-50 p-4 rounded-lg whitespace-pre-wrap">
                {ticket.description || '无描述'}
              </p>
              {ticket.images && ticket.images.length > 0 && (
                <div className="mt-4">
                  <p className="text-sm text-gray-500 mb-2">相关图片</p>
                  <div className="flex flex-wrap gap-2">
                    {ticket.images.map((img, i) => (
                      <a
                        key={i}
                        href={img}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="w-20 h-20 rounded-lg border border-gray-200 overflow-hidden hover:border-primary-400 transition-colors"
                      >
                        <Image src={img} alt={`图片${i + 1}`} width={80} height={80} className="w-full h-full object-cover" unoptimized />
                      </a>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </Card>

          {/* 处理时间线 */}
          <Card>
            <div className="p-6">
              <div className="flex items-center gap-2 mb-4">
                <Clock className="w-5 h-5 text-gray-500" />
                <h2 className="text-lg font-semibold text-gray-900">处理时间线</h2>
              </div>
              {ticket.statusHistory && ticket.statusHistory.length > 0 ? (
                <div className="relative">
                  {/* 竖线 */}
                  <div className="absolute left-4 top-6 bottom-6 w-px bg-gray-200" />
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
                              <span className="text-sm font-medium text-gray-900">
                                {AfterSalesStatusLabels[history.status]}
                              </span>
                              <span className="text-xs text-gray-400">
                                {history.time ? dayjs(history.time).format('YYYY-MM-DD HH:mm:ss') : ''}
                              </span>
                            </div>
                            {history.operator && (
                              <p className="text-xs text-gray-500 mt-0.5">操作人: {history.operator}</p>
                            )}
                            {history.remark && (
                              <p className="text-sm text-gray-600 mt-1 bg-gray-50 px-3 py-2 rounded">
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
                <p className="text-gray-400 text-center py-8">暂无处理记录</p>
              )}
            </div>
          </Card>

          {/* 内部备注 */}
          {ticket.internalNotes && (
            <Card>
              <div className="p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-3">内部备注</h2>
                <p className="text-gray-600 bg-amber-50 p-4 rounded-lg border border-amber-100 whitespace-pre-wrap">
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
              <h2 className="text-lg font-semibold text-gray-900 mb-4">关联订单</h2>
              <div className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">订单号</span>
                  <button
                    onClick={() => router.push(`/orders/${ticket.orderId}`)}
                    className="font-mono text-primary-600 hover:text-primary-700 flex items-center gap-1"
                  >
                    {ticket.orderNo || ticket.orderId}
                    <ExternalLink className="w-3 h-3" />
                  </button>
                </div>
              </div>
            </div>
          </Card>

          {/* 客户信息 */}
          <Card>
            <div className="p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">客户信息</h2>
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <User className="w-5 h-5 text-gray-400 mt-0.5" />
                  <div>
                    <p className="text-xs text-gray-500">客户姓名</p>
                    <p className="font-medium text-gray-900">{ticket.customerName || '-'}</p>
                  </div>
                </div>
                {ticket.customerPhone && (
                  <div className="flex items-start gap-3">
                    <Phone className="w-5 h-5 text-gray-400 mt-0.5" />
                    <div>
                      <p className="text-xs text-gray-500">联系电话</p>
                      <p className="font-medium text-gray-900">{ticket.customerPhone}</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </Card>

          {/* 工单详细信息 */}
          <Card>
            <div className="p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">工单信息</h2>
              <div className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">工单ID</span>
                  <span className="font-mono text-gray-600 text-xs">{ticket.id}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">来源</span>
                  <span className="text-gray-700">
                    {ticket.source === 'customer' ? '客户提交' : ticket.source === 'agent' ? '客服创建' : '-'}
                  </span>
                </div>
                {ticket.handlerName && (
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">处理人</span>
                    <span className="text-gray-700">{ticket.handlerName}</span>
                  </div>
                )}
                {ticket.assignedAt && (
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">分配时间</span>
                    <span className="text-gray-700">
                      {dayjs(ticket.assignedAt).format('YYYY-MM-DD HH:mm')}
                    </span>
                  </div>
                )}
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">创建时间</span>
                  <span className="text-gray-700">
                    {ticket.createdAt ? dayjs(ticket.createdAt).format('YYYY-MM-DD HH:mm') : '-'}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">更新时间</span>
                  <span className="text-gray-700">
                    {ticket.updatedAt ? dayjs(ticket.updatedAt).format('YYYY-MM-DD HH:mm') : '-'}
                  </span>
                </div>
                {ticket.closedAt && (
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">关闭时间</span>
                    <span className="text-gray-700">
                      {dayjs(ticket.closedAt).format('YYYY-MM-DD HH:mm')}
                    </span>
                  </div>
                )}
                {ticket.closeReason && (
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-500">关闭原因</span>
                    <span className="text-gray-700">{ticket.closeReason}</span>
                  </div>
                )}
              </div>
            </div>
          </Card>
        </div>
      </div>

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
          <p className="text-gray-600">
            确定要将工单 <span className="font-medium text-gray-900">{ticket.ticketNo}</span> 的状态更新为{' '}
            <span className="font-medium text-primary-600">
              {pendingAction ? AfterSalesStatusLabels[pendingAction.targetStatus] : ''}
            </span>{' '}
            吗？
          </p>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">处理备注（可选）</label>
            <textarea
              value={statusRemark}
              onChange={(e) => setStatusRemark(e.target.value)}
              placeholder="请输入处理备注..."
              rows={3}
              className="w-full px-3 py-2 rounded border border-gray-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}
