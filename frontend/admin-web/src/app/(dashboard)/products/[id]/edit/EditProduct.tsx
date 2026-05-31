'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import ProductForm from '@/components/products/ProductForm'
import { productApi } from '@/lib/api'
import { Loading } from '@/components/ui'
import { useRouteId } from '@/lib/use-route-id'
import { toast } from 'sonner'
import type { Product, ProductFormData } from '@/types'

export default function EditProductPage() {
  const router = useRouter()
  const productId = useRouteId('id')

  const [product, setProduct] = useState<Product | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!productId) return
    const loadProduct = async () => {
      setLoading(true)
      try {
        const res = await productApi.getProduct(productId)
        setProduct(res.data.data)
      } catch {
        toast.error('加载商品失败')
        router.push('/products')
      } finally {
        setLoading(false)
      }
    }
    loadProduct()
  }, [productId, router])

  const handleSubmit = async (data: ProductFormData) => {
    await productApi.updateProduct(productId, data)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loading size="lg" text="加载中..." />
      </div>
    )
  }

  if (!product) return null

  const initialData: Partial<ProductFormData> = {
    name: product.name,
    sku: product.sku,
    brand: product.brand,
    categoryId: product.categoryId,
    description: product.description,
    pricingType: product.pricingType,
    price: product.price,
    costPrice: product.costPrice,
    unit: product.unit,
    status: product.status,
    images: product.images || [],
    detailImages: product.detailImages || [],
    specifications: product.specifications,
    processingItems: product.processingItems,
    colors: product.colors || [],
    sellingMethods: product.sellingMethods || [],
    doorWidths: product.doorWidths || [],
    skus: product.skus || [],
  }

  return (
    <div>
      <div className="px-6 pt-6 pb-2">
        <h1 className="text-xl font-bold text-gray-900">编辑商品</h1>
        <p className="text-sm text-gray-500 mt-1">修改商品 {product.name} 的信息</p>
      </div>
      <ProductForm
        initialData={initialData}
        onSubmit={handleSubmit}
        submitText="保存修改"
      />
    </div>
  )
}
