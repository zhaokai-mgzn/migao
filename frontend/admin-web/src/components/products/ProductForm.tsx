'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Plus, Trash2, Truck } from 'lucide-react'
import { toast } from 'sonner'
import { Button, Input, Select } from '@/components/ui'
import ImageUploader from './ImageUploader'
import SkuMatrix from './SkuMatrix'
import ProductAttributes from './ProductAttributes'
import RichTextEditor from './RichTextEditor'
import { categoryApi, processingItemApi } from '@/lib/api'
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
} from '@/types'

interface ProductFormProps {
  initialData?: Partial<ProductFormData>
  /**
   * 表单提交回调。第二个参数为提交按钮决策的目标状态。
   * 父组件可在此完成 创建/更新 商品基础信息后再串联 SKU/颜色/属性 的持久化。
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

  const [form, setForm] = useState<ProductFormData>({
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
      } catch {
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
      { processingItemId: 0, customPrice: 0 } as ProductProcessingItemConfig,
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
    if (patch.processingItemId !== undefined) {
      const ref = processingItems.find(
        (p) => Number(p.id) === Number(patch.processingItemId)
      )
      merged = {
        ...merged,
        processingItemName: ref?.name,
        // 若用户尚未设置自定义价，则带入加工项基础价作为默认值
        customPrice:
          merged.customPrice && merged.customPrice > 0
            ? merged.customPrice
            : ref?.basePrice || 0,
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

  /** 滚动到第一个错误项 */
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

  /**
   * 校验表单。targetStatus 为 'draft' 时仅做最低限度校验。
   */
  const validate = (targetStatus: ProductStatus): boolean => {
    const errs: Record<string, string> = {}
    const isDraft = targetStatus === 'draft'

    if (!form.name.trim()) errs.name = '请输入商品标题'
    else if (form.name.length > TITLE_MAX)
      errs.name = `标题不超过 ${TITLE_MAX} 字`

    if (!isDraft) {
      if (!form.skuCode || !form.skuCode.trim()) errs.skuCode = '请输入货号'
      else if (form.skuCode.length > 30) errs.skuCode = '货号不超过 30 字'

      if (!form.unit) errs.unit = '请选择计价单位'
      if (!form.categoryId) errs.categoryId = '请选择商品分类'
      if (!form.images || form.images.length === 0)
        errs.images = '请至少上传 1 张商品主图'

      // SKU 维度
      if (!form.colors || form.colors.length === 0)
        errs.colors = '请至少添加 1 种颜色'
      else {
        const incomplete = form.colors.find(
          (c) => !c.colorName || !c.colorName.trim() || !c.colorImageUrl
        )
        if (incomplete) errs.colors = '颜色必须填写名称并上传图片'
      }
      if (!form.sellingMethods || form.sellingMethods.length === 0)
        errs.sellingMethods = '请至少添加 1 种售卖方式'
      if (!form.doorWidths || form.doorWidths.length === 0)
        errs.doorWidths = '请至少添加 1 种规格尺寸'

      // SKU 价格 / 库存
      if (
        form.colors &&
        form.colors.length > 0 &&
        form.sellingMethods &&
        form.sellingMethods.length > 0 &&
        form.doorWidths &&
        form.doorWidths.length > 0
      ) {
        const totalCells =
          form.colors.length * form.sellingMethods.length * form.doorWidths.length
        const list = form.skus || []
        const filled = list.filter(
          (s) => Number(s.price) > 0 && Number(s.stock) >= 0
        )
        const allValid =
          list.length >= totalCells &&
          list.every((s) => Number(s.price) > 0 && Number(s.stock) >= 0)
        if (!allValid || filled.length < totalCells)
          errs.skus = '请完整填写所有 SKU 的价格与库存'
      }

      if (form.supportsProcessing) {
        const cfg = form.processingItemConfigs || []
        if (
          cfg.length === 0 ||
          cfg.some((c) => !c.processingItemId || c.customPrice < 0)
        )
          errs.processingItemConfigs = '请至少配置 1 项加工项并填写价格'
      }
    }

    setErrors(errs)
    if (Object.keys(errs).length > 0) {
      scrollToFirstError(Object.keys(errs))
    }
    return Object.keys(errs).length === 0
  }

  // ========== 提交 ==========

  /**
   * 计算 SKU 矩阵的衍生价格作为兜底（SKU 最低价 → 表单 price 字段）
   */
  const derivePrice = (skus: ProductSku[] = []): number => {
    if (skus.length === 0) return form.price
    const positive = skus.map((s) => Number(s.price)).filter((p) => p > 0)
    if (positive.length === 0) return form.price
    return Math.min(...positive)
  }

