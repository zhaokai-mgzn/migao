-- 入库单的幂等与并发健壮性（issue #5148）—— 建单幂等键 + 单号索引口径 + 单据来源
--
-- ## 一句话（本迁移只动 `inbound_orders` 一张表）
--   ① 单号唯一索引的**范围**由「全局唯一」改为「**租户内唯一**」
--      （`uk_inbound_orders_no ON (inbound_no)` → 同名索引 `ON (tenant_id, inbound_no) WHERE deleted = 0`），
--      使索引范围与 V111 建表注释逐字写的「租户内唯一」**一致**；
--   ② 新增 `import_run_id`（建单**运行级**幂等键）+ **部分唯一索引**：
--      同一份导入重跑 ⇒ 不会建出第二张草稿单（否则两张都过账 = 库存加两次，issue #5148 GAP-02）；
--   ③ 新增 `source`（`purchase` / `opening`）+ CHECK 取值约束 —— 期初导入与正常采购必须可区分
--      （#5149 的「批次建账」单依赖它做基线冻结点）；
--   ④ 覆写三处列注释，使**库里的真值**与实现口径一致（口径只留一个方向）。
--
-- ## 为什么单号索引改「租户内」而不是把注释改成「全局唯一」
--   V111（**已发布、逐字节冻结**，不可改）的建表段逐字写着
--   「业务单号 RK-yyyyMMdd-NNNN（DB 唯一约束防重号；**租户内唯一**）」，而它建的是**全局**唯一索引
--   —— 注释与索引矛盾，只能统一一个方向。本迁移选**改索引**，三条理由：
--     ① 同族先例就在**同一个 V111 文件**里：`uk_stock_batches_no` = `UNIQUE (tenant_id, batch_no)`，
--        其注释逐字「批次号在**租户内**唯一（不是全局唯一：多租户各自的序号空间独立）」；
--        `uk_users_tenant_worker_no`（V98）亦同族；
--     ② 序号由**服务端进程内计数器**生成（换了进程就从 0001 重新走）⇒ 全局唯一会让 A 租户的号段
--        被 B 租户占住：A 建单撞唯一索引失败，**跨租户可用性耦合**（自己的号被别人决定）；
--     ③ 「全局唯一」⇒「租户内唯一」是**更弱**的约束：任何满足全局唯一的存量集合必然满足租户内唯一
--        ⇒ 本改动对存量数据**恒成立、无需回填、无有损项**（反向则不成立）。
--   ⚠️ 索引谓词带 `deleted = 0`：与 `uk_users_tenant_worker_no`（V98）同族 —— 软删行的号可回收，
--      且与 MyBatis-Plus `@TableLogic` 的查询口径（一律带 `deleted = 0`）**逐字同界**，
--      不会出现「应用认为号可用、索引认为被占」的分裂。
--   ⚠️ **索引名保持 `uk_inbound_orders_no` 不变**（只改列与谓词）：V111 的终态对账 `DO` 块按**索引名**
--      核验它存在。换名会让 V111 在被重复执行时对账失败（而 `MigrationRunner` 的硬要求是
--      「所有迁移可重复执行」）—— 换名是比改范围更大的破坏面。
--
-- ## 为什么幂等键是「运行级」而不是复用 `client_request_keys`
--   `client_request_keys`（V50，issue #4037）解决的是「**同一 HTTP 请求**重放」；
--   本单的触发场景是「**同一份导入重跑**」（期初/迁移导入重跑、网络重试、文员重复提交），
--   它的天然身份是「哪一次导入运行」⇒ 键直接落在**单据行**上（`import_run_id`），
--   下游（#5149 批次建账）也能凭它追出「这批基线是哪次导入冻结的」。
--   部分唯一索引谓词 `import_run_id IS NOT NULL` ⇒ **不带运行标识的普通建单一行都不受影响**
--   （手工建单、既有前端路径行为逐字不变）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · 列：`ADD COLUMN IF NOT EXISTS`；索引：`DROP INDEX IF EXISTS` + `CREATE UNIQUE INDEX IF NOT EXISTS`；
--   · 约束：`DROP CONSTRAINT IF EXISTS` + 重建（两遍执行同一终态）；
--   · `COMMENT ON …` 覆盖式（天然幂等）；
--   · 文末 `DO` 块**终态对账**两遍都成立（既是幂等自证，也是判据漂移的停止条件）。
--   ⚠️ `CREATE UNIQUE INDEX` **没有** `CONCURRENTLY`：本表在建单流水上量级有限，且
--      `CONCURRENTLY` 不能在事务块里执行（本文件显式 `BEGIN/COMMIT`，两条执行路径必须同语义）。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V118__rollback_inbound_order_idempotency.sql（本单只登记，不落码）
-- -- DROP INDEX IF EXISTS uk_inbound_orders_tenant_import_run;
-- -- ALTER TABLE inbound_orders DROP CONSTRAINT IF EXISTS ck_inbound_orders_source;
-- -- ALTER TABLE inbound_orders DROP COLUMN IF EXISTS source;
-- -- ALTER TABLE inbound_orders DROP COLUMN IF EXISTS import_run_id;
-- -- DROP INDEX IF EXISTS uk_inbound_orders_no;
-- -- CREATE UNIQUE INDEX IF NOT EXISTS uk_inbound_orders_no ON inbound_orders (inbound_no);
-- ```
-- **回滚是半有损的**：`source` / `import_run_id` 的**取值回不来**（列被丢弃），
-- 且「同一运行只建一张单」这条保证随之消失（重跑导入会重新开始建重复单）⇒ 回滚后必须人工去重。
-- 单号索引回滚回全局唯一在存量数据上**恒可行**（租户内唯一 ⇒ 全局唯一对存量不成立），
-- 故回滚后若已有跨租户同号，`CREATE UNIQUE INDEX` 会失败 —— 这也是**有意**的：
-- 宁可回滚失败并让人看见，也不静默丢掉唯一性约束。
--
-- ## bootstrap 终态同步（同 V99/V100/V108/V111/V115 纪律）
--   `docs/sql/schema.sql`（新建库路径**不跑迁移链**）已同步本文件终态。
--
-- ## 停止条件（fail-closed）
--   ① `inbound_orders` / `tenants` 任一不存在 ⇒ 迁移失败并停下（不 CREATE TABLE 兜底 ——
--      会造出无外键/无索引的影子表）；
--   ② 终态对账报「列缺失」/「索引形态不符」/「`source` 可空或 CHECK 未覆盖取值」
--      ⇒ 写语句判据漂移或被部分回滚 ⇒ 回滚本迁移，不硬推。
--
-- ## 显式事务（同 V97/V102/V107/V108/V111/V115 的实测口径）
--   `psql -f` 默认逐条 autocommit ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒
--   留下**半完成态**。两条执行路径（`MigrationRunner` 的 `jdbc.execute(整份文件)` 与 `psql -f`）
--   必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 前置表存在性（fail-closed：缺表立即停，不兜底建表）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(t, ', ') INTO missing
      FROM (VALUES ('tenants'), ('inbound_orders')) AS v(t)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = v.t);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V117 前置表缺失：% —— 不兜底建表（会造出无外键/无索引的影子表），迁移停下', missing;
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 单号唯一索引：全局唯一 → 租户内唯一（谓词 `deleted = 0`；**索引名不变**）
-- ══════════════════════════════════════════════════════════════════════════════════════
DROP INDEX IF EXISTS uk_inbound_orders_no;

CREATE UNIQUE INDEX IF NOT EXISTS uk_inbound_orders_no
    ON inbound_orders (tenant_id, inbound_no)
    WHERE deleted = 0;

COMMENT ON COLUMN inbound_orders.inbound_no IS
    '入库单号 RK-yyyyMMdd-NNNN（V111；V117 起**租户内唯一**）。唯一索引 = uk_inbound_orders_no (tenant_id, inbound_no) WHERE deleted = 0 —— V111 建的是**全局**唯一索引，与建表注释「租户内唯一」矛盾（issue #5148 统一口径，同族先例 uk_stock_batches_no / uk_users_tenant_worker_no）。序号由服务端原子计数器生成 + 建单前查库内占用并重试（进程重启/多副本从 0001 重走也不会撞号），DB 唯一索引仍是最后一道兜底';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 建单幂等键：`import_run_id` + **部分唯一索引**（同族先例 `uk_users_tenant_worker_no`）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE inbound_orders
    ADD COLUMN IF NOT EXISTS import_run_id VARCHAR(128);

-- 同一 (tenant_id, import_run_id) 至多一张**未软删**的单：
--   · 谓词 `import_run_id IS NOT NULL` ⇒ 普通建单（不带运行标识）不受任何影响；
--   · 谓词 `deleted = 0` ⇒ 软删行不占用运行标识（与 uk_users_tenant_worker_no 同口径）。
CREATE UNIQUE INDEX IF NOT EXISTS uk_inbound_orders_tenant_import_run
    ON inbound_orders (tenant_id, import_run_id)
    WHERE import_run_id IS NOT NULL AND deleted = 0;

COMMENT ON COLUMN inbound_orders.import_run_id IS
    '建单**运行级**幂等键（V117，issue #5148）：一次导入运行的标识（由调用方给，建议用稳定的运行 id / 批次键，勿用随机数）。同一 (tenant_id, import_run_id) 至多一张未软删的单（部分唯一索引 uk_inbound_orders_tenant_import_run）⇒ 同一份导入重跑**不会**建出第二张草稿单（也就不会两张都过账 ⇒ 库存加两次）。NULL = 普通建单，不参与去重';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 单据来源 `source` ∈ {purchase, opening}（取值约束 + 存量默认）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE inbound_orders
    ADD COLUMN IF NOT EXISTS source VARCHAR(16) NOT NULL DEFAULT 'purchase';

-- 约束幂等：先 DROP（若存在）再建，保证两遍执行同一终态。
-- 存量行与未显式指定者一律落在默认值 'purchase' 上（V111 时期只有「采购收货」一种来源）
-- ⇒ 新约束对存量**恒成立**，故可直接 VALIDATE（无需 NOT VALID 两段式）。
ALTER TABLE inbound_orders DROP CONSTRAINT IF EXISTS ck_inbound_orders_source;

ALTER TABLE inbound_orders
    ADD CONSTRAINT ck_inbound_orders_source
    CHECK (source IN ('purchase', 'opening'));

COMMENT ON COLUMN inbound_orders.source IS
    '单据来源（V117，issue #5148）：purchase 采购收货 / opening 期初建账（迁移导入）。CHECK ck_inbound_orders_source 限定这两个取值（写别的值当场 23514，不静默落库）；存量行一律 purchase。下游「批次建账」单凭它做基线冻结点（#5149：期初导入与正常采购必须能区分）';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑤ 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    n              INTEGER;
    missing        TEXT;
    constraint_def TEXT;
BEGIN
    -- ① 两列必须在（列缺失 ⇒ 幂等键/来源静默失效，重跑导入照样建重复单）
    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('import_run_id'), ('source')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'inbound_orders'
                          AND column_name = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V117 终态对账失败：inbound_orders 缺列 % —— 回滚本迁移', missing;
    END IF;

    -- ② `source` 必须 NOT NULL（可空 = 「没有来源」这种第三种状态悄悄存在）
    SELECT count(*) INTO n
      FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'inbound_orders'
       AND column_name = 'source' AND is_nullable = 'NO';
    IF n = 0 THEN
        RAISE EXCEPTION 'V117 终态对账失败：source 可为空（来源必须恒有值）—— 回滚本迁移';
    END IF;

    -- ③ CHECK 约束必须覆盖 purchase / opening（漏了它 ⇒ 取值约束形同不存在）
    SELECT pg_get_constraintdef(oid) INTO constraint_def
      FROM pg_constraint
     WHERE conname = 'ck_inbound_orders_source'
       AND conrelid = 'inbound_orders'::regclass;
    IF constraint_def IS NULL THEN
        RAISE EXCEPTION 'V117 终态对账失败：ck_inbound_orders_source 约束不存在 —— 回滚本迁移';
    END IF;
    IF constraint_def NOT LIKE '%purchase%' OR constraint_def NOT LIKE '%opening%' THEN
        RAISE EXCEPTION 'V117 终态对账失败：source 取值约束未覆盖 purchase/opening，实际 = % —— 回滚本迁移', constraint_def;
    END IF;

    -- ④ 单号唯一索引必须是**租户内**（列 = (tenant_id, inbound_no)、带 deleted 谓词）——
    --    只核索引名会漏掉「名字在、范围还是全局」这一形态（本迁移要修的正是它）
    SELECT count(*) INTO n
      FROM pg_indexes
     WHERE schemaname = 'public' AND tablename = 'inbound_orders'
       AND indexname = 'uk_inbound_orders_no'
       AND indexdef LIKE '%UNIQUE%'
       AND indexdef LIKE '%(tenant_id, inbound_no)%'
       AND indexdef LIKE '%deleted = 0%';
    IF n = 0 THEN
        RAISE EXCEPTION 'V117 终态对账失败：uk_inbound_orders_no 不是「(tenant_id, inbound_no) WHERE deleted = 0」的唯一索引（单号口径仍与注释矛盾）—— 回滚本迁移';
    END IF;

    -- ⑤ 幂等键的部分唯一索引必须在（缺它 ⇒ 重跑导入会建第二张单、库存加两次）
    SELECT count(*) INTO n
      FROM pg_indexes
     WHERE schemaname = 'public' AND tablename = 'inbound_orders'
       AND indexname = 'uk_inbound_orders_tenant_import_run'
       AND indexdef LIKE '%UNIQUE%'
       AND indexdef LIKE '%(tenant_id, import_run_id)%'
       AND indexdef LIKE '%import_run_id IS NOT NULL%';
    IF n = 0 THEN
        RAISE EXCEPTION 'V117 终态对账失败：uk_inbound_orders_tenant_import_run 缺失或形态不符 —— 同一导入重跑会建出第二张单 —— 回滚本迁移';
    END IF;
END $$;

COMMIT;
