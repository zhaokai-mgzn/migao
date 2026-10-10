'use client'

import { useState } from 'react'
import { Table, Badge, StatusBadge, Pagination } from '@/components/ui'
import type { TableColumn } from '@/components/ui'
import Image from 'next/image'
import { cn, resolveImageUrl } from '@/lib/utils'
import type { Product, ProductStatus } from '@/types'
import DateTimeCell from '@/components/common/DateTimeCell'
import { ProductStatusLabels } from '@/types'
// 🔴 issue #6669 追加任务 3：涉钱读数口径收敛到 `@/lib/money` 一处真值（与财务域/计件域同源）
import { money } from '@/lib/money'

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
  onRecommend: (product: Product) => void
  onUnrecommend: (product: Product) => void
  onDelete: (product: Product) => void
}

// 状态底色框颜色映射（A2: 出售中=绿/已下架=灰/审核中=橙/草稿=蓝）
const STATUS_BADGE_COLORS: Record<ProductStatus, string> = {
  on_sale: 'bg-green-50 text-green-700 border-green-200',
  under_review: 'bg-amber-50 text-amber-700 border-amber-200',
  draft: 'bg-blue-50 text-blue-700 border-blue-200',
  off_sale: 'bg-neutral-50 text-neutral-700 border-neutral-200',
}

// 数字千分位
function formatNumber(value?: number): string {
  if (value === undefined || value === null) return '0'
  return value.toLocaleString('zh-CN')
}

/**
 * 「销售额」= **钱** ⇒ 走唯一口径 `@/lib/money`（千分位 + **固定**两位小数）。
 *
 * 修前是 `¥${value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}` —— **只给上限没给下限**
 * ⇒ 同一列并存 `¥25,049`（整数不带两位）与 `¥26,099.8`（小数跟实际值截断）两种形态
 * （issue #6669 追加任务 3 的真机读图证据）。
 */
