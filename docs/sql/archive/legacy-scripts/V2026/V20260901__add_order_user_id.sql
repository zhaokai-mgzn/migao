-- V20260901: 订单表增加 user_id 字段（C 端数据隔离）
-- 背景：小布（C 端 customer 角色）查询订单时此前无用户级隔离，
-- order_query 可查到租户内全部订单（数据隔离漏洞）。
-- 本次迁移：orders.user_id 绑定下单用户（users.id），C 端查询强制按 user_id 过滤。
-- 存量回填见 docs/sql/migrations/V20260902__backfill_order_user_id.sql
ALTER TABLE orders ADD COLUMN IF NOT EXISTS user_id VARCHAR(64);

-- 回填索引：C 端"我的订单"查询路径
CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);

COMMENT ON COLUMN orders.user_id IS '下单用户ID（users.id，C 端数据隔离依据；商户代下单可为空或商户员工ID）';
