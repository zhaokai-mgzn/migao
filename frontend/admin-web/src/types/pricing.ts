// 价格本读面（issue #7375 段 3）：一个 SKU 的三层价格一次给全；缺层 = 没有该层价。

export interface PriceBookRow {
  id: string
  price: number
  /** 协议价：客户 id（**只给程序用，不上屏** —— 上屏用 customer_name） */
  customer_id?: string
  /** 协议价：客户展示名（服务端给：微信昵称 → 手机号 → 未命名客户 / 客户已移除，issue #7623） */
  customer_name?: string
  /** 等级价：VIP 等级 */
  vip_level?: string
  /** 阶梯价：门槛与上限 */
  min_qty?: number
  max_qty?: number | null
}

export interface PriceBookView {
  /** 服务端回的 SKU id（雪花号可能超出 JS 安全整数 ⇒ 只做展示/对账，**不要**再拿它去算） */
  skuId: number | string
  customerId?: string | null
  protocol: PriceBookRow[]
  vipLevels: PriceBookRow[]
  tiers: PriceBookRow[]
}
