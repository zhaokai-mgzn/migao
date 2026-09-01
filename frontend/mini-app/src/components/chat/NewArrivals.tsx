import { View, Text, Image, ScrollView } from '@tarojs/components'
import { useCallback, useEffect, useState } from 'react'
import { getNewArrivals } from '../../services/productService'
import './NewArrivals.scss'

/** 新品推荐横滑卡片（空态欢迎屏）——主流 C 端客服"猜你喜欢/新品"位 */

interface ProductLite {
  id: string
  name: string
  price: number | string
  image?: string
  sales_count?: number
}

const PLACEHOLDER_IMAGE = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iODAiIGhlaWdodD0iODAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjgwIiBoZWlnaHQ9IjgwIiBmaWxsPSIjRjNGNEY2Ii8+PHRleHQgeD0iNDAiIHk9IjQ0IiBmb250LXNpemU9IjEyIiBmaWxsPSIjOUNBM0FGIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj7llYblk4E8L3RleHQ+PC9zdmc+'

interface NewArrivalsProps {
  /** 点击商品：唤起对话询问该商品 */
  onPick: (productName: string) => void
}

export default function NewArrivals({ onPick }: NewArrivalsProps) {
  const [products, setProducts] = useState<ProductLite[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    getNewArrivals(6)
      .then((list) => {
        if (!cancelled) setProducts(list)
      })
      .catch(() => {
        // 新品推荐失败不阻塞对话（降级为不显示）
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const handleTap = useCallback(
    (p: ProductLite) => {
      onPick(p.name || '这个商品')
    },
    [onPick],
  )

  if (loading || products.length === 0) return null

  return (
    <View className='new-arrivals'>
      <View className='new-arrivals__header'>
        <Text className='new-arrivals__title'>🔥 新品推荐</Text>
        <Text className='new-arrivals__hint'>点一下问问小布</Text>
      </View>
      <ScrollView className='new-arrivals__scroll' scrollX enhanced showScrollbar={false}>
        <View className='new-arrivals__row'>
          {products.map((p) => {
            const imageUrl = p.image || PLACEHOLDER_IMAGE
            const price = typeof p.price === 'number' ? p.price.toFixed(2) : String(p.price ?? '')
            return (
              <View
                key={p.id}
                className='new-arrivals__card'
                hoverClass='new-arrivals__card--hover'
                onClick={() => handleTap(p)}
              >
                <Image className='new-arrivals__img' src={imageUrl} mode='aspectFill' />
                <Text className='new-arrivals__name'>{p.name}</Text>
                <View className='new-arrivals__price-row'>
                  <Text className='new-arrivals__price-unit'>¥</Text>
                  <Text className='new-arrivals__price'>{price}</Text>
                </View>
              </View>
            )
          })}
        </View>
      </ScrollView>
    </View>
  )
}
