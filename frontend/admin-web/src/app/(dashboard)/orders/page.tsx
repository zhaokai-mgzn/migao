'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, Search, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import { orderApi } from '@/lib/api'
import { Pagination, Modal, Button, Input, Select } from '@/components/ui'
import { OrderTable } from '@/components/orders'
import type { Order, OrderStatus } from '@/types'
import { OrderStatusLabels } from '@/types'
import dayjs from 'dayjs'
import { cn } from '@/lib/utils'

// 状态 Tab 配置
const statusTabs: { key: OrderStatus | ''; label: string }[] = [
  { key: '', label: '全部' },
  { key: 'pending', label: '待确认' },
  { key: 'confirmed', label: '已确认' },
  { key: 'producing', label: '生产中' },
  { key: 'shipped', label: '已发货' },
  { key: 'completed', label: '已完成' },
  { key: 'cancelled', label: '已取消' },
]

export default function OrdersPage() {
  const router = useRouter()
  const [orders, setOrders] = useState<Order[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  // 筛选
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<OrderStatus | ''>('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')

  // 实际提交的搜索参数
  const [searchParams, setSearchParams] = useState<{
    keyword: string
    status: OrderStatus | ''
    startDate: string
    endDate: string
  }>({ keyword: '', status: '', startDate: '', endDate: '' })

  // 状态统计
  const [statusCounts, setStatusCounts] = useState<Record<string, number>>({})

  // 删除确认弹窗
  const [deleteModalOpen, setDeleteModalOpen] = useState(false)
  const [deletingOrder, setDeletingOrder] = useState<Order | null>(null)

  // 状态更新弹窗
  const [statusModalOpen, setStatusModalOpen] = useState(false)
  const [statusUpdatingOrder, setStatusUpdatingOrder] = useState<Order | null>(null)
  const [newStatus, setNewStatus] = useState<OrderStatus>('pending')

  // 加载订单
  const loadOrders = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = {
        page: current,
        size: pageSize,
      }
      if (searchParams.keyword) params.keyword = searchParams.keyword
      if (searchParams.status) params.status = searchParams.status
      if (searchParams.startDate) params.startDate = searchParams.startDate
      if (searchParams.endDate) params.endDate = searchParams.endDate

      const res = await orderApi.getOrders(params as any)
      const pageData = res.data?.data
      setOrders(pageData?.items || [])
      setTotal(pageData?.total || 0)
    } catch (error) {
      console.error('加载订单失败:', error)
      toast.error('加载订单失败')
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, searchParams])

  // 加载状态统计（简单实现：对全部订单做一次无状态筛选获取总数）
  const loadStatusCounts = useCallback(async () => {
    try {
      // 获取各状态数量 - 实际可用 dashboard API，此处简单获取总数
      const res = await orderApi.getOrders({ page: 1, size: 1 })
      const totalCount = res.data?.data?.total || 0
      setStatusCounts((prev) => ({ ...prev, all: totalCount }))
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    loadOrders()
  }, [loadOrders])

  useEffect(() => {
    loadStatusCounts()
  }, [loadStatusCounts])

  // 搜索
  const handleSearch = () => {
    setCurrent(1)
    setSearchParams({ keyword, status: statusFilter, startDate, endDate })
  }

  // 重置
  const handleReset = () => {
    setKeyword('')
    setStatusFilter('')
    setStartDate('')
    setEndDate('')
    setCurrent(1)
    setSearchParams({ keyword: '', status: '', startDate: '', endDate: '' })
  }

  // Tab 切换
  const handleTabChange = (status: OrderStatus | '') => {
    setStatusFilter(status)
    setCurrent(1)
    setSearchParams((prev) => ({ ...prev, status }))
  }

  // 删除
  const handleDelete = (order: Order) => {
    setDeletingOrder(order)
    setDeleteModalOpen(true)
  }

  const confirmDelete = async () => {
    if (!deletingOrder) return
    try {
      await orderApi.deleteOrder(deletingOrder.id)
      toast.success('删除成功')
      loadOrders()
    } catch {
      toast.error('删除失败')
    } finally {
      setDeleteModalOpen(false)
      setDeletingOrder(null)
    }
  }

  // 状态更新
  const handleOpenStatusModal = (order: Order) => {
    setStatusUpdatingOrder(order)
    setNewStatus(order.status)
    setStatusModalOpen(true)
  }

  const confirmStatusUpdate = async () => {
    if (!statusUpdatingOrder) return
    try {
      await orderApi.updateOrderStatus(statusUpdatingOrder.id, { status: newStatus })
      toast.success('状态更新成功')
      loadOrders()
    } catch {
      toast.error('状态更新失败')
    } finally {
      setStatusModalOpen(false)
      setStatusUpdatingOrder(null)
    }
  }

  const statusOptions: OrderStatus[] = ['pending', 'confirmed', 'producing', 'shipped', 'completed', 'cancelled']

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">订单管理</h1>
          <p className="text-sm text-gray-500 mt-1">管理客户订单，跟踪订单状态和物流</p>
        </div>
        <Button onClick={() => router.push('/orders/new')}>
          <Plus className="w-4 h-4 mr-1.5" />
          创建订单
        </Button>
      </div>

      {/* 状态 Tab 栏 */}
      <div className="flex items-center gap-0 bg-white border border-gray-200 rounded-t-lg overflow-x-auto">
        {statusTabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handleTabChange(tab.key as OrderStatus | '')}
            className={cn(
              'relative px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2',
              searchParams.status === tab.key
                ? 'text-primary-600 border-primary-600 bg-primary-50/50'
                : 'text-gray-500 border-transparent hover:text-gray-700 hover:bg-gray-50'
            )}
          >
            {tab.label}
            {tab.key === '' && statusCounts.all !== undefined && (
              <span className="ml-1 text-xs text-gray-400">({statusCounts.all})</span>
            )}
          </button>
        ))}
      </div>

      {/* 搜索筛选栏 */}
      <div className="bg-white border-x border-gray-200 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[200px]">
            <Input
              label="关键词搜索"
              placeholder="订单号、客户名"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          <div className="min-w-[140px]">
            <Select
              label="状态筛选"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as OrderStatus | '')}
              options={[
                { value: '', label: '全部状态' },
                { value: 'pending', label: '待确认' },
                { value: 'confirmed', label: '已确认' },
                { value: 'producing', label: '生产中' },
                { value: 'shipped', label: '已发货' },
                { value: 'completed', label: '已完成' },
                { value: 'cancelled', label: '已取消' },
              ]}
            />
          </div>
          <div className="min-w-[160px]">
            <label className="block text-sm font-medium text-gray-700 mb-1.5">开始日期</label>
            <input
              type="date"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full h-9 px-3 rounded border border-gray-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
          </div>
          <div className="min-w-[160px]">
            <label className="block text-sm font-medium text-gray-700 mb-1.5">结束日期</label>
            <input
              type="date"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full h-9 px-3 rounded border border-gray-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <Button variant="secondary" onClick={handleReset} disabled={loading}>
              <RotateCcw className="w-4 h-4 mr-1" />
              重置
            </Button>
            <Button onClick={handleSearch} loading={loading}>
              <Search className="w-4 h-4 mr-1" />
              搜索
            </Button>
          </div>
        </div>
      </div>

      {/* 数据表格 */}
      <div className="bg-white rounded-b-lg border border-t-0 border-gray-200">
        <OrderTable
          orders={orders}
          loading={loading}
          onStatusUpdate={handleOpenStatusModal}
          onDelete={handleDelete}
        />

        {/* 分页 */}
        <Pagination
          current={current}
          pageSize={pageSize}
          total={total}
          onChange={setCurrent}
          onPageSizeChange={(size) => { setPageSize(size); setCurrent(1) }}
        />
      </div>

      {/* 删除确认弹窗 */}
      <Modal
        open={deleteModalOpen}
        onClose={() => setDeleteModalOpen(false)}
        title="确认删除"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteModalOpen(false)}>取消</Button>
            <Button variant="danger" onClick={confirmDelete}>确认删除</Button>
          </>
        }
      >
        <p className="text-gray-600">
          确定要删除订单 <span className="font-medium text-gray-900">{deletingOrder?.orderNo}</span> 吗？此操作不可恢复。
        </p>
      </Modal>

      {/* 状态更新弹窗 */}
      <Modal
        open={statusModalOpen}
        onClose={() => setStatusModalOpen(false)}
        title="更新订单状态"
        footer={
          <>
            <Button variant="secondary" onClick={() => setStatusModalOpen(false)}>取消</Button>
            <Button onClick={confirmStatusUpdate}>确认更新</Button>
          </>
        }
      >
        <div className="space-y-4">
          <p className="text-gray-600">
            订单号: <span className="font-medium text-gray-900">{statusUpdatingOrder?.orderNo}</span>
          </p>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">选择新状态</label>
            <div className="flex flex-wrap gap-2">
              {statusOptions.map((status) => (
                <button
                  key={status}
                  onClick={() => setNewStatus(status)}
                  className={cn(
                    'px-4 py-2 rounded-lg border text-sm font-medium transition-all',
                    newStatus === status
                      ? 'border-primary-500 bg-primary-50 text-primary-700'
                      : 'border-gray-200 hover:border-gray-300 text-gray-700'
                  )}
                >
                  {OrderStatusLabels[status]}
                </button>
              ))}
            </div>
          </div>
        </div>
      </Modal>
    </div>
  )
}
