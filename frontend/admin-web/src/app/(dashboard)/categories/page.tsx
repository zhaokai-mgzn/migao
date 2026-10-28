'use client'

import { useState, useEffect, useCallback } from 'react'
import { Plus } from 'lucide-react'
import { Button, Modal, Loading, PageHeader, PageCard, EmptyState } from '@/components/ui'
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
    <div className="p-6 space-y-4">
      {/* Header */}
      <PageHeader
        title="分类管理"
        subtitle="管理商品分类：新增、编辑、删除和排序"
        actions={
          <Button onClick={handleAdd}>
            <Plus className="w-4 h-4 mr-1.5" />
            添加分类
          </Button>
        }
      />

      {/* Category list — 全宽，扁平结构 */}
      <PageCard>
        {loading ? (
          <div className="py-12">
            <Loading text="加载中…" />
          </div>
        ) : categories.length === 0 ? (
          /* 空态（issue #7007，用户裁定「文案精简美化」）：**文案不与副标题逐字重复** ——
             原正文那句「管理商品分类：新增、编辑、删除和排序」与上方 `PageHeader` 的 subtitle
             **一字不差**（§31 P2 信息不重复），故换成本页**独有**的「第一步做什么」。
             ⚠️ 有意**不复用**按钮名「添加分类」（页头已有同名按钮 ⇒ 两处同名会让
             `getByText` 歧义、读屏也会念两遍）。 */
          <EmptyState
            testId="categories-empty"
            icon="package"
            title="还没有商品分类"
            description="先建一个分类，再往里加商品。建好后可以上下调顺序、随时改名或删除。"
          />
        ) : (
          <CategoryTree
            categories={categories}
            onEdit={handleEdit}
            onDelete={setDeleteTarget}
            onMoveUp={handleMoveUp}
            onMoveDown={handleMoveDown}
          />
        )}
      </PageCard>

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