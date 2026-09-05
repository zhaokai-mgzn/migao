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
    } catch (e) {
      // Error handled by API layer
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadCategories()
  }, [loadCategories])

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

  // issue #2905：上移/下移
  const handleMoveUp = async (category: Category) => {
    try {
      await categoryApi.moveCategory(category.id, 'up')
      toast.success(`「${category.name}」已上移`)
      loadCategories()
    } catch (e) {
      // Error handled by API layer
    }
  }

  const handleMoveDown = async (category: Category) => {
    try {
      await categoryApi.moveCategory(category.id, 'down')
      toast.success(`「${category.name}」已下移`)
      loadCategories()
    } catch (e) {
      // Error handled by API layer
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await categoryApi.deleteCategory(deleteTarget.id)
      toast.success('分类已删除')
      setDeleteTarget(null)
      loadCategories()
    } catch (e) {
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
          <h1 className="text-xl font-bold text-neutral-900">分类管理</h1>
          <p className="text-sm text-neutral-500 mt-1">管理商品分类，支持对分类进行新增、编辑、删除和排序</p>
        </div>
        <Button onClick={handleAdd}>
          <Plus className="w-4 h-4 mr-1.5" />
          添加分类
        </Button>
      </div>

      {/* Category list — 全宽，扁平结构 */}
      <div className="bg-white rounded-lg border border-neutral-200 p-5">
        {loading ? (
          <div className="py-12">
            <Loading text="加载中..." />
          </div>
        ) : categories.length === 0 ? (
          <div className="py-12 text-center text-sm text-neutral-500">
            管理商品分类，支持对分类进行新增、编辑、删除和排序
          </div>
        ) : (
          <CategoryTree
            categories={categories}
            onEdit={handleEdit}
            onDelete={setDeleteTarget}
            onMoveUp={handleMoveUp}
            onMoveDown={handleMoveDown}
          />
        )}
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
        <p className="text-neutral-600">
          确定要删除分类 <span className="font-medium text-neutral-900">{deleteTarget?.name}</span> 吗？
        </p>
      </Modal>
    </div>
  )
}