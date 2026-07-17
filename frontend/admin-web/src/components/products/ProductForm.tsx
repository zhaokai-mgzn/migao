'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, Trash2, RotateCcw, Settings2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button, Input, Select, Modal, Loading } from '@/components/ui'
import ImageUploader from './ImageUploader'
import SkuMatrix from './SkuMatrix'
import ProductAttributes from './ProductAttributes'
import RichTextEditor from './RichTextEditor'
import CategoryTree from './CategoryTree'
import CategoryDialog from './CategoryDialog'
import { categoryApi, processingItemApi } from '@/lib/api'
import { validateProductForm, derivePrice } from '@/lib/product-utils'
import type {
  ProductFormData,
  ProductStatus,
  Category,
  ProcessingItem,
  ProductColor,
  ProductSku,
  SellingMethod,
  StockDeductionMode,
  ProductProcessingItemConfig,
  CategoryFormData,
} from '@/types'

interface ProductFormProps {
  initialData?: Partial<ProductFormData>
  /**
   * 表单提交回调。第二个参数为提交按钮决策的目标状态。
   */
  onSubmit: (data: ProductFormData, targetStatus: ProductStatus) => Promise<void>
  submitText?: string
}

// 字段在 DOM 中的可滚动锚点 ID
const ANCHORS = {
  name: 'pf-name',
  skuCode: 'pf-sku-code',
  unit: 'pf-unit',
  categoryId: 'pf-category',
  images: 'pf-images',
  colors: 'pf-colors',
  sellingMethods: 'pf-selling-methods',
  doorWidths: 'pf-door-widths',
  skus: 'pf-skus',
  processingItemConfigs: 'pf-processing',
} as const

// 扁平化分类树为下拉选项
function flattenCategories(
  categories: Category[],
  level = 0
): { value: string; label: string }[] {
  const result: { value: string; label: string }[] = []
  for (const cat of categories) {
    const prefix = '\u00A0\u00A0'.repeat(level)
    result.push({
      value: cat.id,
      label: `${prefix}${level > 0 ? '└ ' : ''}${cat.name}`,
    })
    if (cat.children && cat.children.length > 0) {
      result.push(...flattenCategories(cat.children, level + 1))
    }
  }
  return result
}

const TITLE_MAX = 60
const DEFAULT_FORM: ProductFormData = {
  name: '',
  sku: '',
  skuCode: '',
  brand: '',
  categoryId: '',
  description: '',
  pricingType: 'fixed',
  price: 0,
  costPrice: undefined,
  unit: '',
  stockDeductionMode: 'on_place',
  supportsProcessing: false,
  status: 'draft',
  images: [],
  detailImages: [],
  specifications: {},
  processingItems: [],
  colors: [],
  sellingMethods: [],
  doorWidths: [],
  skus: [],
  processingItemConfigs: [],
}

