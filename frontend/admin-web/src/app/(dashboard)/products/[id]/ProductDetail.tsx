'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, Edit, ArrowUpCircle, ArrowDownCircle } from 'lucide-react'
import Image from 'next/image'
import { Button, Badge, Loading } from '@/components/ui'
import { productApi } from '@/lib/api'
import request from '@/lib/request'
import { useRouteId } from '@/lib/use-route-id'
import { resolveImageUrl } from '@/lib/utils'

/** 行内编辑 SKU 价格 */
function SkuPriceCell({ productId, sku, onUpdated }: {
  productId: string; sku: any; onUpdated: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState('')
  const [loading, setLoading] = useState(false)

  const startEdit = () => {
    setValue(sku.price?.toString() || '')
    setEditing(true)
  }

  const save = async () => {
    const num = parseFloat(value)
    if (isNaN(num) || num < 0) { toast.error('请输入有效价格'); return }
    setLoading(true)
    try {
      await request.patch(`/api/admin/agent/products/${productId}/skus/${sku.id}`, { price: num })
      toast.success(`SKU 价格已更新`)
      setEditing(false)
      onUpdated()
    } catch (e: any) {
      toast.error(e?.response?.data?.error?.message || '更新失败')
    } finally { setLoading(false) }
  }

  if (editing) {
    return (
      <div className="flex items-center gap-1 justify-end">
        <input
          autoFocus
          type="number"
          step="0.01"
          className="w-20 h-7 px-1.5 text-xs border border-blue-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-400 text-right"
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEditing(false) }}
          onBlur={() => setEditing(false)}
          disabled={loading}
        />
      </div>
    )
  }

  const price = typeof sku.price === 'number' ? sku.price : null
  return (
    <button
      onClick={startEdit}
      className="hover:bg-blue-50 px-1.5 py-0.5 rounded transition-colors cursor-pointer"
      title="点击编辑价格"
    >
      {price != null ? `¥${price.toFixed(2)}` : '-'}
    </button>
  )
}
import { toast } from 'sonner'
import type { Product, ProductStatus, ProductSku } from '@/types'
import { ProductStatusLabels, PricingTypeLabels, SellingMethodLabels } from '@/types'

// specifications 中常见 key 的中文标签映射
const SPEC_LABELS: Record<string, string> = {
  weight: '克重',
  material: '材质',
  function: '功能',
  craft: '工艺',
  style: '风格',
  pattern: '图案',
  curtainType: '窗帘类型',
  fabric: '面料材质',
  shading: '遮光度',
  scene: '适用场景',
}

// 库存扣减方式：兼容后端 on_order/on_payment 与表单 on_place/on_pay 两套枚举
const STOCK_DEDUCTION_LABELS: Record<string, string> = {
  on_order: '拍下减库存',
  on_place: '拍下减库存',
  on_payment: '付款减库存',
  on_pay: '付款减库存',
}

/** 基础 HTML 消毒：移除 script 标签和事件处理器，防 XSS */
function sanitizeHtml(html: string): string {
  return html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/<script\b[^>]*\/>/gi, '')
    .replace(/\son\w+\s*=\s*"[^"]*"/gi, '')
    .replace(/\son\w+\s*=\s*'[^']*'/gi, '')
    .replace(/<iframe\b[^<]*(?:(?!<\/iframe>)<[^<]*)*<\/iframe>/gi, '')
    .replace(/javascript\s*:/gi, '')
}

