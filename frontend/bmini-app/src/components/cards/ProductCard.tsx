import { View, Text, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
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
  /** 点击「去下单」回调：把商品名带入对话下单流程 */
  onOrder?: (productName: string) => void
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

export default function ProductCard({ data, onOrder }: ProductCardProps) {
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

  const handleViewDetail = () => {
    Taro.showToast({ title: '功能开发中', icon: 'none' })
  }

  const handleOrder = () => {
    onOrder?.(data.name || '这个商品')
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
        <View className='product-card__btn product-card__btn--outline' onClick={handleViewDetail}>
          <Text className='product-card__btn-text product-card__btn-text--outline'>查看详情</Text>
        </View>
        <View className='product-card__btn product-card__btn--primary' onClick={handleOrder}>
          <Text className='product-card__btn-text product-card__btn-text--primary'>去下单</Text>
        </View>
      </View>
    </View>
  )
}
