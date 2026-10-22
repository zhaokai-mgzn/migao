// 价格本读面（issue #7375 段 3）：一个 SKU 的三层价格一次给全；缺层 = 没有该层价。

export interface PriceBookRow {
  id: string
  price: number
  /** 协议价：客户 id */
  customer_id?: string
  /** 等级价：VIP 等级 */
  vip_level?: string
  /** 阶梯价：门槛与上限 */
  min_qty?: number
  max_qty?: number | null
}

export interface PriceBookView {
  skuId: number
  customerId?: string | null
  protocol: PriceBookRow[]
  vipLevels: PriceBookRow[]
  tiers: PriceBookRow[]
}