export default function ProductDetailPage() {
  const router = useRouter()
  const productId = useRouteId('id')

  const [product, setProduct] = useState<Product | null>(null)
  const [loading, setLoading] = useState(true)
  const [previewImg, setPreviewImg] = useState<string | null>(null)

  const loadProduct = useCallback(async () => {
    if (!productId) return
    setLoading(true)
    try {
      const res = await productApi.getProduct(productId)
      setProduct(res.data.data)
    } catch (e) {
      toast.error('加载商品失败')
      router.push('/products')
    } finally {
      setLoading(false)
    }
  }, [productId, router])

  useEffect(() => { loadProduct() }, [loadProduct])

  const handleStatusChange = async (newStatus: ProductStatus) => {
    if (!product) return
    try {
      await productApi.updateProductStatus(product.id, newStatus)
      toast.success(newStatus === 'on_sale' ? '已上架' : '已下架')
      setProduct({ ...product, status: newStatus })
    } catch (e) {
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

  const statusVariant: Record<ProductStatus, 'success' | 'default' | 'warning' | 'info'> = {
    on_sale: 'success',
    off_sale: 'default',
    under_review: 'info',
    draft: 'warning',
  }

  const allImages = [...(product.images || []), ...(product.detailImages || [])]

  // 计价单位：优先 pricingUnit，其次 specifications.unit，再次 product.unit
  const priceUnit =
    product.pricingUnit ||
    (product.specifications && product.specifications.unit) ||
    product.unit ||
    ''
  const priceText = priceUnit
    ? `¥${product.price.toFixed(2)}/${priceUnit}`
    : `¥${product.price.toFixed(2)}`

  // 商品属性条目（过滤空值）
  const specEntries: Array<{ key: string; label: string; value: string }> = []
  const specs = product.specifications || {}
  // 优先按预定义 key 顺序展示
  const orderedKeys = Object.keys(SPEC_LABELS)
  const seen = new Set<string>()
  for (const k of orderedKeys) {
    const v = specs[k]
    if (v && String(v).trim()) {
      specEntries.push({ key: k, label: SPEC_LABELS[k], value: String(v) })
      seen.add(k)
    }
  }
  // 其他未识别的 key 原样展示（如 unit 等已在基本信息展示则跳过）
  const SKIP_SPEC_KEYS = new Set(['unit'])
  for (const [k, v] of Object.entries(specs)) {
    if (seen.has(k) || SKIP_SPEC_KEYS.has(k)) continue
    if (v && String(v).trim()) {
      specEntries.push({ key: k, label: k, value: String(v) })
    }
  }

  const skus: ProductSku[] = product.skus || []
  const stockDeductionLabel = product.stockDeductionMode
    ? STOCK_DEDUCTION_LABELS[product.stockDeductionMode]
    : undefined

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
          <Button onClick={() => router.push(`/products/${product.id}/edit`)}>
            <Edit className="w-4 h-4 mr-1.5" />
            编辑
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-6">
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
                <dd className="text-sm font-medium text-gray-900 mt-0.5">{priceText}</dd>
              </div>
              {product.costPrice !== undefined && (
                <div>
                  <dt className="text-xs text-gray-500">成本价</dt>
                  <dd className="text-sm text-gray-900 mt-0.5">¥{product.costPrice.toFixed(2)}</dd>
                </div>
              )}
              <div>
                <dt className="text-xs text-gray-500">库存</dt>
                <dd className="text-sm text-gray-900 mt-0.5">{product.totalStock ?? product.stock ?? '-'}</dd>
              </div>
              {stockDeductionLabel && (
                <div>
                  <dt className="text-xs text-gray-500">库存扣减方式</dt>
                  <dd className="text-sm text-gray-900 mt-0.5">{stockDeductionLabel}</dd>
                </div>
              )}
              {product.stockWarningThreshold != null && (
                <div>
                  <dt className="text-xs text-gray-500">库存预警阈值</dt>
                  <dd className="text-sm text-gray-900 mt-0.5">{product.stockWarningThreshold}</dd>
                </div>
              )}
              {product.skuCode && (
                <div>
                  <dt className="text-xs text-gray-500">货号</dt>
                  <dd className="text-sm text-gray-900 mt-0.5 font-mono">{product.skuCode}</dd>
                </div>
              )}
              <div>
                <dt className="text-xs text-gray-500">在售颜色</dt>
                <dd className="text-sm text-gray-900 mt-0.5">{product.colorCount ?? (product.colors?.length ?? '-')}</dd>
              </div>
              {product.salesCount != null && (
                <div>
                  <dt className="text-xs text-gray-500">累计销量</dt>
                  <dd className="text-sm text-gray-900 mt-0.5">{product.salesCount}</dd>
                </div>
              )}
              {product.salesAmount != null && (
                <div>
                  <dt className="text-xs text-gray-500">累计销售额</dt>
                  <dd className="text-sm text-gray-900 mt-0.5">¥{product.salesAmount.toFixed(2)}</dd>
                </div>
              )}
              {product.editedBy && (
                <div>
                  <dt className="text-xs text-gray-500">最后编辑人</dt>
                  <dd className="text-sm text-gray-900 mt-0.5">{product.editedBy}</dd>
                </div>
              )}
              {product.editedAt && (
                <div>
                  <dt className="text-xs text-gray-500">最后编辑时间</dt>
                  <dd className="text-sm text-gray-900 mt-0.5">{product.editedAt}</dd>
                </div>
              )}
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

          {/* 商品属性 */}
          {specEntries.length > 0 && (
            <div className="bg-gray-50 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-3">商品属性</h3>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
                {specEntries.map((item) => (
                  <div key={item.key}>
                    <dt className="text-xs text-gray-500">{item.label}</dt>
                    <dd className="text-sm text-gray-900 mt-0.5">{item.value}</dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          {/* 销售信息（SKU） */}
          {skus.length > 0 && (
            <div className="bg-gray-50 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-3">销售信息</h3>
              <div className="overflow-x-auto rounded-md border border-gray-200 bg-white">
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-50 text-gray-600">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium">颜色</th>
                      <th className="px-3 py-2 text-left font-medium">售卖方式</th>
                      <th className="px-3 py-2 text-left font-medium">门幅</th>
                      <th className="px-3 py-2 text-left font-medium">货号</th>
                      <th className="px-3 py-2 text-right font-medium">库存</th>
                      <th className="px-3 py-2 text-right font-medium">价格</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {skus.map((sku) => (
                      <tr key={sku.id} className="text-gray-900">
                        <td className="px-3 py-2">{sku.colorName || '-'}</td>
                        <td className="px-3 py-2">
                          {sku.sellingMethod ? SellingMethodLabels[sku.sellingMethod] || sku.sellingMethod : '-'}
                        </td>
                        <td className="px-3 py-2">{sku.doorWidth || '-'}</td>
                        <td className="px-3 py-2 font-mono text-xs">{sku.skuCode || '-'}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{sku.stock ?? '-'}</td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          <SkuPriceCell
                            productId={product.id}
                            sku={sku}
                            onUpdated={loadProduct}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 颜色列表 */}
          {product.colors && product.colors.length > 0 && (
            <div className="bg-gray-50 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-3">商品颜色</h3>
              <div className="flex flex-wrap gap-2">
                {product.colors.map((c) => (
                  <div
                    key={c.id}
                    className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-gray-200 bg-white text-sm"
                  >
                    {c.mainColorHex && (
                      <span
                        className="w-4 h-4 rounded-full border border-gray-300 shrink-0"
                        style={{ backgroundColor: c.mainColorHex }}
                      />
                    )}
                    <span>{c.colorName}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Processing items */}
          {product.processingItemConfigs && product.processingItemConfigs.length > 0 && (
            <div className="bg-gray-50 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">加工项</h3>
              <div className="space-y-2">
                {product.processingItemConfigs.map((cfg, idx) => (
                  <div key={idx} className="flex items-center justify-between text-sm">
                    <span className="font-medium text-gray-800">{cfg.processingItemName || '未知加工项'}</span>
                    <span className="text-blue-600 font-medium">¥{cfg.customPrice?.toFixed(2) || '0.00'}/米</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Description */}
          {product.description && (
            <div className="bg-gray-50 rounded-lg p-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">商品描述</h3>
              {/^\s*</.test(product.description) ? (
                <div
                  className="product-description text-sm text-gray-700 leading-relaxed"
                  dangerouslySetInnerHTML={{ __html: sanitizeHtml(product.description) }}
                />
              ) : (
                <p className="text-sm text-gray-600 whitespace-pre-wrap">{product.description}</p>
              )}
            </div>
          )}

          {/* 商品图片 */}
          <div className="bg-gray-50 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">商品图片</h3>
            {allImages.length > 0 ? (
              <div className="space-y-3">
                {/* Main image */}
                {product.images?.[0] && (
                  <div
                    className="w-full max-w-sm aspect-square rounded-lg overflow-hidden bg-white cursor-pointer"
                    onClick={() => setPreviewImg(product.images[0])}
                  >
                    <Image src={resolveImageUrl(product.images[0])} alt={product.name} width={400} height={400} className="w-full h-full object-cover" unoptimized />
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
                        <Image src={resolveImageUrl(url)} alt={`详情图 ${i + 1}`} width={200} height={200} className="w-full h-full object-cover" unoptimized />
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

      {/* Image preview */}
      {previewImg && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4 cursor-pointer"
          onClick={() => setPreviewImg(null)}
        >
          <Image src={resolveImageUrl(previewImg)} alt="预览" width={1200} height={900} className="max-w-full max-h-[85vh] object-contain rounded-lg" unoptimized />
        </div>
      )}
    </div>
  )
}
