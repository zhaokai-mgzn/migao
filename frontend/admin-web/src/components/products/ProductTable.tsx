'use client'

import { Table, Badge, Pagination } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import Image from 'next/image'
import { cn } from '@/lib/utils'
import type { Product, ProductStatus } from '@/types'
import { ProductStatusLabels } from '@/types'

export type ProductSortField = 'stock' | 'salesCount' | 'salesAmount' | 'createdAt'
export type ProductSortOrder = 'asc' | 'desc'

interface ProductTableProps {
  products: Product[]
  loading: boolean
  total: number
  page: number
  pageSize: number
  selectedIds: string[]
  sortField?: ProductSortField
  sortOrder?: ProductSortOrder
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
  onSelectChange: (ids: string[]) => void
  onSortChange: (field: ProductSortField) => void
  onView: (product: Product) => void
  onEdit: (product: Product) => void
  onPutOnShelf: (product: Product) => void
  onTakeOffShelf: (product: Product) => void
  onDelete: (product: Product) => void
}

// 状态徽章颜色映射（PRD：出售中绿/仓库中灰/审核中橙/草稿蓝）
const STATUS_BADGE_VARIANT: Record<ProductStatus, 'success' | 'default' | 'warning' | 'info'> = {
  on_sale: 'success',
  in_warehouse: 'default',
  under_review: 'warning',
  draft: 'info',
  off_sale: 'default',
}

