-- V143 — 按批次库存盘点（最小录入式）：批次分录的**盘点来源**与幂等键（issue #5865）
--
-- ## 一句话
-- `stock_batch_consumptions` 加一列 `stocktake_run_id`（盘点运行级幂等键）+ 一条部分唯一索引，
-- 并把 **reason 取值集合扩到三值**（+ `stocktake`）、把**两族行的列形状钉成互斥**
-- （`ck_batch_consumption_source_shape`）。
--
-- ## 用户裁定（2026-10-01 会话）
--   「入库单的单批次剩余库存米数是否有设计这个字段？**要支持用户按批次做库存盘点**」→
--   档位选 **A 最小录入式**（不做盘点单实体）；盘盈盘亏口径选 **实盘为准，差异写台账调整**。
--
-- ## 为什么不是「复用 processing_order_no 塞一个盘点号」
-- 盘点**没有**加工单、**没有**订单明细行。把盘点号塞进 `processing_order_no`、把占位串塞进
-- `order_item_id`，会让「按加工单查回来」这条既有读面（`GET /api/admin/batch-stock/consumptions
-- ?processingOrderNo=`）查出盘点行 —— 那是**假账**：读的人分不清「这一单扣了 3 米」与
-- 「这一批被盘掉了 3 米」。本迁移选**结构上分开**：
--
-- | | 扣减 / 回补行 | 盘点行 |
-- |---|---|---|
-- | `reason` | `processing_order` / `processing_order_cancelled` | `stocktake` |
-- | `processing_order_no` | **NOT NULL**（加工单号 JG-…） | **必须 NULL** |
-- | `order_item_id` | **NOT NULL**（= order_items.id） | **必须 NULL** |
-- | `stocktake_run_id` | **必须 NULL** | **NOT NULL**（幂等键） |
--
-- 上表由 `ck_batch_consumption_source_shape` 逐行钉住（违反 ⇒ 23514），
-- 于是「这批为什么少了 1.5 米」这条问题的答案不靠约定、靠约束。
--
-- ## 幂等键为什么落在**单据行**上（照 V117 的 `inbound_orders.import_run_id` 先例）
-- 一次盘点的天然身份是「哪一次提交」⇒ 键直接落在分录行上，配**部分唯一索引**
-- `uk_batch_consumption_stocktake (tenant_id, stocktake_run_id, batch_id) WHERE stocktake_run_id
-- IS NOT NULL AND deleted = 0`：同一 run id 的重复请求（网络重试 / 连点）**撞唯一键**，
-- 而不是靠应用层先查后写（那是 TOCTOU）。谓词让**不带运行标识的扣料行一行都不受影响**。
--
-- ## 为什么 `processing_order_no` / `order_item_id` 要 DROP NOT NULL
-- 不是为了放宽扣料行（它们仍由上表的形状约束要求非空）—— 是为了让**盘点行能诚实地为空**：
-- 保留 NOT NULL 会逼出一个占位串，而占位串就是上面那条「假账」。
-- `uk_batch_consumption_line` 参与列含 NULL ⇒ 盘点行之间不会互相撞（PG 的唯一索引把 NULL 视为互异）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `ADD COLUMN IF NOT EXISTS` / `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT` /
-- `CREATE UNIQUE INDEX IF NOT EXISTS` / `ALTER COLUMN … DROP NOT NULL`（本身幂等）⇒ 第二遍净效果相同。
--
-- ## 回滚（**可执行**，不是散文）
--
-- 下面每一条以 `-- -- ` 开头 = **真的 SQL**（真库判据 `BatchStocktakeRealDbTest` 的
-- `rollbackPathIsExecutableAndRestoresTheContract` 会把这些行抽出来**逐句实跑**：任一句报错 ⇒ 判据红）。
-- 顺序即安全顺序、**不可交换**：
-- ① 先摘掉本迁移新加的约束与索引 →
-- ② **删掉盘点行**（它们是唯一可能带 NULL 单据列的行；不删就没法把两列恢复成 NOT NULL
--    —— 这一步原先只写在散文里，实测 `SET NOT NULL` 直接 **23502**，回滚路径根本走不通）→
-- ③ 恢复两个 NOT NULL → ④ 把 reason 取值集合收回两值（**先 DROP 再 ADD**：直接 ADD 会 **42710**）。
--
-- ⚠️ **有损**（如实登记）：`stocktake_run_id` 的取值**与盘点行本身**都回不来 ⇒ 余量会**跳回盘点前的读数**
-- ——那是「实物被盘过」这个事实在账上被抹掉。存量环境若已盘过点，回滚后需**人工重盘**
-- （没有自动补偿路径）；要保留盘点事实就不要回滚，改往前修。
--
-- -- ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS ck_batch_consumption_source_shape;
-- -- DROP INDEX IF EXISTS uk_batch_consumption_stocktake;
-- -- DELETE FROM stock_batch_consumptions WHERE reason = 'stocktake';
-- -- ALTER TABLE stock_batch_consumptions DROP COLUMN IF EXISTS stocktake_run_id;
-- -- ALTER TABLE stock_batch_consumptions ALTER COLUMN processing_order_no SET NOT NULL;
-- -- ALTER TABLE stock_batch_consumptions ALTER COLUMN order_item_id SET NOT NULL;
-- -- ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS ck_batch_consumption_reason;
-- -- ALTER TABLE stock_batch_consumptions ADD CONSTRAINT ck_batch_consumption_reason CHECK (reason IN ('processing_order', 'processing_order_cancelled'));

