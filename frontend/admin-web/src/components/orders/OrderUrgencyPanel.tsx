'use client'

import { useEffect, useState } from 'react'
import { Zap } from 'lucide-react'
import { toast } from 'sonner'
import { toastRequestError } from '@/lib/api-error'
import { orderApi } from '@/lib/api'
import { Badge, Button, Card } from '@/components/ui'
import { cn } from '@/lib/utils'
import { isUrgentFlag, urgentBadgeText } from '@/lib/order-urgency'
import type { Order } from '@/types'

/**
 * 订单**加急 / 要求到货日**（issue #5177）—— 做在**订单详情页**上，**不是售后页**。
 *
 * 写面 = `PUT /api/admin/orders/{id}/urgency`（冻结契约）：
 * `{ isUrgent, requiredDeliveryDate }`；`requiredDeliveryDate === ''` ⇒ **清空**。
 *
 * ## 口径（两条红线）
 *
 * 1. **缺省不变**：初值取**服务端值**（`order.isUrgent` / `order.requiredDeliveryDate`），
 *    `isUrgent` 缺省即 `false` = 不加急 —— **不做客户端默认**、**不得默认勾上**；
 *    `requiredDeliveryDate` 缺省即 `''` = 未指定（不猜一个日期）。
 * 2. **零联动**：这里只读写**订单**的加急字段，与售后工单的 `priority` **无任何关系**
 *    （不 import、不显示、不同步 —— 两者只是命名风格相近）。
 *
 * ## 为什么徽标读 `order.isUrgent` 而不是本地 `isUrgent`
 *
 * 徽标代表**库里的事实**、勾选框代表**这次要改成什么** —— 保存成功后由父级重新拉单
 * （`onChanged`）把徽标刷新成服务端真值。这样「点了保存但服务端没变」在屏幕上是**看得见**的
 * （徽标不动），而不是被本地 state 假装成成功。
 */
export default function OrderUrgencyPanel({
  order,
  onChanged,
}: {
  order: Order
  onChanged: () => void
}) {
  const [isUrgent, setIsUrgent] = useState(order.isUrgent === true)
  const [deliveryDate, setDeliveryDate] = useState(order.requiredDeliveryDate ?? '')
  const [saving, setSaving] = useState(false)

  // 订单重新加载（或切到另一张单）⇒ 控件同步回**服务端真值**
  useEffect(() => {
    setIsUrgent(order.isUrgent === true)
    setDeliveryDate(order.requiredDeliveryDate ?? '')
  }, [order.id, order.isUrgent, order.requiredDeliveryDate])

  const handleSave = async () => {
    setSaving(true)
    try {
      // 两个键都**显式给**：本次保存把加急与到货日都改成控件的值
      // （`''` ⇒ 服务端按「清空到货日」处理，不会误解成「不改」）。
      await orderApi.updateUrgency(order.id, {
        isUrgent,
        requiredDeliveryDate: deliveryDate,
      })
      toast.success('加急 / 到货日已更新')
      onChanged()
    } catch (e) {
      toastRequestError(e, '更新加急 / 到货日失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card className="mb-5">
      <div className="p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-1.5 text-sm font-medium text-neutral-900">
            <Zap className="w-4 h-4 text-neutral-500" />
            加急 / 到货日
          </div>
          {/* 徽标 = 库里的事实（服务端值），不是本地草稿 */}
          <span data-testid="order-urgency-badge">
            {isUrgentFlag(order) ? (
              <Badge variant="warning">{urgentBadgeText(order)}</Badge>
            ) : (
              <span className="text-xs text-neutral-400">{urgentBadgeText(order)}</span>
            )}
          </span>
        </div>

        <div className="flex flex-wrap items-end gap-4">
          {/* 开关用 `role="switch"`（**不是**原生 checkbox）：订单详情页上其它区块也有勾选框，
              原生 checkbox 会让既有的 `getByRole('checkbox')` 变成「命中多个」。 */}
          <div className="flex items-center gap-2 h-9">
            <button
              type="button"
              role="switch"
              aria-checked={isUrgent}
              aria-label="加急"
              onClick={() => setIsUrgent((v) => !v)}
              className={cn(
                'inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors',
                isUrgent ? 'bg-primary-600' : 'bg-neutral-300'
              )}
            >
              <span
                className={cn(
                  'ml-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform',
                  isUrgent && 'translate-x-4'
                )}
              />
            </button>
            <span className="text-sm text-neutral-700">加急（插队）</span>
          </div>

          <div>
            <label
              htmlFor="order-required-delivery-date"
              className="block text-sm text-neutral-600 mb-1"
            >
              要求到货日
            </label>
            <input
              type="date"
              id="order-required-delivery-date"
              value={deliveryDate}
              onChange={(e) => setDeliveryDate(e.target.value)}
              className="h-9 px-3 rounded border border-neutral-300 bg-white text-sm focus:outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/15"
            />
          </div>

          <Button onClick={handleSave} loading={saving}>
            保存
          </Button>
          <span className="text-xs text-neutral-400 pb-2.5">
            留空 = 未指定（清空后不再参与派单排序）；加急单不参与合并，在智能派单页单独派单
          </span>
        </div>
      </div>
    </Card>
  )
}
