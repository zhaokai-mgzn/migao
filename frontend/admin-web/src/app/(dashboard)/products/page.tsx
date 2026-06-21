'use client'

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Plus, RotateCcw, Search, Calendar } from 'lucide-react'
import { Button, Modal } from '@/components/ui'
import ProductTable, { ProductSortField, ProductSortOrder } from '@/components/products/ProductTable'
import { productApi } from '@/lib/api'
import { toast } from 'sonner'
import type { Product, ProductStatus } from '@/types'

// 状态选项（PRD：全部/出售中/已下架/审核中/草稿）
const STATUS_OPTIONS: { value: '' | ProductStatus; label: string }[] = [
  { value: '', label: '全部' },
  { value: 'on_sale', label: '出售中' },
  { value: 'off_sale', label: '已下架' },
  { value: 'under_review', label: '审核中' },
  { value: 'draft', label: '草稿' },
]

type BatchAction = 'on_shelf' | 'off_shelf' | 'delete'

interface SingleConfirm {
  product: Product
  action: 'on_shelf' | 'off_shelf' | 'delete'
}

export default function ProductsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()

  // ===== 搜索表单（受控）=====
  const [productId, setProductId] = useState(searchParams.get('productId') || '')
  const [name, setName] = useState(searchParams.get('name') || '')
  const [skuCode, setSkuCode] = useState(searchParams.get('skuCode') || '')
  const [status, setStatus] = useState<'' | ProductStatus>(
    (searchParams.get('status') as ProductStatus | null) || ''
  )
  const [createdFrom, setCreatedFrom] = useState(searchParams.get('createdFrom') || '')
  const [createdTo, setCreatedTo] = useState(searchParams.get('createdTo') || '')

  // ===== 排序与分页 =====
  const [page, setPage] = useState(Number(searchParams.get('page')) || 1)
  const [pageSize, setPageSize] = useState(Number(searchParams.get('size')) || 10)
  // #387: low_stock=true → 按库存升序展示（低库存优先）
  const lowStockOnly = searchParams.get('low_stock') === 'true'
  const [sortField, setSortField] = useState<ProductSortField>(
    (lowStockOnly ? 'stock' : (searchParams.get('sortBy') as ProductSortField)) || 'createdAt'
  )
  const [sortOrder, setSortOrder] = useState<ProductSortOrder>(
    (lowStockOnly ? 'asc' : (searchParams.get('sortOrder') as ProductSortOrder)) || 'desc'
  )

  // ===== 数据 =====
  const [products, setProducts] = useState<Product[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<string[]>([])

  // ===== 弹窗 =====
  const [batchAction, setBatchAction] = useState<BatchAction | null>(null)
  const [singleConfirm, setSingleConfirm] = useState<SingleConfirm | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // ===== URL 同步（仅在已提交搜索后触发） =====
  const syncUrl = useCallback(
    (overrides: Record<string, string | number | undefined> = {}) => {
      const merged: Record<string, string | number | undefined> = {
        productId,
        name,
        skuCode,
        status,
        createdFrom,
        createdTo,
        page,
        size: pageSize,
        sortBy: sortField,
        sortOrder,
        ...overrides,
      }
      const url = new URLSearchParams()
      Object.entries(merged).forEach(([key, val]) => {
        if (val !== undefined && val !== '' && val !== null) {
          url.set(key, String(val))
        }
      })
      // #387: 保持 low_stock 参数（从 Dashboard 卡片跳转时设置）
      if (lowStockOnly) url.set('low_stock', 'true')
      router.replace(`/products?${url.toString()}`, { scroll: false })
    },
    [productId, name, skuCode, status, createdFrom, createdTo, page, pageSize, sortField, sortOrder, lowStockOnly, router]
  )

  // ===== 加载列表（只读取 URL 中已提交的查询参数） =====
  const loadProducts = useCallback(async () => {
    setLoading(true)
    try {
      const res = await productApi.getProducts({
        page,
        size: pageSize,
        productId: searchParams.get('productId') || undefined,
        name: searchParams.get('name') || undefined,
        skuCode: searchParams.get('skuCode') || undefined,
        status: (searchParams.get('status') as ProductStatus) || undefined,
        createdFrom: searchParams.get('createdFrom') || undefined,
        createdTo: searchParams.get('createdTo') || undefined,
        sortBy: sortField,
        sortOrder,
      })
      const data = res.data.data
      setProducts(data?.items || [])
      setTotal(data?.total || 0)
    } catch (e) {
      // Error handled by API layer
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, sortField, sortOrder, searchParams])

  useEffect(() => {
    loadProducts()
  }, [loadProducts])

  // ===== 搜索/重置 =====
  const handleSearch = () => {
    setPage(1)
    setSelectedIds([])
    syncUrl({ page: 1 })
  }

  const handleReset = () => {
    setProductId('')
    setName('')
    setSkuCode('')
    setStatus('')
    setCreatedFrom('')
    setCreatedTo('')
    setPage(1)
    setSortField('createdAt')
    setSortOrder('desc')
    setSelectedIds([])
    router.replace('/products', { scroll: false })
  }

  // ===== 分页 =====
  const handlePageChange = (newPage: number) => {
    setPage(newPage)
    syncUrl({ page: newPage })
  }
  const handlePageSizeChange = (newSize: number) => {
    setPageSize(newSize)
    setPage(1)
    syncUrl({ page: 1, size: newSize })
  }

  // ===== 排序 =====
  const handleSortChange = (field: ProductSortField) => {
    let nextOrder: ProductSortOrder = 'desc'
    if (sortField === field) {
      nextOrder = sortOrder === 'desc' ? 'asc' : 'desc'
    }
    setSortField(field)
    setSortOrder(nextOrder)
    syncUrl({ sortBy: field, sortOrder: nextOrder })
  }

  // ===== 单条操作（触发确认弹窗） =====
  const handleView = (p: Product) => router.push(`/products/${p.id}`)
  const handleEdit = (p: Product) => router.push(`/products/${p.id}/edit`)
  const handlePutOnShelf = (p: Product) => setSingleConfirm({ product: p, action: 'on_shelf' })
  const handleTakeOffShelf = (p: Product) => setSingleConfirm({ product: p, action: 'off_shelf' })
  const handleDeleteSingle = (p: Product) => setSingleConfirm({ product: p, action: 'delete' })

  // ===== 单条确认提交 =====
  const submitSingleConfirm = async () => {
    if (!singleConfirm) return
    const { product, action } = singleConfirm
    setSubmitting(true)
    try {
      if (action === 'on_shelf') {
        await productApi.updateProductStatus(product.id, 'on_sale')
        toast.success('已上架')
      } else if (action === 'off_shelf') {
        await productApi.updateProductStatus(product.id, 'off_sale')
        toast.success('已下架')
      } else if (action === 'delete') {
        await productApi.deleteProduct(product.id)
        toast.success('已删除')
      }
      setSingleConfirm(null)
      loadProducts()
    } catch (e) {
      // handled by API layer
    } finally {
      setSubmitting(false)
    }
  }

  // ===== 批量操作 =====
  const submitBatch = async () => {
    if (!batchAction || selectedIds.length === 0) return
    setSubmitting(true)
    try {
      if (batchAction === 'on_shelf') {
        await productApi.batchOnShelf(selectedIds)
        toast.success(`已上架 ${selectedIds.length} 个商品`)
      } else if (batchAction === 'off_shelf') {
        await productApi.batchOffShelf(selectedIds)
        toast.success(`已下架 ${selectedIds.length} 个商品`)
      } else if (batchAction === 'delete') {
        await productApi.batchDelete(selectedIds)
        toast.success(`已删除 ${selectedIds.length} 个商品`)
      }
      setBatchAction(null)
      setSelectedIds([])
      loadProducts()
    } catch (e) {
      // handled by API layer
    } finally {
      setSubmitting(false)
    }
  }

  // ===== 批量导出 =====
  const handleExport = async () => {
    const toastId = toast.loading('正在导出，请稍候...')
    try {
      const res = await productApi.exportProducts({
        productId: productId || undefined,
        name: name || undefined,
        skuCode: skuCode || undefined,
        status: (status as ProductStatus) || undefined,
        createdFrom: createdFrom || undefined,
        createdTo: createdTo || undefined,
      })
      const blob = res.data instanceof Blob ? res.data : new Blob([res.data as BlobPart])
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `products_${new Date().toISOString().slice(0, 10)}.xlsx`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
      toast.success('导出成功', { id: toastId })
    } catch (err: any) {
      const msg = err?.response?.data?.message || err?.message || '导出失败'
      toast.error(`导出失败：${msg}`, { id: toastId })
    }
  }

  const hasSelection = selectedIds.length > 0

  // ===== 弹窗文案 =====
  const confirmDialog = useMemo(() => {
    if (batchAction) {
      const count = selectedIds.length
      if (batchAction === 'on_shelf') {
        return {
          title: '立即上架',
          desc: `是否确认上架${count > 1 ? `选中的 ${count} 个商品` : ''}？`,
          variant: 'primary' as const,
          onSubmit: submitBatch,
          onClose: () => setBatchAction(null),
        }
      }
      if (batchAction === 'off_shelf') {
        return {
          title: '立即下架',
          desc: `是否确认下架${count > 1 ? `选中的 ${count} 个商品` : ''}？商品下架后状态变更为"已下架"，可重新对商品进行管理上架。`,
          variant: 'primary' as const,
          onSubmit: submitBatch,
          onClose: () => setBatchAction(null),
        }
      }
      return {
        title: '删除商品',
        desc: '确认删除后数据将无法恢复，是否继续？',
        variant: 'primary' as const,
        onSubmit: submitBatch,
        onClose: () => setBatchAction(null),
      }
    }
    if (singleConfirm) {
      const { action } = singleConfirm
      if (action === 'on_shelf') {
        return {
          title: '立即上架',
          desc: '是否确认上架？',
          variant: 'primary' as const,
          onSubmit: submitSingleConfirm,
          onClose: () => setSingleConfirm(null),
        }
      }
      if (action === 'off_shelf') {
        return {
          title: '立即下架',
          desc: '是否确认下架？商品下架后状态变更为"已下架"，可重新对商品进行管理上架。',
          variant: 'primary' as const,
          onSubmit: submitSingleConfirm,
          onClose: () => setSingleConfirm(null),
        }
      }
      return {
        title: '删除商品',
        desc: '确认删除后数据将无法恢复，是否继续？',
        variant: 'primary' as const,
        onSubmit: submitSingleConfirm,
        onClose: () => setSingleConfirm(null),
      }
    }
    return null
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchAction, singleConfirm, selectedIds.length])

  return (
    <div className="p-6 space-y-4">
      {/* 页面标题 */}
      <div>
        <h1 className="text-xl font-bold text-gray-900">商品列表</h1>
      </div>

      {/* 搜索区 */}
      <div className="bg-white rounded-lg border border-gray-200 p-5">
        {/* 第一行：商品ID / 商品标题 / 商品货号 */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-x-8 gap-y-4">
          <FormField label="商品ID">
            <input
              type="text"
              value={productId}
              onChange={(e) => setProductId(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="请输入商品ID"
              className="w-full h-9 px-3 rounded border border-gray-300 bg-white text-sm placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
          </FormField>
          <FormField label="商品标题">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="请输入商品标题"
              className="w-full h-9 px-3 rounded border border-gray-300 bg-white text-sm placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
          </FormField>
          <FormField label="商品货号">
            <input
              type="text"
              value={skuCode}
              onChange={(e) => setSkuCode(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="请输入商品ID"
              className="w-full h-9 px-3 rounded border border-gray-300 bg-white text-sm placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
          </FormField>
        </div>

        {/* 第二行：状态 / 创建时间 / 按钮 */}
        <div className="grid grid-cols-1 md:grid-cols-[1fr_1fr_auto] gap-x-8 gap-y-4 mt-4 items-end">
          <FormField label="状态">
            <div className="relative">
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value as '' | ProductStatus)}
                className="w-full h-9 pl-3 pr-9 rounded border border-gray-300 bg-white text-sm appearance-none focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              >
                {STATUS_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <svg
                className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </div>
          </FormField>
          <FormField label="创建时间">
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Calendar className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                <input
                  type="date"
                  value={createdFrom}
                  onChange={(e) => setCreatedFrom(e.target.value)}
                  placeholder="开始日期"
                  className="w-full h-9 pl-8 pr-3 rounded border border-gray-300 bg-white text-sm text-gray-700 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                />
              </div>
              <span className="text-gray-400 text-sm">至</span>
              <div className="relative flex-1">
                <input
                  type="date"
                  value={createdTo}
                  onChange={(e) => setCreatedTo(e.target.value)}
                  placeholder="结束日期"
                  className="w-full h-9 pl-3 pr-3 rounded border border-gray-300 bg-white text-sm text-gray-700 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                />
              </div>
            </div>
          </FormField>
          <div className="flex items-center gap-3">
            <Button onClick={handleSearch}>
              <Search className="w-4 h-4 mr-1.5" />
              搜索
            </Button>
            <Button variant="secondary" onClick={handleReset}>
              <RotateCcw className="w-4 h-4 mr-1.5" />
              重置
            </Button>
          </div>
        </div>
      </div>

      {/* 工具栏 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            disabled={!hasSelection}
            onClick={() => setBatchAction('off_shelf')}
          >
            批量下架
          </Button>
          <Button
            variant="secondary"
            disabled={!hasSelection}
            onClick={() => setBatchAction('on_shelf')}
          >
            批量上架
          </Button>
          <Button variant="secondary" onClick={handleExport}>
            批量导出
          </Button>
          {hasSelection && (
            <span className="text-sm text-gray-500 ml-2">
              已选 <span className="text-primary-600 font-medium">{selectedIds.length}</span> 项
            </span>
          )}
        </div>
        <div>
          <Button onClick={() => router.push('/products/new')}>
            <Plus className="w-4 h-4 mr-1.5" />
            新增商品
          </Button>
        </div>
      </div>

      {/* 表格 */}
      <ProductTable
        products={products}
        loading={loading}
        total={total}
        page={page}
        pageSize={pageSize}
        selectedIds={selectedIds}
        sortField={sortField}
        sortOrder={sortOrder}
        onPageChange={handlePageChange}
        onPageSizeChange={handlePageSizeChange}
        onSelectChange={setSelectedIds}
        onSortChange={handleSortChange}
        onView={handleView}
        onEdit={handleEdit}
        onPutOnShelf={handlePutOnShelf}
        onTakeOffShelf={handleTakeOffShelf}
        onDelete={handleDeleteSingle}
      />

      {/* 确认弹窗（批量 / 单条共用） */}
      <Modal
        open={!!confirmDialog}
        onClose={() => confirmDialog?.onClose()}
        title={confirmDialog?.title || ''}
        width={420}
        footer={
          <>
            <Button
              variant="secondary"
              onClick={() => confirmDialog?.onClose()}
              disabled={submitting}
            >
              取消
            </Button>
            <Button onClick={() => confirmDialog?.onSubmit()} loading={submitting}>
              确定
            </Button>
          </>
        }
      >
        <p className="text-sm text-gray-600 leading-relaxed">{confirmDialog?.desc}</p>
      </Modal>
    </div>
  )
}

// 表单字段（label 在左/上）
function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <label className="text-sm text-gray-700 whitespace-nowrap min-w-[64px] text-right">
        {label}
      </label>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  )
}
