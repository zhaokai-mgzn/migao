-- 批次消耗台账（issue #5145 阶段 1）—— 派加工单即扣批次库存的**事实账**
--
-- ## 一句话
--   新表 `stock_batch_consumptions`：**一行 = 一次批次余量变更**（负 = 派工扣减、正 = 作废回补）。
--   余量**派生** = `stock_batches.quantity + Σ(delta)` —— **不原地改** `stock_batches.quantity`
--   （V111 裁定「批次行不可改、冲销走新单据」）。
--
-- ## 为什么是**新表**，而不是给 `stock_ledger_entries` 加一列 `batch_no`
--   （issue #5145 把两条路都留给我选，这里给理由；两条都实现过一遍再回退，不是想当然）
--   ① **粒度冲突**：`stock_ledger_entries` 是 **SKU 级**事实账，它的不变式逐字写在 V53 里 ——
--      「同一 SKU 的相邻两行必须首尾相接：本行 `before_qty` == 该 SKU 上一行的 `after_qty`」。
--      而批次扣减**不改 `product_skus.stock`**（路线 A：SKU 账 = 销售账，支付时扣，一字不动）
--      ⇒ 往那张表里写一行，只有两种落法，**两种都是坏的**：
--        (a) `before_qty`/`after_qty` 填**批次余量** ⇒ 同一列的语义中途变成另一个量，
--            按 `sku_id` 读台账（既有端点 `GET /api/admin/stock-ledger?skuId=`）会把两种数量
--            交错成一条**看起来连续、实则跳变**的链（静默误导，且没有任何检查会变红）；
--        (b) 填**SKU 库存**的前后值 ⇒ 为一次**没有发生**的 SKU 变更伪造一个 delta，
--            直接污染「库存为什么从 X 变成 Y」这个该表唯一要回答的问题。
--   ② **两本账是路线 A 有意分离的**（用户裁定「按你建议来 A」）：SKU 账 = 销售账、
--      批次账 = 实物账。一张表承载两种粒度，就是把「必须能解释的差额」变成表内脏数据。
--   ③ **要查得回来**：本单的判据是「按**批次 / 加工单 / 订单**查回来」——新表三个过滤列
--      各配一条索引（`uk`/`idx_*`，见下），而往 SKU 账上挂一列 `batch_no` 只能答出其中一个维度。
--   ④ **不动既有契约**：`stock_ledger_entries.reason` 的 `ck_stock_ledger_reason` 约束、
--      既有三个查询索引、`StockLedgerService.record` 的入参签名**一个字都不用改**
--      ⇒ 销售账那条链的回归面 = 0（「不能损失客户」）。
--
-- ## 口径（本表的全部语义）
--   · `delta` = `after_qty - before_qty`（**带符号**，与 `stock_ledger_entries.delta` 同族：
--     正 = 增加/回补，负 = 减少/扣减）⇒ 余量 = `stock_batches.quantity + Σ(delta)`。
--   · `before_qty` / `after_qty` = **该批次余量**的变更前后值（不是 SKU 库存）——
--     列名与台账同族，但**量纲由本表的 `batch_id NOT NULL` 界定**（这就是与 (a) 的区别：
--     这里没有「同一列两种含义」，整张表只有批次余量一种量纲）。
--   · `reason` 二态：`processing_order`（派工扣减）/ `processing_order_cancelled`（作废回补）。
--     与 V111 的 `ck_stock_ledger_reason` **同款**纪律：取值集合写进 CHECK 约束，
--     不是只写在 Java 常量里（否则脏值能落库且无人发现）。
--   · `order_item_id` **NOT NULL**：本表的每一行都必须答得出「哪一行订单明细用掉的」
--     （派工是指令、明细行是承诺；答不出这一条 = 扣减无法与订单对账）。
--   · 精度 `NUMERIC(12,1)`：与 `product_skus.stock` / `stock_batches.quantity` 逐字一致
--     （V115 / issue #5063）—— 小数场景（2.7 米）必须逐值可对，不得取整。
--
-- ## 幂等闸（判据「不重复扣」/「作废回补可重跑」的落点）
--   `uk_batch_consumption_line (tenant_id, processing_order_no, batch_id, order_item_id, reason)`
--   **partial unique（WHERE deleted = 0）**：
--     · 同一张加工单的同一行明细，对同一批次只可能有一条「扣减」行、一条「回补」行；
--     · 重复生成加工单在更上游就被 `uk_processing_orders_active` 拒（本表是第二道网）；
--     · 取消回补**可重跑**：第二遍插入撞唯一键 ⇒ 服务层识别为「已回补」并跳过，而非报错。
--   注：`order_item_id` 是 `order_items.id`（全局唯一），故同一加工单内不同行天然可分。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · 表：`CREATE TABLE IF NOT EXISTS`；索引：`CREATE INDEX IF NOT EXISTS`；
--   · 约束：`DROP CONSTRAINT IF EXISTS` + 「不存在才 ADD」（`pg_constraint` 判据）；
--   · 注释：`COMMENT ON` 覆盖式（天然幂等）；
--   · 文末 `DO` 块**终态对账**两遍都成立（既是幂等自证，也是判据漂移的停止条件）。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V117__rollback_stock_batch_consumptions.sql（本单只登记，不落码）
-- -- DROP TABLE IF EXISTS stock_batch_consumptions;
-- ```
-- **回滚是有损的**：消耗事实（从哪个批次扣了多少米）**回不来** ⇒ 余量分布与对账读面一并失效，
-- 退回「批次只写不扣」。属**有意**（回滚一个已生效的事实账本就不该静默复原余量）。
--
-- ## bootstrap 终态同步（同 V99/V100/V108/V111 纪律）
-- `docs/sql/schema.sql`（新建库路径**不跑迁移链**）已同步本文件终态。
--
-- ## 停止条件（fail-closed）
--   ① `stock_batches` / `stock_ledger_entries` / `products` / `tenants` 任一不存在 ⇒ 迁移失败并停下
--      （不 CREATE TABLE 兜底 —— 会造出无外键/无索引的影子表）；
--   ② 终态对账报「表缺失」/「列缺失」/「reason 约束未放行」/「唯一索引缺失」/「查询索引缺失」
--      ⇒ 写语句判据漂移或被部分回滚 ⇒ 回滚本迁移，不硬推。
--
-- ## 显式事务（同 V97 / V102 / V107 / V108 / V111 的实测口径）
-- `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条
-- autocommit** ⇒ 不显式 `BEGIN/COMMIT` 时，中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
-- 两条执行路径必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 前置表存在性（fail-closed：缺表立即停，不兜底建表）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(t, ', ') INTO missing
      FROM (VALUES ('tenants'), ('products'), ('stock_batches'), ('stock_ledger_entries')) AS v(t)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = v.t);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V116 前置表缺失：% —— 迁移停下（不兜底建表）', missing;
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 批次消耗台账
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS stock_batch_consumptions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- 批次主键（批次行**不可删**（V111）⇒ 可以加 FK；加它是为了让「扣了一个不存在的批次」当场失败）
    batch_id BIGINT NOT NULL REFERENCES stock_batches(id),
    -- 批次号冗余：读面按批次号查/展示时不必 join 回 stock_batches（且批次号是业务主键）
    batch_no VARCHAR(32) NOT NULL,
    product_id VARCHAR(64) NOT NULL REFERENCES products(id),
    -- 同 stock_ledger_entries.sku_id：不加 FK（SKU 会被硬删重建），追溯优先用 sku_code
    sku_id BIGINT,
    sku_code VARCHAR(64),
    -- 变化量（正 = 回补，负 = 扣减），恒等于 after_qty - before_qty（NUMERIC(12,1)，V115/#5063）
    delta NUMERIC(12,1) NOT NULL,
    -- 本**批次余量**的变更前后值（不是 SKU 库存 —— 见文件头「为什么是新表」）
    before_qty NUMERIC(12,1) NOT NULL,
    after_qty NUMERIC(12,1) NOT NULL,
    -- processing_order 派工扣减 / processing_order_cancelled 作废回补（取值集合见 ck_batch_consumption_reason）
    reason VARCHAR(32) NOT NULL,
    -- 业务单据：加工单号 JG-yyyyMMdd-NNNN（判据「按加工单查回来」）
    processing_order_no VARCHAR(32) NOT NULL,
    -- 业务单据：订单号（判据「按订单查回来」；冗余自 processing_orders.order_id → orders.order_no）
    order_no VARCHAR(32),
    -- 订单明细行 id（= 加工单快照的 itemId；判据「哪一行用掉的」，NOT NULL）
    -- 订单明细行 id（= 加工单快照的 itemId；判据「哪一行用掉的」，NOT NULL）。
    -- 宽度 VARCHAR(36) 与 order_items.id 逐字一致 —— 它是 ASSIGN_UUID 主键，**不是** BIGINT
    order_item_id VARCHAR(36) NOT NULL,
    operator VARCHAR(64) NOT NULL,
    note VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INT NOT NULL DEFAULT 0
);