function formatCurrency(value?: number): string {
  if (value === undefined || value === null) return money(0)
  return money(value)
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
  onRecommend,
  onUnrecommend,
  onDelete,
}: ProductTableProps) {
  const [brokenImages, setBrokenImages] = useState<Set<string>>(new Set())

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
          className="w-4 h-4 rounded border-neutral-300 text-primary-600 focus:ring-primary-500 cursor-pointer"
        />
      ),
    },
    // 🔴 #5877（用户 2026-10-01 裁定「列表中的商品ID移除，不要展示在列表」）：
    // 「商品ID」列**整列删除**（表头 + 行内 `<td>` 由 `Table` 按 `columns` 渲染 ⇒ 一并消失）。
    // ⚠️ 列数由 11 → 10：`Table` 的加载态/空态 `colSpan={columns.length}` 是**动态**的 ⇒ 自动跟上
    //（判据 = ProductTable.test.tsx 的「列数 = 10 + colSpan = 10」）。
    // ⚠️ 搜索区里的「商品ID」筛选**同日被追加裁定整条移除**（用户 2026-10-01 追加原话
    //    「搜索区的商品ID筛选也要移除」，issue #5877）—— 本行此前写的「筛选项保留」是**追加裁定之前**
    //    的口径，已作废。两处口径必须一致，对应注释见
    //    `frontend/admin-web/src/app/(dashboard)/products/page.tsx` 的 #5877 说明。
    {
      key: 'name',
      title: '商品标题',
      render: (record) => (
        <div className="flex items-start gap-3 min-w-[200px]">
          <div className="w-10 h-10 rounded-md overflow-hidden bg-neutral-100 flex-shrink-0 border border-neutral-200">
            {(() => {
              const rawUrl = record.images?.[0]
              const imgUrl = rawUrl ? resolveImageUrl(rawUrl) : ''
              if (imgUrl && !brokenImages.has(imgUrl)) {
                return (
                  <Image
                    src={imgUrl}
                    alt={record.name}
                    width={40}
                    height={40}
                    className="w-full h-full object-cover"
                    unoptimized
                    onError={() => setBrokenImages(prev => new Set(prev).add(imgUrl))}
                  />
                )
              }
              return <div className="w-full h-full flex items-center justify-center text-neutral-300 text-[10px]">无图</div>
            })()}
          </div>
          <div className="flex-1 min-w-0">
            {/* issue #6662 判据 ⑤：`line-clamp-2` 会截断长标题 —— 给 `title` 让鼠标悬停可读全 */}
            <div
              className="text-sm text-neutral-900 leading-snug break-words line-clamp-2"
              title={record.name || undefined}
            >
              {record.name}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: 'skuCode',
      title: '商品货号',
      width: '100px',
      render: (record) => {
        const code = record.skuCode || record.sku || ''
        const display = code && code.length > 10 ? `${code.slice(0, 10)}...` : code
        return (
          <span
            className="text-neutral-700 text-sm font-mono"
            title={code || undefined}
          >
            {display || '-'}
          </span>
        )
      },
    },
    {
      key: 'colorCount',
      title: '在售颜色',
      width: '80px',
      align: 'center',
      render: (record) => (
        <span className="text-neutral-700 text-sm">共{record.colorCount ?? 0}色</span>
      ),
    },
    {
      key: 'stock',
      title: '库存',
      width: '80px',
      align: 'left',
      sortable: true,
      render: (record) => {
        const stock = record.stock ?? 0
        // #1200: 库存 ≤ 阈值时飘红，库存 = 0 加粗；优先使用商品级预警阈值，默认 5
        const threshold = record.stockWarningThreshold ?? 5
        const isLow = stock <= threshold
        const isZero = stock === 0
        return (
          <span className={cn(
            'text-sm font-medium',
            isLow ? 'text-red-600' : 'text-neutral-700',
            isZero && 'font-bold'
          )}>
            {formatNumber(stock)}
          </span>
        )
      },
    },
    {
      key: 'salesCount',
      title: '销量',
      width: '80px',
      align: 'left',
      sortable: true,
      render: (record) => (
        <span className="text-neutral-700 text-sm">{formatNumber(record.salesCount)}</span>
      ),
    },
    {
      key: 'salesAmount',
      title: '销售额',
      width: '100px',
      align: 'left',
      sortable: true,
      render: (record) => (
        <span className="text-neutral-700 text-sm">{formatCurrency(record.salesAmount)}</span>
      ),
    },
    {
      key: 'createdAt',
      title: '创建时间',
      width: '150px',
      align: 'left',
      sortable: true,
      render: (record) => <DateTimeCell value={record.createdAt} />,
    },
    {
      key: 'status',
      title: '状态',
      width: '80px',
      align: 'left',
      render: (record) => (
        <StatusBadge
          label={ProductStatusLabels[record.status] || record.status}
          color={STATUS_BADGE_COLORS[record.status]}
        />
      ),
    },
    {
      key: 'actions',
      title: '操作',
      width: '160px',
      align: 'left',
      render: (record) => {
        const stop = (e: React.MouseEvent) => e.stopPropagation()
        const linkBase = 'text-primary-600 hover:text-primary-700 hover:underline transition-colors'
        const dangerLink = 'text-red-500 hover:text-red-600 hover:underline transition-colors'
        return (
          <div className="flex items-center gap-3 text-sm whitespace-nowrap">
            {/* 出售中：查看 编辑 推荐/取消推荐 下架 删除 */}
            {record.status === 'on_sale' && (
              <>
                <button onClick={(e) => { stop(e); onView(record) }} className={linkBase}>查看</button>
                <button onClick={(e) => { stop(e); onEdit(record) }} className={linkBase}>编辑</button>
                {record.recommended ? (
                  <button onClick={(e) => { stop(e); onUnrecommend(record) }} className="text-amber-600 hover:text-amber-700 hover:underline transition-colors">取消推荐</button>
                ) : (
                  <button onClick={(e) => { stop(e); onRecommend(record) }} className={linkBase}>推荐</button>
                )}
                <button onClick={(e) => { stop(e); onTakeOffShelf(record) }} className={linkBase}>下架</button>
                <button onClick={(e) => { stop(e); onDelete(record) }} className={dangerLink}>删除</button>
              </>
            )}
            {/* 已下架：查看 编辑 上架 删除 */}
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
    <div className="bg-white rounded-lg border border-neutral-200">
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
          // 🔴 issue #6687：最小宽度由 1200 收窄到 1120 —— 1200 是**硬撑出来的**宽度：
          // 在 1440×980 上容器只有 ~1100px，多出来的 100px 全部落在横向滚动区里，
          // 而「操作」列正好在表尾 ⇒ **滚到右端时那一列被右下角黄金策浮球（56×56，fixed z-50）压住**
          // （命中测试实测：点「推荐」被浮球吃掉）。layout 的 `<main>` 同时预留 `pr-20` 安全区；
          // 两者合起来把「操作」列的可点区域推到浮球矩形之外（几何判据见
          // frontend/admin-web/tests/unit/floating-assistant-safe-zone.test.ts）。
          minWidth={1120}
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
              className="w-4 h-4 rounded border-neutral-300 text-primary-600 focus:ring-primary-500 cursor-pointer pointer-events-auto"
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
