'use client'

import { ShoppingBag } from 'lucide-react'
import Image from 'next/image'
import Link from 'next/link'
import { resolveImageUrl } from '@/lib/utils'

interface ProductCardProps {
  data: Record<string, unknown>
}

export default function ProductCard({ data }: ProductCardProps) {
  const product = (data.product as Record<string, unknown>) || data
  const name = (product.name as string) || '未知商品'
  const price = Number(product.price || 0)
  const unit = (product.unit as string) || '件'
  const images = (product.images as string[]) || []
  const specs = (product.specifications as Record<string, string>) || {}
  const description = (product.description as string) || ''
  // 商品不可变标识（agent 侧只下发 id，路由由**本端**生成，见 #4016 P14 第四节）
  const productId = product.id ? String(product.id) : ''

  const content = (
    <div className="bg-white border border-neutral-200 rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow">
      <div className="flex gap-3 p-3">
        {/* 商品图片 */}
        <div className="w-16 h-16 flex-shrink-0 rounded-lg bg-neutral-100 overflow-hidden flex items-center justify-center">
          {images.length > 0 ? (
            <Image
              src={resolveImageUrl(images[0])}
              alt={name}
              width={64}
              height={64}
              className="w-full h-full object-cover"
              unoptimized
            />
          ) : (
            <ShoppingBag className="w-6 h-6 text-neutral-300" />
          )}
        </div>

        {/* 商品信息 */}
        <div className="flex-1 min-w-0">
          <h4 className="text-sm font-medium text-neutral-800 truncate">{name}</h4>
          
          {/* 规格 */}
          {Object.keys(specs).length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {Object.entries(specs).slice(0, 3).map(([key, value]) => (
                <span
                  key={key}
                  className="text-[10px] px-1.5 py-0.5 bg-neutral-50 text-neutral-500 border border-neutral-100 rounded"
                >
                  {key}: {value}
                </span>
              ))}
            </div>
          )}

          {description && (
            <p className="text-[11px] text-neutral-400 mt-1 line-clamp-1">{description}</p>
          )}

          {/* 价格 */}
          <div className="flex items-baseline gap-1 mt-1.5">
            <span className="text-sm font-bold text-red-500">¥{price.toFixed(2)}</span>
            <span className="text-[10px] text-neutral-400">/{unit}</span>
          </div>
        </div>
      </div>
    </div>
  )

  // 有商品 id 时整卡可点跳转商品详情（#4016 P14 ④：会话里的商品清单此前完全不可点，
  // 用户只能手打商品名）。⚠️ href **只**由工具结果真值 `product.id` 拼出 ——
  // 卡数据里任何 href/url/link 字段一律不采信（模型不得编造链接）。
  if (productId) {
    return (
      <Link
        href={`/products/${productId}`}
        className="block hover:opacity-90 transition-opacity"
        title={`查看商品 ${name}`}
      >
        {content}
      </Link>
    )
  }
  return content
}