-- 幂等闸：同一加工单的同一明细行 × 同一批次 × 同一 reason 只允许一行（见文件头「幂等闸」）
CREATE UNIQUE INDEX IF NOT EXISTS uk_batch_consumption_line
    ON stock_batch_consumptions (tenant_id, processing_order_no, batch_id, order_item_id, reason)
    WHERE deleted = 0;

-- 三个查询维度（判据：按批次 / 加工单 / 订单都能查回来）+ SKU 维度（余量汇总）
CREATE INDEX IF NOT EXISTS idx_batch_consumptions_tenant_batch
    ON stock_batch_consumptions (tenant_id, batch_no, id);
CREATE INDEX IF NOT EXISTS idx_batch_consumptions_tenant_po
    ON stock_batch_consumptions (tenant_id, processing_order_no, id);
CREATE INDEX IF NOT EXISTS idx_batch_consumptions_tenant_order
    ON stock_batch_consumptions (tenant_id, order_no, id);
CREATE INDEX IF NOT EXISTS idx_batch_consumptions_tenant_sku
    ON stock_batch_consumptions (tenant_id, sku_id, id);

-- reason 取值集合（同 V111 对 ck_stock_ledger_reason 的纪律：写进约束，不只写在 Java 常量里）
ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS ck_batch_consumption_reason;

