'use client'

import { Eye, ClipboardList, Trash2 } from 'lucide-react'
import { Table } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import type { Order } from '@/types'
import OrderStatusBadge from './OrderStatusBadge'
import dayjs from 'dayjs'

interface OrderTableProps {
  orders: Order[]
  loading?: boolean
  onStatusUpdate?: (order: Order) => void
  onDelete?: (order: Order) => void
}

function formatAmount(amount: number): string {
  return `¥${(amount ?? 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function OrderTable({ orders, loading, onStatusUpdate, onDelete }: OrderTableProps) {
  const columns: TableColumn<Order>[] = [
    {
      key: 'orderNo',
      title: '订单号',
      width: '160px',
      render: (record) => (
        <span className="font-mono text-sm text-gray-600">{record.orderNo}</span>
      ),
    },
    {
      key: 'customerName',
      title: '客户名',
      width: '120px',
      render: (record) => (
        <div>
          <div className="font-medium text-gray-900">{record.customerName}</div>
          <div className="text-xs text-gray-400">{record.customerPhone}</div>
        </div>
      ),
    },
    {
      key: 'items',
      title: '商品摘要',
      render: (record) => {
        const itemsSummary = record.items?.map((i) => i.productName).join('、') || '-'
        const count = record.items?.length || 0
        return (
          <div className="max-w-[200px]">
            <div className="text-sm text-gray-700 truncate" title={itemsSummary}>
              {itemsSummary}
            </div>
            {count > 0 && (
              <span className="text-xs text-gray-400">共 {count} 项</span>
            )}
          </div>
        )
      },
    },
    {
      key: 'totalAmount',
      title: '总金额',
      width: '120px',
      align: 'right',
      render: (record) => (
        <span className="font-semibold text-gray-900">{formatAmount(record.totalAmount)}</span>
      ),
    },
    {
      key: 'status',
      title: '状态',
      width: '110px',
      render: (record) => (
        <OrderStatusBadge
          status={record.status}
          onClick={onStatusUpdate ? () => onStatusUpdate(record) : undefined}
        />
      ),
    },
    {
      key: 'createdAt',
      title: '下单时间',
      width: '150px',
      render: (record) => (
        <span className="text-sm text-gray-500">
          {record.createdAt ? dayjs(record.createdAt).format('YYYY-MM-DD HH:mm') : '-'}
        </span>
      ),
    },
    {
      key: 'action',
      title: '操作',
      width: '130px',
      align: 'center',
      render: (record) => (
        <div className="flex items-center justify-center gap-1">
          <button
            onClick={(e) => { e.stopPropagation(); window.location.href = `/orders/${record.id}` }}
            className="p-1.5 text-blue-600 hover:bg-blue-50 rounded transition-colors"
            title="查看详情"
          >
            <Eye className="w-4 h-4" />
          </button>
          {onStatusUpdate && (
            <button
              onClick={(e) => { e.stopPropagation(); onStatusUpdate(record) }}
              className="p-1.5 text-purple-600 hover:bg-purple-50 rounded transition-colors"
              title="更新状态"
            >
              <ClipboardList className="w-4 h-4" />
            </button>
          )}
          {onDelete && (
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(record) }}
              className="p-1.5 text-red-600 hover:bg-red-50 rounded transition-colors"
              title="删除"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
        </div>
      ),
    },
  ]

  return (
    <Table
      columns={columns}
      dataSource={orders}
      loading={loading}
      rowKey="id"
      onRowClick={(record) => { window.location.href = `/orders/${record.id}` }}
    />
  )
}
