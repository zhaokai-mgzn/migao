'use client'

import { useEffect, useState, useCallback, Fragment } from 'react'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'
import { processingItemApi, processingCategoryApi, categoryApi } from '@/lib/api'
import { Modal, Button } from '@/components/ui'
import type { ProcessingItem, ProcessingCategory, PricingMethod, Category } from '@/types'

// 扁平化分类树为 checkbox 选项
function flattenCategories(
  categories: Category[],
  level = 0
): { value: string; label: string; indent: number }[] {
  const result: { value: string; label: string; indent: number }[] = []
  for (const cat of categories) {
    const prefix = '  '.repeat(level)
    result.push({
      value: cat.id,
      label: `${prefix}${level > 0 ? '└ ' : ''}${cat.name}`,
      indent: level,
    })
    if (cat.children && cat.children.length > 0) {
      result.push(...flattenCategories(cat.children, level + 1))
    }
  }
  return result
}

// 弹窗内表单数据
interface FormData {
  name: string
  unitPrice: string
  pricingMethod: PricingMethod | ''
  discount: string
  discountQty: string
  discountRate: string
  categoryId: string
  applicableProductCategories: string[]
}

// 计价方式 → 单位映射
const PRICING_UNIT_MAP: Record<string, string> = {
  per_meter: '米',
  per_piece: '套',
  fixed: '件',
  per_area: '平方米',
}

// 计价方式选项
const PRICING_METHOD_OPTIONS = [
  { value: 'per_meter', label: '按购买米数计价（单价 × 米数）' },
  { value: 'per_piece', label: '按购买套数计价（单价 × 件数）' },
  { value: 'fixed', label: '固定一口价（不论尺寸/数量）' },
  { value: 'per_area', label: '按面积计价（单价 × 宽 × 高 × 数量）' },
]

// 优惠类型选项
const DISCOUNT_OPTIONS = [
  { value: '', label: '无优惠' },
  { value: 'amount_off', label: '按金额满减' },
]

// 满X件选项（2-99）
const QTY_OPTIONS = Array.from({ length: 98 }, (_, i) => ({
  value: String(i + 2),
  label: `满${i + 2}件`,
}))

const EMPTY_FORM: FormData = {
  name: '',
  unitPrice: '',
  pricingMethod: '',
  discount: '',
  discountQty: '2',
  discountRate: '',
  categoryId: '',
  applicableProductCategories: [],
}

