'use client'

import { Fragment, useCallback, useEffect, useState } from 'react'
import { AlertCircle, FolderTree, Plus } from 'lucide-react'
import { toast } from 'sonner'
import { Button, Modal } from '@/components/ui'
import { processingCategoryApi, processingItemApi } from '@/lib/api'
import type { ProcessingCategory, ProcessingItem } from '@/types'
import { DISCOUNT_OPTIONS, EMPTY_FORM, ItemForm, QTY_OPTIONS } from './processing-shared'

/**
 * 「加工项与加工费」域的**加工项面板**（issue #6585 从 `ProcessingBoard` 拆出，cut & paste + 补 import）。
 *
 * ## 它回答一个问题
 *
 * 「我有哪些加工项？」—— 列表 + 新增/编辑/删除 + 加工分类（抽屉）。
 * 加工费（哪几个一起用收多少）在 {@link import('./FeeCombinationsPanel').default}，**同一个域的另一件事**。
 *
 * ## 自包含（issue #6585 的核心 constract）
 *
 * 面板**自己拉自己的数据**（`processingItemApi.getProcessingItems` + `processingCategoryApi.getProcessingCategories`），
 * 不依赖外层喂 props ⇒ 可以单独 `render(<ProcessingItemsPanel />`，也可以被配置指挥台直接挂载。
 * 🔴 一份数据两处用的老形态（加工项 + 分类同一次请求喂列表与勾选源）已随之拆开：加工费面板自己拉目录。
 *
 * ## `embedded`（issue #6580 的形态口径，本拆分沿用）
 *
 * `true` = 被配置指挥台（`/settings` 的「加工项与加工费」域）挂载 —— 那种形态下本面板**不渲染自己那一层
 * 区块标题**「加工项」（域面板已给标题与一句话）；其余一律相同。独立路由 / 旧 tab 形态按 `embedded=false`
 * 原样渲染（标题在）。
 *
 * ## 零行为变更（本拆分**不改一行逻辑/文案/testid**）
 *
 * 对照 v1 `ProcessingBoard` 的 `tab === 'items'` 分支逐字搬运；`onLoadingChange` 只是把原本由 board
 * 持有的 `itemsLoading` 上报回去（board 的「刷新」按钮 `disabled` 判据不变）。
 */
