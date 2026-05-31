'use client'

import { ShoppingBag } from 'lucide-react'
import Image from 'next/image'
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

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-shadow">
      <div className="flex gap-3 p-3">
        {/* 商品图片 */}
        <div className="w-16 h-16 flex-shrink-0 rounded-lg bg-gray-100 overflow-hidden flex items-center justify-center">
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
            <ShoppingBag className="w-6 h-6 text-gray-300" />
          )}
        </div>

        {/* 商品信息 */}
        <div className="flex-1 min-w-0">
          <h4 className="text-sm font-medium text-gray-800 truncate">{name}</h4>
          
          {/* 规格 */}
          {Object.keys(specs).length > 0 && (
            <div className="flex flex-wrap gap-1 mt-1">
              {Object.entries(specs).slice(0, 3).map(([key, value]) => (
                <span
                  key={key}
                  className="text-[10px] px-1.5 py-0.5 bg-gray-50 text-gray-500 border border-gray-100 rounded"
                >
                  {key}: {value}
                </span>
              ))}
            </div>
          )}

          {description && (
            <p className="text-[11px] text-gray-400 mt-1 line-clamp-1">{description}</p>
          )}

          {/* 价格 */}
          <div className="flex items-baseline gap-1 mt-1.5">
            <span className="text-sm font-bold text-red-500">¥{price.toFixed(2)}</span>
            <span className="text-[10px] text-gray-400">/{unit}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
