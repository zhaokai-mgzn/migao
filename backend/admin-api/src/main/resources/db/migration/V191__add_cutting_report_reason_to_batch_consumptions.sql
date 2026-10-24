-- V191 — 批次台账第四个来源：裁剪报工确认批次（issue #7647）
--
-- ## 一句话
-- `ck_batch_consumption_reason` 的取值集合由三值扩到四值（+ `cutting_report`）：
-- 一行 = 裁剪报工时对**该行批次归属**的核对 / 纠偏（负 = 扣实裁批次，正 = 回补原批次）。
--
-- ## 用户裁定（逐字，2026-10-24）
--   「裁剪报工的时候需要工人裁剪的哪个批次，如果通过智能派单的就默认展示指定批次，允许工人改，
--     如果没指定批次就需要工人手输才能完成报工，并且实时更新库存」
--   「只有整卷售卖的时候才需要出库，裁剪不需要生成出库」
--   ⇒ 保留 #5144 裁定 3「派工即扣」，报工做**核对 + 纠偏**（同批次 ⇒ 零写入；换批次 ⇒ 回补 + 扣减；
--     派工未指派 ⇒ 报工时按本次米数扣）。裁剪**不生成出库单**，直接落批次账。
--
-- ## 为什么是**新来源**而不是复用 `processing_order`
-- 复用会让作废回补（`StockBatchConsumptionService#reverse`）分不清「派工那一笔」与「报工纠偏那一笔」：
-- 派工行与纠偏回补行同属一个 (批次, 订单行)，按行回补会把同一对回补两次 ⇒ 账上多回补一笔。
-- 新来源 + 回补改成**净额口径**之后，「作废 ⇒ 该行净额归零」由构造保证（判据 =
-- `StockBatchConsumptionCuttingReportTest#reverseRestoresNetToZeroWhenReportMovedBatch`）。
--
-- ## 🔴 为什么要同时把 `uk_batch_consumption_line` 收窄（真库 23505，单测测不出来）
--   V116 的幂等闸是 `(tenant_id, processing_order_no, batch_id, order_item_id, reason) WHERE deleted = 0`
--   的**部分唯一索引**（它的目的是「派工不重复扣 / 作废回补可重跑」）。报工纠偏**天然会写多行**：
--   ① 派工未指定的行**分次报工** ⇒ 同一 (批次 × 明细行 × cutting_report) 第二次扣减撞唯一键；
--   ② 工人先改成 B、又改回 A ⇒ A 上会同时有「回补 + 扣减」两行。
--   ⇒ 幂等闸的**对象**只该是派工两条腿（`processing_order` / `processing_order_cancelled`），
--   报工行用**净额**语义（同一行同一批次多行，读面按 Σdelta 聚合）。谓词加 `reason <> 'cutting_report'`：
--   派工侧的唯一性一字未动（判据见 `BatchConsumptionLedgerRealDbTest` 的 23505 用例）。
--
# ## 列形状（无需改约束）
-- 本族行与 `processing_order` 同形：`stocktake_run_id` 为 NULL、`processing_order_no` / `order_item_id`
-- 非空 ⇒ 现有 `ck_batch_consumption_source_shape` 原样成立（它把 stocktake 族与非 stocktake 族钉成互斥，
-- 不枚举具体 reason）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` 本身幂等 ⇒ 第二遍净效果相同。
--
-- ## 回滚（**可执行**，不是散文）
-- 顺序即安全顺序：① 先把报工来源的行删掉（不删就没法把取值集合收回去）→ ② 先 DROP 再 ADD（直接 ADD
-- 会 42710）。
--
-- -- DELETE FROM stock_batch_consumptions WHERE reason = 'cutting_report';
-- -- DROP INDEX IF EXISTS uk_batch_consumption_line;
-- -- CREATE UNIQUE INDEX uk_batch_consumption_line ON stock_batch_consumptions (tenant_id, processing_order_no, batch_id, order_item_id, reason) WHERE deleted = 0;
-- -- ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS ck_batch_consumption_reason;
-- -- ALTER TABLE stock_batch_consumptions ADD CONSTRAINT ck_batch_consumption_reason CHECK (reason IN ('processing_order', 'processing_order_cancelled', 'stocktake'));

BEGIN;

-- ① 幂等闸收窄：报工纠偏行允许同一 (批次 × 明细行) 多行（分次报工 / 换批次后再换回，都是合法事实）；
--    派工两条腿的唯一性**一字未动**（谓词只是把它们之外的那一族排除掉）。
DROP INDEX IF EXISTS uk_batch_consumption_line;
CREATE UNIQUE INDEX IF NOT EXISTS uk_batch_consumption_line
    ON stock_batch_consumptions (tenant_id, processing_order_no, batch_id, order_item_id, reason)
    WHERE deleted = 0 AND reason <> 'cutting_report';

ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS ck_batch_consumption_reason;
ALTER TABLE stock_batch_consumptions
    ADD CONSTRAINT ck_batch_consumption_reason
    CHECK (reason IN ('processing_order', 'processing_order_cancelled', 'stocktake', 'cutting_report'));

COMMENT ON CONSTRAINT ck_batch_consumption_reason ON stock_batch_consumptions IS
    '变更来源取值集合（V116 建、V143 加 stocktake、V191 加 cutting_report）：processing_order 派工扣减 / processing_order_cancelled 作废回补 / stocktake 盘点差异 / cutting_report 裁剪报工确认批次（负 = 扣实裁批次，正 = 回补原批次）';

-- 终态对账（写错谓词必须当场停，而不是留一个"看着在、其实没钉住"的迁移）
DO $$
DECLARE
    constraint_def TEXT;
BEGIN
    SELECT pg_get_constraintdef(c.oid) INTO constraint_def
      FROM pg_constraint c
     WHERE c.conname = 'ck_batch_consumption_reason'
       AND c.conrelid = 'stock_batch_consumptions'::regclass;
    IF constraint_def IS NULL OR constraint_def NOT LIKE '%cutting_report%' THEN
        RAISE EXCEPTION 'V191 终态对账失败：ck_batch_consumption_reason 未放行 cutting_report（实际 = %）—— 回滚本迁移',
            constraint_def;
    END IF;
    IF constraint_def NOT LIKE '%stocktake%' THEN
        RAISE EXCEPTION 'V191 终态对账失败：ck_batch_consumption_reason 丢了 stocktake（实际 = %）—— 回滚本迁移',
            constraint_def;
    END IF;

    -- 幂等闸：必须是部分唯一索引、且把 cutting_report 排除在外（漏掉谓词 ⇒ 分次报工撞 23505）
    SELECT indexdef INTO constraint_def FROM pg_indexes
     WHERE indexname = 'uk_batch_consumption_line'
       AND tablename = 'stock_batch_consumptions';
    IF constraint_def IS NULL OR constraint_def NOT LIKE '%UNIQUE%'
       OR constraint_def NOT LIKE '%cutting_report%' THEN
        RAISE EXCEPTION 'V191 终态对账失败：uk_batch_consumption_line 没有排除 cutting_report（实际 = %）'
            ' —— 回滚本迁移', constraint_def;
    END IF;
END $$;

COMMIT;
