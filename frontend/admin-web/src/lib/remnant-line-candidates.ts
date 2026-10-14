/**
 * 余料台账「按商品行搜索」的候选行（issue #6883）—— **纯映射**（拆出来是为了能被定点判据钉住）。
 *
 * ## 为什么单独一个模块
 *
 * 这段映射原先写死在页面里，且依赖两个**当时拿不到的键**：
 * - `it.id` —— **列表**响应不下发 `order_items.id`（issue #2916 的副产品）⇒ 页面上那句
 *   `filter((it) => !!it.id)` **恒 false** ⇒ 「按商品行搜索」整条链路**搜不出任何一行**；
 * - `it.color` / `it.specification` —— 详情响应里都没有（真值 = `processingInfo.colorName` / `doorWidth`）。
 *
 * 后端已补 `OrderItemBrief.id`（issue #6883）⇒ 这里只做一件事：**把每一行连同它**自己**的行主键
 * 摊平出来**。**绝不**去重、**绝不**去猜：同名同量的两行是**两条**候选，各带各的主键
 * （上一版靠「品名 + 颜色 + 规格 + 数量」在详情里重新找一行，而那两个字段恒 `undefined`
 * ⇒ 判据恒真 ⇒ **可能把余料挂到错行**）。
 */
import { orderItemSku } from './order-item-sku'
import type { OrderBrief } from '@/types'

export interface RemnantLineCandidate {
  /** 订单主键（提交时带上，便于后端校验归属） */
  orderId: string
  orderNo: string
  customerName: string
  /** 订单**行**主键（`order_items.id`）—— 余料登记 / 匹配的挂账对象 */
  itemId: string
  productName: string
  /** 颜色（`processingInfo.colorName`） */
  color: string
  /** 门幅（`processingInfo.doorWidth`，已归一到 `2.8米`） */
  specification: string
  quantity: number
}

/**
 * 摊平订单列表 ⇒ 候选行。
 *
 * 没有行主键的行**直接丢弃**（历史响应 / 后端未升级）：拿不到主键就指认不了「是哪一行」，
 * 放出来只会让商家选一个**挂不上账**的候选 —— 宁可少列，也不给假候选。
 */
export function remnantLineCandidates(orders: OrderBrief[]): RemnantLineCandidate[] {
  const out: RemnantLineCandidate[] = []
  for (const order of orders) {
    for (const item of order.items ?? []) {
      if (!item.id) continue
      const sku = orderItemSku(item)
      out.push({
        orderId: order.id,
        orderNo: order.orderNo,
        customerName: order.customerName,
        itemId: item.id,
        productName: item.productName,
        color: sku.color,
        specification: sku.doorWidth,
        quantity: Number(item.quantity),
      })
    }
  }
  return out
}