export default function ProcessingPage() {
  const [items, setItems] = useState<ProcessingItem[]>([])
  const [categories, setCategories] = useState<ProcessingCategory[]>([])
  const [productCategories, setProductCategories] = useState<Category[]>([])
  const [catOptions, setCatOptions] = useState<{ value: string; label: string; indent: number }[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  // 编辑弹窗
  const [formOpen, setFormOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<FormData>(EMPTY_FORM)
  const [errors, setErrors] = useState<Record<string, string>>({})

  // 删除确认
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false)
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null)

  // 加载数据
  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [itemsRes, catsRes, prodCatsRes] = await Promise.all([
        processingItemApi.getProcessingItems({ page: 1, size: 999 }),
        processingCategoryApi.getProcessingCategories(),
        categoryApi.getCategories(),
      ])
      const pageData = itemsRes.data?.data
      setItems(pageData?.items || [])
      setCategories(catsRes.data?.data || [])
      const prodCats = prodCatsRes.data?.data || []
      setProductCategories(prodCats)
      setCatOptions(flattenCategories(prodCats))
    } catch (error) {
      console.error('加载数据失败:', error)
      toast.error('加载数据失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  // 打开新增弹窗
  const openCreate = () => {
    setEditingId(null)
    // 默认选中第一个加工分类；无分类时留空并在弹窗内引导创建
    setForm({ ...EMPTY_FORM, categoryId: categories[0]?.id || '' })
    setErrors({})
    setFormOpen(true)
  }

  // 打开编辑弹窗
  const openEdit = (item: ProcessingItem) => {
    setEditingId(item.id)
    setForm({
      name: item.name,
      unitPrice: String(item.unitPrice ?? item.basePrice ?? ''),
      pricingMethod: item.pricingMethod || 'per_meter',
      discount: '',
      discountQty: '2',
      discountRate: '',
      categoryId: item.categoryId || categories[0]?.id || '',
      applicableProductCategories: item.applicableProductCategories || [],
    })
    setErrors({})
    setFormOpen(true)
  }

  // 关闭弹窗（保存中不允许关闭）
  const closeForm = () => {
    if (saving) return
    setFormOpen(false)
  }

  // 字段变更
  const updateField = <K extends keyof FormData>(field: K, value: FormData[K]) => {
    setForm((prev) => ({ ...prev, [field]: value }))
    setErrors((prev) => ({ ...prev, [field]: '' }))
  }

  // 校验表单
  const validate = (): Record<string, string> => {
    const errs: Record<string, string> = {}
    if (!form.name.trim()) {
      errs.name = '请输入加工项名称'
    } else if (form.name.trim().length > 20) {
      errs.name = '名称不能超过20个字符'
    }

    const price = parseFloat(form.unitPrice)
    if (!form.unitPrice.trim()) {
      errs.unitPrice = '请输入加工项价格'
    } else if (isNaN(price) || price < 0.1 || price > 999.99) {
      errs.unitPrice = '价格范围 0.10 ~ 999.99'
    } else if (form.unitPrice.includes('.') && form.unitPrice.split('.')[1]?.length > 2) {
      errs.unitPrice = '最多2位小数'
    }

    if (!form.pricingMethod) {
      errs.pricingMethod = '请选择计价方式'
    }

    if (!form.categoryId) {
      errs.categoryId = '请先选择或创建加工分类'
    }

    return errs
  }

  // 弹窗内一键创建加工分类（新商家从 0 首次使用加工项时的流程断点修复）
  const [newCategoryName, setNewCategoryName] = useState('')
  const [creatingCategory, setCreatingCategory] = useState(false)
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
      await loadData()
      // 自动选中刚创建的分类
      const created = res.data?.data
      if (created?.id) {
        setForm((prev) => ({ ...prev, categoryId: created.id }))
      } else {
        // 兜底：刷新后选第一个
        setForm((prev) => ({ ...prev, categoryId: categories[0]?.id || '' }))
      }
      setNewCategoryName('')
    } catch (error) {
      console.error('创建加工分类失败:', error)
      toast.error('创建加工分类失败')
    } finally {
      setCreatingCategory(false)
    }
  }

  // 保存
  const handleSubmit = async () => {
    const errs = validate()
    if (Object.keys(errs).length > 0) {
      setErrors(errs)
      return
    }

    setSaving(true)
    try {
      const pricingMethod = form.pricingMethod as PricingMethod
      const payload = {
        name: form.name.trim(),
        categoryId: form.categoryId, // 用户显式选择（此前强取 categories[0] 且新租户为空 → 提交 'default' 报「加工分类不存在」）
        pricingMethod,
        unitPrice: parseFloat(form.unitPrice),
        unit: PRICING_UNIT_MAP[pricingMethod] || '套',
        status: 'active' as const,
        applicableProductCategories: form.applicableProductCategories,
      }

      if (editingId) {
        await processingItemApi.updateProcessingItem(editingId, payload)
        toast.success('已更新加工项')
      } else {
        await processingItemApi.createProcessingItem(payload)
        toast.success('已新增加工项')
      }

      setFormOpen(false)
      await loadData()
    } catch (error) {
      console.error('保存失败:', error)
      toast.error('保存失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  // 请求删除
  const requestDelete = (id: string) => {
    setDeleteTargetId(id)
    setDeleteConfirmOpen(true)
  }

  // 确认删除
  const confirmDelete = async () => {
    if (!deleteTargetId) return
    try {
      await processingItemApi.deleteProcessingItem(deleteTargetId)
      toast.success('删除成功')
      await loadData()
    } catch (error) {
      toast.error('删除失败')
    } finally {
      setDeleteConfirmOpen(false)
      setDeleteTargetId(null)
    }
  }

  // 获取计价方式显示文字
  const getPricingMethodLabel = (method: string) => {
    const opt = PRICING_METHOD_OPTIONS.find((o) => o.value === method)
    return opt?.label || method
  }

  return (
    <div className="p-6">
      {/* 页面标题 */}
      <h1 className="text-xl font-semibold text-neutral-900 mb-2">加工项配置</h1>
      <p className="text-sm text-neutral-500 mb-6">
        加工项是指为特定订单定制的产品修改服务，例如窗帘的长度裁剪、打孔方式选择等。
        您可以在这里管理可用的加工项类型和价格，下单时客户可选择需要的加工服务。
      </p>

      {/* 顶部操作栏 */}
      <div className="flex items-center justify-end gap-3 mb-4">
        <Button onClick={openCreate}>
          <Plus className="w-4 h-4 mr-1.5" />
          新增加工项
        </Button>
      </div>

      {/* 列表（只读） */}
      <div className="bg-white rounded-lg border border-neutral-200 overflow-hidden">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-neutral-200 bg-neutral-50/60">
              <th className="px-4 py-3 text-left text-sm font-semibold text-neutral-900 w-[30%] whitespace-nowrap">
                加工项名称
              </th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-neutral-900 w-[20%] whitespace-nowrap">
                加工项价格
              </th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-neutral-900 w-[25%] whitespace-nowrap">
                加工项计价方式
              </th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-neutral-900 w-[25%] whitespace-nowrap">
                操作
              </th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={4} className="px-4 py-12 text-center text-neutral-500">
                  <div className="flex items-center justify-center gap-2">
                    <div className="w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full animate-spin" />
                    加载中...
                  </div>
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-12 text-center text-sm text-neutral-400">
                  暂无加工项，点击右上角「新增加工项」开始创建
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <Fragment key={item.id}>
                  <tr className="border-b border-neutral-100 hover:bg-neutral-50/40">
                    <td className="px-4 py-3 text-sm text-neutral-900">{item.name}</td>
                    <td className="px-4 py-3 text-sm text-neutral-900">
                      {Number(item.unitPrice ?? item.basePrice ?? 0).toFixed(2)}
                    </td>
                    <td className="px-4 py-3 text-sm text-neutral-900">
                      {getPricingMethodLabel(item.pricingMethod || '')}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3 whitespace-nowrap">
                        <button
                          onClick={() => openEdit(item)}
                          className="text-sm text-primary-600 hover:text-primary-700 hover:underline transition-colors"
                        >
                          编辑
                        </button>
                        <button
                          onClick={() => requestDelete(item.id)}
                          className="text-sm text-red-500 hover:text-red-600 hover:underline transition-colors"
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

      {/* 新增/编辑加工项弹窗 */}
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
            <Button onClick={handleSubmit} loading={saving}>
              保存
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          {/* 加工项名称 */}
          <div>
            <label className="block text-sm font-medium text-neutral-800 mb-1.5">
              加工项名称<span className="text-red-500 ml-0.5">*</span>
            </label>
            <input
              type="text"
              className={`w-full h-9 px-3 rounded border text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ${
                errors.name ? 'border-red-500' : 'border-neutral-300'
              }`}
              placeholder="请输入加工项名称（最多20个字符）"
              maxLength={20}
              value={form.name}
              onChange={(e) => updateField('name', e.target.value)}
            />
            {errors.name && <p className="mt-1 text-xs text-red-600">{errors.name}</p>}
          </div>

          {/* 加工项价格 */}
          <div>
            <label className="block text-sm font-medium text-neutral-800 mb-1.5">
              加工项价格<span className="text-red-500 ml-0.5">*</span>
            </label>
            <input
              type="number"
              className={`w-full h-9 px-3 rounded border text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ${
                errors.unitPrice ? 'border-red-500' : 'border-neutral-300'
              }`}
              placeholder="请输入价格（0.10 ~ 999.99）"
              step="0.01"
              min="0.10"
              max="999.99"
              value={form.unitPrice}
              onChange={(e) => updateField('unitPrice', e.target.value)}
            />
            {errors.unitPrice && <p className="mt-1 text-xs text-red-600">{errors.unitPrice}</p>}
          </div>

          {/* 计价方式 */}
          <div>
            <label className="block text-sm font-medium text-neutral-800 mb-1.5">
              加工项计价方式<span className="text-red-500 ml-0.5">*</span>
            </label>
            <select
              className={`w-full h-9 px-3 pr-8 rounded border bg-white text-sm appearance-none focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ${
                errors.pricingMethod ? 'border-red-500' : 'border-neutral-300'
              }`}
              value={form.pricingMethod}
              onChange={(e) => updateField('pricingMethod', e.target.value as PricingMethod | '')}
            >
              <option value="" disabled>
                请选择计价方式
              </option>
              {PRICING_METHOD_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            {errors.pricingMethod && (
              <p className="mt-1 text-xs text-red-600">{errors.pricingMethod}</p>
            )}
          </div>

          {/* 加工分类（必选：后端加工项强依赖加工分类，新租户从 0 需先建） */}
          <div>
            <label className="block text-sm font-medium text-neutral-800 mb-1.5">
              加工分类<span className="text-red-500 ml-0.5">*</span>
            </label>
            {categories.length > 0 ? (
              <select
                className={`w-full h-9 px-3 pr-8 rounded border bg-white text-sm appearance-none focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 ${
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
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 space-y-2">
                <p className="text-xs text-amber-700">
                  当前还没有加工分类，加工项必须归属于一个加工分类。请先创建：
                </p>
                <div className="flex gap-2">
                  <input
                    type="text"
                    className="flex-1 h-9 px-3 rounded border border-amber-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                    placeholder="请输入加工分类名称，如：基础加工"
                    value={newCategoryName}
                    onChange={(e) => setNewCategoryName(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleCreateCategory()}
                  />
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={handleCreateCategory}
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
            <label className="block text-sm font-medium text-neutral-800 mb-1.5">设置优惠</label>
            <select
              className="w-full h-9 px-3 pr-8 rounded border border-neutral-300 bg-white text-sm appearance-none focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
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
                  className="h-9 px-3 pr-8 rounded border border-neutral-300 bg-white text-sm appearance-none focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
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
                    className="w-32 h-9 px-3 rounded-l border border-neutral-300 text-sm placeholder:text-neutral-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
                    placeholder="请输入折扣力度"
                    value={form.discountRate}
                    onChange={(e) => updateField('discountRate', e.target.value)}
                  />
                  <span className="h-9 px-2 flex items-center border border-l-0 border-neutral-300 rounded-r bg-neutral-50 text-sm text-neutral-600">
                    折
                  </span>
                </div>
              </div>
            )}
          </div>

          {/* 适用商品分类 */}
          <div className="space-y-2">
            <label className="block text-sm font-medium text-neutral-800">适用商品分类</label>
            <div className="max-h-40 overflow-y-auto border border-neutral-200 rounded-lg p-2 space-y-1">
              {catOptions.map((opt) => (
                <label
                  key={opt.value}
                  className="flex items-center gap-2 text-sm hover:bg-neutral-50 px-1 py-0.5 rounded cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={form.applicableProductCategories.includes(opt.value)}
                    onChange={(e) => {
                      const current = form.applicableProductCategories
                      if (e.target.checked) {
                        setForm({
                          ...form,
                          applicableProductCategories: [...current, opt.value],
                        })
                      } else {
                        setForm({
                          ...form,
                          applicableProductCategories: current.filter((id) => id !== opt.value),
                        })
                      }
                    }}
                    className="rounded border-neutral-300 text-primary-600 focus:ring-primary-500"
                  />
                  <span
                    className="text-neutral-700"
                    style={{ paddingLeft: `${opt.indent * 12}px` }}
                  >
                    {opt.label.trim()}
                  </span>
                </label>
              ))}
              {catOptions.length === 0 && (
                <p className="text-neutral-400 text-xs py-1">暂无商品分类</p>
              )}
            </div>
            <p className="text-xs text-neutral-400">不选则适用所有商品分类</p>
          </div>
        </div>
      </Modal>

      {/* 删除确认对话框 */}
      <Modal
        open={deleteConfirmOpen}
        onClose={() => setDeleteConfirmOpen(false)}
        title="确认删除"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteConfirmOpen(false)}>
              取消
            </Button>
            <Button variant="danger" onClick={confirmDelete}>
              确定
            </Button>
          </>
        }
      >
        <p className="text-neutral-600 text-sm leading-relaxed">
          删除后，当用户再购买已关联当前加工项的商品时，将不会再看到当前加工项。确定要删除当前加工项吗？
        </p>
      </Modal>
    </div>
  )
}
