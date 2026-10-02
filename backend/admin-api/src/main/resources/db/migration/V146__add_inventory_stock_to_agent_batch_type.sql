-- V146 — 批次资源两张表的「取值白名单」补上第三个具名批量 `inventory_stock`（issue #6044 缺陷 A）
--
-- ## 一句话
-- 代码侧（issue #5950）已能写 `batch_type='inventory_stock'`（field=`stock`），但 **V127 建的两条
-- CHECK 从头到尾只有两个值** ⇒ 真库上 `POST /api/admin/agent/batches` 100% 撞 23514 ⇒ 500
-- ⇒ 米宝的「批量库存调整」**从未成功过一次**。本迁移把两个取值纳入两条白名单
-- （DROP CONSTRAINT + 重新 ADD CONSTRAINT）。
--
-- ## 两条一起补（**只补一条 = 没补**）
-- | 约束 | 表 | 现状（真库只读实测） | 缺的取值 |
-- |---|---|---|---|
-- | `ck_agent_batch_type` | `agent_batches` | `IN ('product_price','product_status')` | `inventory_stock` |
-- | `ck_agent_batch_item_field` | `agent_batch_items` | `IN ('basePrice','status')` | `stock` |
-- 只补第一条 ⇒ 批次行落得下、**明细行仍被 23514 拒**（同一请求的下一次写库照旧 500）。
-- 两条的真值来源同一个（`AgentBatchService` 的 `TYPE_*` / `FIELD_*` 常量）—— 判据见
-- `tests/unit_ci_workflows/test_agent_batch_type_domain.py`（值域 ⊆ 白名单 + 迁移终态 == schema.sql 终态）。
--
-- ## 现场读数（2026-10-02 B 端真实 LLM 评测，issue #6044）
-- ```
-- [admin-api] Caused by: org.postgresql.util.PSQLException: ERROR: new row for relation "agent_batches"
--             violates check constraint "ck_agent_batch_type"
--             详细：Failing row contains (3992547c-…, 1, inventory_stock, preview, 1, 0, 0, user_admin_001, …)
--    at com.migao.admin.service.AgentBatchService.create(AgentBatchService.java)
-- ```
-- 真库现状（只读实测）：
-- ```
-- CHECK (((batch_type)::text = ANY ((ARRAY['product_price'::character varying,
--                                          'product_status'::character varying])::text[])))
-- ```
--
-- ## 为什么是「补白名单」而不是「改回两值」
-- `inventory_stock` 是**已交付**的能力（第三个具名批量：批量库存调整，复用同一批次契约与撤销
-- 状态机），不是新设计 —— 缺的只是 DB 侧这一半。同批的
-- `V143__add_stocktake_to_batch_consumptions.sql` 改的是**另一张表**（`stock_batch_consumptions`）
-- ⇒ 看得出来是同一次改动漏了 `agent_batches` 这一半。
--
-- ## 对存量数据安全
-- 本迁移只**放宽**白名单（两个旧值照旧在列），且 `agent_batches` 上不可能存在
-- `inventory_stock` 的行（写入路径一直被本约束拒）⇒ 不重写任何既有行。
-- 真库实测存量行数 = 0（`SELECT count(*) FROM agent_batches`）。
--
-- ## 幂等（`MigrationRunner` 要求所有迁移可重复执行）
-- `DROP CONSTRAINT IF EXISTS` + `ADD CONSTRAINT`（本身就是同一条迁移里成对出现）⇒ 第二遍净效果相同。
-- 终态对账用 `pg_get_constraintdef` 取**实际**约束定义（不是只看名字在不在）⇒ 写错谓词当场停。
--
-- ## 与 `db/init/schema.sql` 的关系
-- 新建库走**基线**（`schema.sql`，不跑历史迁移链）⇒ 该文件的 `ck_agent_batch_type` 必须同步为三值，
-- 否则「全新安装」与「迁移态」两个终态不一致。这条对账由
-- `tests/unit_ci_workflows/test_agent_batch_type_domain.py` 逐值钉住
-- （判据 = 代码写入的 `batch_type` 取值集合 ⊆ 迁移链终态 ∪ schema.sql 终态允许的取值集合）。
--
-- ## 回滚（**可执行**，不是散文）
-- 下面以 `-- -- ` 开头的行是真 SQL。⚠️ **有损**：若存量库已存在 `inventory_stock` 批次行
-- （或 `field='stock'` 的明细行），回滚前必须先处置它们（否则 `ADD CONSTRAINT` 当场 23514 失败）
-- —— 这也是「往前修、不往后滚」的理由。顺序即安全顺序：先明细后批次（外键方向）。
--
-- -- ALTER TABLE agent_batch_items DROP CONSTRAINT IF EXISTS ck_agent_batch_item_field;
-- -- ALTER TABLE agent_batch_items ADD CONSTRAINT ck_agent_batch_item_field CHECK (field IN ('basePrice', 'status'));
-- -- ALTER TABLE agent_batches DROP CONSTRAINT IF EXISTS ck_agent_batch_type;
-- -- ALTER TABLE agent_batches ADD CONSTRAINT ck_agent_batch_type CHECK (batch_type IN ('product_price', 'product_status'));

