-- V153（issue #6812，用户 2026-10-13 裁定）：入库单来源新增 `photo`（工人拍照入库）
--
-- 为什么加这个取值：工人拍照链一次收一卷布，上游标签上的米数是**这一卷的卷长**；
-- 该来源单据的明细行「数量」是**卷数**（默认 1）、`roll_length_m` 是**每卷米数**，
-- 入库米数 = 数量 × 卷长（由 `InboundOrderService#metersFor` 一处换算，驱动库存/批次/台账/成本）。
-- 其余来源（purchase / opening）**逐字保持现状**：数量即米数，卷长仍是「仅记录」的记录列（#5034）。
--
-- 为什么用 source 做单位分界：`roll_length_m` 在采购单上也能填（记录列），拿「有没有填卷长」
-- 当单位开关会把商家手建单与存量行一起改读法。source 是只由这条链写的列，且**不由客户端给**
-- （`InboundOrderService#create(req, tenant, operator, forcedSource)` 的服务端强制值）。
--
-- 形态：只放宽 CHECK 的取值集合（列类型 VARCHAR(16) 不变、存量行全部满足新约束）⇒ 幂等、
-- 可重复执行；回滚见文件末尾（把 photo 行改回 purchase 之后再收窄约束）。

ALTER TABLE inbound_orders DROP CONSTRAINT IF EXISTS ck_inbound_orders_source;
ALTER TABLE inbound_orders
    ADD CONSTRAINT ck_inbound_orders_source
    CHECK (source IN ('purchase', 'opening', 'photo'));

COMMENT ON COLUMN inbound_orders.source IS
    '单据来源：purchase 采购收货 / opening 期初建账 / photo 工人拍照入库（photo：明细行数量=卷数、roll_length_m=每卷米数，入库米数=数量×卷长；V153 / issue #6812）';

-- ───────────────────────── 回滚（半有损：photo 单会失去单位口径）─────────────────────────
-- -- UPDATE inbound_orders SET source = 'purchase' WHERE source = 'photo';
-- -- ALTER TABLE inbound_orders DROP CONSTRAINT IF EXISTS ck_inbound_orders_source;
-- -- ALTER TABLE inbound_orders ADD CONSTRAINT ck_inbound_orders_source CHECK (source IN ('purchase', 'opening'));
--
-- 终态自检（应各返回 0 行表示不符）：
--   SELECT conname FROM pg_constraint WHERE conname = 'ck_inbound_orders_source'
--     AND pg_get_constraintdef(oid) NOT LIKE '%photo%';
--   SELECT count(*) FROM inbound_orders WHERE source NOT IN ('purchase', 'opening', 'photo');
