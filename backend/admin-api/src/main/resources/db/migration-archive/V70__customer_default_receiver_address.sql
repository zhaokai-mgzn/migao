-- 客户默认收货信息（issue #4419）：收货人姓名 / 收货人电话 / 收货详细地址
--
-- 背景（用户 2026-09-19 反馈）：客户管理功能缺乏对客户「收货地址信息」的记录 ——
-- `customer_profiles` 只有 region_province/city/district（**客户所在地区**，不是收货地址），
-- 订单侧只有 `orders.customer_address` 一个 TEXT（每单重填，不沉淀到客户档案）。
-- 同批的 `default_logistics_type` / `default_logistics_company`（V47）虽有列，
-- 但 admin-web 客户管理页从未暴露（`grep -rn "defaultLogistics" frontend/admin-web/src` = 0 命中）
-- ⇒ 形态是「有列无界面」+「收货地址无处可存」。
--
-- 口径（用户 2026-09-19 裁定）：**单个默认收货地址**，不做多地址簿；
-- 地址为**单字段文本**，与 `orders.customer_address` 同口径（下单时逐字带出，避免拼接歧义）。
-- `default_` 前缀与既有 `default_logistics_*` 同族，为将来多地址簿留位。
--
-- 幂等：`ADD COLUMN IF NOT EXISTS`（bootstrap-first 路径下 schema.sql 已建终态，迁移链会再跑一遍）。

ALTER TABLE customer_profiles ADD COLUMN IF NOT EXISTS default_receiver_name VARCHAR(100);
ALTER TABLE customer_profiles ADD COLUMN IF NOT EXISTS default_receiver_phone VARCHAR(20);
ALTER TABLE customer_profiles ADD COLUMN IF NOT EXISTS default_receiver_address TEXT;

COMMENT ON COLUMN customer_profiles.default_receiver_name IS '默认收货人姓名（客户管理「收货信息」；新增订单选客户自动带出，issue #4419）';
COMMENT ON COLUMN customer_profiles.default_receiver_phone IS '默认收货人电话（新增订单选客户自动带出，issue #4419）';
COMMENT ON COLUMN customer_profiles.default_receiver_address IS '默认收货详细地址（单字段文本，与 orders.customer_address 同口径；新增订单选客户自动带出，issue #4419）';
