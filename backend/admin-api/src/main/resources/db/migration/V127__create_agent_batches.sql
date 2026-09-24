-- 批量更新的批次资源（agent_batches / agent_batch_items）—— issue #5314 **服务端包**
--
-- ## 一句话
-- 给「批量更新」建它自己的**可撤销载体**：一张批次表 + 一张逐条明细表，
-- 明细里持久化每条的 `old_value`（撤销的唯一依据）与逐条 `status` / `error`
-- （部分失败逐条报告，不做整体回滚）。
--
-- ## 为什么必须有自己的表（不得复用 audit_logs）
-- 用户裁定（2026-09-24，见 `docs/wiki/agent-write-boundary.md` §五 裁定 1）：
-- **撤销是批量的准入前置** —— 批量是「一键确认 N 条 = 用户实际没看 = **盲签**」的唯一来源，
-- 单条可逆写能自愈，批量不能。
-- 而 `audit_logs` 是**有界 fail-open**（3s 超时即丢行，丢行是**允许**的，issue #4071）⇒
-- 拿它当撤销依据 = 撤销会**静默**失去依据（依据丢了不会有任何东西变红）。
-- ⇒ 撤销依据必须落在**自己的、不允许丢行**的表上。
--
-- ## 冻结契约（issue #5314 评论「批量更新能力 —— 设计 + 冻结契约（2026-09-24）」）
-- | 表 | 列 |
-- |---|---|
-- | `agent_batches` | `id, tenant_id, batch_type, status, item_count, success_count, fail_count, created_by, created_at, executed_at, reverted_at` |
-- | `agent_batch_items` | `id, batch_id, resource_id, field, old_value, new_value, status, error` |
-- 状态机：`preview → executing → done | partial → reverted | revert_partial`；
-- **不可撤销** = 状态非 `done`/`partial`、或已 `reverted`。
-- batchType 白名单：`product_price` / `product_status`（**不做通用批量**）。
--
-- ⚠️ **契约之外多一列**：`agent_batch_items.tenant_id`。本仓
-- `MybatisPlusConfig.TenantLineInnerInterceptor` 会给**每张非忽略表**注入 `tenant_id` 谓词
-- （`selectById`/`insert` 都注入）⇒ 明细表缺该列 = 每次查询/插入 SQL 报错。
-- 契约列举的列**逐字齐备**，这一列是**追加**（同时是跨租户隔离的第二道闸）。
--
-- ## 停止条件（fail-closed）
--   ① `tenants` 表不存在 ⇒ 迁移失败并停下（不兜底建表 —— 会造出无外键的影子表）；
--   ② 终态对账报「表缺失」/「契约列缺失」/「状态机约束缺失」/「白名单约束缺失」
--      ⇒ 判据漂移或被部分回滚 ⇒ 回滚本迁移。
--
-- ## bootstrap 终态同步（同 V99/V100/V108/V111/V116/V119/V122 纪律）
--   新建库路径**不跑历史迁移链**：`backend/admin-api/src/main/resources/db/init/schema.sql`
--   已同步本文件终态（两张表 + 两列租户 RLS 策略）。只改一处 ⇒ 新建库缺表 / 存量库缺列。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V128__rollback_agent_batches.sql（本单只登记，不落码）
-- -- DROP TABLE IF EXISTS agent_batch_items;
-- -- DROP TABLE IF EXISTS agent_batches;
-- ```
--   **回滚是有损的**：已经发生的「哪一批改了哪几条、改前是多少」**回不来** ——
--   而那份 `old_value` 正是撤销的依据（丢了就再也撤不回去）。属**有意**。
--
-- ## 显式事务（同 V97/V102/V107/V108/V111/V116/V119/V121/V122 的实测口径）
--   `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条
--   autocommit** ⇒ 不显式 `BEGIN/COMMIT` 时，中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
--   两条执行路径必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 前置表存在性（fail-closed：缺表立即停，不兜底建表）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'tenants') THEN
        RAISE EXCEPTION 'V127 前置表缺失：tenants —— 迁移停下（不兜底建表）';
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 批次表（一行 = 一次批量更新的生命周期）
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS agent_batches (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- product_price（商品级统一定价批量改价）/ product_status（批量上/下架）
    batch_type VARCHAR(32) NOT NULL,
    -- 状态机：preview 预演（尚未生效）→ executing → done | partial → reverted | revert_partial
    status VARCHAR(16) NOT NULL DEFAULT 'preview',
    item_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    -- 发起人（认证上下文的 userId；批量 = 盲签，必须留痕「谁按下了这一键」）
    created_by VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    executed_at TIMESTAMP WITH TIME ZONE,
    reverted_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT ck_agent_batch_type
        CHECK (batch_type IN ('product_price', 'product_status')),
    CONSTRAINT ck_agent_batch_status
        CHECK (status IN ('preview', 'executing', 'done', 'partial', 'reverted', 'revert_partial')),
    -- 计数如实：逐条结果要么成功要么失败，两者之和不得超过条目数
    CONSTRAINT ck_agent_batch_counts
        CHECK (item_count >= 0 AND success_count >= 0 AND fail_count >= 0
               AND success_count + fail_count <= item_count)
);

COMMENT ON TABLE agent_batches IS
    '批量更新的批次（issue #5314 服务端包）—— 一行 = 一次「先预演、再确认、可撤销」的批量写。状态机 preview → executing → done | partial → reverted | revert_partial；不可撤销 = 状态非 done/partial 或已 reverted';
COMMENT ON COLUMN agent_batches.batch_type IS
    '具名批量白名单（本单只两个）：product_price 商品级统一定价批量改价 / product_status 批量上·下架。**不做通用批量** —— 具名批量的可逆性与预览形态是确定的';
