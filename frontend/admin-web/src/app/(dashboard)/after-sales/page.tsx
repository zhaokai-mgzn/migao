'use client'

import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, Search, RotateCcw, FileText, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import { afterSalesApi, orderApi } from '@/lib/api'
import { Pagination, Modal, Button, Input, Select, Badge } from '@/components/ui'
import type {
  AfterSalesTicket,
  AfterSalesStatus,
  AfterSalesType,
  AfterSalesFormData,
  AfterSalesPriority,
  Order,
} from '@/types'
import {
  AfterSalesStatusLabels,
  AfterSalesStatusColors,
  AfterSalesTypeLabels,
  AfterSalesPriorityLabels,
} from '@/types'
import dayjs from 'dayjs'
import { cn } from '@/lib/utils'

// 状态 Tab 配置
const statusTabs: { key: AfterSalesStatus | ''; label: string }[] = [
  { key: '', label: '全部' },
  { key: 'pending', label: '待处理' },
  { key: 'processing', label: '处理中' },
  { key: 'resolved', label: '已完成' },
  { key: 'rejected', label: '已拒绝' },
  { key: 'closed', label: '已关闭' },
]

// 售后类型选项
const ticketTypeOptions: { value: AfterSalesType; label: string }[] = [
  { value: 'return', label: '退货' },
  { value: 'exchange', label: '换货' },
  { value: 'repair', label: '维修' },
  { value: 'refund', label: '退款' },
  { value: 'complaint', label: '投诉' },
  { value: 'other', label: '其他' },
]

