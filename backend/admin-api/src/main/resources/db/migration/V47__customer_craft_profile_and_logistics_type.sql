-- 客户工艺画像 + 常用物流 + 订单物流类型（issue #3984，M2-D）
-- 2026-09-17 用户三项要求：客户记忆（标准/省料/自报）、常用物流/快递、物流类型（express/logistics）

ALTER TABLE customer_profiles ADD COLUMN IF NOT EXISTS craft_mode VARCHAR(16) DEFAULT 'standard';
ALTER TABLE customer_profiles ADD COLUMN IF NOT EXISTS craft_profile JSONB DEFAULT '{}';
ALTER TABLE customer_profiles ADD COLUMN IF NOT EXISTS default_logistics_type VARCHAR(16) DEFAULT 'express';
ALTER TABLE customer_profiles ADD COLUMN IF NOT EXISTS default_logistics_company VARCHAR(128);

ALTER TABLE order_logistics ADD COLUMN IF NOT EXISTS logistics_type VARCHAR(16) DEFAULT 'express';

COMMENT ON COLUMN customer_profiles.craft_mode IS '工艺画像模式：standard 跟随企业固定工艺算料 / economy 主动省料 / self_quoted 自报用料（2026-09-17 客户确认，M2-D）';
COMMENT ON COLUMN customer_profiles.craft_profile IS '工艺偏好 JSON：开数/定型/档位等默认（报价协商读取，M3-F 消费）';
COMMENT ON COLUMN customer_profiles.default_logistics_type IS '客户常用物流类型：express 快递 / logistics 物流专线';
COMMENT ON COLUMN customer_profiles.default_logistics_company IS '客户常用物流/快递公司（下单自动带出）';
COMMENT ON COLUMN order_logistics.logistics_type IS '物流类型：express 快递 / logistics 物流专线（四季安等）';