BEGIN;

-- ① 盘点运行级幂等键（NULL = 不是盘点行）
ALTER TABLE stock_batch_consumptions ADD COLUMN IF NOT EXISTS stocktake_run_id VARCHAR(64);

COMMENT ON COLUMN stock_batch_consumptions.stocktake_run_id IS
    '盘点**运行级**幂等键（V143，issue #5865）：一次盘点提交的标识（由调用方给，同一次提交的重复请求复用同一个值）。同一 (tenant_id, stocktake_run_id, batch_id) 至多一行（部分唯一索引 uk_batch_consumption_stocktake）⇒ 网络重试不会双记。NULL = 不是盘点行（派工扣减 / 作废回补），不参与去重';

-- ② 幂等闸：同一 run × 批次至多一行（谓词保证扣料行不受影响）
CREATE UNIQUE INDEX IF NOT EXISTS uk_batch_consumption_stocktake
    ON stock_batch_consumptions (tenant_id, stocktake_run_id, batch_id)
    WHERE stocktake_run_id IS NOT NULL AND deleted = 0;

-- ③ 两族的列形状互斥（盘点行不得带加工单 / 扣料行必须带）
--    先 DROP NOT NULL：否则「盘点行留空」这条诚实的写法会被列约束顶回去（见文件头）
ALTER TABLE stock_batch_consumptions ALTER COLUMN processing_order_no DROP NOT NULL;
ALTER TABLE stock_batch_consumptions ALTER COLUMN order_item_id DROP NOT NULL;

ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS ck_batch_consumption_reason;
ALTER TABLE stock_batch_consumptions
    ADD CONSTRAINT ck_batch_consumption_reason
    CHECK (reason IN ('processing_order', 'processing_order_cancelled', 'stocktake'));

ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS ck_batch_consumption_source_shape;
ALTER TABLE stock_batch_consumptions
    ADD CONSTRAINT ck_batch_consumption_source_shape
    CHECK (
        (reason = 'stocktake'
            AND stocktake_run_id IS NOT NULL
            AND processing_order_no IS NULL
            AND order_item_id IS NULL
            AND order_no IS NULL)
        OR (reason <> 'stocktake'
            AND stocktake_run_id IS NULL
            AND processing_order_no IS NOT NULL
            AND order_item_id IS NOT NULL)
    );

COMMENT ON CONSTRAINT ck_batch_consumption_source_shape ON stock_batch_consumptions IS
    '来源形状互斥（V143，issue #5865）：盘点行（reason=stocktake）必须带 stocktake_run_id 且**不得**携带加工单/订单列；扣料与回补行反之。「这批为什么少了 1.5 米」因此不靠约定 —— 两族在**列形状**上就分得开';

-- ④ 终态对账（写错谓词 / 漏建索引必须当场停，而不是留一个「看着在、其实没钉住」的迁移）
DO $$
DECLARE
    constraint_def TEXT;
    index_def TEXT;
    column_nullable TEXT;
BEGIN
    SELECT pg_get_constraintdef(c.oid) INTO constraint_def
      FROM pg_constraint c
     WHERE c.conname = 'ck_batch_consumption_source_shape'
       AND c.conrelid = 'stock_batch_consumptions'::regclass;
    IF constraint_def IS NULL THEN
        RAISE EXCEPTION 'V143 终态对账失败：ck_batch_consumption_source_shape 不存在 —— 回滚本迁移';
    END IF;
    IF constraint_def NOT LIKE '%stocktake_run_id IS NOT NULL%'
       OR constraint_def NOT LIKE '%processing_order_no IS NULL%' THEN
        RAISE EXCEPTION 'V143 终态对账失败：形状约束没钉住盘点行（实际 = %）—— 回滚本迁移',
            constraint_def;
    END IF;

    SELECT pg_get_constraintdef(c.oid) INTO constraint_def
      FROM pg_constraint c
     WHERE c.conname = 'ck_batch_consumption_reason'
       AND c.conrelid = 'stock_batch_consumptions'::regclass;
    IF constraint_def IS NULL OR constraint_def NOT LIKE '%stocktake%' THEN
        RAISE EXCEPTION 'V143 终态对账失败：ck_batch_consumption_reason 未放行 stocktake（实际 = %）'
            ' —— 回滚本迁移', constraint_def;
    END IF;

    SELECT indexdef INTO index_def FROM pg_indexes
     WHERE indexname = 'uk_batch_consumption_stocktake'
       AND tablename = 'stock_batch_consumptions';
    IF index_def IS NULL OR index_def NOT LIKE '%UNIQUE%'
       OR index_def NOT LIKE '%stocktake_run_id IS NOT NULL%' THEN
        RAISE EXCEPTION 'V143 终态对账失败：幂等闸 uk_batch_consumption_stocktake 缺失或不是部分唯一索引'
            '（实际 = %）—— 回滚本迁移', index_def;
    END IF;

    SELECT is_nullable INTO column_nullable FROM information_schema.columns
     WHERE table_name = 'stock_batch_consumptions' AND column_name = 'processing_order_no';
    IF column_nullable <> 'YES' THEN
        RAISE EXCEPTION 'V143 终态对账失败：processing_order_no 仍是 NOT NULL（盘点行无法诚实留空）'
            ' —— 回滚本迁移';
    END IF;
END $$;

COMMIT;
