'use client'

import ProductForm from '@/components/products/ProductForm'
import { productApi } from '@/lib/api'
import type { ProductFormData } from '@/types'

export default function NewProductPage() {
  const handleSubmit = async (data: ProductFormData) => {
    await productApi.createProduct(data)
  }

  return (
    <div>
      <div className="px-6 pt-6 pb-2">
        <h1 className="text-xl font-bold text-gray-900">添加商品</h1>
        <p className="text-sm text-gray-500 mt-1">填写商品信息并提交</p>
      </div>
      <ProductForm onSubmit={handleSubmit} submitText="提交并上架" />
    </div>
  )
}
