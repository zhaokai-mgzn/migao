/**
 * 订单**行金额口径单一真值**（issue #4965）。
 *
 * 用户 2026-09-21 裁定（报价单 issue #4965）：「本套金额 = `subtotal + processingFee`，
 * **与 `OrderItemList` 的行小计口径同一份**，勿各算一套」。
 *
 * 本文件就是那一份 —— 屏幕（订单详情明细行）与纸面（报价单每套表 / 本套金额）
 * 必须调用它，**不得**在渲染处各写一次 `item.subtotal + item.processingFee`：
 * 两处各写一次时，将来任何一处口径变化（例如加工费纳入方式调整）都会让
 * 「屏幕显示的金额」与「打给客户的纸面金额」静默不一致 —— 而商家是照纸面对账的。
 *
 * 口径（与后端一致，勿自行加价/推导）：
 * - `subtotal` = 面料行小计（元）
 * - `processingFee` = **行级落库**的加工费（issue #4406：组合价 × 加工费米数），缺省按 0
 * - 行小计 = 两者之和；**不**参与汇总（订单级数字只读订单字段，见 `QuotationDoc` 汇总段）
 */
import type { OrderItem } from '@/types'

/** 行小计（元）= 面料小计 + 该行加工费。缺 `processingFee` ⇒ 按 0（存量单没有该字段）。 */
export function lineSubtotal(item: Pick<OrderItem, 'subtotal' | 'processingFee'>): number {
  return (item.subtotal || 0) + (item.processingFee || 0)
}
