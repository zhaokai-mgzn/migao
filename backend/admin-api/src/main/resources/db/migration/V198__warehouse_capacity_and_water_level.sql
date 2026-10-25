-- V198 / issue #7791：成品仓「容量 + 一仓多件 + 水位智能分配」。
--
-- 为什么改（用户 2026-10-26 逐字）：「后续成品帘打包入库时要自动分配仓位时要能根据仓位水位智能分配」
-- ｜「仓位管理允许批量创建，用户输入一个数字区间后批量生成仓位号」。
--
-- 改前（V196 issue #7750）有意划下的边界：一个仓位同一时刻只放一件在库成品
-- （局部唯一索引 uk_finished_goods_bin_in_stock），分配 = 最小空闲号；不做容量。
-- 本单把该边界改成：一个仓位可放多件到「区域容量」，分配 = 水位（在库件数 / 容量）最低且未满的仓。
--
-- ## 容量为什么落在 warehouse_locations 上（而不是新开一张区域表）
-- 当前「区域」只是仓位行上的 zone_code / zone_name，没有独立的区域实体；再开一张区域表
-- 就等于先把区域升级成实体（含 CRUD/迁移/读面），而本单只需要一个「本区每仓最多几件」的数。
-- 口径 = **同一区域的仓位行共用同一个 capacity**：服务层建号 / 改容量 / 批量建号时按区域同步
-- （见 WarehouseLocationService），DB 只保证单行 1..999。区域容量是**业务闸门**，不是第二份「占用」真相：
-- 在库件数仍只从 finished_goods_stock 的在库行派生（不新增占用标志 / 计数字段）。
--
-- ## 为什么必须 drop uk_finished_goods_bin_in_stock
-- 该唯一索引强制「一仓一件」，与「一仓多件到容量」直接冲突。同套装/部位的幂等仍由
-- uk_finished_goods_set_part_in_stock（以及 V196 遗留的 legacy 索引）兜住，不依赖 bin 索引。
-- 并发容量由服务层在**同一事务**里对候选仓位行 SELECT ... FOR UPDATE 串行化（见
-- WarehouseLocationMapper#selectBestBinForAllocation）；本迁移只补一个按 bin 计数的非唯一索引。
--
-- ## 回滚（新迁移，不删本文件）
-- 回滚段见文件末尾（注释）：重加 bin 唯一索引只在「一仓多件的数据未产生」时可行；一旦产生，
-- 必须先人工把多件仓位的在库行迁走/出库，否则唯一索引建不起来 —— 这是本单**有意接受**的不可逆面。
--
-- 幂等：ADD COLUMN IF NOT EXISTS / DROP INDEX IF EXISTS / 先判后建；显式事务（本仓迁移口径）。

BEGIN;

-- ① 仓位容量（件）：默认 10 件/仓；区域统一由服务层同步
ALTER TABLE warehouse_locations
    ADD COLUMN IF NOT EXISTS capacity INTEGER NOT NULL DEFAULT 10;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_warehouse_locations_capacity') THEN
        ALTER TABLE warehouse_locations
            ADD CONSTRAINT ck_warehouse_locations_capacity CHECK (capacity BETWEEN 1 AND 999);
    END IF;
END $$;

COMMENT ON COLUMN warehouse_locations.capacity IS
    '每仓容量（件；V198 / issue #7791）：同一区域统一，默认 10，1~999。在库件数 ≥ capacity 视为已满，不再分配';

-- ② 一仓多件：去掉「一仓一件」的唯一索引，换成按 bin 计数的非唯一部分索引
DROP INDEX IF EXISTS uk_finished_goods_bin_in_stock;
CREATE INDEX IF NOT EXISTS idx_finished_goods_bin_in_stock
    ON finished_goods_stock (tenant_id, bin_code)
    WHERE status = 'in_stock' AND deleted = 0;

COMMENT ON INDEX idx_finished_goods_bin_in_stock IS
    '水位计数用（V198 / issue #7791）：按 (tenant_id, bin_code) 快速统计在库件数；不再唯一（一仓可放多件）';

-- ③ 终态对账（迁移可重复执行的停止条件）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'warehouse_locations' AND column_name = 'capacity') THEN
        RAISE EXCEPTION 'V198 未落地：warehouse_locations.capacity 缺失';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_indexes
               WHERE indexname = 'uk_finished_goods_bin_in_stock') THEN
        RAISE EXCEPTION 'V198 未落地：uk_finished_goods_bin_in_stock 仍在（一仓多件会被旧约束拦住）';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_indexes
                   WHERE indexname = 'idx_finished_goods_bin_in_stock') THEN
        RAISE EXCEPTION 'V198 未落地：idx_finished_goods_bin_in_stock 缺失（水位计数会退化成全表扫）';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'ck_warehouse_locations_capacity') THEN
        RAISE EXCEPTION 'V198 未落地：ck_warehouse_locations_capacity 缺失';
    END IF;
END $$;

COMMIT;

-- 回滚（回滚前先处理「一仓多件」的存量数据；否则第 ② 步必然失败）：
-- BEGIN;
-- DROP INDEX IF EXISTS idx_finished_goods_bin_in_stock;
-- CREATE UNIQUE INDEX IF NOT EXISTS uk_finished_goods_bin_in_stock
--     ON finished_goods_stock (tenant_id, bin_code)
--     WHERE status = 'in_stock' AND deleted = 0;
-- ALTER TABLE warehouse_locations DROP CONSTRAINT IF EXISTS ck_warehouse_locations_capacity;
-- ALTER TABLE warehouse_locations DROP COLUMN IF EXISTS capacity;
-- COMMIT;