ALTER TABLE stock_batch_consumptions
    ADD CONSTRAINT ck_batch_consumption_reason
    CHECK (reason IN ('processing_order', 'processing_order_cancelled'));

COMMENT ON TABLE stock_batch_consumptions IS
    '批次消耗台账（V116，issue #5145 阶段 1）：一行 = 一次批次余量变更（负 = 派工扣减、正 = 作废回补）。余量派生 = stock_batches.quantity + Σ(delta)，**不原地改** stock_batches.quantity（V111：批次行不可改、冲销走新单据）。本表与 stock_ledger_entries（SKU 级销售账）是**两本账**：批次账 = 实物账，随加工单生成而扣、随作废而回补';

COMMENT ON COLUMN stock_batch_consumptions.delta IS
    '变化量（正 = 回补，负 = 扣减），恒等于 after_qty - before_qty（NUMERIC(12,1)，V115/#5063）';
COMMENT ON COLUMN stock_batch_consumptions.before_qty IS
    '变更前**该批次余量**（= stock_batches.quantity + 此前 Σdelta；**不是** SKU 库存 —— 本表只有批次余量一种量纲）';
COMMENT ON COLUMN stock_batch_consumptions.after_qty IS
    '变更后**该批次余量**（= before_qty + delta）';
COMMENT ON COLUMN stock_batch_consumptions.reason IS
    '变更来源：processing_order 派加工单扣减 / processing_order_cancelled 加工单作废回补（约束 ck_batch_consumption_reason 是硬判据）';
