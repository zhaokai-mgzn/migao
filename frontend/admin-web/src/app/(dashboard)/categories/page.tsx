'use client'

import { useState, useEffect, useCallback } from 'react'
import { Plus } from 'lucide-react'
import { Button, Modal, Loading, PageHeader, PageCard, EmptyState } from '@/components/ui'
import ListLoadError from '@/components/common/ListLoadError'
import CategoryTree from '@/components/products/CategoryTree'
import CategoryDialog from '@/components/products/CategoryDialog'
import { categoryApi } from '@/lib/api'
import { toast } from 'sonner'
import type { Category, CategoryFormData } from '@/types'

export default function CategoriesPage() {
  const [categories, setCategories] = useState<Category[]>([])
  const [loading, setLoading] = useState(true)
  /**
   * 列表读失败（issue #8200 · P1-06）：与「还没有商品分类」**互斥** —— 读不到不是业务事实。
   * 改前这里是空 `catch`（「Error handled by API layer」）⇒ 拦截器 toast ≈4s 一消失，
   * 屏上就只剩空态那句「还没有商品分类 —— 先建一个分类」，与「这个店真的没有分类」逐字相同。
   */
  const [categoriesLoadFailed, setCategoriesLoadFailed] = useState(false)

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
      setCategoriesLoadFailed(false)
    } catch {
      // 🔴 issue #8200 · P1-06：读失败**不清零**（保留上次成功值），也不冒充空态 ——
      // 由下面的常驻失败面承接（DQ-1：不得把「没读到」说成「本来就没有」）。
      setCategoriesLoadFailed(true)
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
        {/* 🔴 issue #8200 · P1-06：读失败的**常驻**出口（`role="alert"` + 真重发）。
            与下方空态**互斥**：失败时「还没有商品分类」一句都不渲染。 */}
        {categoriesLoadFailed && (
          <ListLoadError
            testId="categories-load-error"
            message="分类没读到 —— 不是没有分类，是这次没读成功。请检查网络后重试"
            onRetry={loadCategories}
            retrying={loading}
          />
        )}
        {loading ? (
          <div className="py-12">
            <Loading text="加载中…" />
          </div>
        ) : categories.length === 0 ? (
          /* 🔴 issue #8200 · P1-06：读失败时**不渲染空态** —— 空态是「读成功且真的没有」的事实性
             断言，而真相当下是「没读到」（失败面已在上面常驻）。空态文案口径不变（issue #7007：
             不与副标题逐字重复、不复用按钮名「添加分类」）。 */
          categoriesLoadFailed ? null : (
            <EmptyState
              testId="categories-empty"
              icon="package"
              title="还没有商品分类"
              description="先建一个分类，再往里加商品。建好后可以上下调顺序、随时改名或删除。"
            />
          )
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