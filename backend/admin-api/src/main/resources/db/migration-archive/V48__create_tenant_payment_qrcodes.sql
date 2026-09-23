-- 企业收款二维码设置（issue #3990，M3-F-2；2026-09-17 用户新增要求）
-- 平台不经手资金：商家自设支付宝/微信收款码，C 端支付页展示扫码（规避二清）

CREATE TABLE IF NOT EXISTS tenant_payment_qrcodes (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    payment_type VARCHAR(16) NOT NULL,           -- wechat 微信 / alipay 支付宝
    image_url VARCHAR(512) NOT NULL,             -- 收款码图片地址
    payee_name VARCHAR(128),                     -- 收款主体名称（展示用）
    remark VARCHAR(255),
    status VARCHAR(16) DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_payment_qrcode_tenant_type
    ON tenant_payment_qrcodes (tenant_id, payment_type)
    WHERE deleted = 0;
COMMENT ON TABLE tenant_payment_qrcodes IS '企业收款二维码（微信/支付宝）：顾客扫码直接付给商家，平台不经手资金（二清规避，issue #3990）';
