'use client'

import { useState, useEffect, useCallback } from 'react'
import { Plus } from 'lucide-react'
import { Button, Modal, Loading } from '@/components/ui'
import CategoryTree from '@/components/products/CategoryTree'
import CategoryDialog from '@/components/products/CategoryDialog'
import { categoryApi } from '@/lib/api'
import { toast } from 'sonner'
import type { Category, CategoryFormData } from '@/types'

export default function CategoriesPage() {
  const [categories, setCategories] = useState<Category[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedCategory, setSelectedCategory] = useState<Category | null>(null)

  // Dialog state
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingCategory, setEditingCategory] = useState<Category | null>(null)

  // Delete confirmation
  const [deleteTarget, setDeleteTarget] = useState<Category | null>(null)
  const [deleting, setDeleting] = useState(false)

  const loadCategories = useCallback(async () => {
    setLoading(true)
    try {
      const res = await categoryApi.getCategories()
      setCategories(res.data.data || [])
    } catch {
      // Error handled by API layer
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadCategories()
  }, [loadCategories])

  // Count products in a category (placeholder - would need API support)
  const countChildren = (cat: Category): number => {
    let count = 0
    if (cat.children) {
      count += cat.children.length
      cat.children.forEach((child) => { count += countChildren(child) })
    }
    return count
  }

  const handleAdd = () => {
    setEditingCategory(null)
    setDialogOpen(true)
  }

  const handleEdit = (category: Category) => {
    setEditingCategory(category)
    setDialogOpen(true)
  }

  const handleSubmit = async (data: CategoryFormData) => {
    if (editingCategory) {
      await categoryApi.updateCategory(editingCategory.id, data)
      toast.success('分类已更新')
    } else {
      await categoryApi.createCategory(data)
      toast.success('分类已创建')
    }
    loadCategories()
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await categoryApi.deleteCategory(deleteTarget.id)
      toast.success('分类已删除')
      setDeleteTarget(null)
      if (selectedCategory?.id === deleteTarget.id) {
        setSelectedCategory(null)
      }
      loadCategories()
    } catch {
      // Error handled by API layer
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">分类管理</h1>
          <p className="text-sm text-gray-500 mt-1">管理商品分类，支持多级分类</p>
        </div>
        <Button onClick={handleAdd}>
          <Plus className="w-4 h-4 mr-1.5" />
          添加分类
        </Button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Category tree */}
        <div className="lg:col-span-2">
          <div className="bg-gray-50 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">分类结构</h3>
            {loading ? (
              <div className="py-12">
                <Loading text="加载中..." />
              </div>
            ) : (
              <CategoryTree
                categories={categories}
                selectedId={selectedCategory?.id}
                onSelect={setSelectedCategory}
                onEdit={handleEdit}
                onDelete={setDeleteTarget}
                showActions
              />
            )}
          </div>
        </div>

        {/* Right: Detail panel */}
        <div className="lg:col-span-1">
          <div className="bg-gray-50 rounded-lg p-4 sticky top-6">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">分类详情</h3>
            {selectedCategory ? (
              <div className="space-y-3">
                <div>
                  <dt className="text-xs text-gray-500">分类名称</dt>
                  <dd className="text-sm font-medium text-gray-900 mt-0.5">{selectedCategory.name}</dd>
                </div>
                <div>
                  <dt className="text-xs text-gray-500">分类 ID</dt>
                  <dd className="text-sm text-gray-600 font-mono mt-0.5">{selectedCategory.id}</dd>
                </div>
                <div>
                  <dt className="text-xs text-gray-500">排序权重</dt>
                  <dd className="text-sm text-gray-900 mt-0.5">{selectedCategory.sort ?? 0}</dd>
                </div>
                <div>
                  <dt className="text-xs text-gray-500">子分类数</dt>
                  <dd className="text-sm text-gray-900 mt-0.5">{selectedCategory.children?.length ?? 0}</dd>
                </div>
                <div className="pt-3 flex gap-2">
                  <Button size="sm" variant="secondary" onClick={() => handleEdit(selectedCategory)}>
                    编辑
                  </Button>
                  <Button size="sm" variant="danger" onClick={() => setDeleteTarget(selectedCategory)}>
                    删除
                  </Button>
                </div>
              </div>
            ) : (
              <p className="text-sm text-gray-500 py-4 text-center">
                点击左侧分类查看详情
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Add/Edit dialog */}
      <CategoryDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        onSubmit={handleSubmit}
        category={editingCategory}
        categories={categories}
      />

      {/* Delete confirmation */}
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
          确定要删除分类 <span className="font-medium text-gray-900">{deleteTarget?.name}</span> 吗？
          {deleteTarget?.children && deleteTarget.children.length > 0 && (
            <span className="block mt-2 text-amber-600">
              ⚠️ 该分类下还有 {deleteTarget.children.length} 个子分类，删除后子分类也将被移除。
            </span>
          )}
        </p>
      </Modal>
    </div>
  )
}