export default function AfterSalesPage() {
  const router = useRouter()
  const [tickets, setTickets] = useState<AfterSalesTicket[]>([])
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [current, setCurrent] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  // 筛选
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState<AfterSalesStatus | ''>('')

  // 实际搜索参数
  const [searchParams, setSearchParams] = useState<{
    keyword: string
    status: AfterSalesStatus | ''
  }>({ keyword: '', status: '' })

  // 新建工单弹窗
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [orderSearchKeyword, setOrderSearchKeyword] = useState('')
  const [orderSearchResults, setOrderSearchResults] = useState<Order[]>([])
  const [orderSearching, setOrderSearching] = useState(false)
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null)
  const [newTicketType, setNewTicketType] = useState<AfterSalesType>('return')
  const [newDescription, setNewDescription] = useState('')
  const [newPriority, setNewPriority] = useState<AfterSalesPriority>('normal')

  // 加载工单列表
  const loadTickets = useCallback(async () => {
    setLoading(true)
    try {
      const params: Record<string, unknown> = {
        page: current,
        size: pageSize,
      }
      if (searchParams.keyword) params.keyword = searchParams.keyword
      if (searchParams.status) params.status = searchParams.status

      const res = await afterSalesApi.getTickets(params as any)
      const pageData = res.data?.data
      setTickets(pageData?.items || [])
      setTotal(pageData?.total || 0)
    } catch (error) {
      console.error('加载售后工单失败:', error)
      toast.error('加载售后工单失败')
    } finally {
      setLoading(false)
    }
  }, [current, pageSize, searchParams])

  useEffect(() => {
    loadTickets()
  }, [loadTickets])

  // 搜索
  const handleSearch = () => {
    setCurrent(1)
    setSearchParams({ keyword, status: statusFilter })
  }

  // 重置
  const handleReset = () => {
    setKeyword('')
    setStatusFilter('')
    setCurrent(1)
    setSearchParams({ keyword: '', status: '' })
  }

  // Tab 切换
  const handleTabChange = (status: AfterSalesStatus | '') => {
    setStatusFilter(status)
    setCurrent(1)
    setSearchParams((prev) => ({ ...prev, status }))
  }

  // 搜索订单
  const handleOrderSearch = async () => {
    if (!orderSearchKeyword.trim()) return
    setOrderSearching(true)
    try {
      const res = await orderApi.getOrders({ keyword: orderSearchKeyword, page: 1, size: 10 })
      setOrderSearchResults(res.data?.data?.items || [])
    } catch {
      toast.error('搜索订单失败')
    } finally {
      setOrderSearching(false)
    }
  }

  // 创建工单
  const handleCreateTicket = async () => {
    if (!selectedOrder) {
      toast.error('请选择关联订单')
      return
    }
    if (!newDescription.trim()) {
      toast.error('请输入售后原因描述')
      return
    }
    setCreating(true)
    try {
      const data: AfterSalesFormData = {
        orderId: selectedOrder.id,
        ticketType: newTicketType,
        description: newDescription,
        priority: newPriority,
      }
      const res = await afterSalesApi.createTicket(data)
      toast.success('工单创建成功')
      setCreateModalOpen(false)
      resetCreateForm()
      // 跳转到工单详情
      const ticketId = res.data?.data?.id
      if (ticketId) {
        router.push(`/after-sales/${ticketId}`)
      } else {
        loadTickets()
      }
    } catch {
      toast.error('创建工单失败')
    } finally {
      setCreating(false)
    }
  }

  const resetCreateForm = () => {
    setOrderSearchKeyword('')
    setOrderSearchResults([])
    setSelectedOrder(null)
    setNewTicketType('return')
    setNewDescription('')
    setNewPriority('normal')
  }

  // 状态 Badge 变体映射
  const getStatusVariant = (status: AfterSalesStatus) => {
    const map: Record<string, 'success' | 'warning' | 'error' | 'default' | 'info'> = {
      pending: 'warning',
      processing: 'info',
      resolved: 'success',
      rejected: 'error',
      closed: 'default',
    }
    return map[status] || 'default'
  }

  // 售后类型 Badge
  const getTypeVariant = (type: AfterSalesType) => {
    const map: Record<string, 'success' | 'warning' | 'error' | 'default' | 'info'> = {
      return: 'warning',
      exchange: 'info',
      repair: 'default',
      refund: 'error',
      complaint: 'error',
      other: 'default',
    }
    return map[type] || 'default'
  }

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">售后管理</h1>
          <p className="text-sm text-gray-500 mt-1">管理客户售后工单，处理退货、换货、维修等售后请求</p>
        </div>
        <Button onClick={() => setCreateModalOpen(true)}>
          <Plus className="w-4 h-4 mr-1.5" />
          新建工单
        </Button>
      </div>

      {/* 状态 Tab 栏 */}
      <div className="flex items-center gap-0 bg-white border border-gray-200 rounded-t-lg overflow-x-auto">
        {statusTabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => handleTabChange(tab.key as AfterSalesStatus | '')}
            className={cn(
              'relative px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2',
              searchParams.status === tab.key
                ? 'text-primary-600 border-primary-600 bg-primary-50/50'
                : 'text-gray-500 border-transparent hover:text-gray-700 hover:bg-gray-50'
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 搜索筛选栏 */}
      <div className="bg-white border-x border-gray-200 p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[240px]">
            <Input
              label="关键词搜索"
              placeholder="工单号、订单号、客户名"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
          </div>
          <div className="min-w-[140px]">
            <Select
              label="状态筛选"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as AfterSalesStatus | '')}
              options={[
                { value: '', label: '全部状态' },
                { value: 'pending', label: '待处理' },
                { value: 'processing', label: '处理中' },
                { value: 'resolved', label: '已完成' },
                { value: 'rejected', label: '已拒绝' },
                { value: 'closed', label: '已关闭' },
              ]}
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
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50/50">
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">工单号</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">关联订单</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">客户</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">售后类型</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">状态</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">优先级</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">创建时间</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">更新时间</th>
                <th className="text-right px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wider">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr>
                  <td colSpan={9} className="px-4 py-12 text-center text-gray-400">
                    <div className="flex items-center justify-center gap-2">
                      <div className="w-4 h-4 border-2 border-gray-300 border-t-primary-600 rounded-full animate-spin" />
                      加载中...
                    </div>
                  </td>
                </tr>
              ) : tickets.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-12 text-center text-gray-400">
                    <FileText className="w-8 h-8 mx-auto mb-2 text-gray-300" />
                    暂无售后工单
                  </td>
                </tr>
              ) : (
                tickets.map((ticket) => (
                  <tr
                    key={ticket.id}
                    className="hover:bg-gray-50/50 cursor-pointer transition-colors"
                    onClick={() => router.push(`/after-sales/${ticket.id}`)}
                  >
                    <td className="px-4 py-3">
                      <span className="font-mono text-sm text-gray-900">{ticket.ticketNo}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="font-mono text-sm text-gray-600">{ticket.orderNo || '-'}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="text-sm text-gray-900">{ticket.customerName || '-'}</span>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={getTypeVariant(ticket.ticketType)}>
                        {AfterSalesTypeLabels[ticket.ticketType] || ticket.ticketType}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={getStatusVariant(ticket.status)}>
                        {AfterSalesStatusLabels[ticket.status] || ticket.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      {ticket.priority ? (
                        <Badge variant={ticket.priority === 'critical' ? 'error' : ticket.priority === 'urgent' ? 'warning' : 'default'}>
                          {AfterSalesPriorityLabels[ticket.priority]}
                        </Badge>
                      ) : (
                        <span className="text-sm text-gray-400">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {ticket.createdAt ? dayjs(ticket.createdAt).format('YYYY-MM-DD HH:mm') : '-'}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {ticket.updatedAt ? dayjs(ticket.updatedAt).format('YYYY-MM-DD HH:mm') : '-'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          router.push(`/after-sales/${ticket.id}`)
                        }}
                        className="text-primary-600 hover:text-primary-700 text-sm font-medium"
                      >
                        查看
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        <Pagination
          current={current}
          pageSize={pageSize}
          total={total}
          onChange={setCurrent}
          onPageSizeChange={(size) => { setPageSize(size); setCurrent(1) }}
        />
      </div>

      {/* 新建工单弹窗 */}
      <Modal
        open={createModalOpen}
        onClose={() => { setCreateModalOpen(false); resetCreateForm() }}
        title="新建售后工单"
        footer={
          <>
            <Button variant="secondary" onClick={() => { setCreateModalOpen(false); resetCreateForm() }}>
              取消
            </Button>
            <Button onClick={handleCreateTicket} loading={creating}>
              提交工单
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {/* 关联订单搜索 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">关联订单 *</label>
            {selectedOrder ? (
              <div className="flex items-center justify-between p-3 bg-primary-50 border border-primary-200 rounded-lg">
                <div>
                  <p className="text-sm font-medium text-gray-900">订单号: {selectedOrder.orderNo}</p>
                  <p className="text-xs text-gray-500">客户: {selectedOrder.customerName} | 金额: ¥{selectedOrder.totalAmount?.toLocaleString()}</p>
                </div>
                <button
                  onClick={() => setSelectedOrder(null)}
                  className="text-xs text-gray-500 hover:text-gray-700"
                >
                  更换
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="输入订单号搜索..."
                    value={orderSearchKeyword}
                    onChange={(e) => setOrderSearchKeyword(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleOrderSearch()}
                    className="flex-1 h-9 px-3 rounded border border-gray-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  />
                  <Button onClick={handleOrderSearch} loading={orderSearching} className="h-9">
                    <Search className="w-4 h-4" />
                  </Button>
                </div>
                {orderSearchResults.length > 0 && (
                  <div className="border border-gray-200 rounded-lg max-h-40 overflow-y-auto divide-y divide-gray-100">
                    {orderSearchResults.map((order) => (
                      <button
                        key={order.id}
                        onClick={() => {
                          setSelectedOrder(order)
                          setOrderSearchResults([])
                        }}
                        className="w-full text-left px-3 py-2 hover:bg-gray-50 transition-colors"
                      >
                        <p className="text-sm font-mono text-gray-900">{order.orderNo}</p>
                        <p className="text-xs text-gray-500">{order.customerName} | ¥{order.totalAmount?.toLocaleString()}</p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* 售后类型 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">售后类型 *</label>
            <div className="flex flex-wrap gap-2">
              {ticketTypeOptions.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setNewTicketType(opt.value)}
                  className={cn(
                    'px-3 py-1.5 rounded-lg border text-sm font-medium transition-all',
                    newTicketType === opt.value
                      ? 'border-primary-500 bg-primary-50 text-primary-700'
                      : 'border-gray-200 hover:border-gray-300 text-gray-700'
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          {/* 优先级 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">优先级</label>
            <div className="flex gap-2">
              {(['normal', 'urgent', 'critical'] as AfterSalesPriority[]).map((p) => (
                <button
                  key={p}
                  onClick={() => setNewPriority(p)}
                  className={cn(
                    'px-3 py-1.5 rounded-lg border text-sm font-medium transition-all',
                    newPriority === p
                      ? p === 'critical' ? 'border-red-500 bg-red-50 text-red-700'
                        : p === 'urgent' ? 'border-amber-500 bg-amber-50 text-amber-700'
                        : 'border-primary-500 bg-primary-50 text-primary-700'
                      : 'border-gray-200 hover:border-gray-300 text-gray-700'
                  )}
                >
                  {AfterSalesPriorityLabels[p]}
                </button>
              ))}
            </div>
          </div>

          {/* 售后原因描述 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">售后原因描述 *</label>
            <textarea
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
              placeholder="请详细描述售后原因..."
              rows={4}
              className="w-full px-3 py-2 rounded border border-gray-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}