export default function ProductForm({
  initialData,
  onSubmit,
  submitText,
}: ProductFormProps) {
  const router = useRouter()
  const [submitting, setSubmitting] = useState<ProductStatus | null>(null)
  const [categories, setCategories] = useState<Category[]>([])
  const [processingItems, setProcessingItems] = useState<ProcessingItem[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const formRef = useRef<HTMLDivElement>(null)
  const isEdit = !!initialData

  // #1403: 管理分类弹窗状态
  const [catModalOpen, setCatModalOpen] = useState(false)
  const [catModalLoading, setCatModalLoading] = useState(false)
  const [editingCategory, setEditingCategory] = useState<Category | null>(null)
  const [catDialogOpen, setCatDialogOpen] = useState(false)
  const [presetParent, setPresetParent] = useState<Category | null>(null)
  const [catDeleteTarget, setCatDeleteTarget] = useState<Category | null>(null)
  const [catDeleting, setCatDeleting] = useState(false)

  const [form, setForm] = useState<ProductFormData>({
    ...DEFAULT_FORM,
    ...initialData,
  })

  // 加载分类与加工项
  useEffect(() => {
    const load = async () => {
      try {
        const [catRes, procRes] = await Promise.all([
          categoryApi.getCategories(),
          processingItemApi.getProcessingItems({ page: 1, size: 100 }),
        ])
        setCategories(catRes.data.data || [])
        setProcessingItems(procRes.data.data?.items || [])
      } catch (e) {
        // Errors handled by API layer
      }
    }
    load()
  }, [])

  // 编辑场景同步 initialData
  useEffect(() => {
    if (initialData) {
      setForm((prev) => ({ ...prev, ...initialData }))
    }
  }, [initialData])

  const updateField = <K extends keyof ProductFormData>(
    key: K,
    value: ProductFormData[K]
  ) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    if (errors[key]) {
      setErrors((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
    }
  }

  const updateMany = (patch: Partial<ProductFormData>) => {
    setForm((prev) => ({ ...prev, ...patch }))
    if (Object.keys(patch).some((k) => errors[k])) {
      setErrors((prev) => {
        const next = { ...prev }
        Object.keys(patch).forEach((k) => delete next[k])
        return next
      })
    }
  }

  const titleCount = form.name.length

  const categoryOptions = useMemo(
    () => flattenCategories(categories),
    [categories]
  )

  // ========== 加工项配置 ==========

  const handleAddProcessingConfig = () => {
    const next = [
      ...(form.processingItemConfigs || []),
      { processingItemId: null, customPrice: 0 } as ProductProcessingItemConfig,
    ]
    updateField('processingItemConfigs', next)
  }

  const handleUpdateProcessingConfig = (
    idx: number,
    patch: Partial<ProductProcessingItemConfig>
  ) => {
    const list = [...(form.processingItemConfigs || [])]
    const current = list[idx]
    if (!current) return
    let merged: ProductProcessingItemConfig = { ...current, ...patch }
    if (patch.processingItemId !== undefined && patch.processingItemId !== null) {
      // 加工项 ID 为字符串 UUID（如 "proc_item_punch_nano"），不能用 Number 转换
      const targetId = String(patch.processingItemId)
      const ref = processingItems.find((p) => String(p.id) === targetId)
      if (ref) {
        // 优先采用加工项基础价；仅当用户已显式输入大于 0 的自定义价时保留
        const hasCustomPrice =
          current.customPrice !== undefined &&
          current.customPrice !== null &&
          Number(current.customPrice) > 0
        const refPrice = Number(ref.unitPrice ?? ref.basePrice ?? 0) || 0
        merged = {
          ...merged,
          processingItemId: targetId,
          processingItemName: ref.name,
          customPrice: hasCustomPrice ? Number(current.customPrice) : refPrice,
        }
      }
    }
    list[idx] = merged
    updateField('processingItemConfigs', list)
  }

  const handleRemoveProcessingConfig = (idx: number) => {
    const list = [...(form.processingItemConfigs || [])]
    list.splice(idx, 1)
    updateField('processingItemConfigs', list)
  }

  // ========== 表单校验 ==========

  const scrollToFirstError = (errorKeys: string[]) => {
    for (const key of errorKeys) {
      const anchorId = ANCHORS[key as keyof typeof ANCHORS]
      if (!anchorId) continue
      const el = document.getElementById(anchorId)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        break
      }
    }
  }

  const validate = (targetStatus: ProductStatus): boolean => {
    const errs = validateProductForm(form, targetStatus)
    setErrors(errs)
    if (Object.keys(errs).length > 0) {
      scrollToFirstError(Object.keys(errs))
    }
    return Object.keys(errs).length === 0
  }

  // ========== 提交 ==========

  const handleSubmit = async (targetStatus: ProductStatus) => {
    if (!validate(targetStatus)) return
    setSubmitting(targetStatus)
    try {
      const payload: ProductFormData = {
        ...form,
        sku: form.skuCode || form.sku,
        // 过滤未选中的空占位值，保证后端拿到干净数据
        sellingMethods: (form.sellingMethods || []).filter(Boolean),
        doorWidths: (form.doorWidths || []).filter(Boolean),
        price: derivePrice(form.skus || [], form.price),
        status: targetStatus,
      }
      await onSubmit(payload, targetStatus)
      const labelMap: Record<ProductStatus, string> = {
        on_sale: '已上架',
        under_review: '已提交审核',
        draft: '已存为草稿',
        off_sale: '已下架',
      }
      toast.success(labelMap[targetStatus])
      router.push('/products')
    } catch (error) {
      console.error(`保存商品失败 (${targetStatus}):`, error)
      // Axios 错误已在 request.ts 响应拦截器中统一弹 toast，
      // 此处仅对非 Axios 错误（如 JS 异常）做兜底提示，避免重复弹框
      if (error instanceof Error && !(error as any).isAxiosError) {
        toast.error(error.message || '保存失败，请重试')
      }
    } finally {
      setSubmitting(null)
    }
  }

  // ========== 重置 ==========

  const handleReset = () => {
    if (!confirm('确定要重置当前表单吗？已填写的内容将被清空。')) return
    setForm({ ...DEFAULT_FORM, ...(initialData || {}) })
    setErrors({})
    toast.info('表单已重置')
  }

  // ========== 管理分类弹窗 (#1403) ==========

  const openCatModal = async () => {
    setCatModalOpen(true)
    setCatModalLoading(true)
    try {
      const res = await categoryApi.getCategories()
      setCategories(res.data.data || [])
    } catch (e) {
      // Error handled by API layer
    } finally {
      setCatModalLoading(false)
    }
  }

  const handleCatAdd = () => {
    setEditingCategory(null)
    setPresetParent(null)
    setCatDialogOpen(true)
  }

  const handleCatAddChild = (parent: Category) => {
    setEditingCategory(null)
    setPresetParent(parent)
    setCatDialogOpen(true)
  }

  const handleCatEdit = (category: Category) => {
    setEditingCategory(category)
    setPresetParent(null)
    setCatDialogOpen(true)
  }

  const handleCatSubmit = async (data: CategoryFormData) => {
    if (editingCategory) {
      await categoryApi.updateCategory(editingCategory.id, data)
      toast.success('分类已更新')
    } else {
      await categoryApi.createCategory({
        ...data,
        parentId: presetParent ? presetParent.id : data.parentId,
      })
      toast.success('分类已创建')
    }
    const res = await categoryApi.getCategories()
    setCategories(res.data.data || [])
  }

  const handleCatDelete = async () => {
    if (!catDeleteTarget) return
    setCatDeleting(true)
    try {
      await categoryApi.deleteCategory(catDeleteTarget.id)
      toast.success('分类已删除')
      setCatDeleteTarget(null)
      const res = await categoryApi.getCategories()
      setCategories(res.data.data || [])
    } catch (e) {
      // Error handled by API layer
    } finally {
      setCatDeleting(false)
    }
  }

  // ========== 总库存 ==========

  const totalStock = useMemo(() => {
    const list = form.skus || []
    return list.reduce((sum, s) => sum + (Number(s.stock) || 0), 0)
  }, [form.skus])

  // ========== SKU 子组件 ==========

  const skuValue = useMemo(
    () => ({
      colors: form.colors || [],
      sellingMethods: form.sellingMethods || [],
      doorWidths: form.doorWidths || [],
      skus: form.skus || [],
    }),
    [form.colors, form.sellingMethods, form.doorWidths, form.skus]
  )

  const handleSkuChange = (v: {
    colors: ProductColor[]
    sellingMethods: SellingMethod[]
    doorWidths: string[]
    skus: ProductSku[]
  }) => {
    updateMany({
      colors: v.colors,
      sellingMethods: v.sellingMethods,
      doorWidths: v.doorWidths,
      skus: v.skus,
    })
  }

  return (
    <div ref={formRef} className="max-w-6xl mx-auto pb-28">
      {/* ============ 顶部标题栏 ============ */}
      <div className="flex items-center justify-between px-6 py-4 mb-4 bg-white border border-gray-200 rounded-lg">
        <h2 className="text-lg font-semibold text-gray-900">
          {isEdit ? '编辑商品' : '新增商品'}
        </h2>
        <button
          type="button"
          onClick={handleReset}
          className="inline-flex items-center gap-1.5 px-3 h-8 text-sm text-gray-600 hover:text-primary-600 hover:bg-gray-50 rounded transition-colors"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          重置
        </button>
      </div>

      {/* ============ 基础信息 ============ */}
      <Section title="基础信息">
        <div className="space-y-5">
          {/* 商品分类 */}
          <FieldRow label="商品分类" required>
            <div className="flex items-center gap-2">
              <div id={ANCHORS.categoryId} className="max-w-md flex-1">
                <Select
                  options={categoryOptions}
                  placeholder="请选择"
                  value={form.categoryId}
                  onChange={(e) => updateField('categoryId', e.target.value)}
                  error={errors.categoryId}
                />
              </div>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={openCatModal}
              >
                <Settings2 className="w-3.5 h-3.5 mr-1" />
                管理分类
              </Button>
            </div>
          </FieldRow>

          {/* 商品标题 */}
          <FieldRow label="商品标题" required>
            <div id={ANCHORS.name} className="relative max-w-3xl">
              <Input
                maxLength={TITLE_MAX}
                placeholder="最多可输入50汉字（100字符）"
                value={form.name}
                onChange={(e) => updateField('name', e.target.value)}
                error={errors.name}
                className="pr-14"
              />
              <span
                className={`absolute right-3 top-2.5 text-xs tabular-nums pointer-events-none ${
                  titleCount > TITLE_MAX ? 'text-red-500' : 'text-gray-400'
                }`}
              >
                {titleCount}/{TITLE_MAX}
              </span>
            </div>
          </FieldRow>

          {/* 商品主图 */}
          <FieldRow label="商品主图" required alignTop>
            <div id={ANCHORS.images}>
              <p className="text-xs text-gray-500 mb-2">
                照片要求：比例为 1:1，像素尺寸 1440×1440 及以上；至多可上传 5 张，拖拽可调整顺序
              </p>
              <ImageUploader
                value={form.images}
                onChange={(urls) => updateField('images', urls)}
                max={5}
                multiple
                showOrderBadge
                confirmRemove
              />
              {errors.images && (
                <p className="text-sm text-red-600 mt-2">{errors.images}</p>
              )}
            </div>
          </FieldRow>

          {/* 商品属性 */}
          <FieldRow label="商品属性" alignTop>
            <ProductAttributes
              value={{
                skuCode: form.skuCode || '',
                brand: form.brand || '',
                unit: form.unit || '',
                specifications: form.specifications || {},
              }}
              onChange={(patch) => updateMany(patch)}
              errors={{ skuCode: errors.skuCode, unit: errors.unit }}
            />
          </FieldRow>
        </div>
      </Section>

      {/* ============ 销售信息 ============ */}
      <Section title="销售信息">
        <div className="space-y-7">
          <div id={ANCHORS.colors}>
            <div id={ANCHORS.sellingMethods} />
            <div id={ANCHORS.doorWidths} />
            <div id={ANCHORS.skus} />
            <SkuMatrix
              value={skuValue}
              onChange={handleSkuChange}
              errors={{
                colors: errors.colors,
                sellingMethods: errors.sellingMethods,
                doorWidths: errors.doorWidths,
                skus: errors.skus,
              }}
            />
          </div>

          {/* 总库存（只读） */}
          <FieldRow label="总库存" required alignTop>
            <div className="flex items-center gap-2">
              <div className="relative w-44">
                <input
                  readOnly
                  value={totalStock}
                  className="w-full h-9 px-3 pr-8 text-sm rounded border border-gray-200 bg-gray-50 text-gray-700 cursor-not-allowed"
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">
                  件
                </span>
              </div>
            </div>
            <p className="mt-1.5 text-xs text-gray-500">
              此处是商品所有销售规格总库存数量，若需修改请在销售规格表格内修改对应库存
            </p>
          </FieldRow>

          {/* 拍下减库存 */}
          <FieldRow label="拍下减库存" required alignTop>
            <RadioGroup<StockDeductionMode>
              value={form.stockDeductionMode || 'on_place'}
              onChange={(v) => updateField('stockDeductionMode', v)}
              options={[
                { value: 'on_place', label: '是' },
                { value: 'on_pay', label: '否（付款减库存）' },
              ]}
            />
          </FieldRow>

          {/* 是否支持加工 */}
          <FieldRow label="是否支持加工" required alignTop>
            <div className="space-y-3">
              <RadioGroup<boolean>
                value={!!form.supportsProcessing}
                onChange={(v) => {
                  updateField('supportsProcessing', v)
                  if (!v) updateField('processingItemConfigs', [])
                }}
                options={[
                  { value: true, label: '是' },
                  { value: false, label: '否' },
                ]}
              />
              {form.supportsProcessing && (
                <div id={ANCHORS.processingItemConfigs} className="space-y-2">
                  {(form.processingItemConfigs || []).map((cfg, idx) => (
                    <div key={idx} className="flex items-center gap-2">
                      <div className="w-56">
                        <Select
                          placeholder="请选择加工项"
                          options={processingItems.map((p) => ({
                            value: String(p.id),
                            label: `${p.name}（基础价 ¥${p.unitPrice ?? p.basePrice}/${p.unit}）`,
                          }))}
                          value={
                            cfg.processingItemId != null && cfg.processingItemId !== ''
                              ? String(cfg.processingItemId)
                              : ''
                          }
                          onChange={(e) =>
                            handleUpdateProcessingConfig(idx, {
                              processingItemId: e.target.value || null,
                            })
                          }
                        />
                      </div>
                      <div className="w-44">
                        <Input
                          type="number"
                          min="0"
                          step="0.01"
                          placeholder="请输入加工项价格"
                          value={
                            cfg.customPrice != null && Number(cfg.customPrice) > 0
                              ? String(cfg.customPrice)
                              : ''
                          }
                          onChange={(e) =>
                            handleUpdateProcessingConfig(idx, {
                              customPrice: parseFloat(e.target.value) || 0,
                            })
                          }
                        />
                      </div>
                      <button
                        type="button"
                        onClick={() => handleRemoveProcessingConfig(idx)}
                        className="w-9 h-9 inline-flex items-center justify-center rounded text-gray-400 hover:text-red-500 hover:bg-red-50"
                        title="删除"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                      {idx === (form.processingItemConfigs || []).length - 1 && (
                        <button
                          type="button"
                          onClick={handleAddProcessingConfig}
                          className="w-9 h-9 inline-flex items-center justify-center rounded border border-dashed border-gray-300 text-gray-500 hover:border-primary-400 hover:text-primary-600"
                          title="添加"
                        >
                          <Plus className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  ))}
                  {(form.processingItemConfigs || []).length === 0 && (
                    <div className="flex items-center gap-2">
                      <div className="w-56">
                        <Select
                          placeholder="请选择加工项"
                          options={processingItems.map((p) => ({
                            value: String(p.id),
                            label: `${p.name}（基础价 ¥${p.unitPrice ?? p.basePrice}/${p.unit}）`,
                          }))}
                          value=""
                          onChange={(e) => {
                            if (!e.target.value) return
                            const targetId = String(e.target.value)
                            const ref = processingItems.find(
                              (p) => String(p.id) === targetId
                            )
                            updateField('processingItemConfigs', [
                              {
                                processingItemId: targetId,
                                processingItemName: ref?.name,
                                customPrice:
                                  Number(ref?.unitPrice ?? ref?.basePrice ?? 0) || 0,
                              },
                            ])
                          }}
                        />
                      </div>
                      <div className="w-44">
                        <Input
                          disabled
                          placeholder="请输入加工项价格"
                          value=""
                          onChange={() => {}}
                        />
                      </div>
                      <button
                        type="button"
                        disabled
                        className="w-9 h-9 inline-flex items-center justify-center rounded text-gray-300 cursor-not-allowed"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                      <button
                        type="button"
                        onClick={handleAddProcessingConfig}
                        className="w-9 h-9 inline-flex items-center justify-center rounded border border-dashed border-gray-300 text-gray-500 hover:border-primary-400 hover:text-primary-600"
                        title="添加"
                      >
                        <Plus className="w-4 h-4" />
                      </button>
                    </div>
                  )}
                  {errors.processingItemConfigs && (
                    <p className="text-sm text-red-600">
                      {errors.processingItemConfigs}
                    </p>
                  )}
                </div>
              )}
            </div>
          </FieldRow>

          {/* 发货方式 */}
          <FieldRow label="发货方式">
            <span className="text-sm text-gray-600">
              物流发货 <span className="text-gray-400 mx-1">·</span> 邮费到付
            </span>
          </FieldRow>
        </div>
      </Section>

      {/* ============ 图文描述 ============ */}
      <Section title="图文描述">
        <FieldRow label="商品描述" alignTop>
          <RichTextEditor
            value={form.description || ''}
            onChange={(html) => updateField('description', html)}
            placeholder="图文介绍商品卖点、规格、使用场景等。支持加粗、标题、列表、图片、链接等"
            minHeight={300}
          />
          <p className="mt-1.5 text-xs text-gray-500">
            支持插入图片与链接；插入的图片将上传到 OSS
          </p>
        </FieldRow>

        <div className="mt-5">
          <FieldRow label="详情图" alignTop>
            <ImageUploader
              value={form.detailImages || []}
              onChange={(urls) => updateField('detailImages', urls)}
              max={9}
              multiple
              hint="最多 9 张，可拖拽排序"
            />
          </FieldRow>
        </div>
      </Section>

      {/* ============ 底部固定操作栏 ============ */}
      <div className="fixed bottom-0 left-0 right-0 z-30 bg-white/95 backdrop-blur border-t border-gray-200 shadow-[0_-4px_12px_rgba(0,0,0,0.04)]">
        <div className="max-w-6xl mx-auto flex items-center justify-between gap-3 px-6 py-3">
          <button
            type="button"
            onClick={handleReset}
            className="inline-flex items-center gap-1.5 px-3 h-9 text-sm text-gray-600 hover:text-primary-600 hover:bg-gray-50 rounded transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            重置
          </button>
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              onClick={() => handleSubmit('draft')}
              loading={submitting === 'draft'}
              disabled={submitting !== null && submitting !== 'draft'}
            >
              存草稿
            </Button>
            <Button
              onClick={() => handleSubmit('on_sale')}
              loading={submitting === 'on_sale'}
              disabled={submitting !== null && submitting !== 'on_sale'}
            >
              {submitText || '提交并上架'}
            </Button>
          </div>
        </div>
      </div>

      {/* ============ 管理分类弹窗 (#1403) ============ */}
      <Modal
        open={catModalOpen}
        onClose={() => setCatModalOpen(false)}
        title="分类管理"
        width={640}
        footer={
          <Button variant="secondary" onClick={() => setCatModalOpen(false)}>
            关闭
          </Button>
        }
      >
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-sm text-gray-500">管理商品分类，最多支持二级分类</p>
            <Button onClick={handleCatAdd} size="sm">
              <Plus className="w-4 h-4 mr-1" />
              添加分类
            </Button>
          </div>
          <div className="bg-gray-50 rounded-lg border border-gray-200 p-4 max-h-96 overflow-y-auto">
            {catModalLoading ? (
              <div className="py-12">
                <Loading text="加载中..." />
              </div>
            ) : categories.length === 0 ? (
              <div className="py-12 text-center text-sm text-gray-500">
                暂无分类，点击 &ldquo;添加分类&rdquo; 创建第一个分类
              </div>
            ) : (
              <CategoryTree
                categories={categories}
                onEdit={handleCatEdit}
                onDelete={setCatDeleteTarget}
                onAddChild={handleCatAddChild}
              />
            )}
          </div>
        </div>
      </Modal>

      {/* 添加/编辑分类子弹窗 */}
      <CategoryDialog
        open={catDialogOpen}
        onClose={() => setCatDialogOpen(false)}
        onSubmit={handleCatSubmit}
        category={editingCategory}
        categories={categories}
        presetParentId={presetParent?.id}
      />

      {/* 删除确认 */}
      <Modal
        open={!!catDeleteTarget}
        onClose={() => setCatDeleteTarget(null)}
        title="确认删除"
        footer={
          <>
            <Button variant="secondary" onClick={() => setCatDeleteTarget(null)} disabled={catDeleting}>
              取消
            </Button>
            <Button variant="danger" onClick={handleCatDelete} loading={catDeleting}>
              确认删除
            </Button>
          </>
        }
      >
        <p className="text-gray-600">
          确定要删除分类 <span className="font-medium text-gray-900">{catDeleteTarget?.name}</span> 吗？
          {catDeleteTarget?.children && catDeleteTarget.children.length > 0 && (
            <span className="block mt-2 text-amber-600">
              该分类下还有 {catDeleteTarget.children.length} 个子分类，删除后子分类也将被移除。
            </span>
          )}
        </p>
      </Modal>
    </div>
  )
}

// ========== 辅助子组件 ==========

function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="bg-white rounded-lg border border-gray-200 mb-5 overflow-hidden">
      <header className="px-6 py-3.5 border-b border-gray-100">
        <h3 className="text-base font-semibold text-gray-900 flex items-center gap-2">
          <span className="inline-block w-1 h-4 bg-primary-600 rounded" />
          {title}
        </h3>
      </header>
      <div className="px-6 py-5">{children}</div>
    </section>
  )
}

function FieldRow({
  label,
  required,
  alignTop,
  children,
}: {
  label: string
  required?: boolean
  alignTop?: boolean
  children: React.ReactNode
}) {
  return (
    <div className={`flex gap-4 ${alignTop ? 'items-start' : 'items-center'}`}>
      <label
        className={`shrink-0 w-28 text-sm text-gray-700 text-right ${
          alignTop ? 'pt-2' : ''
        }`}
      >
        {required && <span className="text-red-500 mr-0.5">*</span>}
        {label}
      </label>
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  )
}

interface RadioOption<T> {
  value: T
  label: string
}

function RadioGroup<T extends string | number | boolean>({
  value,
  onChange,
  options,
}: {
  value: T
  onChange: (v: T) => void
  options: RadioOption<T>[]
}) {
  return (
    <div className="flex flex-wrap items-center gap-5 pt-2">
      {options.map((opt) => {
        const active = opt.value === value
        return (
          <label
            key={String(opt.value)}
            className="inline-flex items-center gap-1.5 text-sm cursor-pointer"
          >
            <span
              className={`w-4 h-4 rounded-full border flex items-center justify-center transition-colors ${
                active
                  ? 'border-primary-500'
                  : 'border-gray-300'
              }`}
            >
              {active && (
                <span className="w-2 h-2 rounded-full bg-primary-500" />
              )}
            </span>
            <input
              type="radio"
              className="sr-only"
              checked={active}
              onChange={() => onChange(opt.value)}
            />
            <span className={active ? 'text-gray-800' : 'text-gray-600'}>
              {opt.label}
            </span>
          </label>
        )
      })}
    </div>
  )
}
