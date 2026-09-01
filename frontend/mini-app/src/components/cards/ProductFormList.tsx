import { View, Text, Image } from '@tarojs/components'
import './ProductFormList.scss'

/** 商品表单列表项（与 ProductCard 数据契约兼容） */
export interface ProductFormItem {
  product_id?: string
  id?: string
  name: string
  price: number | string
  /** 划线原价（展示「预计到手」时用） */
  original_price?: number | string
  /** 规格对象（瑞幸式：颜色/门幅/售卖方式等） */
  specifications?: Record<string, any>
  /** 预格式化规格文本（后端已拼好时优先） */
  spec_line?: string
  image?: string
  main_image?: string
  images?: string[]
  sales_count?: number
  description?: string
}

interface ProductFormListProps {
  products: ProductFormItem[]
  /** 点击去下单/规格 chip 的回调（发消息给 LLM） */
  onInteract: (value: string) => void
}

/** 默认占位图 */
const PLACEHOLDER_IMAGE = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iODAiIGhlaWdodD0iODAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjgwIiBoZWlnaHQ9IjgwIiBmaWxsPSIjRjNGNEY2Ii8+PHRleHQgeD0iNDAiIHk9IjQ0IiBmb250LXNpemU9IjEyIiBmaWxsPSIjOUNBM0FGIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIj7llYblk4E8L3RleHQ+PC9zdmc+'

/** 规格标签：取 specifications 的值（颜色/门幅/售卖方式等），可点击切换 */
function buildSpecChips(p: ProductFormItem): string[] {
  if (p.spec_line) return p.spec_line.split(/[·,，]/).map(s => s.trim()).filter(Boolean)
  const specs = p.specifications
  if (!specs) return []
  return Object.values(specs)
    .map(v => (v === null || v === undefined || v === '' ? '' : String(v)))
    .filter(Boolean)
}

export default function ProductFormList({ products, onInteract }: ProductFormListProps) {
  if (!products || products.length === 0) return null

  return (
    <View className='product-form-list'>
      {products.map((p, idx) => {
        const imageUrl = p.image || p.main_image || (p.images && p.images[0]) || PLACEHOLDER_IMAGE
        const price = typeof p.price === 'number' ? p.price.toFixed(2) : p.price || '0.00'
        const originalPrice =
          p.original_price !== undefined && p.original_price !== null && p.original_price !== ''
            ? typeof p.original_price === 'number'
              ? p.original_price.toFixed(2)
              : String(p.original_price)
            : ''
        const showOriginal = originalPrice !== '' && originalPrice !== price
        const specChips = buildSpecChips(p)

        return (
          <View key={p.id || `pl-${idx}`} className='product-form-list__row'>
            <Image className='product-form-list__image' src={imageUrl} mode='aspectFill' />

            <View className='product-form-list__info'>
              <Text className='product-form-list__name'>{p.name}</Text>

              {/* 可点规格 chips（瑞幸式：点击切换规格） */}
              {specChips.length > 0 && (
                <View className='product-form-list__specs'>
                  {specChips.map((chip, cIdx) => (
                    <View
                      key={`chip-${cIdx}`}
                      className='product-form-list__chip'
                      onClick={() => onInteract(`选${p.name} ${chip}规格`)}
                    >
                      <Text className='product-form-list__chip-text'>{chip}</Text>
                    </View>
                  ))}
                </View>
              )}

              <View className='product-form-list__price-row'>
                <Text className='product-form-list__price-unit'>¥</Text>
                <Text className='product-form-list__price'>{price}</Text>
                {showOriginal && (
                  <Text className='product-form-list__price-original'>¥{originalPrice}</Text>
                )}
              </View>
              {showOriginal && (
                <Text className='product-form-list__price-hint'>预计到手</Text>
              )}
              {p.sales_count !== undefined && p.sales_count !== null && (
                <Text className='product-form-list__sales'>已售 {p.sales_count} 件</Text>
              )}
            </View>

            <View
              className='product-form-list__order'
              hoverClass='product-form-list__order--hover'
              onClick={() => onInteract(`我要下单${p.name}`)}
            >
              <Text className='product-form-list__order-text'>去下单</Text>
            </View>
          </View>
        )
      })}
    </View>
  )
}
