'use client'

import type { OrderItem } from '@/types'

interface OrderItemListProps {
  items: OrderItem[]
  className?: string
}

function formatAmount(amount: number): string {
  return `¥${amount.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function OrderItemList({ items, className }: OrderItemListProps) {
  const subtotalSum = items.reduce((sum, item) => sum + item.subtotal, 0)
  const processingFeeSum = items.reduce((sum, item) => sum + (item.processingFee || 0), 0)
  const totalAmount = subtotalSum + processingFeeSum

  return (
    <div className={className}>
      {/* 表头 */}
      <div className="grid grid-cols-12 gap-2 px-4 py-2.5 bg-gray-50 rounded-t-lg text-xs font-semibold text-gray-500 uppercase">
        <div className="col-span-4">商品信息</div>
        <div className="col-span-2 text-center">数量</div>
        <div className="col-span-2 text-right">单价</div>
        <div className="col-span-2 text-right">加工费</div>
        <div className="col-span-2 text-right">小计</div>
      </div>

      {/* 明细行 */}
      <div className="divide-y divide-gray-100">
        {items.map((item, index) => (
          <div key={item.id || index} className="grid grid-cols-12 gap-2 px-4 py-3 items-center">
            <div className="col-span-4">
              <div className="font-medium text-gray-900 text-sm">{item.productName}</div>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1">
                {item.sku && (
                  <span className="text-xs text-gray-400">SKU: {item.sku}</span>
                )}
                {item.specification && (
                  <span className="text-xs text-gray-400">规格: {item.specification}</span>
                )}
                {item.width && (
                  <span className="text-xs text-gray-400">宽: {item.width}m</span>
                )}
                {item.height && (
                  <span className="text-xs text-gray-400">高: {item.height}m</span>
                )}
              </div>
              {item.processingInfo && Object.keys(item.processingInfo).length > 0 && (
                <div className="mt-1 text-xs text-amber-600">
                  加工: {Object.entries(item.processingInfo).map(([k, v]) => `${k}: ${v}`).join(', ')}
                </div>
              )}
            </div>
            <div className="col-span-2 text-center text-sm text-gray-700">
              ×{item.quantity}
            </div>
            <div className="col-span-2 text-right text-sm text-gray-700">
              {formatAmount(item.unitPrice)}
            </div>
            <div className="col-span-2 text-right text-sm text-gray-500">
              {item.processingFee ? formatAmount(item.processingFee) : '-'}
            </div>
            <div className="col-span-2 text-right text-sm font-medium text-gray-900">
              {formatAmount(item.subtotal + (item.processingFee || 0))}
            </div>
          </div>
        ))}
      </div>

      {/* 合计 */}
      <div className="border-t border-gray-200 px-4 py-3 space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-gray-500">商品金额</span>
          <span className="text-gray-700">{formatAmount(subtotalSum)}</span>
        </div>
        {processingFeeSum > 0 && (
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">加工费合计</span>
            <span className="text-amber-600">{formatAmount(processingFeeSum)}</span>
          </div>
        )}
        <div className="flex justify-between text-base font-semibold pt-2 border-t border-gray-100">
          <span className="text-gray-900">订单总金额</span>
          <span className="text-blue-600">{formatAmount(totalAmount)}</span>
        </div>
      </div>
    </div>
  )
}
