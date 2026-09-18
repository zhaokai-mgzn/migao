'use client'

import { craftSpecRows, isCraftSpecKey } from '@/lib/craft-display'
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
      <div className="grid grid-cols-12 gap-2 px-4 py-2.5 bg-neutral-50 rounded-t-lg text-xs font-semibold text-neutral-500 uppercase">
        <div className="col-span-4">商品信息</div>
        <div className="col-span-2 text-center">数量</div>
        <div className="col-span-2 text-right">单价</div>
        <div className="col-span-2 text-right">加工费</div>
        <div className="col-span-2 text-right">小计</div>
      </div>

      {/* 明细行 */}
      <div className="divide-y divide-neutral-100">
        {items.map((item, index) => {
          // 工艺规格（issue #4355 / 设计文档 §4.9 ②）：直读 processing_info，缺值行已丢弃
          const specRows = craftSpecRows(item.processingInfo)
          // 工艺键已由规格块按标签展示 ⇒ 键值兜底行只留非工艺键（同一真值不重复展示）
          const otherEntries = Object.entries(item.processingInfo ?? {}).filter(
            ([key]) => !isCraftSpecKey(key)
          )
          return (
          <div key={item.id || index} className="grid grid-cols-12 gap-2 px-4 py-3 items-center">
            <div className="col-span-4">
              <div className="font-medium text-neutral-900 text-sm">{item.productName}</div>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1">
                {item.sku && (
                  <span className="text-xs text-neutral-400">SKU: {item.sku}</span>
                )}
                {/* 销售信息：颜色、销售方式、门幅 */}
                {item.processingInfo && typeof item.processingInfo === 'object' && (
                  <>
                    {(item.processingInfo as any).colorName && (
                      <span className="text-xs text-primary-600 font-medium">{(item.processingInfo as any).colorName}</span>
                    )}
                    {(item.processingInfo as any).sellingMethod && (
                      <span className="text-xs text-neutral-400">
                        {(() => { const m: Record<string, string> = { bulk_cut: '散剪', full_roll: '整卷', per_meter: '按米', per_piece: '按件' }; return m[(item.processingInfo as any).sellingMethod] || (item.processingInfo as any).sellingMethod })()}
                      </span>
                    )}
                    {(item.processingInfo as any).doorWidth && (
                      <span className="text-xs text-neutral-400">门幅: {(item.processingInfo as any).doorWidth}</span>
                    )}
                  </>
                )}
                {item.specification && (
                  <span className="text-xs text-neutral-400">规格: {item.specification}</span>
                )}
                {item.width && (
                  <span className="text-xs text-neutral-400">宽: {item.width}m</span>
                )}
                {item.height && (
                  <span className="text-xs text-neutral-400">高: {item.height}m</span>
                )}
              </div>
              {/* 工艺规格（设计文档 §4.9 ②）：无任何工艺键时整块不出现 */}
              {specRows.length > 0 && (
                <div className="mt-1.5 space-y-0.5">
                  <div className="text-xs font-medium text-neutral-500">工艺规格</div>
                  {specRows.map((row) => (
                    <div key={row.label} className="flex flex-wrap gap-x-2 text-xs">
                      <span className="text-neutral-400">{row.label}</span>
                      <span className="text-neutral-700">{row.value}</span>
                    </div>
                  ))}
                </div>
              )}
              {otherEntries.length > 0 && (
                <div className="mt-1 text-xs text-amber-600">
                  加工: {otherEntries.map(([k, v]) => `${k}: ${v}`).join(', ')}
                </div>
              )}
            </div>
            <div className="col-span-2 text-center text-sm text-neutral-700">
              ×{item.quantity}
            </div>
            <div className="col-span-2 text-right text-sm text-neutral-700">
              {formatAmount(item.unitPrice)}
            </div>
            <div className="col-span-2 text-right text-sm text-neutral-500">
              {item.processingFee ? formatAmount(item.processingFee) : '-'}
            </div>
            <div className="col-span-2 text-right text-sm font-medium text-neutral-900">
              {formatAmount(item.subtotal + (item.processingFee || 0))}
            </div>
          </div>
          )
        })}
      </div>

      {/* 合计 */}
      <div className="border-t border-neutral-200 px-4 py-3 space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-neutral-500">商品金额</span>
          <span className="text-neutral-700">{formatAmount(subtotalSum)}</span>
        </div>
        {processingFeeSum > 0 && (
          <div className="flex justify-between text-sm">
            <span className="text-neutral-500">加工费合计</span>
            <span className="text-amber-600">{formatAmount(processingFeeSum)}</span>
          </div>
        )}
        <div className="flex justify-between text-base font-semibold pt-2 border-t border-neutral-100">
          <span className="text-neutral-900">订单总金额</span>
          <span className="text-primary-600">{formatAmount(totalAmount)}</span>
        </div>
      </div>
    </div>
  )
}
