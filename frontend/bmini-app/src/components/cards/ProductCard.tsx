import { useState } from 'react'
import { View, Text, Image } from '@tarojs/components'
import './ProductCard.scss'

interface ProductCardProps {
  data: {
    product_id?: string
    id?: string
    name: string
    price: number | string
    /** 划线原价（展示「预计到手」时用） */
    original_price?: number | string
    /** 规格对象（瑞幸式规格行：颜色/门幅/售卖方式等） */
    specifications?: Record<string, any>
    /** 预格式化规格文本（后端已拼好时优先） */
    spec_line?: string
    image?: string
    main_image?: string
    images?: string[]
    sales_count?: number
    description?: string
  }
  /** 点击「查看」回调（issue #7264）：把商品名带进对话，让黄金策介绍商品（商家端不下单） */
  onView?: (productName: string) => void
}

/** 默认占位图 */
const PLACEHOLDER_IMAGE = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iODAiIGhlaWdodD0iODAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjgwIiBoZWlnaHQ9IjgwIiBmaWxsPSIjRjNGNEY2Ii8+PHRleHQgeD0iNDAiIHk9IjQ0IiBmb250LXNpemU9IjEyIiBmaWxsPSIjOUNBM0FGIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj7llYblk4E8L3RleHQ+PC9zdmc+'

/** 从 specifications 对象拼出规格行（优先 spec_line） */
function buildSpecLine(data: ProductCardProps['data']): string {
  if (data.spec_line) return data.spec_line
  const specs = data.specifications
  if (!specs) return ''
  const LABELS: Record<string, string> = {
    colorName: '颜色',
    color: '颜色',
    doorWidth: '门幅',
    width: '门幅',
    sellMethod: '售卖方式',
    sellingMethod: '售卖方式',
    curtainLength: '帘高',
    height: '高度',
  }
  const parts: string[] = []
  for (const [key, value] of Object.entries(specs)) {
    if (value == null || value === '') continue
    const label = LABELS[key]
    parts.push(label ? `${label} ${value}` : String(value))
  }
  return parts.join(' · ')
}

export default function ProductCard({ data, onView }: ProductCardProps) {
  // 查看防连点锁：点击后锁卡（issue #3040 收尾 #3038；issue #7264 改为「查看」语义）
  const [sent, setSent] = useState(false)
  const imageUrl = data.image || data.main_image || (data.images && data.images[0]) || PLACEHOLDER_IMAGE
  const price = typeof data.price === 'number' ? data.price.toFixed(2) : data.price || '0.00'
  const originalPrice =
    data.original_price !== undefined && data.original_price !== null && data.original_price !== ''
      ? typeof data.original_price === 'number'
        ? data.original_price.toFixed(2)
        : String(data.original_price)
      : ''
  const showOriginal = originalPrice !== '' && originalPrice !== price
  const specLine = buildSpecLine(data)

  const handleView = () => {
    if (sent) return
    setSent(true)
    onView?.(data.name || '这个商品')
  }

  const handleImageError = () => {
    // Image 组件不支持直接替换 src，错误时显示占位样式即可
  }

  return (
    <View className='product-card'>
      <View className='product-card__main'>
        <Image
          className='product-card__image'
          src={imageUrl}
          mode='aspectFill'
          onError={handleImageError}
        />
        <View className='product-card__info'>
          <Text className='product-card__name'>{data.name}</Text>

          {/* 规格行（瑞幸式：颜色/门幅/售卖方式等） */}
          {specLine && <Text className='product-card__spec'>{specLine}</Text>}

          <View className='product-card__price-row'>
            <Text className='product-card__price-unit'>¥</Text>
            <Text className='product-card__price'>{price}</Text>
            {showOriginal ? (
              <Text className='product-card__price-original'>¥{originalPrice}</Text>
            ) : null}
          </View>
          {showOriginal && (
            <Text className='product-card__price-hint'>预计到手</Text>
          )}
          {data.sales_count !== undefined && data.sales_count !== null && (
            <Text className='product-card__sales'>已售 {data.sales_count} 件</Text>
          )}
        </View>
      </View>

      {data.description && (
        <View className='product-card__desc'>
          <Text className='product-card__desc-text'>{data.description}</Text>
        </View>
      )}

      <View className='product-card__actions'>
        {/* issue #7264（用户 2026-10-18 逐字「商品列表控件带上了『去下单』按钮，这个不符合黄金策的
            定位和功能，可以改成查看」）：黄金策是商家经营助手，商家不是下单方 ⇒ 按钮 =「查看」，
            点击发 `查看<商品名>` 让 agent 在对话里介绍商品（与 PC 端商品卡的「查看商品」同口径）。
            issue #6666 判据 3 的「查看详情」死入口仍不复活：这里不是空 Toast，是真发消息。 */}
        <View className={`product-card__btn product-card__btn--primary${sent ? ' product-card__btn--locked' : ''}`} onClick={handleView}>
          <Text className='product-card__btn-text product-card__btn-text--primary'>查看</Text>
        </View>
      </View>
    </View>
  )
}
