-- V11: 资金流水表（财务对账）
-- 作为现金流的单一事实来源：订单确认支付/退款时由 OrderService 自动登记，线下收支可手动登记。

CREATE TABLE IF NOT EXISTS finance_transactions (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    transaction_no VARCHAR(64) NOT NULL,          -- 流水号 FIN-yyyyMMdd-XXXX
    order_id VARCHAR(36),                          -- 关联订单 UUID（线下收支可为空）
    order_no VARCHAR(64),                          -- 冗余订单号，便于展示与检索
    type VARCHAR(20) NOT NULL,                     -- income / refund
    amount DECIMAL(12,2) NOT NULL DEFAULT 0,       -- 金额（正数）
    payment_method VARCHAR(32),                    -- wechat / alipay / bank_transfer / cash / other
    status VARCHAR(20) NOT NULL DEFAULT 'success', -- pending / success / failed
    operator VARCHAR(64),                          -- 操作人（用户名）
    occurred_at TIMESTAMPTZ,                       -- 交易发生时间
    remark VARCHAR(500),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS uk_finance_txn_no ON finance_transactions(tenant_id, transaction_no);
CREATE INDEX IF NOT EXISTS idx_finance_txn_order ON finance_transactions(order_id);
CREATE INDEX IF NOT EXISTS idx_finance_txn_occurred ON finance_transactions(tenant_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_finance_txn_type ON finance_transactions(tenant_id, type, status);
