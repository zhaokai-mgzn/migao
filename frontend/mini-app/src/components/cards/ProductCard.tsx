import { View, Text, Image } from '@tarojs/components'
import Taro from '@tarojs/taro'
import './ProductCard.scss'

interface ProductCardProps {
  data: {
    product_id?: string
    id?: string
    name: string
    price: number | string
    image?: string
    main_image?: string
    images?: string[]
    sales_count?: number
    description?: string
  }
}

/** 默认占位图 */
const PLACEHOLDER_IMAGE = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iODAiIGhlaWdodD0iODAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjgwIiBoZWlnaHQ9IjgwIiBmaWxsPSIjRjNGNEY2Ii8+PHRleHQgeD0iNDAiIHk9IjQ0IiBmb250LXNpemU9IjEyIiBmaWxsPSIjOUNBM0FGIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj7llYblk4E8L3RleHQ+PC9zdmc+'

export default function ProductCard({ data }: ProductCardProps) {
  const imageUrl = data.image || data.main_image || (data.images && data.images[0]) || PLACEHOLDER_IMAGE
  const price = typeof data.price === 'number' ? data.price.toFixed(2) : data.price || '0.00'

  const handleViewDetail = () => {
    Taro.showToast({ title: '功能开发中', icon: 'none' })
  }

  const handleConsult = () => {
    Taro.showToast({ title: '功能开发中', icon: 'none' })
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
          <Text className='product-card__price'>¥{price}</Text>
          {data.sales_count !== undefined && data.sales_count !== null && (
            <Text className='product-card__sales'>销量: {data.sales_count}</Text>
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
        <View className='product-card__btn product-card__btn--primary' onClick={handleConsult}>
          <Text className='product-card__btn-text product-card__btn-text--primary'>咨询客服</Text>
        </View>
      </View>
    </View>
  )
}