COMMENT ON COLUMN stock_batch_consumptions.processing_order_no IS
    '加工单号 JG-yyyyMMdd-NNNN（派工扣减与该单同事务写入；作废回补引用同一单号 ⇒ 可按单号整单对账）';
COMMENT ON COLUMN stock_batch_consumptions.order_no IS
    '订单号（冗余，便于「按订单查回来」时不 join processing_orders）';
COMMENT ON COLUMN stock_batch_consumptions.order_item_id IS
    '订单明细行 id（= 加工单快照行的 itemId）。NOT NULL：派工指定的是「哪一行用哪个批次」，答不出这一条就无法与订单对账';
COMMENT ON COLUMN stock_batch_consumptions.operator IS
    '操作人：登录用户名（手机号）；内部服务调用 = internal-service；无认证上下文（测试）= system';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    n              INTEGER;
    missing        TEXT;
    constraint_def TEXT;
BEGIN
    -- ① 表必须在
    SELECT count(*) INTO n
      FROM information_schema.tables
     WHERE table_schema = 'public' AND table_name = 'stock_batch_consumptions';
    IF n = 0 THEN
        RAISE EXCEPTION 'V116 终态对账失败：表 stock_batch_consumptions 缺失 —— 回滚本迁移';
    END IF;

    -- ② 十五列必须在（缺一列即功能静默缺失）
    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('id'), ('tenant_id'), ('batch_id'), ('batch_no'), ('product_id'),
                   ('sku_id'), ('sku_code'), ('delta'), ('before_qty'), ('after_qty'),
                   ('reason'), ('processing_order_no'), ('order_no'), ('order_item_id'),
                   ('operator'), ('note'), ('created_at'), ('deleted')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'stock_batch_consumptions'
                          AND column_name = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V116 终态对账失败：stock_batch_consumptions 缺列 % —— 回滚本迁移', missing;
    END IF;

    -- ③ reason 约束必须**同时放行两个取值**（漏了回补取值 ⇒ 作废回补当场 23514，判据「对称回补」全断）
    SELECT pg_get_constraintdef(oid) INTO constraint_def
      FROM pg_constraint
     WHERE conname = 'ck_batch_consumption_reason'
       AND conrelid = 'stock_batch_consumptions'::regclass;
    IF constraint_def IS NULL THEN
        RAISE EXCEPTION 'V116 终态对账失败：ck_batch_consumption_reason 约束不存在 —— 回滚本迁移';
    END IF;
    IF constraint_def NOT LIKE '%processing_order%'
       OR constraint_def NOT LIKE '%processing_order_cancelled%' THEN
        RAISE EXCEPTION 'V116 终态对账失败：reason 约束未同时放行两个取值，实际 = % —— 回滚本迁移',
            constraint_def;
    END IF;

    -- ④ 幂等闸唯一索引必须在（漏了它 ⇒ 重复扣减不会被任何检查发现）
    SELECT count(*) INTO n
      FROM pg_indexes
     WHERE schemaname = 'public' AND tablename = 'stock_batch_consumptions'
       AND indexname = 'uk_batch_consumption_line';
    IF n = 0 THEN
        RAISE EXCEPTION 'V116 终态对账失败：uk_batch_consumption_line 缺失 —— 重复扣减会静默发生 —— 回滚本迁移';
    END IF;

    -- ⑤ 四条查询索引必须在（判据「按批次/加工单/订单查回来」+ 余量汇总）
    SELECT string_agg(i, ', ') INTO missing
      FROM (VALUES ('idx_batch_consumptions_tenant_batch'),
                   ('idx_batch_consumptions_tenant_po'),
                   ('idx_batch_consumptions_tenant_order'),
                   ('idx_batch_consumptions_tenant_sku')) AS v(i)
     WHERE NOT EXISTS (SELECT 1 FROM pg_indexes
                        WHERE schemaname = 'public' AND tablename = 'stock_batch_consumptions'
                          AND indexname = v.i);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V116 终态对账失败：查询索引缺失 % —— 回滚本迁移', missing;
    END IF;
END $$;

COMMIT;