COMMENT ON COLUMN agent_batches.status IS
    'preview 预演（old_value 已采集、业务尚未改动）/ executing / done 全部成功 / partial 部分失败（逐条报告）/ reverted 已全部还原 / revert_partial 撤销中有条目还原失败';
COMMENT ON COLUMN agent_batches.created_by IS
    '发起人 userId（取自认证上下文，body 伪造不了）—— 批量是盲签的主要来源，必须留痕';

CREATE INDEX IF NOT EXISTS idx_agent_batches_tenant_created
    ON agent_batches (tenant_id, created_at DESC);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 逐条明细表（🔴 old_value = 撤销的唯一依据，预览阶段就落库）
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS agent_batch_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id VARCHAR(64) NOT NULL REFERENCES agent_batches(id) ON DELETE CASCADE,
    -- 见文件头「契约之外多一列」：MyBatis-Plus 租户插件会给本表注入 tenant_id 谓词
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- 资源 ID（商品 ID，逐字）：批量条目必须精确可寻址，不做名称解析
    resource_id VARCHAR(64) NOT NULL,
    -- basePrice（product_price）/ status（product_status）
    field VARCHAR(32) NOT NULL,
    -- 🔴 撤销的唯一依据：预览阶段按 DB 当前值采集并持久化（不能只在内存里）
    old_value TEXT,
    new_value TEXT,
    -- pending 未执行 / success / failed（含 error）/ reverted / revert_failed / skipped（执行阶段就失败过 ⇒ 从未生效）
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    -- 逐条失败原因（部分失败逐条报告的载体；成功为 NULL）
    error VARCHAR(500),
    CONSTRAINT ck_agent_batch_item_field
        CHECK (field IN ('basePrice', 'status')),
    CONSTRAINT ck_agent_batch_item_status
        CHECK (status IN ('pending', 'success', 'failed', 'reverted', 'revert_failed', 'skipped'))
);

COMMENT ON TABLE agent_batch_items IS
    '批量更新的逐条明细（issue #5314 服务端包）—— 一行 = 一个资源的一个字段的 before → after；old_value 是撤销的唯一依据（不得改用 audit_logs：审计有界 fail-open，丢行允许）';
COMMENT ON COLUMN agent_batch_items.old_value IS
    '改前值 = 撤销的唯一依据。预览阶段按 **DB 当前值**采集并持久化；撤销时逐条还原为它';
COMMENT ON COLUMN agent_batch_items.status IS
    'pending 未执行 / success 已生效 / failed 执行失败（见 error）/ reverted 已还原 / revert_failed 还原失败（见 error）/ skipped 执行阶段就失败过、从未生效、撤销时无需还原';
COMMENT ON COLUMN agent_batch_items.tenant_id IS
    '租户列（契约列举之外追加）：MyBatis-Plus TenantLineInnerInterceptor 会给本表注入 tenant_id 谓词，缺列即 SQL 报错；同时是跨租户隔离的第二道闸';

CREATE INDEX IF NOT EXISTS idx_agent_batch_items_batch
    ON agent_batch_items (batch_id, id);
CREATE INDEX IF NOT EXISTS idx_agent_batch_items_tenant
    ON agent_batch_items (tenant_id, batch_id);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 行级租户隔离（与全库同构；`CREATE POLICY` 无 IF NOT EXISTS ⇒ DO 块幂等包裹）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE agent_batches ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies
                    WHERE schemaname = 'public' AND tablename = 'agent_batches'
                      AND policyname = 'tenant_isolation_agent_batches') THEN
        CREATE POLICY tenant_isolation_agent_batches ON agent_batches
            USING (tenant_id::text = current_setting('app.current_tenant_id'));
    END IF;
END $$;

ALTER TABLE agent_batch_items ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies
                    WHERE schemaname = 'public' AND tablename = 'agent_batch_items'
                      AND policyname = 'tenant_isolation_agent_batch_items') THEN
        CREATE POLICY tenant_isolation_agent_batch_items ON agent_batch_items
            USING (tenant_id::text = current_setting('app.current_tenant_id'));
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑤ 终态对账（fail-closed：任一契约列 / 约束不在 ⇒ 抛错并回滚整份迁移）
--    —— 「跑完了」不等于「落对了」：部分回滚会留下一个看起来在、实际缺列的表
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(t || '.' || c, ', ') INTO missing
      FROM (VALUES
            ('agent_batches', 'id'), ('agent_batches', 'tenant_id'),
            ('agent_batches', 'batch_type'), ('agent_batches', 'status'),
            ('agent_batches', 'item_count'), ('agent_batches', 'success_count'),
            ('agent_batches', 'fail_count'), ('agent_batches', 'created_by'),
            ('agent_batches', 'created_at'), ('agent_batches', 'executed_at'),
            ('agent_batches', 'reverted_at'),
            ('agent_batch_items', 'id'), ('agent_batch_items', 'batch_id'),
            ('agent_batch_items', 'resource_id'), ('agent_batch_items', 'field'),
            ('agent_batch_items', 'old_value'), ('agent_batch_items', 'new_value'),
            ('agent_batch_items', 'status'), ('agent_batch_items', 'error'),
            ('agent_batch_items', 'tenant_id')
           ) AS v(t, c)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = v.t AND column_name = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V127 终态对账失败：缺列 %', missing;
    END IF;

    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('ck_agent_batch_type'), ('ck_agent_batch_status'), ('ck_agent_batch_counts'),
                   ('ck_agent_batch_item_field'), ('ck_agent_batch_item_status')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V127 终态对账失败：缺约束 %（状态机 / 白名单没被 DB 钉住）', missing;
    END IF;
END $$;

COMMIT;