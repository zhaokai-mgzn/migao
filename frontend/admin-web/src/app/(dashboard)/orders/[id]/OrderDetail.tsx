'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter, useParams } from 'next/navigation'
import { ArrowLeft, MapPin, Phone, User, Calendar, Package, Truck, Ban } from 'lucide-react'
import { toast } from 'sonner'
import { orderApi } from '@/lib/api'
import { Button, Card, Loading, Modal } from '@/components/ui'
import { OrderStatusBadge, OrderTimeline, OrderItemList, LogisticsInfo, LogisticsForm } from '@/components/orders'
import type { Order, OrderStatus, LogisticsFormData } from '@/types'
import { OrderStatusLabels, NextStatusMap, NextStatusActionLabels } from '@/types'
import dayjs from 'dayjs'
import { cn } from '@/lib/utils'

export default function OrderDetailPage() {
  const router = useRouter()
  const params = useParams()
  const orderId = params.id as string

  const [order, setOrder] = useState<Order | null>(null)
  const [loading, setLoading] = useState(true)

  // 状态更新确认弹窗
  const [statusConfirmOpen, setStatusConfirmOpen] = useState(false)
  const [pendingStatus, setPendingStatus] = useState<OrderStatus | null>(null)
  const [statusUpdating, setStatusUpdating] = useState(false)

  // 取消订单确认弹窗
  const [cancelConfirmOpen, setCancelConfirmOpen] = useState(false)

  // 物流信息弹窗
  const [logisticsFormOpen, setLogisticsFormOpen] = useState(false)

  // 加载订单
  const loadOrder = useCallback(async () => {
    if (!orderId) return
    setLoading(true)
    try {
      const res = await orderApi.getOrder(orderId)
      const data = res.data?.data
      if (data) setOrder(data)
    } catch (error) {
      console.error('加载订单失败:', error)
      toast.error('加载订单详情失败')
    } finally {
      setLoading(false)
    }
  }, [orderId])

  useEffect(() => {
    loadOrder()
  }, [loadOrder])

  // 推进到下一状态
  const handleNextStatus = () => {
    if (!order) return
    const next = NextStatusMap[order.status]
    if (!next) return
    setPendingStatus(next)
    setStatusConfirmOpen(true)
  }

  // 确认状态更新
  const confirmStatusUpdate = async () => {
    if (!order || !pendingStatus) return
    setStatusUpdating(true)
    try {
      await orderApi.updateOrderStatus(order.id, { status: pendingStatus })
      toast.success('状态更新成功')
      setStatusConfirmOpen(false)
      setPendingStatus(null)
      loadOrder()
    } catch {
      toast.error('状态更新失败')
    } finally {
      setStatusUpdating(false)
    }
  }

  // 取消订单
  const handleCancelOrder = async () => {
    if (!order) return
    setStatusUpdating(true)
    try {
      await orderApi.updateOrderStatus(order.id, { status: 'cancelled' })
      toast.success('订单已取消')
      setCancelConfirmOpen(false)
      loadOrder()
    } catch {
      toast.error('取消订单失败')
    } finally {
      setStatusUpdating(false)
    }
  }

  // 物流信息提交
  const handleLogisticsSubmit = async (data: LogisticsFormData) => {
    if (!order) return
    await orderApi.updateLogistics(order.id, data)
    toast.success('物流信息已更新')
    loadOrder()
  }

  // 格式化金额
  const formatAmount = (amount: number) => {
    return `¥${(amount ?? 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
  }

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center min-h-[400px]">
        <Loading size="lg" text="加载订单详情..." />
      </div>
    )
  }

  if (!order) {
    return (
      <div className="p-6 text-center py-12">
        <p className="text-gray-500 mb-4">订单不存在或已被删除</p>
        <Button onClick={() => router.push('/orders')}>返回订单列表</Button>
      </div>
    )
  }

  const nextAction = NextStatusActionLabels[order.status]
  const canCancel = ['pending', 'confirmed'].includes(order.status)

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push('/orders')}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-gray-600" />
          </button>
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-gray-900">订单详情</h1>
              <OrderStatusBadge status={order.status} />
            </div>
            <p className="text-sm text-gray-500 mt-1 font-mono">订单号: {order.orderNo}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {nextAction && (
            <Button onClick={handleNextStatus}>
              {nextAction}
            </Button>
          )}
          {canCancel && (
            <Button variant="danger" onClick={() => setCancelConfirmOpen(true)}>
              <Ban className="w-4 h-4 mr-1.5" />
              取消订单
            </Button>
          )}
        </div>
      </div>

      {/* 状态概览卡片 */}
      <Card className="mb-6">
        <div className="p-6">
          <div className="flex items-center justify-between mb-6">
            <div>
              <p className="text-sm text-gray-500 mb-1">订单金额</p>
              <p className="text-3xl font-bold text-gray-900">{formatAmount(order.totalAmount)}</p>
            </div>
            <div className="text-right">
              <p className="text-sm text-gray-500 mb-1">下单时间</p>
              <p className="text-sm font-medium text-gray-700">
                {order.createdAt ? dayjs(order.createdAt).format('YYYY-MM-DD HH:mm') : '-'}
              </p>
            </div>
          </div>

          {/* 状态流转步骤条 */}
          <OrderTimeline
            currentStatus={order.status}
            statusHistory={order.statusHistory}
          />
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 左侧 */}
        <div className="lg:col-span-2 space-y-6">
          {/* 订单明细 */}
          <Card>
            <div className="p-6">
              <div className="flex items-center gap-2 mb-4">
                <Package className="w-5 h-5 text-gray-500" />
                <h2 className="text-lg font-semibold text-gray-900">订单明细</h2>
              </div>
              {order.items && order.items.length > 0 ? (
                <OrderItemList items={order.items} />
              ) : (
                <p className="text-gray-400 text-center py-8">暂无订单明细</p>
              )}
            </div>
          </Card>

          {/* 物流信息 */}
          <Card>
            <div className="p-6">
              <LogisticsInfo
                logistics={order.logistics}
                onEdit={() => setLogisticsFormOpen(true)}
              />
            </div>
          </Card>

          {/* 备注 */}
          {order.remark && (
            <Card>
              <div className="p-6">
                <h2 className="text-lg font-semibold text-gray-900 mb-3">订单备注</h2>
                <p className="text-gray-600 bg-gray-50 p-4 rounded-lg">{order.remark}</p>
              </div>
            </Card>
          )}
        </div>

        {/* 右侧 */}
        <div className="space-y-6">
          {/* 客户信息 */}
          <Card>
            <div className="p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">客户信息</h2>
              <div className="space-y-4">
                <div className="flex items-start gap-3">
                  <User className="w-5 h-5 text-gray-400 mt-0.5" />
                  <div>
                    <p className="text-xs text-gray-500">客户姓名</p>
                    <p className="font-medium text-gray-900">{order.customerName}</p>
                  </div>
                </div>
                <div className="flex items-start gap-3">
                  <Phone className="w-5 h-5 text-gray-400 mt-0.5" />
                  <div>
                    <p className="text-xs text-gray-500">联系电话</p>
                    <p className="font-medium text-gray-900">{order.customerPhone}</p>
                  </div>
                </div>
                {order.customerAddress && (
                  <div className="flex items-start gap-3">
                    <MapPin className="w-5 h-5 text-gray-400 mt-0.5" />
                    <div>
                      <p className="text-xs text-gray-500">收货地址</p>
                      <p className="font-medium text-gray-900">{order.customerAddress}</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </Card>

          {/* 订单信息 */}
          <Card>
            <div className="p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">订单信息</h2>
              <div className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">订单ID</span>
                  <span className="font-mono text-gray-600 text-xs">{order.id}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">创建时间</span>
                  <span className="text-gray-700">
                    {order.createdAt ? dayjs(order.createdAt).format('YYYY-MM-DD HH:mm') : '-'}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">更新时间</span>
                  <span className="text-gray-700">
                    {order.updatedAt ? dayjs(order.updatedAt).format('YYYY-MM-DD HH:mm') : '-'}
                  </span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">商品数量</span>
                  <span className="text-gray-700">{order.items?.length || 0} 项</span>
                </div>
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
            <Button onClick={confirmStatusUpdate} loading={statusUpdating}>
              确认
            </Button>
          </>
        }
      >
        <p className="text-gray-600">
          确定要将订单 <span className="font-medium text-gray-900">{order.orderNo}</span> 的状态更新为{' '}
          <span className="font-medium text-primary-600">
            {pendingStatus ? OrderStatusLabels[pendingStatus] : ''}
          </span>{' '}
          吗？
        </p>
      </Modal>

      {/* 取消订单确认弹窗 */}
      <Modal
        open={cancelConfirmOpen}
        onClose={() => setCancelConfirmOpen(false)}
        title="取消订单"
        footer={
          <>
            <Button variant="secondary" onClick={() => setCancelConfirmOpen(false)} disabled={statusUpdating}>
              暂不取消
            </Button>
            <Button variant="danger" onClick={handleCancelOrder} loading={statusUpdating}>
              确认取消
            </Button>
          </>
        }
      >
        <p className="text-gray-600">
          确定要取消订单 <span className="font-medium text-gray-900">{order.orderNo}</span> 吗？取消后不可恢复。
        </p>
      </Modal>

      {/* 物流信息弹窗 */}
      <LogisticsForm
        open={logisticsFormOpen}
        onClose={() => setLogisticsFormOpen(false)}
        onSubmit={handleLogisticsSubmit}
        initialData={order.logistics ? {
          company: order.logistics.company,
          trackingNo: order.logistics.trackingNo,
        } : undefined}
      />
    </div>
  )
}