  const handleSubmit = async (targetStatus: ProductStatus) => {
    if (!validate(targetStatus)) return
    setSubmitting(targetStatus)
    try {
      const payload: ProductFormData = {
        ...form,
        // 兼容老字段：sku 与 skuCode 同步
        sku: form.skuCode || form.sku,
        price: derivePrice(form.skus),
        status: targetStatus,
      }
      await onSubmit(payload, targetStatus)
      const labelMap: Record<ProductStatus, string> = {
        on_sale: '已上架',
        under_review: '已提交审核',
        in_warehouse: '已放入仓库',
        draft: '已存为草稿',
        off_sale: '已下架',
      }
      toast.success(labelMap[targetStatus])
      router.push('/products')
    } catch {
      // Error handled by API layer
    } finally {
      setSubmitting(null)
    }
  }

  // ========== 渲染 ==========

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
    <div ref={formRef} className="max-w-5xl mx-auto pb-28">
      {/* ============ 基础信息 ============ */}
      <Section title="基础信息" desc="商品标题、分类、主图与基础属性">
        <div className="space-y-5">
          {/* 标题 */}
          <div id={ANCHORS.name}>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-sm font-medium text-gray-700">
                商品标题<span className="text-red-500 ml-1">*</span>
              </label>
              <span
                className={`text-xs tabular-nums ${
                  titleCount > TITLE_MAX ? 'text-red-500' : 'text-gray-400'
                }`}
              >
                {titleCount}/{TITLE_MAX}
              </span>
            </div>
            <Input
              maxLength={TITLE_MAX}
              placeholder="请输入商品标题（最多 60 字）"
              value={form.name}
              onChange={(e) => updateField('name', e.target.value)}
              error={errors.name}
            />
          </div>

          {/* 分类 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div id={ANCHORS.categoryId}>
              <Select
                label="商品分类"
                required
                options={categoryOptions}
                placeholder="请选择分类"
                value={form.categoryId}
                onChange={(e) => updateField('categoryId', e.target.value)}
                error={errors.categoryId}
              />
            </div>
          </div>

          {/* 主图 / 详情图 */}
          <div id={ANCHORS.images} className="space-y-3">
            <ImageUploader
              label="商品主图 *"
              value={form.images}
              onChange={(urls) => updateField('images', urls)}
              max={5}
              multiple
              showOrderBadge
              confirmRemove
              hint="1-5 张，第 1 张为封面（可拖拽调整顺序）；支持 JPG / PNG / WEBP，单张不超过 5MB"
            />
            {errors.images && (
              <p className="text-sm text-red-600">{errors.images}</p>
            )}
            <ImageUploader
              label="详情图"
              value={form.detailImages || []}
              onChange={(urls) => updateField('detailImages', urls)}
              max={9}
              multiple
              hint="最多 9 张，可拖拽排序"
            />
          </div>

