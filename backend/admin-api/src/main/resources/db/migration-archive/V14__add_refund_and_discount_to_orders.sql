-- V14: 订单退款/优惠字段
-- refund_amount: 累计已退款金额（>0 表示"已退款"，前端徽标判定依据）
-- refund_at: 最近一次退款时间
-- discount_amount: 优惠金额（应收 totalAmount 与实收 actualAmount 的差额落库）

ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_amount DECIMAL(12,2) DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS refund_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_amount DECIMAL(12,2) DEFAULT 0;
