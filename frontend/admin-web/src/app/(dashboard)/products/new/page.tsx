'use client'

import ProductForm from '@/components/products/ProductForm'
import { productApi } from '@/lib/api'
import type { ProductFormData } from '@/types'

export default function NewProductPage() {
  const handleSubmit = async (data: ProductFormData) => {
    await productApi.createProduct(data)
  }

  return <ProductForm onSubmit={handleSubmit} submitText="提交并上架" />
}
