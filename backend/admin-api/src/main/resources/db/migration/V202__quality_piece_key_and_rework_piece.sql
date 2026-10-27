-- V202__quality_piece_key_and_rework_piece.sql
--
-- 返工单 / 质检单的「件」定位键（issue #7945，用户 2026-10-27 裁定）
--
-- ## 一句话
-- 改前：质检单只有 `order_item_id`（部位行）、返工单只有 `operation_id`（件隐含在工序实例里）
-- ⇒ 同一订单两樘窗的同一部位**分不开**（「像在给订单整体记质检」）；PC 返工列表也答不出「返的是哪一件」。
-- 改后：两张单都落 **套号 × 部位**（= 一张水洗唛码 = `processing_set_part_tokens` 一行）。
--
-- ## 口径（用户逐字）
-- 「应该只记录返工单，不产生质检数据，返工是因为布料有质量问题，而质检是因为加工厂做工有问题，两者有区别」
-- 「（某件成品帘的定位键）套号 × 部位」
--   · 返工单 = **材料（布料）质量问题**的唯一载体，**不**自动生成质检记录（撤销 #7919 的自动落库）；
--   · 质检单 = **做工（加工）质量问题**的载体，独立判定，不由返工触发；
--   · 两单的唯一交集是「件」：`(set_id, set_no, order_item_id)`。
--
-- ## 为什么件键必须是套 × 部位
-- 本仓 `processing_order_sets` 一版 = 一樘窗（`docs/design/set-code-and-scan-loop.md`）；
-- `processing_set_part_tokens` 一行 = 一部位一码（码内容 = 单号 + 套号 + 部位）。
-- 只用 `order_item_id` 时，一单两樘窗的「布帘」共用一条当前判定 ⇒ 质检结果串件。
--
-- ## 存量（不猜）
-- 两列全部可空；存量行留空 ⇒ 读面显示「未定位到件」，统计单列，**不补、不折算、不猜第 1 套**。
--
-- ## 回滚
-- 新增列全部可空；`DROP COLUMN` 会丢件级留痕 ⇒ 不回滚（保留列即可被旧代码忽略）。
--
-- ## 显式事务（MigrationRunner 整份 execute / psql -f 逐条 autocommit 同语义）
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE rework_orders
    ADD COLUMN IF NOT EXISTS order_item_id VARCHAR(36),
    ADD COLUMN IF NOT EXISTS set_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS set_no VARCHAR(64),
    ADD COLUMN IF NOT EXISTS position_name VARCHAR(128);

-- 同一件**最多一张未完结的车间返工单**（part unique index；售后来源仍由售后单维度的既有索引兜住）
CREATE UNIQUE INDEX IF NOT EXISTS uk_rework_orders_open_per_piece
    ON rework_orders (tenant_id, set_no, order_item_id)
    WHERE source = 'worker'
      AND status IN ('draft', 'in_progress')
      AND deleted = 0;

CREATE INDEX IF NOT EXISTS idx_rework_orders_piece
    ON rework_orders (tenant_id, order_item_id, set_no) WHERE deleted = 0;

ALTER TABLE quality_inspections
    ADD COLUMN IF NOT EXISTS set_id VARCHAR(64),
    ADD COLUMN IF NOT EXISTS set_no VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_quality_inspections_piece
    ON quality_inspections (tenant_id, set_no, order_item_id, inspected_at) WHERE deleted = 0;

COMMENT ON COLUMN rework_orders.order_item_id IS
    '部位行（order_items.id）：返工单的「件」= 套号 × 部位（issue #7945，用户 2026-10-27 裁定；存量 NULL = 未定位，不猜）';
COMMENT ON COLUMN rework_orders.set_no IS
    '套号快照（processing_order_sets.set_no）：与 order_item_id 一起构成一件成品帘 = 一张水洗唛码';
COMMENT ON COLUMN rework_orders.position_name IS
    '部位展示名快照（报返工那一刻从工序实例取）：读面不 join 猜';
COMMENT ON COLUMN quality_inspections.set_no IS
    '套号（issue #7945）：与 order_item_id 一起构成一件成品帘；存量 NULL = 未定位（不折算到任一樘）';

-- 终态对账（fail-closed：迁移没生效就让建库/迁移链当场红）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'rework_orders' AND column_name = 'set_no') THEN
        RAISE EXCEPTION 'rework_orders.set_no 缺列（issue #7945 迁移未生效）';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'quality_inspections' AND column_name = 'set_no') THEN
        RAISE EXCEPTION 'quality_inspections.set_no 缺列（issue #7945 迁移未生效）';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_indexes
                    WHERE indexname = 'uk_rework_orders_open_per_piece') THEN
        RAISE EXCEPTION 'uk_rework_orders_open_per_piece 缺索引（issue #7945 迁移未生效）';
    END IF;
END $$;

COMMIT;