export default function ProcessingItemsPanel({
  embedded = false,
  onLoadingChange,
  onReloadReady,
}: {
  embedded?: boolean
  /** 把本面板的加载态上报给外层（board 的「刷新」按钮要在**任一**面板加载中时置灰） */
  onLoadingChange?: (loading: boolean) => void
  /** 把本面板的取数入口交给外层（board 的「刷新」按钮要能一键重取**两个**面板） */
  onReloadReady?: (reload: () => void) => void
} = {}) {
  const [items, setItems] = useState<ProcessingItem[]>([])
  const [categories, setCategories] = useState<ProcessingCategory[]>([])
  const [itemsLoading, setItemsLoading] = useState(true)
  const [itemsError, setItemsError] = useState('')
  const [saving, setSaving] = useState(false)

  const [formOpen, setFormOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<ItemForm>(EMPTY_FORM)
  const [errors, setErrors] = useState<Record<string, string>>({})

  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null)

  /** 加工分类抽屉（次区：分类只用于归类，不占主列表的位置） */
  const [categoryOpen, setCategoryOpen] = useState(false)
  const [newCategoryName, setNewCategoryName] = useState('')
  const [creatingCategory, setCreatingCategory] = useState(false)

  /**
   * 加工项 + 加工分类：**一份数据两处用**（列表 + 新建/编辑表单的分类下拉）。
   */
  const loadItems = useCallback(async () => {
    setItemsLoading(true)
    setItemsError('')
    const [itemsRes, catsRes] = await Promise.allSettled([
      processingItemApi.getProcessingItems({ page: 1, size: 999 }),
      processingCategoryApi.getProcessingCategories(),
    ])
    if (itemsRes.status === 'fulfilled') {
      setItems(itemsRes.value.data?.data?.items || [])
    } else {
      setItems([])
      setItemsError('加工项加载失败，请重试')
    }
    // 分类只喂表单下拉与抽屉：它失败不得把加工项列表一起打白屏（同 #4307 的处置）
    setCategories(catsRes.status === 'fulfilled' ? catsRes.value.data?.data || [] : [])
    setItemsLoading(false)
  }, [])

  useEffect(() => {
    void loadItems()
  }, [loadItems])

  useEffect(() => {
    onLoadingChange?.(itemsLoading)
  }, [itemsLoading, onLoadingChange])

  useEffect(() => {
    // 面板自带取数 ⇒ 外层的「刷新」只能借这条线（卸载时还原成空操作，避免点到已卸载面板）
    onReloadReady?.(() => void loadItems())
    return () => onReloadReady?.(() => {})
  }, [loadItems, onReloadReady])

  // ────────────────────────── 加工项：CRUD ──────────────────────────

  const openCreate = () => {
    setEditingId(null)
    // 默认选中第一个加工分类；无分类时留空并在弹窗内引导创建
    setForm({ ...EMPTY_FORM, categoryId: categories[0]?.id || '' })
    setErrors({})
    setFormOpen(true)
  }

  const openEdit = (item: ProcessingItem) => {
    setEditingId(item.id)
    setForm({
      name: item.name,
      discount: '',
      discountQty: '2',
      discountRate: '',
      categoryId: item.categoryId || categories[0]?.id || '',
    })
    setErrors({})
    setFormOpen(true)
  }

  const closeForm = () => {
    if (saving) return
    setFormOpen(false)
  }

  const updateField = <K extends keyof ItemForm>(field: K, value: ItemForm[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }))
    setErrors((prev) => ({ ...prev, [field]: '' }))
  }

  const validate = (): Record<string, string> => {
    const errs: Record<string, string> = {}
    if (!form.name.trim()) {
      errs.name = '请输入加工项名称'
    } else if (form.name.trim().length > 20) {
      errs.name = '名称不能超过20个字符'
    }

    if (!form.categoryId) {
      errs.categoryId = '请先选择或创建加工分类'
    }

    return errs
  }

  /** 加工分类写路径统一出口（表单内联创建 + 抽屉创建共用，避免第二份实现） */
  const handleCreateCategory = async () => {
    const name = newCategoryName.trim()
    if (!name) {
      toast.error('请输入加工分类名称')
      return
    }
    setCreatingCategory(true)
    try {
      const res = await processingCategoryApi.createProcessingCategory({ name, sort: 0 })
      toast.success('加工分类已创建')
      await loadItems()
      // 自动选中刚创建的分类（表单开着时立刻可用；抽屉场景下 setForm 无害 —— openCreate 会重置）
      const created = res.data?.data
      setForm((prev) => ({ ...prev, categoryId: created?.id || prev.categoryId || categories[0]?.id || '' }))
      setNewCategoryName('')
    } catch (error) {
      console.error('创建加工分类失败:', error)
      toast.error('创建加工分类失败')
    } finally {
      setCreatingCategory(false)
    }
  }

  const handleSubmit = async () => {
    const errs = validate()
    if (Object.keys(errs).length > 0) {
      setErrors(errs)
      return
    }

    setSaving(true)
    try {
      const payload = {
        name: form.name.trim(),
        categoryId: form.categoryId, // 用户显式选择（此前强取 categories[0] 且新租户为空 → 提交 'default' 报「加工分类不存在」）
        // 单位恒为「米」（#4882）：加工费按米计价是行业口径（#3005），V83 目录 16 项全 per_meter；
        // 计价方式既已整体退场，就没有第二个取值来源 —— 这里不留可变量，也不按计价方式查表。
        unit: '米',
        status: 'active' as const,
      }

      if (editingId) {
        await processingItemApi.updateProcessingItem(editingId, payload)
        toast.success('已更新加工项')
      } else {
        await processingItemApi.createProcessingItem(payload)
        toast.success('已新增加工项')
      }

      setFormOpen(false)
      await loadItems()
    } catch (error) {
      console.error('保存失败:', error)
      toast.error('保存失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  const requestDelete = (id: string) => {
    setDeleteTargetId(id)
    setDeleteConfirmOpen(true)
  }

  const confirmDelete = async () => {
    if (!deleteTargetId) return
    try {
      await processingItemApi.deleteProcessingItem(deleteTargetId)
      toast.success('删除成功')
      await loadItems()
    } catch {
      toast.error('删除失败')
    } finally {
      setDeleteConfirmOpen(false)
      setDeleteTargetId(null)
    }
  }

  const categoryNameOf = (item: ProcessingItem) =>
    item.categoryName || categories.find((c) => c.id === item.categoryId)?.name || '—'

  return (
    <div className="space-y-5" data-testid="processing-items-panel">
      <section className="rounded-lg border border-neutral-200 bg-white" data-testid="processing-items">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-neutral-100 px-4 py-3">
          <div className="flex items-baseline gap-2">
            {!embedded && (
              <h2 className="text-sm font-medium text-neutral-800" data-testid="processing-items-title">
                加工项
              </h2>
            )}
            <span className="text-sm text-neutral-500" data-testid="processing-items-total">
              {items.length} 项
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {/* 次操作：分类只用于归类，走抽屉，不占主列表 */}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setCategoryOpen(true)}
              data-testid="processing-categories-open"
            >
              <FolderTree className="mr-1.5 h-4 w-4" />
              加工分类（{categories.length}）
            </Button>
            <Button size="sm" onClick={openCreate} data-testid="processing-item-new">
              <Plus className="mr-1.5 h-4 w-4" />
              新增加工项
            </Button>
          </div>
        </div>

        {itemsError ? (
          <div className="m-4 flex items-center gap-2 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            <AlertCircle className="h-4 w-4" />
            <span data-testid="processing-items-error">{itemsError}</span>
            <Button variant="secondary" size="sm" onClick={() => void loadItems()} data-testid="processing-items-retry">
              重试
            </Button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="mt-3 w-full border-collapse">
              <thead>
                <tr className="border-b border-neutral-200 bg-neutral-50/60">
                  <th className="w-[45%] whitespace-nowrap px-4 py-3 text-left text-sm font-semibold text-neutral-900">
                    加工项名称
                  </th>
                  <th className="w-[30%] whitespace-nowrap px-4 py-3 text-left text-sm font-semibold text-neutral-900">
                    加工分类
                  </th>
                  <th className="w-[25%] whitespace-nowrap px-4 py-3 text-left text-sm font-semibold text-neutral-900">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody>
                {itemsLoading ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-12 text-center text-neutral-500">
                      <div className="flex items-center justify-center gap-2">
                        <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary-600 border-t-transparent" />
                        加载中...
                      </div>
                    </td>
                  </tr>
                ) : items.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-12 text-center text-sm text-neutral-400">
                      <span data-testid="processing-items-empty">
                        暂无加工项 —— 点右上「新增加工项」建第一个（如 韩褶、打孔）
                        {categories.length === 0 && '；当前还没有加工分类，可在新增弹窗里直接创建'}
                      </span>
                    </td>
                  </tr>
                ) : (
                  items.map((item) => (
                    <Fragment key={item.id}>
                      <tr className="border-b border-neutral-100 hover:bg-neutral-50/40" data-testid={`processing-item-${item.id}`}>
                        <td className="px-4 py-3 text-sm text-neutral-900">{item.name}</td>
                        <td className="px-4 py-3 text-sm text-neutral-600">{categoryNameOf(item)}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-3 whitespace-nowrap">
                            <button
                              onClick={() => openEdit(item)}
                              className="text-sm text-primary-600 transition-colors hover:text-primary-700 hover:underline"
                            >
                              编辑
                            </button>
                            <button
                              onClick={() => requestDelete(item.id)}
                              className="text-sm text-red-500 transition-colors hover:text-red-600 hover:underline"
                            >
                              删除
                            </button>
                          </div>
                        </td>
                      </tr>
                    </Fragment>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── 抽屉：加工分类（次区，只读列表 + 新建；改/删不在此，后端也未提供）── */}
      <Modal
        open={categoryOpen}
        onClose={() => setCategoryOpen(false)}
        title="加工分类"
        width={480}
        footer={
          <Button variant="secondary" onClick={() => setCategoryOpen(false)}>
            关闭
          </Button>
        }
      >
        <div className="space-y-3">
          <p className="text-xs text-neutral-500">
            分类只用于给加工项归类（如「基础加工」「窗帘加工」）；加工项必须归属于一个分类。
          </p>
          {categories.length === 0 ? (
            <p className="text-sm text-neutral-500" data-testid="processing-categories-empty">
              还没有加工分类 —— 在下面新建一个。
            </p>
          ) : (
            <ul className="divide-y divide-neutral-100" data-testid="processing-categories-list">
              {categories.map((c) => (
                <li key={c.id} className="py-2 text-sm text-neutral-900" data-testid={`processing-category-${c.id}`}>
                  {c.name}
                </li>
              ))}
            </ul>
          )}
          <div className="flex gap-2">
            <input
              type="text"
              className="h-9 flex-1 rounded border border-neutral-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              placeholder="新分类名称（如：基础加工）"
              value={newCategoryName}
              onChange={(e) => setNewCategoryName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && void handleCreateCategory()}
              data-testid="processing-category-name"
            />
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => void handleCreateCategory()}
              loading={creatingCategory}
              className="shrink-0"
            >
              创建
            </Button>
          </div>
        </div>
      </Modal>

      {/* ── 新增/编辑加工项弹窗 ── */}
      <Modal
        open={formOpen}
        onClose={closeForm}
        title={editingId ? '编辑加工项' : '新增加工项'}
        width={560}
        maskClosable={!saving}
        footer={
          <>
            <Button variant="secondary" onClick={closeForm} disabled={saving}>
              取消
            </Button>
            <Button onClick={() => void handleSubmit()} loading={saving}>
              保存
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {/* 加工项名称 */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-neutral-800">
              加工项名称<span className="ml-0.5 text-red-500">*</span>
            </label>
            <input
              type="text"
              className={`h-9 w-full rounded border px-3 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ${
                errors.name ? 'border-red-500' : 'border-neutral-300'
              }`}
              placeholder="请输入加工项名称（最多20个字符）"
              maxLength={20}
              value={form.name}
              onChange={(e) => updateField('name', e.target.value)}
            />
            {errors.name && <p className="mt-1 text-xs text-red-600">{errors.name}</p>}
          </div>

          {/* 加工分类（必选：后端加工项强依赖加工分类，新租户从 0 需先建） */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-neutral-800">
              加工分类<span className="ml-0.5 text-red-500">*</span>
            </label>
            {categories.length > 0 ? (
              <select
                className={`h-9 w-full appearance-none rounded border bg-white px-3 pr-8 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ${
                  errors.categoryId ? 'border-red-500' : 'border-neutral-300'
                }`}
                value={form.categoryId}
                onChange={(e) => updateField('categoryId', e.target.value)}
              >
                <option value="" disabled>
                  请选择加工分类
                </option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            ) : (
              <div className="space-y-2 rounded-lg border border-amber-200 bg-amber-50 p-3">
                <p className="text-xs text-amber-700">
                  当前还没有加工分类，加工项必须归属于一个加工分类。请先创建：
                </p>
                <div className="flex gap-2">
                  <input
                    type="text"
                    className="h-9 flex-1 rounded border border-amber-300 bg-white px-3 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                    placeholder="请输入加工分类名称，如：基础加工"
                    value={newCategoryName}
                    onChange={(e) => setNewCategoryName(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && void handleCreateCategory()}
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => void handleCreateCategory()}
                    loading={creatingCategory}
                    className="shrink-0"
                  >
                    创建
                  </Button>
                </div>
              </div>
            )}
            {errors.categoryId && categories.length > 0 && (
              <p className="mt-1 text-xs text-red-600">{errors.categoryId}</p>
            )}
          </div>

          {/* 设置优惠 */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-neutral-800">设置优惠</label>
            <select
              className="h-9 w-full appearance-none rounded border border-neutral-300 bg-white px-3 pr-8 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
              value={form.discount}
              onChange={(e) => updateField('discount', e.target.value)}
            >
              {DISCOUNT_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

            {form.discount === 'amount_off' && (
              <div className="mt-2 flex items-center gap-2">
                <select
                  className="h-9 appearance-none rounded border border-neutral-300 bg-white px-3 pr-8 text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                  value={form.discountQty}
                  onChange={(e) => updateField('discountQty', e.target.value)}
                >
                  {QTY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <div className="flex items-center">
                  <input
                    type="text"
                    className="h-9 w-32 rounded-l border border-neutral-300 px-3 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                    placeholder="请输入折扣力度"
                    value={form.discountRate}
                    onChange={(e) => updateField('discountRate', e.target.value)}
                  />
                  <span className="flex h-9 items-center rounded-r border border-l-0 border-neutral-300 bg-neutral-50 px-2 text-sm text-neutral-600">
                    折
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      </Modal>

      {/* ── 删除确认（危险操作二次确认）── */}
      <Modal
        open={deleteConfirmOpen}
        onClose={() => setDeleteConfirmOpen(false)}
        title="确认删除"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteConfirmOpen(false)}>
              取消
            </Button>
            <Button variant="danger" onClick={() => void confirmDelete()}>
              确定
            </Button>
          </>
        }
      >
        <p className="text-sm leading-relaxed text-neutral-600">
          删除后，当用户再购买已关联当前加工项的商品时，将不会再看到当前加工项。确定要删除当前加工项吗？
        </p>
      </Modal>
    </div>
  )
}
