-- 供应商主数据（issue #7369，P0-1 段 1）
--
-- ## 一句话
-- 入库单上的供应商今天只是**一段文本**（`InboundLabelView` 自注「MVP 不建主数据」）⇒
-- 「同一家染厂被录成三种写法」「账期找谁对」「这家停了还在收货」全都无从机判。
-- 本表把供应商升级为**档案**：一行 = 一家供应商（名称 / 联系人 / 账期 / 状态）。
--
-- ## 为什么不复用 inbound_orders 的 supplier 文本列
-- 那是**单据上的快照**（一笔收货对应一个供应商名），基数与生命周期都不同：
-- 供应商要能改名、停用、被多张单据引用；文本列改名就要回写历史单据（改历史 = 篡改留痕）。
-- ⇒ 主数据独立成表；单据侧的引用（`supplier_id`）由本 issue 的**段 2**（采购单/收货）落地，
-- 本段只做档案本身，**不动任何既有单据的写面**。
--
-- ## 冻结契约（本单 PR body 逐字列出）
-- | 表 | 列 |
-- |---|---|
-- | `suppliers` | `id, tenant_id, name, contact_name, contact_phone, payment_terms_days, status, remark, created_at, updated_at, deleted` |
--
-- ⚠️ `tenant_id` 是**必须**的：`MybatisPlusConfig.TenantLineInnerInterceptor` 会给每张非忽略表
-- 注入 `tenant_id` 谓词（`selectById` / `insert` 都注入）⇒ 缺该列 = 每次查询/插入 SQL 报错。
--
-- ## 停止条件（fail-closed）
--   ① `tenants` 表不存在 ⇒ 迁移失败停下（不兜底建表 —— 会造出无外键的影子表）；
--   ② 终态对账报「表缺失」/「契约列缺失」/「租户 RLS 策略缺失」⇒ 整份回滚。
--
-- ## bootstrap 终态同步（同 V99/V108/V127/V133 纪律）
-- 新建库路径**不跑历史迁移链** ⇒ `backend/admin-api/src/main/resources/db/init/schema.sql`
-- 已同步本文件终态（表 + 索引 + 行级租户隔离策略 + 注释）。只改一处 ⇒ 新建库缺表。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V170__rollback_suppliers.sql（本单只登记，不落码）
-- -- DROP TABLE IF EXISTS suppliers;
-- ```
-- ⚠️ 回滚是**有损**的：已录入的供应商档案与账期会一并消失。属**有意**。
--
-- ## 显式事务
-- `MigrationRunner` 用 `jdbc.execute(整份文件)`（PG 隐式包一个事务）；而 `psql -f` 默认逐条
-- autocommit ⇒ 不显式 `BEGIN/COMMIT` 时中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
-- 两条执行路径必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS suppliers (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,
    contact_name VARCHAR(64),
    contact_phone VARCHAR(32),
    payment_terms_days INTEGER,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    remark TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    deleted BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT ck_suppliers_status CHECK (status IN ('active', 'inactive')),
    CONSTRAINT ck_suppliers_terms CHECK (payment_terms_days IS NULL OR (payment_terms_days >= 0 AND payment_terms_days <= 365))
);

-- 读面唯一路径 = 「本租户的档案列表（按名称搜）」；部分索引避开软删行
CREATE INDEX IF NOT EXISTS idx_suppliers_tenant_name
    ON suppliers (tenant_id, name)
    WHERE deleted = FALSE;

COMMENT ON TABLE suppliers IS '供应商主数据（issue #7369，P0-1 段 1）：一行 = 一家供应商。单据侧引用（supplier_id）由段 2 落地 —— 本表不参与任何既有单据写面。';
COMMENT ON COLUMN suppliers.payment_terms_days IS '账期天数：NULL = 未设置；0 = 现结；正数 = 账期（0~365，越界由 CHECK 与服务层双向拦）';
COMMENT ON COLUMN suppliers.status IS '档案状态：active 在用 / inactive 停用（停用后不可再被新单据选中，由段 2 在写面拦）';

-- 行级租户隔离（**幂等**：PG 不支持 CREATE POLICY IF NOT EXISTS ⇒
-- 照 V25/V42 的 `DO $$ + pg_policies` 范式包守卫。裸 CREATE POLICY 会在
-- bootstrap-first 库（schema.sql 已建同名策略）上抛「策略已存在」⇒ 整份回滚 + 每次启动重跑，
-- 实测口径见 issue #3615；判据 = test_migration_idempotency.py::test_new_migrations_have_no_unguarded_policy）
ALTER TABLE suppliers ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
         WHERE tablename = 'suppliers' AND policyname = 'tenant_isolation_suppliers'
    ) THEN
        CREATE POLICY tenant_isolation_suppliers ON suppliers
            USING (tenant_id::text = current_setting('app.current_tenant_id'));
    END IF;
END $$;

-- 终态对账（fail-closed）
DO $$
DECLARE
    missing_columns TEXT;
BEGIN
    IF to_regclass('public.suppliers') IS NULL THEN
        RAISE EXCEPTION 'suppliers 表缺失（issue #7369 迁移未生效）';
    END IF;

    SELECT string_agg(c, ', ')
      INTO missing_columns
      FROM unnest(ARRAY['id', 'tenant_id', 'name', 'contact_name', 'contact_phone',
                        'payment_terms_days', 'status', 'remark',
                        'created_at', 'updated_at', 'deleted']) AS c
     WHERE NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'suppliers' AND column_name = c
     );

    IF missing_columns IS NOT NULL THEN
        RAISE EXCEPTION 'suppliers 契约列缺失：%', missing_columns;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
         WHERE tablename = 'suppliers' AND policyname = 'tenant_isolation_suppliers'
    ) THEN
        RAISE EXCEPTION 'suppliers 租户 RLS 策略缺失（tenant_isolation_suppliers）';
    END IF;
END $$;

COMMIT;
