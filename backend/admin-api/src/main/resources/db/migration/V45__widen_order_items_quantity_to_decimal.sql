-- =====================================================================
-- V45: 订单明细数量放宽为 DECIMAL(10,2)（issue #3666）
-- =====================================================================
-- 现象：order_items.quantity 是 INTEGER，但数量口径按计价方式（docs/testing/
-- acceptance-protocol.md:225）——per_meter=米数 / per_set=1 / per_area=宽×高（㎡）。
-- per_area 的合法面积可以是小数：门幅 2.8m × 3m = 8.4 ㎡，刺绣工艺 30 元/㎡
-- 应为 252.00 元；整数列只能表示 8 → 240.00 元 = 少收 12.00 元。
--
-- 裁定（产品负责人，方案 A）：放宽为 DECIMAL(10,2)，与 base_price DECIMAL(10,2)、
-- subtotal DECIMAL(12,2) 的既有金额口径一致。
--
-- 安全要点（可在已有数据的库上执行）：
--   ① 无条件 ALTER —— MigrationRunner 按 schema_migrations 记录跳过已执行文件，
--      不会重放；PG 的 INTEGER → DECIMAL(10,2) 是**无损扩宽**，存量值原样保留
--      （3 → 3.00），不丢数据、不报错；
--   ② 列已存在但不是 numeric（老库是 INTEGER）→ 正常扩宽；
--      列已是 numeric（新库由 docs/sql/schema_full.sql 建）→ 等价状态，ALTER 合法；
--   ③ 列缺失（列不存在）→ 由下面的 ADD COLUMN IF NOT EXISTS 兜底补建，
--      两条语句都幂等（与 V41「对齐 bootstrap schema」同一模式）；
--   ④ 不用 DO 块/多语句拼接 —— MigrationRunner 把整文件交给一次 jdbc.execute，
--      保持"一条 DDL 一个语义"最不易踩驱动解析坑。
-- =====================================================================

ALTER TABLE order_items
    ALTER COLUMN quantity TYPE DECIMAL(10,2) USING quantity::DECIMAL(10,2);

ALTER TABLE order_items ADD COLUMN IF NOT EXISTS quantity DECIMAL(10,2) DEFAULT 1;

COMMENT ON COLUMN order_items.quantity IS
    '数量（口径按计价方式：per_meter=米数 / per_set=1 / per_area=宽×高㎡，可为小数）。issue #3666 由 INTEGER 放宽为 DECIMAL(10,2)';
