'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Plus, X } from 'lucide-react'
import Image from 'next/image'
import { toast } from 'sonner'
import { productApi, categoryApi } from '@/lib/api'
import { Button, Input, Select } from '@/components/ui'
import type { Category, ProductFormData } from '@/types'

export default function CreateProductPage() {
  const router = useRouter()
  const [loading, setLoading] = useState(false)
  const [categories, setCategories] = useState<Category[]>([])
  const [formData, setFormData] = useState<ProductFormData>({
    name: '',
    categoryId: '',
    description: '',
    price: 0,
    unit: '米',
    status: 'off_sale',
    images: [],
    specifications: {},
  })
  const [errors, setErrors] = useState<Record<string, string>>({})

  // 加载分类
  useEffect(() => {
    const loadCategories = async () => {
      try {
        const res = await categoryApi.getCategories()
        setCategories(res.data.data)
      } catch (error) {
        toast.error('加载分类失败')
      }
    }
    loadCategories()
  }, [])

  // 验证表单
  const validate = (): boolean => {
    const newErrors: Record<string, string> = {}
    
    if (!formData.name.trim()) {
      newErrors.name = '请输入商品名称'
    }
    if (!formData.categoryId) {
      newErrors.categoryId = '请选择商品分类'
    }
    if (formData.price <= 0) {
      newErrors.price = '价格必须大于0'
    }
    if (!formData.unit.trim()) {
      newErrors.unit = '请输入计价单位'
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  // 处理提交
  const handleSubmit = async (status: 'on_sale' | 'off_sale') => {
    if (!validate()) return

    setLoading(true)
    try {
      await productApi.createProduct({
        ...formData,
        status,
      })
      toast.success(status === 'on_sale' ? '商品已上架' : '商品已保存')
      router.push('/products')
    } catch (error) {
      toast.error('保存失败')
    } finally {
      setLoading(false)
    }
  }

  // 处理图片上传（占位）
  const handleImageUpload = () => {
    // 模拟上传，生成随机图片 URL
    const mockUrl = `https://picsum.photos/200/200?random=${Date.now()}`
    setFormData({
      ...formData,
      images: [...formData.images, mockUrl],
    })
  }

  // 删除图片
  const handleRemoveImage = (index: number) => {
    setFormData({
      ...formData,
      images: formData.images.filter((_, i) => i !== index),
    })
  }

  // 获取分类选项（扁平化）
  const getCategoryOptions = (): { value: string; label: string }[] => {
    const options: { value: string; label: string }[] = []
    
    const flatten = (cats: Category[], prefix = '') => {
      cats.forEach((cat) => {
        options.push({
          value: cat.id,
          label: prefix + cat.name,
        })
        if (cat.children && cat.children.length > 0) {
          flatten(cat.children, prefix + '  ')
        }
      })
    }
    
    flatten(categories)
    return options
  }

  return (
    <div className="p-6">
      {/* 返回按钮 */}
      <button
        onClick={() => router.back()}
        className="flex items-center text-gray-600 hover:text-gray-900 mb-6"
      >
        <ArrowLeft className="w-4 h-4 mr-1" />
        返回
      </button>

      {/* 页面标题 */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">新增商品</h1>
        <p className="text-sm text-gray-500 mt-1">
          填写商品信息，创建新商品
        </p>
      </div>

      {/* 表单 */}
      <div className="max-w-3xl bg-white rounded-lg border border-gray-200 p-6">
        <div className="space-y-6">
          {/* 商品名称 */}
          <Input
            label="商品名称"
            placeholder="请输入商品名称"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            error={errors.name}
            required
          />

          {/* 商品分类 */}
          <Select
            label="商品分类"
            placeholder="请选择分类"
            options={getCategoryOptions()}
            value={formData.categoryId}
            onChange={(e) => setFormData({ ...formData, categoryId: e.target.value })}
            error={errors.categoryId}
            required
          />

          {/* 商品图片 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              商品图片
            </label>
            <div className="flex flex-wrap gap-3">
              {formData.images.map((url, index) => (
                <div key={index} className="relative w-20 h-20 rounded-lg overflow-hidden bg-gray-100">
                  <Image src={url} alt="" width={80} height={80} className="w-full h-full object-cover" unoptimized />
                  <button
                    onClick={() => handleRemoveImage(index)}
                    className="absolute top-0 right-0 p-1 bg-red-500 text-white rounded-bl-lg"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </div>
              ))}
              <button
                onClick={handleImageUpload}
                className="w-20 h-20 rounded-lg border-2 border-dashed border-gray-300 flex flex-col items-center justify-center text-gray-400 hover:border-primary-500 hover:text-primary-500 transition-colors"
              >
                <Plus className="w-6 h-6" />
                <span className="text-xs mt-1">上传</span>
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-2">
              建议尺寸 800×800，支持 JPG/PNG 格式
            </p>
          </div>

          {/* 价格和单位 */}
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="价格"
              type="number"
              placeholder="请输入价格"
              value={formData.price || ''}
              onChange={(e) => setFormData({ ...formData, price: parseFloat(e.target.value) || 0 })}
              error={errors.price}
              required
            />
            <Input
              label="计价单位"
              placeholder="如：米、件、套"
              value={formData.unit}
              onChange={(e) => setFormData({ ...formData, unit: e.target.value })}
              error={errors.unit}
              required
            />
          </div>

          {/* 商品描述 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              商品描述
            </label>
            <textarea
              rows={4}
              className="w-full px-3 py-2 rounded border border-gray-300 text-sm placeholder:text-gray-400 focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15 resize-none"
              placeholder="请输入商品描述"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
            />
          </div>

          {/* 规格属性 */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              规格属性
            </label>
            <div className="bg-gray-50 rounded-lg p-4">
              <p className="text-sm text-gray-500">
                规格属性功能开发中，后续支持添加颜色、尺寸等规格
              </p>
            </div>
          </div>
        </div>

        {/* 底部操作 */}
        <div className="flex items-center justify-end gap-3 mt-8 pt-6 border-t border-gray-200">
          <Button variant="secondary" onClick={() => router.back()}>
            取消
          </Button>
          <Button
            variant="secondary"
            onClick={() => handleSubmit('off_sale')}
            loading={loading}
          >
            保存草稿
          </Button>
          <Button
            onClick={() => handleSubmit('on_sale')}
            loading={loading}
          >
            保存并上架
          </Button>
        </div>
      </div>
    </div>
  )
}
