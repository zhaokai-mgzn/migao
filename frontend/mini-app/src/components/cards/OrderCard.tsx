import { View, Text } from '@tarojs/components'
import './OrderCard.scss'

interface OrderItem {
  product_name?: string
  productName?: string
  product_code?: string
  productCode?: string
  quantity?: number
  unit_price?: number
  unitPrice?: number
  amount?: number
}

interface OrderInfo {
  id?: string
  order_no?: string
  orderNo?: string
  customer_name?: string
  customerName?: string
  customer_phone?: string
  customerPhone?: string
  total_amount?: number
  totalAmount?: number
  status?: string
  status_text?: string
  statusText?: string
  items_count?: number
  itemsCount?: number
  items?: OrderItem[]
  created_at?: string
  createdAt?: string
}

interface OrderCardProps {
  /** 归一化后的 order 卡片载荷：{"order": {...}} 单订单 / {"orders": [...]} 列表 */
  data: Record<string, unknown>
}

/** 订单状态中文标签（与后端 OrderQueryTool.ORDER_STATUS_TEXT 对齐） */
const STATUS_MAP: Record<string, { text: string; className: string }> = {
  pending: { text: '待付款', className: 'order-card__status--pending' },
  confirmed: { text: '已确认', className: 'order-card__status--confirmed' },
  producing: { text: '生产中', className: 'order-card__status--producing' },
  shipped: { text: '已发货', className: 'order-card__status--shipped' },
  completed: { text: '已完成', className: 'order-card__status--completed' },
  cancelled: { text: '已取消', className: 'order-card__status--cancelled' },
}

function statusInfo(order: OrderInfo) {
  const map = STATUS_MAP[order.status || '']
  if (map) return map
  const text = order.status_text || order.statusText || order.status || ''
  return { text, className: 'order-card__status--default' }
}

function formatAmount(amount: number | undefined | null): string {
  if (amount === undefined || amount === null || Number.isNaN(Number(amount))) return ''
  return Number(amount).toFixed(2)
}

function formatDate(dateStr: string | undefined): string {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return dateStr
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${month}-${day} ${hours}:${minutes}`
}

/** 单笔订单卡片（Receipt 模式：订单号+状态 / 商品明细 / 时间+合计） */
function OrderRow({ order }: { order: OrderInfo }) {
  const orderNo = order.order_no || order.orderNo || ''
  const customerName = order.customer_name || order.customerName || ''
  const totalAmount = formatAmount(order.total_amount ?? order.totalAmount)
  const items = order.items || []
  const itemCount = order.items_count ?? order.itemsCount ?? items.length
  const status = statusInfo(order)

  // 商品明细展示：最多 3 行，超出显示「等N件」
  const shownItems = items.slice(0, 3)

  return (
    <View className='order-card'>
      {/* 头部：订单号 + 状态 chip */}
      <View className='order-card__header'>
        <Text className='order-card__order-no'>{orderNo ? `订单 ${orderNo}` : '订单'}</Text>
        <Text className={`order-card__status ${status.className}`}>{status.text}</Text>
      </View>

      {/* 商品明细（有 items 时渲染明细，否则显示件数） */}
      {shownItems.length > 0 ? (
        <View className='order-card__items'>
          {shownItems.map((item, idx) => (
            <View key={`item-${idx}`} className='order-card__item-row'>
              <View className='order-card__item-info'>
                <Text className='order-card__item-name'>
                  {item.product_name || item.productName || ''}
                </Text>
                <Text className='order-card__item-qty'>
                  {typeof item.quantity === 'number' && item.quantity > 0
                    ? `×${item.quantity}`
                    : ''}
                </Text>
              </View>
              {formatAmount(item.amount ?? (item.unit_price ?? 0) * (item.quantity ?? 0)) && (
                <Text className='order-card__item-amount'>
                  ¥{formatAmount(item.amount ?? (item.unit_price ?? 0) * (item.quantity ?? 0))}
                </Text>
              )}
            </View>
          ))}
          {itemCount > shownItems.length && (
            <Text className='order-card__item-more'>等{itemCount}件商品</Text>
          )}
        </View>
      ) : (
        itemCount > 0 && (
          <View className='order-card__items'>
            <Text className='order-card__item-more'>共{itemCount}件商品</Text>
          </View>
        )
      )}

      {customerName && (
        <View className='order-card__customer-row'>
          <Text className='order-card__customer'>客户：{customerName}</Text>
        </View>
      )}

      {/* 底部：下单时间 + 合计金额 */}
      <View className='order-card__footer'>
        <Text className='order-card__date'>{formatDate(order.created_at || order.createdAt)}</Text>
        {totalAmount && (
          <View className='order-card__total'>
            <Text className='order-card__total-label'>合计</Text>
            <Text className='order-card__amount'>¥{totalAmount}</Text>
          </View>
        )}
      </View>
    </View>
  )
}

export default function OrderCard({ data }: OrderCardProps) {
  // 兼容后端归一化后的两种载荷：{"order": {...}} 单订单 / {"orders": [...]} 列表
  const single = (data.order as OrderInfo | undefined) ?? undefined
  const orders = Array.isArray(data.orders) ? (data.orders as OrderInfo[]) : undefined

  // 无任何可识别订单数据 → 不渲染（避免空「订单」盒子）
  if (!single && (!orders || orders.length === 0)) return null

  if (single) {
    return <OrderRow order={single} />
  }

  return (
    <View className='order-card__list'>
      {orders!.map((order, index) => (
        <OrderRow key={(order.id as string) || (order.order_no as string) || index} order={order} />
      ))}
    </View>
  )
}
