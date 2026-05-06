'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { Plus } from 'lucide-react'
import { Button, Select, Input, Modal, EmptyState } from '@/components/ui'
import ProductTable from '@/components/products/ProductTable'
import { productApi, categoryApi } from '@/lib/api'
import { toast } from 'sonner'
import type { Product, ProductStatus, Category } from '@/types'

// Flatten categories for select
function flattenCategories(categories: Category[]): { value: string; label: string }[] {
  const result: { value: string; label: string }[] = []
  const flatten = (cats: Category[], prefix = '') => {
    for (const cat of cats) {
      result.push({ value: cat.id, label: prefix + cat.name })
      if (cat.children && cat.children.length > 0) {
        flatten(cat.children, prefix + cat.name + ' / ')
      }
    }
  }
  flatten(categories)
  return result
}

export default function ProductsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()

  // State from URL params
  const [page, setPage] = useState(Number(searchParams.get('page')) || 1)
  const [pageSize, setPageSize] = useState(Number(searchParams.get('size')) || 10)
  const [keyword, setKeyword] = useState(searchParams.get('keyword') || '')
  const [categoryId, setCategoryId] = useState(searchParams.get('categoryId') || '')
  const [status, setStatus] = useState(searchParams.get('status') || '')

  const [products, setProducts] = useState<Product[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [categories, setCategories] = useState<Category[]>([])

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<Product | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Sync URL params
  const updateUrl = useCallback((params: Record<string, string | number>) => {
    const url = new URLSearchParams()
    const merged = { page, size: pageSize, keyword, categoryId, status, ...params }
    Object.entries(merged).forEach(([key, val]) => {
      if (val && val !== '' && val !== 0) url.set(key, String(val))
    })
    router.replace(`/products?${url.toString()}`, { scroll: false })
  }, [page, pageSize, keyword, categoryId, status, router])

  // Load categories
  useEffect(() => {
    categoryApi.getCategories().then((res) => {
      setCategories(res.data.data || [])
    }).catch(() => {})
  }, [])

  // Load products
  const loadProducts = useCallback(async () => {
    setLoading(true)
    try {
      const res = await productApi.getProducts({
        page,
        size: pageSize,
        keyword: keyword || undefined,
        categoryId: categoryId || undefined,
        status: (status as ProductStatus) || undefined,
      })
      const data = res.data.data
      setProducts(data?.items || [])
      setTotal(data?.total || 0)
    } catch {
      // Error handled by API layer
    } finally {
      setLoading(false)
    }
  }, [page, pageSize, keyword, categoryId, status])

  useEffect(() => {
    loadProducts()
  }, [loadProducts])

  // Handlers
  const handleSearch = () => {
    setPage(1)
    updateUrl({ page: 1 })
  }

  const handleReset = () => {
    setKeyword('')
    setCategoryId('')
    setStatus('')
    setPage(1)
    router.replace('/products', { scroll: false })
  }

  const handlePageChange = (newPage: number) => {
    setPage(newPage)
    updateUrl({ page: newPage })
  }

  const handlePageSizeChange = (newSize: number) => {
    setPageSize(newSize)
    setPage(1)
    updateUrl({ page: 1, size: newSize })
  }

  const handleStatusChange = async (id: string, newStatus: ProductStatus) => {
    try {
      await productApi.updateProductStatus(id, newStatus)
      toast.success(newStatus === 'on_sale' ? '已上架' : '已下架')
      loadProducts()
    } catch {
      // Error handled by API layer
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await productApi.deleteProduct(deleteTarget.id)
      toast.success('删除成功')
      setDeleteTarget(null)
      loadProducts()
    } catch {
      // Error handled by API layer
    } finally {
      setDeleting(false)
    }
  }

  const statusOptions = [
    { value: '', label: '全部状态' },
    { value: 'on_sale', label: '上架' },
    { value: 'off_sale', label: '下架' },
    { value: 'draft', label: '草稿' },
  ]

  const categoryOptions = [
    { value: '', label: '全部分类' },
    ...flattenCategories(categories),
  ]

  const isEmpty = !loading && products.length === 0 && !keyword && !categoryId && !status

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">商品管理</h1>
          <p className="text-sm text-gray-500 mt-1">管理所有商品信息</p>
        </div>
        <Button onClick={() => router.push('/products/new')}>
          <Plus className="w-4 h-4 mr-1.5" />
          添加商品
        </Button>
      </div>

      {isEmpty ? (
        <EmptyState
          title="暂无商品"
          description="点击上方按钮添加第一个商品"
          icon="package"
          action={
            <Button onClick={() => router.push('/products/new')}>
              <Plus className="w-4 h-4 mr-1.5" />
              添加商品
            </Button>
          }
        />
      ) : (
        <>
          {/* Filters */}
          <div className="bg-gray-50 p-4 rounded-lg mb-4">
            <div className="flex flex-wrap items-end gap-4">
              <div className="min-w-[200px]">
                <Input
                  label="关键词搜索"
                  placeholder="商品名称、SKU"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                />
              </div>
              <div className="min-w-[160px]">
                <Select
                  label="分类"
                  options={categoryOptions}
                  value={categoryId}
                  onChange={(e) => { setCategoryId(e.target.value); setPage(1) }}
                />
              </div>
              <div className="min-w-[140px]">
                <Select
                  label="状态"
                  options={statusOptions}
                  value={status}
                  onChange={(e) => { setStatus(e.target.value); setPage(1) }}
                />
              </div>
              <div className="flex items-center gap-2 ml-auto">
                <Button variant="secondary" size="sm" onClick={handleReset}>
                  重置
                </Button>
                <Button size="sm" onClick={handleSearch}>
                  搜索
                </Button>
              </div>
            </div>
          </div>

          {/* Table */}
          <ProductTable
            products={products}
            loading={loading}
            total={total}
            page={page}
            pageSize={pageSize}
            onPageChange={handlePageChange}
            onPageSizeChange={handlePageSizeChange}
            onStatusChange={handleStatusChange}
            onDelete={(product) => setDeleteTarget(product)}
          />
        </>
      )}

      {/* Delete confirmation modal */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="确认删除"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)} disabled={deleting}>
              取消
            </Button>
            <Button variant="danger" onClick={handleDelete} loading={deleting}>
              确认删除
            </Button>
          </>
        }
      >
        <p className="text-gray-600">
          确定要删除商品 <span className="font-medium text-gray-900">{deleteTarget?.name}</span> 吗？此操作不可撤销。
        </p>
      </Modal>
    </div>
  )
}