          {/* 商品描述（富文本） */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              商品描述
            </label>
            <RichTextEditor
              value={form.description || ''}
              onChange={(html) => updateField('description', html)}
              placeholder="图文介绍商品卖点、规格、使用场景等。支持加粗、标题、列表、图片、链接等"
              minHeight={300}
            />
            <p className="mt-1.5 text-xs text-gray-500">
              支持插入图片与链接；插入的图片将上传到 OSS
            </p>
          </div>
        </div>
      </Section>

      {/* ============ 商品属性 ============ */}
      <Section title="商品属性" desc="货号、品牌、计价单位与扩展属性">
        <div id={ANCHORS.skuCode}>
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
        </div>
      </Section>

      {/* ============ 销售信息 ============ */}
      <Section title="销售信息" desc="SKU 矩阵、库存策略与加工服务">
        <div className="space-y-6">
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

          {/* 库存扣减模式 */}
          <FieldRow label="库存扣减" required>
            <div className="space-y-2">
              <RadioGroup<StockDeductionMode>
                value={form.stockDeductionMode || 'on_place'}
                onChange={(v) => updateField('stockDeductionMode', v)}
                options={[
                  { value: 'on_place', label: '拍下减库存' },
                  { value: 'on_pay', label: '付款减库存' },
                ]}
              />
              <p className="text-xs text-gray-500">
                拍下减库存：买家下单时扣减库存；付款减库存：买家付款后扣减库存
              </p>
            </div>
          </FieldRow>

          {/* 加工服务 */}
          <FieldRow label="是否支持加工" required>
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
          </FieldRow>

          {form.supportsProcessing && (
            <div
              id={ANCHORS.processingItemConfigs}
              className="rounded-lg border border-gray-200 bg-gray-50/40 p-4 space-y-3"
            >
              <div className="flex items-center justify-between">
                <h5 className="text-sm font-medium text-gray-800">
                  加工项配置
                </h5>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={handleAddProcessingConfig}
                  type="button"
                >
                  <Plus className="w-4 h-4 mr-1" /> 添加加工项
                </Button>
              </div>
              {(form.processingItemConfigs || []).length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-3">
                  请添加至少 1 项加工项
                </p>
              ) : (
                <div className="space-y-2">
                  {(form.processingItemConfigs || []).map((cfg, idx) => (
                    <div
                      key={idx}
                      className="flex items-end gap-3 bg-white p-3 rounded border border-gray-200"
                    >
                      <div className="flex-1">
                        <Select
                          label="加工项"
                          options={[
                            { value: '', label: '请选择' },
                            ...processingItems.map((p) => ({
                              value: String(p.id),
                              label: `${p.name}（基础价 ¥${p.basePrice}/${p.unit}）`,
                            })),
                          ]}
                          value={
                            cfg.processingItemId
                              ? String(cfg.processingItemId)
                              : ''
                          }
                          onChange={(e) =>
                            handleUpdateProcessingConfig(idx, {
                              processingItemId: Number(e.target.value),
                            })
                          }
                        />
                      </div>
                      <div className="w-40">
                        <Input
                          label="自定义价格"
                          type="number"
                          min="0"
                          step="0.01"
                          placeholder="0.00"
                          value={
                            cfg.customPrice > 0 ? String(cfg.customPrice) : ''
                          }
                          onChange={(e) =>
                            handleUpdateProcessingConfig(idx, {
                              customPrice: parseFloat(e.target.value) || 0,
                            })
                          }
                        />
                        {(!cfg.customPrice || cfg.customPrice <= 0) && cfg.processingItemId > 0 && (() => {
                          const ref = processingItems.find(p => Number(p.id) === Number(cfg.processingItemId))
                          return ref ? (
                            <p className="text-xs text-gray-400 mt-1">使用默认价格: ¥{ref.basePrice}/{ref.unit}</p>
                          ) : null
                        })()}
                      </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRemoveProcessingConfig(idx)}
                        className="text-red-500 hover:text-red-600"
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}
              {errors.processingItemConfigs && (
                <p className="text-sm text-red-600">
                  {errors.processingItemConfigs}
                </p>
              )}
            </div>
          )}

          {/* 物流服务 */}
          <FieldRow label="物流服务">
            <span className="inline-flex items-center gap-1.5 text-sm text-gray-700 bg-gray-100 px-2.5 py-1 rounded">
              <Truck className="w-3.5 h-3.5" />
              邮费到付
            </span>
          </FieldRow>
        </div>
      </Section>

      {/* ============ 提交按钮 ============ */}
      <div className="fixed bottom-0 left-0 right-0 z-30 bg-white/95 backdrop-blur border-t border-gray-200 shadow-[0_-4px_12px_rgba(0,0,0,0.04)]">
        <div className="max-w-5xl mx-auto flex items-center justify-end gap-3 px-6 py-3">
          <Button
            variant="ghost"
            onClick={() => handleSubmit('draft')}
            loading={submitting === 'draft'}
            disabled={submitting !== null && submitting !== 'draft'}
          >
            存为草稿
          </Button>
          <Button
            variant="secondary"
            onClick={() => handleSubmit('in_warehouse')}
            loading={submitting === 'in_warehouse'}
            disabled={submitting !== null && submitting !== 'in_warehouse'}
          >
            放入仓库
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
  )
}

// ========== 辅助子组件 ==========

function Section({
  title,
  desc,
  children,
}: {
  title: string
  desc?: string
  children: React.ReactNode
}) {
  return (
    <section className="bg-white rounded-lg border border-gray-200 mb-5 overflow-hidden">
      <header className="px-6 py-4 border-b border-gray-100">
        <h3 className="text-base font-semibold text-gray-900 flex items-center gap-2">
          <span className="inline-block w-1 h-4 bg-primary-600 rounded" />
          {title}
        </h3>
        {desc && <p className="text-xs text-gray-500 mt-1 ml-3">{desc}</p>}
      </header>
      <div className="px-6 py-5">{children}</div>
    </section>
  )
}

function FieldRow({
  label,
  required,
  children,
}: {
  label: string
  required?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center gap-4">
      <label className="text-sm font-medium text-gray-700 w-28 shrink-0">
        {label}
        {required && <span className="text-red-500 ml-1">*</span>}
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
    <div className="flex flex-wrap items-center gap-4">
      {options.map((opt) => {
        const active = opt.value === value
        return (
          <label
            key={String(opt.value)}
            className={`inline-flex items-center gap-2 px-3 h-9 rounded border text-sm cursor-pointer transition-colors ${
              active
                ? 'border-primary-500 bg-primary-50 text-primary-700'
                : 'border-gray-300 text-gray-700 hover:border-gray-400'
            }`}
          >
            <span
              className={`w-3.5 h-3.5 rounded-full border ${
                active
                  ? 'border-primary-500 bg-primary-500 ring-2 ring-primary-100'
                  : 'border-gray-400'
              }`}
            />
            <input
              type="radio"
              className="sr-only"
              checked={active}
              onChange={() => onChange(opt.value)}
            />
            {opt.label}
          </label>
        )
      })}
    </div>
  )
}
