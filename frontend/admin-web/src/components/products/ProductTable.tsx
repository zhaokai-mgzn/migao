'use client'

import { useRouter } from 'next/navigation'
import { Table, Badge, Pagination } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import { Edit, Trash2, ArrowUpCircle, ArrowDownCircle, Eye } from 'lucide-react'
import Image from 'next/image'
import type { Product, ProductStatus } from '@/types'
import { ProductStatusLabels } from '@/types'

interface ProductTableProps {
  products: Product[]
  loading: boolean
  total: number
  page: number
  pageSize: number
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
  onStatusChange: (id: string, status: ProductStatus) => void
  onDelete: (product: Product) => void
}

export default function ProductTable({
  products,
  loading,
  total,
  page,
  pageSize,
  onPageChange,
  onPageSizeChange,
  onStatusChange,
  onDelete,
}: ProductTableProps) {
  const router = useRouter()

  const columns: TableColumn<Product>[] = [
    {
      key: 'image',
      title: '商品图片',
      width: '80px',
      render: (record) => (
        <div className="w-12 h-12 rounded-md overflow-hidden bg-gray-100 flex-shrink-0">
          {record.images && record.images.length > 0 ? (
            <Image
              src={record.images[0]}
              alt={record.name}
              width={48}
              height={48}
              className="w-full h-full object-cover"
              unoptimized
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-gray-400 text-xs">
              无图
            </div>
          )}
        </div>
      ),
    },
    {
      key: 'name',
      title: '商品名称',
      render: (record) => (
        <div>
          <div className="font-medium text-gray-900 truncate max-w-[200px]">{record.name}</div>
          {record.brand && <div className="text-xs text-gray-500 mt-0.5">{record.brand}</div>}
        </div>
      ),
    },
    {
      key: 'sku',
      title: 'SKU',
      render: (record) => (
        <span className="text-gray-600 text-sm font-mono">{record.sku || '-'}</span>
      ),
    },
    {
      key: 'category',
      title: '分类',
      render: (record) => (
        <span className="text-gray-600">{record.categoryName || '-'}</span>
      ),
    },
    {
      key: 'price',
      title: '价格',
      align: 'right',
      render: (record) => (
        <span className="font-medium text-gray-900">
          ¥{record.price.toFixed(2)}
          {record.unit && <span className="text-xs text-gray-500 ml-0.5">/{record.unit}</span>}
        </span>
      ),
    },
    {
      key: 'stock',
      title: '库存',
      align: 'center',
      render: (record) => (
        <span className={record.stock !== undefined && record.stock < 10 ? 'text-red-600 font-medium' : 'text-gray-600'}>
          {record.stock ?? '-'}
        </span>
      ),
    },
    {
      key: 'status',
      title: '状态',
      align: 'center',
      render: (record) => {
        const variantMap: Record<ProductStatus, 'success' | 'default' | 'warning'> = {
          on_sale: 'success',
          off_sale: 'default',
          draft: 'warning',
          in_warehouse: 'default',
          under_review: 'warning',
        }
        return (
          <Badge variant={variantMap[record.status]}>
            {ProductStatusLabels[record.status] || record.status}
          </Badge>
        )
      },
    },
    {
      key: 'actions',
      title: '操作',
      width: '180px',
      align: 'center',
      render: (record) => (
        <div className="flex items-center justify-center gap-1">
          <button
            onClick={(e) => { e.stopPropagation(); router.push(`/products/${record.id}`) }}
            className="p-1.5 text-gray-500 hover:text-primary-600 hover:bg-primary-50 rounded transition-colors"
            title="查看"
          >
            <Eye className="w-4 h-4" />
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); router.push(`/products/${record.id}/edit`) }}
            className="p-1.5 text-gray-500 hover:text-primary-600 hover:bg-primary-50 rounded transition-colors"
            title="编辑"
          >
            <Edit className="w-4 h-4" />
          </button>
          {record.status === 'on_sale' ? (
            <button
              onClick={(e) => { e.stopPropagation(); onStatusChange(record.id, 'off_sale') }}
              className="p-1.5 text-gray-500 hover:text-amber-600 hover:bg-amber-50 rounded transition-colors"
              title="下架"
            >
              <ArrowDownCircle className="w-4 h-4" />
            </button>
          ) : (
            <button
              onClick={(e) => { e.stopPropagation(); onStatusChange(record.id, 'on_sale') }}
              className="p-1.5 text-gray-500 hover:text-green-600 hover:bg-green-50 rounded transition-colors"
              title="上架"
            >
              <ArrowUpCircle className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(record) }}
            className="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded transition-colors"
            title="删除"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      ),
    },
  ]

  return (
    <div>
      <Table<Product>
        columns={columns}
        dataSource={products}
        loading={loading}
        rowKey="id"
        onRowClick={(record) => router.push(`/products/${record.id}`)}
      />
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
