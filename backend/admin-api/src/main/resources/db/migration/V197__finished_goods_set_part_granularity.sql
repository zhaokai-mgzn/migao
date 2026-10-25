-- V197 / issue #7762：成品在库粒度从「订单行」改成「套 × 部位」（一张水洗唛 = 一个仓位）。
--
-- 为什么改（用户 2026-10-25 逐字）：同一订单 5 套的布帘各有自己的仓位号/标签，工人扫哪张码就出哪一件
-- ⇒ 一个订单行不再足够标识「这一件成品」，必须带上套（processing_order_sets）与部位 token
-- （processing_set_part_tokens）。V196 的订单行唯一索引随之改成「套 × 部位」唯一，旧的订单行形态
-- 保留一条 set_id IS NULL 的部分唯一索引兜底（存量行不丢、也不允许同订单行重复在库）。
--
-- 幂等：全部 IF NOT EXISTS / 先判后建；显式事务（本仓迁移口径）。

BEGIN;

-- ① 成品在库：套 × 部位五列
ALTER TABLE finished_goods_stock ADD COLUMN IF NOT EXISTS set_id VARCHAR(64);
ALTER TABLE finished_goods_stock ADD COLUMN IF NOT EXISTS set_no VARCHAR(64);
ALTER TABLE finished_goods_stock ADD COLUMN IF NOT EXISTS set_index INTEGER;
ALTER TABLE finished_goods_stock ADD COLUMN IF NOT EXISTS part_token_id VARCHAR(64);
ALTER TABLE finished_goods_stock ADD COLUMN IF NOT EXISTS short_code VARCHAR(20);

COMMENT ON COLUMN finished_goods_stock.set_id IS
    '所属套（processing_order_sets.id；V197 / issue #7762）。NULL = V196 遗留的订单行粒度行（不追溯回填）';
COMMENT ON COLUMN finished_goods_stock.set_no IS '套号快照（processing_order_sets.set_no）';
COMMENT ON COLUMN finished_goods_stock.set_index IS '第几套（1 起；标签「第 N 套 / 共 M 套」用）';
COMMENT ON COLUMN finished_goods_stock.part_token_id IS
    '部位码行（processing_set_part_tokens.id）—— 一张水洗唛 = 一个仓位 = 一行在库';
COMMENT ON COLUMN finished_goods_stock.short_code IS
    '水洗唛短码快照（印在纸上的可抄入口 /s/<短码>）；与 part_token_id 是同一行的两种表示';

-- 旧的「订单行在库唯一」：一个订单行现在可能有多个套 × 部位在库 ⇒ 必须撤掉
DROP INDEX IF EXISTS uk_finished_goods_order_item_in_stock;

-- 新唯一：一个套的同一部位只允许一行在库（套 × 部位 = 一件成品 = 一个仓位）
CREATE UNIQUE INDEX IF NOT EXISTS uk_finished_goods_set_part_in_stock
    ON finished_goods_stock (tenant_id, set_id, order_item_id)
    WHERE status = 'in_stock' AND deleted = 0 AND set_id IS NOT NULL;

-- 兜底：V196 遗留（set_id IS NULL）的订单行粒度行仍保持「一个订单行一行在库」
CREATE UNIQUE INDEX IF NOT EXISTS uk_finished_goods_legacy_item_in_stock
    ON finished_goods_stock (tenant_id, order_id, order_item_id)
    WHERE status = 'in_stock' AND deleted = 0 AND set_id IS NULL;

-- ② 入库单明细：同一张成品入库单里要能看出这一行属于哪套 / 哪个部位码
ALTER TABLE inbound_order_items ADD COLUMN IF NOT EXISTS set_id VARCHAR(64);
ALTER TABLE inbound_order_items ADD COLUMN IF NOT EXISTS set_no VARCHAR(64);
ALTER TABLE inbound_order_items ADD COLUMN IF NOT EXISTS short_code VARCHAR(20);

COMMENT ON COLUMN inbound_order_items.set_id IS
    '所属套（V197 / issue #7762）：成品入库按「套 × 部位」逐行入库，一行 = 一张水洗唛';
COMMENT ON COLUMN inbound_order_items.set_no IS '套号快照（与 finished_goods_stock.set_no 同值）';
COMMENT ON COLUMN inbound_order_items.short_code IS '部位码短码快照（标签与追溯用）';

-- ③ 出库单来源：扫水洗唛出库（scan）
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_outbound_orders_source') THEN
        ALTER TABLE outbound_orders DROP CONSTRAINT ck_outbound_orders_source;
    END IF;
    ALTER TABLE outbound_orders
        ADD CONSTRAINT ck_outbound_orders_source CHECK (source IN ('manual', 'ship', 'scan'));
END $$;

-- ④ 终态对账（迁移可重复执行的停止条件）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'finished_goods_stock' AND column_name = 'part_token_id') THEN
        RAISE EXCEPTION 'V197 未落地：finished_goods_stock.part_token_id 缺失';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_indexes
                   WHERE indexname = 'uk_finished_goods_set_part_in_stock') THEN
        RAISE EXCEPTION 'V197 未落地：套 × 部位在库唯一索引缺失';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_constraint
               WHERE conname = 'ck_outbound_orders_source'
                 AND pg_get_constraintdef(oid) NOT LIKE '%scan%') THEN
        RAISE EXCEPTION 'V197 未落地：outbound_orders.source 未放行 scan';
    END IF;
END $$;

COMMIT;
