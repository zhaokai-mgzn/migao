'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { Button, Input, Select } from '@/components/ui'
import ImageUploader from './ImageUploader'
import { categoryApi, processingItemApi } from '@/lib/api'
import { toast } from 'sonner'
import type {
  ProductFormData,
  ProductStatus,
  PricingType,
  Category,
  ProcessingItem,
} from '@/types'
import { PricingTypeLabels } from '@/types'

interface ProductFormProps {
  initialData?: Partial<ProductFormData>
  onSubmit: (data: ProductFormData) => Promise<void>
  submitText?: string
}

// Flatten category tree for select options
function flattenCategories(categories: Category[], level = 0): { value: string; label: string }[] {
  const result: { value: string; label: string }[] = []
  for (const cat of categories) {
    const prefix = '\u00A0\u00A0'.repeat(level)
    result.push({ value: cat.id, label: `${prefix}${level > 0 ? '└ ' : ''}${cat.name}` })
    if (cat.children && cat.children.length > 0) {
      result.push(...flattenCategories(cat.children, level + 1))
    }
  }
  return result
}

export default function ProductForm({ initialData, onSubmit, submitText = '保存' }: ProductFormProps) {
  const router = useRouter()
  const [submitting, setSubmitting] = useState(false)
  const [categories, setCategories] = useState<Category[]>([])
  const [processingItems, setProcessingItems] = useState<ProcessingItem[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})

  const [form, setForm] = useState<ProductFormData>({
    name: '',
    sku: '',
    brand: '',
    categoryId: '',
    description: '',
    pricingType: 'fixed',
    price: 0,
    costPrice: undefined,
    unit: '件',
    status: 'draft' as ProductStatus,
    images: [],
    detailImages: [],
    specifications: {},
    processingItems: [],
    ...initialData,
  })

  // Load categories and processing items
  useEffect(() => {
    const loadData = async () => {
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
    loadData()
  }, [])

  // Sync initialData when editing
  useEffect(() => {
    if (initialData) {
      setForm((prev) => ({ ...prev, ...initialData }))
    }
  }, [initialData])

  const updateField = <K extends keyof ProductFormData>(key: K, value: ProductFormData[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    if (errors[key]) {
      setErrors((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
    }
  }

  const validate = (): boolean => {
    const newErrors: Record<string, string> = {}
    if (!form.name.trim()) newErrors.name = '请输入商品名称'
    if (!form.categoryId) newErrors.categoryId = '请选择分类'
    if (form.price <= 0) newErrors.price = '价格必须大于 0'
    if (!form.unit.trim()) newErrors.unit = '请输入单位'
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async () => {
    if (!validate()) return
    setSubmitting(true)
    try {
      await onSubmit(form)
      toast.success('保存成功')
      router.push('/products')
    } catch {
      // Error handled by API layer
    } finally {
      setSubmitting(false)
    }
  }

  const pricingTypeOptions = Object.entries(PricingTypeLabels).map(([value, label]) => ({
    value,
    label,
  }))

  const statusOptions = [
    { value: 'draft', label: '草稿' },
    { value: 'on_sale', label: '上架' },
    { value: 'off_sale', label: '下架' },
  ]

  const unitOptions = [
    { value: '米', label: '米' },
    { value: '片', label: '片' },
    { value: '件', label: '件' },
    { value: '平方米', label: '平方米' },
    { value: '套', label: '套' },
  ]

  const categoryOptions = flattenCategories(categories)

  const handleProcessingToggle = (itemId: string) => {
    const current = form.processingItems || []
    if (current.includes(itemId)) {
      updateField('processingItems', current.filter((id) => id !== itemId))
    } else {
      updateField('processingItems', [...current, itemId])
    }
  }

  return (
    <div className="max-w-4xl mx-auto">
      {/* Basic Info */}
      <div className="p-6 border-b border-gray-200">
        <h3 className="text-base font-semibold text-gray-900 mb-4">基本信息</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Input
            label="商品名称"
            required
            placeholder="请输入商品名称"
            value={form.name}
            onChange={(e) => updateField('name', e.target.value)}
            error={errors.name}
          />
          <Input
            label="SKU"
            placeholder="商品编码"
            value={form.sku || ''}
            onChange={(e) => updateField('sku', e.target.value)}
          />
          <Select
            label="商品分类"
            required
            options={categoryOptions}
            placeholder="请选择分类"
            value={form.categoryId}
            onChange={(e) => updateField('categoryId', e.target.value)}
            error={errors.categoryId}
          />
          <Input
            label="品牌"
            placeholder="品牌名称（可选）"
            value={form.brand || ''}
            onChange={(e) => updateField('brand', e.target.value)}
          />
          <div className="col-span-1 md:col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1.5">商品描述</label>
            <textarea
              className="w-full px-3 py-2 rounded border border-gray-300 bg-white text-sm placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
              rows={3}
              placeholder="请输入商品描述"
              value={form.description || ''}
              onChange={(e) => updateField('description', e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Pricing */}
      <div className="p-6 border-b border-gray-200">
        <h3 className="text-base font-semibold text-gray-900 mb-4">价格信息</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <Select
            label="计价方式"
            options={pricingTypeOptions}
            value={form.pricingType || 'fixed'}
            onChange={(e) => updateField('pricingType', e.target.value as PricingType)}
          />
          <Input
            label="单价（元）"
            required
            type="number"
            step="0.01"
            min="0"
            placeholder="0.00"
            value={form.price > 0 ? String(form.price) : ''}
            onChange={(e) => updateField('price', parseFloat(e.target.value) || 0)}
            error={errors.price}
          />
          <Input
            label="成本价（元）"
            type="number"
            step="0.01"
            min="0"
            placeholder="可选"
            value={form.costPrice ? String(form.costPrice) : ''}
            onChange={(e) => updateField('costPrice', parseFloat(e.target.value) || undefined)}
          />
          <Select
            label="单位"
            required
            options={unitOptions}
            value={form.unit}
            onChange={(e) => updateField('unit', e.target.value)}
            error={errors.unit}
          />
        </div>
      </div>

      {/* Images */}
      <div className="p-6 border-b border-gray-200">
        <h3 className="text-base font-semibold text-gray-900 mb-4">图片管理</h3>
        <div className="space-y-4">
          <ImageUploader
            label="商品主图"
            value={form.images}
            onChange={(urls) => updateField('images', urls)}
            max={1}
            hint="建议尺寸 800x800，支持 JPG/PNG，不超过 5MB"
          />
          <ImageUploader
            label="详情图"
            value={form.detailImages || []}
            onChange={(urls) => updateField('detailImages', urls)}
            max={9}
            multiple
            hint="最多 9 张，可拖拽排序"
          />
        </div>
      </div>

      {/* Processing items */}
      {processingItems.length > 0 && (
        <div className="p-6 border-b border-gray-200">
          <h3 className="text-base font-semibold text-gray-900 mb-4">加工项配置</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
            {processingItems.map((item) => {
              const isChecked = (form.processingItems || []).includes(item.id)
              return (
                <label
                  key={item.id}
                  className={`flex items-center gap-2 p-3 rounded-lg border cursor-pointer transition-colors ${
                    isChecked ? 'border-primary-500 bg-primary-50' : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={isChecked}
                    onChange={() => handleProcessingToggle(item.id)}
                    className="rounded border-gray-300 text-primary-600 focus:ring-primary-500"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-900 truncate">{item.name}</div>
                    <div className="text-xs text-gray-500">
                      ¥{item.basePrice}/{item.unit}
                    </div>
                  </div>
                </label>
              )
            })}
          </div>
        </div>
      )}

      {/* Status */}
      <div className="p-6 border-b border-gray-200">
        <h3 className="text-base font-semibold text-gray-900 mb-4">状态设置</h3>
        <div className="max-w-xs">
          <Select
            label="商品状态"
            options={statusOptions}
            value={form.status}
            onChange={(e) => updateField('status', e.target.value as ProductStatus)}
          />
        </div>
      </div>

      {/* Actions */}
      <div className="p-6 flex items-center justify-end gap-3">
        <Button variant="secondary" onClick={() => router.back()}>
          取消
        </Button>
        <Button onClick={handleSubmit} loading={submitting}>
          {submitText}
        </Button>
      </div>
    </div>
  )
}
