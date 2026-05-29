'use client'

import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { ArrowLeft, Edit, ArrowUpCircle, ArrowDownCircle } from 'lucide-react'
import Image from 'next/image'
import { Button, Badge, Loading } from '@/components/ui'
import { productApi } from '@/lib/api'
import { toast } from 'sonner'
import type { Product, ProductStatus } from '@/types'
import { ProductStatusLabels, PricingTypeLabels } from '@/types'

export default function ProductDetailPage() {
  const params = useParams()
  const router = useRouter()
  const productId = params.id as string

  const [product, setProduct] = useState<Product | null>(null)
  const [loading, setLoading] = useState(true)
  const [previewImg, setPreviewImg] = useState<string | null>(null)

  useEffect(() => {
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

  const handleStatusChange = async (newStatus: ProductStatus) => {
    if (!product) return
    try {
      await productApi.updateProductStatus(product.id, newStatus)
      toast.success(newStatus === 'on_sale' ? '已上架' : '已下架')
      setProduct({ ...product, status: newStatus })
    } catch {
      // Error handled by API layer
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loading size="lg" text="加载中..." />
      </div>
    )
  }

  if (!product) return null

  const statusVariant: Record<ProductStatus, 'success' | 'default' | 'warning'> = {
    on_sale: 'success',
    off_sale: 'default',
    draft: 'warning',
    in_warehouse: 'default',
    under_review: 'warning',
  }

  const allImages = [...(product.images || []), ...(product.detailImages || [])]

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push('/products')}
            className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <h1 className="text-xl font-bold text-gray-900">{product.name}</h1>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant={statusVariant[product.status]}>
                {ProductStatusLabels[product.status]}
              </Badge>
              {product.sku && (
                <span className="text-sm text-gray-500 font-mono">SKU: {product.sku}</span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {product.status === 'on_sale' ? (
            <Button variant="secondary" onClick={() => handleStatusChange('off_sale')}>
              <ArrowDownCircle className="w-4 h-4 mr-1.5" />
              下架
            </Button>
          ) : (
            <Button variant="secondary" onClick={() => handleStatusChange('on_sale')}>
              <ArrowUpCircle className="w-4 h-4 mr-1.5" />
              上架
            </Button>
          )}
          <Button onClick={() => { window.location.href = `/products/${product.id}/edit` }}>
            <Edit className="w-4 h-4 mr-1.5" />
            编辑
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Images */}
        <div className="lg:col-span-1">
          <div className="bg-gray-50 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">商品图片</h3>
            {allImages.length > 0 ? (
              <div className="space-y-3">
                {/* Main image */}
                {product.images?.[0] && (
                  <div
                    className="w-full aspect-square rounded-lg overflow-hidden bg-white cursor-pointer"
                    onClick={() => setPreviewImg(product.images[0])}
                  >
                    <Image src={product.images[0]} alt={product.name} width={400} height={400} className="w-full h-full object-cover" unoptimized />
                  </div>
                )}
                {/* Detail images grid */}
                {(product.detailImages?.length ?? 0) > 0 && (
                  <div className="grid grid-cols-3 gap-2">
                    {product.detailImages!.map((url, i) => (
                      <div
                        key={i}
                        className="aspect-square rounded-md overflow-hidden bg-white cursor-pointer"
                        onClick={() => setPreviewImg(url)}
                      >
                        <Image src={url} alt={`详情图 ${i + 1}`} width={200} height={200} className="w-full h-full object-cover" unoptimized />
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div className="w-full aspect-square rounded-lg bg-gray-200 flex items-center justify-center text-gray-400">
                暂无图片
              </div>
            )}
          </div>
        </div>

        {/* Right: Info */}
        <div className="lg:col-span-2 space-y-6">
          {/* Basic info */}
          <div className="bg-gray-50 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">基本信息</h3>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
              <div>
                <dt className="text-xs text-gray-500">分类</dt>
                <dd className="text-sm text-gray-900 mt-0.5">{product.categoryName || '-'}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">品牌</dt>
                <dd className="text-sm text-gray-900 mt-0.5">{product.brand || '-'}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">计价方式</dt>
                <dd className="text-sm text-gray-900 mt-0.5">
                  {product.pricingType ? PricingTypeLabels[product.pricingType] : '-'}
                </dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">单价</dt>
                <dd className="text-sm font-medium text-gray-900 mt-0.5">
                  ¥{product.price.toFixed(2)}/{product.unit}
                </dd>
              </div>
              {product.costPrice !== undefined && (
                <div>
                  <dt className="text-xs text-gray-500">成本价</dt>
                  <dd className="text-sm text-gray-900 mt-0.5">¥{product.costPrice.toFixed(2)}</dd>
                </div>
              )}
              <div>
                <dt className="text-xs text-gray-500">库存</dt>
                <dd className="text-sm text-gray-900 mt-0.5">{product.stock ?? '-'}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">创建时间</dt>
                <dd className="text-sm text-gray-900 mt-0.5">{product.createdAt || '-'}</dd>
              </div>
              <div>
                <dt className="text-xs text-gray-500">更新时间</dt>
                <dd className="text-sm text-gray-900 mt-0.5">{product.updatedAt || '-'}</dd>
              </div>
            </dl>
          </div>

          {/* Description */}
          {product.description && (
            <div className="bg-gray-50 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">商品描述</h3>
              <p className="text-sm text-gray-600 whitespace-pre-wrap">{product.description}</p>
            </div>
          )}

          {/* Processing items */}
          {product.processingItems && product.processingItems.length > 0 && (
            <div className="bg-gray-50 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">加工项</h3>
              <div className="flex flex-wrap gap-2">
                {product.processingItems.map((itemId) => (
                  <Badge key={itemId} variant="info">{itemId}</Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Image preview */}
      {previewImg && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4 cursor-pointer"
          onClick={() => setPreviewImg(null)}
        >
          <Image src={previewImg} alt="预览" width={1200} height={900} className="max-w-full max-h-[85vh] object-contain rounded-lg" unoptimized />
        </div>
      )}
    </div>
  )
}