BEGIN;

-- ① 摘掉两条两值白名单（DROP 先于 ADD：直接 ADD 会因同名约束已存在而 42710）
ALTER TABLE agent_batches DROP CONSTRAINT IF EXISTS ck_agent_batch_type;
ALTER TABLE agent_batch_items DROP CONSTRAINT IF EXISTS ck_agent_batch_item_field;

-- ② 三值 `batch_type`：`inventory_stock` = 批量库存调整（issue #5950；field 必须是 `stock`，
--    字段配对由 `AgentBatchService.TYPE_FIELD` 在应用层 fail-closed）
ALTER TABLE agent_batches
    ADD CONSTRAINT ck_agent_batch_type
    CHECK (batch_type IN ('product_price', 'product_status', 'inventory_stock'));

COMMENT ON CONSTRAINT ck_agent_batch_type ON agent_batches IS
    '具名批量白名单（V146 起三值，issue #6044 缺陷 A）：product_price 商品级统一定价批量改价 / product_status 批量上·下架 / inventory_stock 批量库存调整。**不做通用批量** —— 具名批量的可逆性与预览形态是确定的。代码侧取值集合必须 ⊆ 本白名单，判据见 tests/unit_ci_workflows/test_agent_batch_type_domain.py';

-- ③ 三值 `field`：`stock` = 库存（`AgentWriteValues.FIELD_STOCK`，与逐条改库存同名字段）
ALTER TABLE agent_batch_items
    ADD CONSTRAINT ck_agent_batch_item_field
    CHECK (field IN ('basePrice', 'status', 'stock'));

COMMENT ON CONSTRAINT ck_agent_batch_item_field ON agent_batch_items IS
    '批次明细的字段白名单（V146 起三值，issue #6044 缺陷 A）：basePrice 改价 / status 上·下架 / stock 库存调整。取值来自 AgentWriteValues 的 FIELD_* 常量（单一源），判据见 tests/unit_ci_workflows/test_agent_batch_type_domain.py';

-- ④ 终态对账（写错谓词 / 漏放行必须当场停，而不是留一个「看着在、其实没钉住」的迁移）
DO $$
DECLARE
    constraint_def TEXT;
BEGIN
    SELECT pg_get_constraintdef(c.oid) INTO constraint_def
      FROM pg_constraint c
     WHERE c.conname = 'ck_agent_batch_type'
       AND c.conrelid = 'agent_batches'::regclass;
    IF constraint_def IS NULL THEN
        RAISE EXCEPTION 'V146 终态对账失败：ck_agent_batch_type 不存在 —— 回滚本迁移';
    END IF;
    IF constraint_def NOT LIKE '%inventory_stock%' THEN
        RAISE EXCEPTION 'V146 终态对账失败：白名单没放行 inventory_stock（实际 = %）—— 回滚本迁移',
            constraint_def;
    END IF;
    IF constraint_def NOT LIKE '%product_price%' OR constraint_def NOT LIKE '%product_status%' THEN
        RAISE EXCEPTION 'V146 终态对账失败：两个既有取值被挤掉了（实际 = %）—— 回滚本迁移',
            constraint_def;
    END IF;

    SELECT pg_get_constraintdef(c.oid) INTO constraint_def
      FROM pg_constraint c
     WHERE c.conname = 'ck_agent_batch_item_field'
       AND c.conrelid = 'agent_batch_items'::regclass;
    IF constraint_def IS NULL THEN
        RAISE EXCEPTION 'V146 终态对账失败：ck_agent_batch_item_field 不存在 —— 回滚本迁移';
    END IF;
    IF constraint_def NOT LIKE '%stock%' THEN
        RAISE EXCEPTION 'V146 终态对账失败：明细字段白名单没放行 stock（实际 = %）—— 回滚本迁移',
            constraint_def;
    END IF;
    IF constraint_def NOT LIKE '%basePrice%' OR constraint_def NOT LIKE '%status%' THEN
        RAISE EXCEPTION 'V146 终态对账失败：两个既有字段被挤掉了（实际 = %）—— 回滚本迁移',
            constraint_def;
    END IF;
END $$;

COMMIT;
