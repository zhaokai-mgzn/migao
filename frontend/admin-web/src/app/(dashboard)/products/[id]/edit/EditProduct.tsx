'use client'

import { useCallback, useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import ProductForm from '@/components/products/ProductForm'
import { productApi } from '@/lib/api'
import { Button, Loading } from '@/components/ui'
import ListLoadError from '@/components/common/ListLoadError'
import { useRouteId } from '@/lib/use-route-id'
import { toEnglishSpecKeys } from '@/lib/attribute-keys'
import { toast } from 'sonner'
import type { Product, ProductFormData } from '@/types'

export default function EditProductPage() {
  const router = useRouter()
  const productId = useRouteId('id')

  const [product, setProduct] = useState<Product | null>(null)
  const [loading, setLoading] = useState(true)
  /**
   * 读失败标记（issue #8057，「四态契约」③）：修前 `catch` 是 `toast.error` + `router.push('/products')`，
   * 随即 `if (!product) return null` —— 失败被画成**整页空白**（没有一句话、没有重试出口）。
   */
  const [loadError, setLoadError] = useState(false)

  const loadProduct = useCallback(async () => {
    if (!productId) return
    setLoading(true)
    setLoadError(false)
    try {
      const res = await productApi.getProduct(productId)
      setProduct(res.data.data)
    } catch (e) {
      console.error('加载商品失败:', e)
      toast.error('加载商品失败')
      setLoadError(true)
    } finally {
      setLoading(false)
    }
  }, [productId])

  useEffect(() => {
    loadProduct()
  }, [loadProduct])

  const handleSubmit = async (data: ProductFormData) => {
    await productApi.updateProduct(productId, data)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loading size="lg" text="加载中…" />
      </div>
    )
  }

  if (!product) {
    // 失败 ≠ 不存在 ≠ 空白页（issue #8057）：失败时说「没读到」+ 给重试出口；
    // 只有**服务端明确没这只商品**时才说「不存在」。
    if (loadError) {
      return (
        <div className="p-6 space-y-4">
          <ListLoadError
            testId="edit-product-load-error"
            message="商品加载失败 —— 不是「商品不存在」，是没读到。表单没有回填，请重试。"
            onRetry={() => void loadProduct()}
            retrying={loading}
          />
          <Button variant="secondary" onClick={() => router.push('/products')}>返回商品列表</Button>
        </div>
      )
    }
    return (
      <div className="p-6 text-center py-12">
        <p className="text-neutral-500 mb-4">商品不存在或已被删除</p>
        <Button onClick={() => router.push('/products')}>返回商品列表</Button>
      </div>
    )
  }

  const initialData: Partial<ProductFormData> = {
    name: product.name,
    sku: product.sku,
    skuCode: product.skuCode,
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
    // 反显归一化：agent 落库为中文 key（克重/材质/...），编辑表单内部用英文 key
    // （weight/material/...），此处 中文→英文 保证 agent 建的商品编辑时属性正常回显
    // （issue #3044）
    specifications: toEnglishSpecKeys(product.specifications || {}),
    stockDeductionMode: (product.stockDeductionMode === 'on_order' ? 'on_place' : product.stockDeductionMode === 'on_payment' ? 'on_pay' : 'on_place') as ProductFormData['stockDeductionMode'],
    colors: product.colors || [],
    // 售卖方式（商品级基础属性）与 1 卷米数（商品货号级基础参数）—— 顶层字段，直接回显
    sellingMethods: product.sellingMethods || [],
    rollLengthM: product.rollLengthM ?? null,
    doorWidths: product.doorWidths || [],
    skus: product.skus || [],
  }

  return (
    <div>
      <ProductForm
        initialData={initialData}
        onSubmit={handleSubmit}
        submitText="保存修改"
      />
    </div>
  )
}