// 格式化时间为 yyyy-MM-dd HH:mm
function formatDateTime(input?: string): string {
  if (!input) return '-'
  const date = new Date(input)
  if (Number.isNaN(date.getTime())) return input
  const pad = (n: number) => n.toString().padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

// 数字千分位
function formatNumber(value?: number): string {
  if (value === undefined || value === null) return '0'
  return value.toLocaleString('zh-CN')
}

function formatCurrency(value?: number): string {
  if (value === undefined || value === null) return '¥0'
  return `¥${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
}

export default function ProductTable({
  products,
  loading,
  total,
  page,
  pageSize,
  selectedIds,
  sortField,
  sortOrder,
  onPageChange,
  onPageSizeChange,
  onSelectChange,
  onSortChange,
  onView,
  onEdit,
  onPutOnShelf,
  onTakeOffShelf,
  onDelete,
}: ProductTableProps) {
  const allChecked = products.length > 0 && products.every((p) => selectedIds.includes(p.id))
  const partialChecked = !allChecked && products.some((p) => selectedIds.includes(p.id))

  const handleSelectAll = () => {
    if (allChecked) {
      // 取消所有当前页选择
      const currentIds = new Set(products.map((p) => p.id))
      onSelectChange(selectedIds.filter((id) => !currentIds.has(id)))
    } else {
      // 选中当前页所有
      const merged = Array.from(new Set([...selectedIds, ...products.map((p) => p.id)]))
      onSelectChange(merged)
    }
  }

  const handleSelectOne = (id: string) => {
    if (selectedIds.includes(id)) {
      onSelectChange(selectedIds.filter((x) => x !== id))
    } else {
      onSelectChange([...selectedIds, id])
    }
  }

  const columns: TableColumn<Product>[] = [
    {
      key: '__select',
      title: '',
      width: '48px',
      align: 'center',
      render: (record) => (
        <input
          type="checkbox"
          checked={selectedIds.includes(record.id)}
          onClick={(e) => e.stopPropagation()}
          onChange={() => handleSelectOne(record.id)}
          className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500 cursor-pointer"
        />
      ),
    },
    {
      key: 'id',
      title: '商品ID',
      width: '110px',
      render: (record) => (
        <span className="text-gray-700 font-mono text-sm">{record.id}</span>
      ),
    },
    {
      key: 'name',
      title: '商品标题',
      render: (record) => (
        <div className="flex items-start gap-3 min-w-[220px]">
          <div className="w-10 h-10 rounded-md overflow-hidden bg-gray-100 flex-shrink-0 border border-gray-200">
            {record.images && record.images.length > 0 ? (
              <Image
                src={record.images[0]}
                alt={record.name}
                width={40}
                height={40}
                className="w-full h-full object-cover"
                unoptimized
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-gray-300 text-[10px]">无图</div>
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm text-gray-900 leading-snug break-words line-clamp-2">{record.name}</div>
          </div>
        </div>
      ),
    },
    {
      key: 'skuCode',
      title: '商品货号',
      width: '140px',
      render: (record) => (
        <span className="text-gray-700 text-sm font-mono">
          {record.skuCode || record.sku || '-'}
        </span>
      ),
    },
    {
      key: 'colorCount',
      title: '在售颜色',
      width: '100px',
      align: 'center',
      render: (record) => (
        <span className="text-gray-700 text-sm">共{record.colorCount ?? 0}色</span>
      ),
    },
    {
      key: 'stock',
      title: '库存',
      width: '110px',
      align: 'left',
      sortable: true,
      render: (record) => {
        const stock = record.stock ?? 0
        const isLow = stock < 100
        return (
          <span className={cn('text-sm font-medium', isLow ? 'text-red-600' : 'text-gray-700')}>
            {formatNumber(stock)}
          </span>
        )
      },
    },
    {
      key: 'salesCount',
      title: '销量',
      width: '110px',
      align: 'left',
      sortable: true,
      render: (record) => (
        <span className="text-gray-700 text-sm">{formatNumber(record.salesCount)}</span>
      ),
    },
    {
      key: 'salesAmount',
      title: '销售额',
      width: '120px',
      align: 'left',
      sortable: true,
      render: (record) => (
        <span className="text-gray-700 text-sm">{formatCurrency(record.salesAmount)}</span>
      ),
    },
    {
      key: 'createdAt',
      title: '创建时间',
      width: '160px',
      align: 'left',
      sortable: true,
      render: (record) => (
        <span className="text-gray-600 text-sm">{formatDateTime(record.createdAt)}</span>
      ),
    },
    {
      key: 'status',
      title: '状态',
      width: '100px',
      align: 'left',
      render: (record) => (
        <Badge variant={STATUS_BADGE_VARIANT[record.status]}>
          {ProductStatusLabels[record.status] || record.status}
        </Badge>
      ),
    },
    {
      key: 'actions',
      title: '操作',
      width: '170px',
      align: 'left',
      render: (record) => {
        const stop = (e: React.MouseEvent) => e.stopPropagation()
        const linkBase = 'text-primary-600 hover:text-primary-700 hover:underline transition-colors'
        const dangerLink = 'text-red-500 hover:text-red-600 hover:underline transition-colors'
        return (
          <div className="flex items-center gap-3 text-sm">
            {/* 出售中：查看 编辑 下架 删除 */}
            {record.status === 'on_sale' && (
              <>
                <button onClick={(e) => { stop(e); onView(record) }} className={linkBase}>查看</button>
                <button onClick={(e) => { stop(e); onEdit(record) }} className={linkBase}>编辑</button>
                <button onClick={(e) => { stop(e); onTakeOffShelf(record) }} className={linkBase}>下架</button>
                <button onClick={(e) => { stop(e); onDelete(record) }} className={dangerLink}>删除</button>
              </>
            )}
            {/* 仓库中：查看 编辑 上架 删除 */}
            {record.status === 'in_warehouse' && (
              <>
                <button onClick={(e) => { stop(e); onView(record) }} className={linkBase}>查看</button>
                <button onClick={(e) => { stop(e); onEdit(record) }} className={linkBase}>编辑</button>
                <button onClick={(e) => { stop(e); onPutOnShelf(record) }} className={linkBase}>上架</button>
                <button onClick={(e) => { stop(e); onDelete(record) }} className={dangerLink}>删除</button>
              </>
            )}
            {/* 已下架（兼容旧状态）：与仓库中一致 */}
            {record.status === 'off_sale' && (
              <>
                <button onClick={(e) => { stop(e); onView(record) }} className={linkBase}>查看</button>
                <button onClick={(e) => { stop(e); onEdit(record) }} className={linkBase}>编辑</button>
                <button onClick={(e) => { stop(e); onPutOnShelf(record) }} className={linkBase}>上架</button>
                <button onClick={(e) => { stop(e); onDelete(record) }} className={dangerLink}>删除</button>
              </>
            )}
            {/* 审核中：仅查看 */}
            {record.status === 'under_review' && (
              <button onClick={(e) => { stop(e); onView(record) }} className={linkBase}>查看</button>
            )}
            {/* 草稿：编辑 删除 */}
            {record.status === 'draft' && (
              <>
                <button onClick={(e) => { stop(e); onEdit(record) }} className={linkBase}>编辑</button>
                <button onClick={(e) => { stop(e); onDelete(record) }} className={dangerLink}>删除</button>
              </>
            )}
          </div>
        )
      },
    },
  ]

  return (
    <div className="bg-white rounded-lg border border-gray-200">
      {/* 自定义表头第一列：全选复选框（覆盖 Table 内部默认表头中的空标题） */}
      <div className="relative">
        <Table<Product>
          columns={columns}
          dataSource={products}
          loading={loading}
          rowKey="id"
          sortField={sortField}
          sortOrder={sortOrder}
          onSort={(field) => onSortChange(field as ProductSortField)}
        />
        {/* 浮动定位的全选 checkbox（落在第一列表头里） */}
        {products.length > 0 && (
          <div className="absolute top-0 left-0 h-[45px] w-12 flex items-center justify-center pointer-events-none">
            <input
              type="checkbox"
              checked={allChecked}
              ref={(el) => {
                if (el) el.indeterminate = partialChecked
              }}
              onChange={handleSelectAll}
              className="w-4 h-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500 cursor-pointer pointer-events-auto"
            />
          </div>
        )}
      </div>
      {total > 0 && (
        <Pagination
          current={page}
          pageSize={pageSize}
          total={total}
          onChange={onPageChange}
          onPageSizeChange={onPageSizeChange}
          showTotal
          showSizeChanger
        />
      )}
    </div>
  )
}
