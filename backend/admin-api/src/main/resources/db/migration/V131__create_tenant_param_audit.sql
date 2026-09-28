-- 企业参数变更留痕（tenant_param_audit）—— issue #5131 **P6**
--
-- ## 一句话
-- 给「企业参数中心」补一张**只追加**的变更账：**一行 = 一个参数键的一次变更**
-- （谁 / 何时 / 哪个域的哪个键 / 改前值 → 改后值 / 属于哪一次保存）。
--
-- ## 为什么必须有（设计文档 §6.3 的 P6）
-- 今天**没有任何**配置变更审计：算料参数**每一项都直接改米数 = 改钱**（`docs/design/tenant-params-center.md` §22 P4），
-- 改错了无法归因 —— 「谁把上下卷边从 0.3 改成 0.25 的」只能靠翻应用日志。
--
-- ## 口径裁定（用户 2026-09-26，issue #5131 评论）：**B = best-effort**
-- 审计写失败**只记日志**（+ 计数），**不让配置保存失败**。理由：这是**配置页**（不是资金流转），
-- 可用性优先；审计表是主要留痕载体，写入失败必须以**显眼的方式**留痕（结构化日志 + 计数），
-- 并且**不得静默**。⇒ 本表**不是**「配置写入的前置条件」：它不在配置写入的事务里（那是口径 A = fail-closed）。
-- 残留（如实登记）：可能出现「改了钱、查不到谁改的」—— 那条路径的日志行
-- `PARAM_AUDIT_WRITE_FAILED` 与指标 `migao.tenant_param_audit.write_failed` 就是它的可观测面。
--
-- ## 表形状的两条来源（照抄既有家法，不另造）
--   ① **只追加旁路账** = `worker_report_audits`（V98，issue #4733）：`identity_source` 记录
--      **身份是怎么确定的** ⇒ 本表同款（`actor_source`），并补一列 `actor_unknown_reason`
--      —— 「取不到身份」时记**未知 + 原因**，**不得**编一个用户出来（`actor_source='unknown'` 时该列必非空，见约束）。
--   ② **逐字段 before → after** = `agent_batch_items`（V127，issue #5314）：一行 = 一个键的
--      `old_value` → `new_value`，同一次操作的行共享一个操作 id（本表 = `operation_id`）。
--
-- ## 为什么是独立表而不是给 `craft_calc_configs` 加列
-- 审计是**无限增长**的追加账（一行一次变更），而 `craft_calc_configs` 是**单行**配置（`uk_craft_calc_configs_tenant`）；
-- 加列只能存「最后一次」，那正是「无法归因」本身。且本表**跨域**（`param_domain`）——
-- 增量 2 的「一套 PUT 覆盖六域」落地时新增域**不需要再建表/再迁移**。
--
-- ## 停止条件（fail-closed，不静默降级）
--   ① `tenants` 表不存在 ⇒ 迁移失败并停下（不兜底建表 —— 会造出无外键的影子表）；
--   ② 终态对账报「表缺失」/「契约列缺失」/「来源约束缺失」/「行级隔离缺失」⇒ 判据漂移或被部分回滚 ⇒ 回滚整份迁移。
--
-- ## bootstrap 终态同步（同 V99/V100/V108/V111/V116/V119/V122/V127 纪律）
--   新建库路径**不跑历史迁移链**：`backend/admin-api/src/main/resources/db/init/schema.sql`
--   已同步本文件终态（本表 + 两条索引 + 行级租户隔离策略）。只改一处 ⇒ 新建库缺表 / 存量库缺列。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V132__rollback_tenant_param_audit.sql（本单只登记，不落码）
-- -- DROP TABLE IF EXISTS tenant_param_audit;
-- ```
--   **回滚是有损的**：已经发生的「谁把哪个参数从 A 改成 B」**回不来**。属**有意**。
--
-- ## 显式事务（同 V97/V102/V107/V108/V111/V116/V119/V121/V122/V127 的实测口径）
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
        RAISE EXCEPTION 'V131 前置表缺失：tenants —— 迁移停下（不兜底建表）';
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 变更账（只追加；一行 = 一个参数键的一次变更）
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS tenant_param_audit (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- 参数域：craft_calc（算料，当前唯一写面）；增量 2 的六域收口按同名列追加取值，**不需要新迁移**
    param_domain VARCHAR(32) NOT NULL,
    -- 参数键（如 hem_margin / oversize_width_threshold）；**不做白名单** —— 键集随算料引擎演进
    param_key VARCHAR(64) NOT NULL,
    -- 改前 / 改后（NULL = 该键此前**没有**存储值 ⇒ 本租户当时在用引擎默认值；不是「值是空」）
    old_value TEXT,
    new_value TEXT,
    -- 谁改的（认证上下文；取不到 ⇒ 全 NULL + actor_source='unknown' + 原因，**不编用户**）
    actor_id VARCHAR(64),
    actor_name VARCHAR(64),
    -- security_context = 取自 SecurityContext 的 SecurityUser（权威）/ unknown = 无认证上下文（见 actor_unknown_reason）
    actor_source VARCHAR(16) NOT NULL,
    -- actor_source='unknown' 时**必填**：为什么归因不了（如 no_authentication_context）
    actor_unknown_reason VARCHAR(64),
    -- 操作形态：put（当前唯一写面 = 全量替换）
    operation VARCHAR(32) NOT NULL,
    -- 一次保存的身份：同一次 PUT 写下的多行共享它（日志行里也打它 ⇒ 日志 ↔ 账本可对账）
    operation_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0,
    -- 一行 = 一次变更：两个值不得相同（同值行 = 噪音，且会让「改过没有」判错）
    CONSTRAINT ck_tenant_param_audit_changed CHECK (old_value IS DISTINCT FROM new_value),
    -- 来源只在两个取值内（新的来源形态必须先改这条约束 —— 显式，不静默扩面）
    CONSTRAINT ck_tenant_param_audit_source CHECK (actor_source IN ('security_context', 'unknown')),
    -- 🔴 「不知道是谁」必须带原因：两个条件同真同假（`unknown` 而无原因 = 静默丢归因）
    CONSTRAINT ck_tenant_param_audit_unknown
        CHECK ((actor_source = 'unknown') = (actor_unknown_reason IS NOT NULL))
);

COMMENT ON TABLE tenant_param_audit IS
    '企业参数变更留痕（V131，issue #5131 P6，**只追加**）：一行 = 一个参数键的一次变更'
    '（谁 / 何时 / 哪个域哪个键 / 改前→改后 / 属于哪一次保存）。口径 = **best-effort**'
    '（用户 2026-09-26 裁定）：审计写失败只记日志 + 计数（PARAM_AUDIT_WRITE_FAILED / migao.tenant_param_audit.write_failed），'
    '**不让配置保存失败** ⇒ 本表不在配置写入的事务里';
COMMENT ON COLUMN tenant_param_audit.param_domain IS
    '参数域：craft_calc = 算料配置（当前唯一写面 = PUT /api/admin/production/craft-calc-config）；'
    '增量 2 的「一套 PUT 覆盖六域」按同名列追加取值，不需要新迁移';
COMMENT ON COLUMN tenant_param_audit.old_value IS
    '改前值。NULL = 该键此前**没有**存储值（本租户当时在用引擎默认值 / 该列尚无值）—— 不是「值是空」；'
    '配置行本身不存在时（首次保存）本列全为 NULL';
COMMENT ON COLUMN tenant_param_audit.actor_source IS
    '身份**是怎么确定的**（同 worker_report_audits.identity_source 的口径）：'
    'security_context = 取自 SecurityContext 的 SecurityUser（权威，body 伪造不了）；'
    'unknown = 无认证上下文（服务令牌 / 定时任务 / 测试），此时 actor_id/actor_name 为 NULL 且 actor_unknown_reason 必非空';
COMMENT ON COLUMN tenant_param_audit.actor_unknown_reason IS
    '为什么归因不了（仅 actor_source=''unknown'' 时非空，由 ck_tenant_param_audit_unknown 钉住）：'
    '如 no_authentication_context —— 如实记「未知 + 原因」，**不得**编一个用户或写成 system 冒充归属';
COMMENT ON COLUMN tenant_param_audit.operation_id IS
    '一次保存的身份：同一次 PUT 写下的多行共享它（应用侧同时把该 id 打进配置写入的日志行 ⇒ 日志 ↔ 账本可对账）';

CREATE INDEX IF NOT EXISTS idx_tenant_param_audit_key
    ON tenant_param_audit (tenant_id, param_domain, param_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tenant_param_audit_operation
    ON tenant_param_audit (tenant_id, operation_id);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 行级租户隔离（与全库同构；`CREATE POLICY` 无 IF NOT EXISTS ⇒ DO 块幂等包裹）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE tenant_param_audit ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies
                    WHERE schemaname = 'public' AND tablename = 'tenant_param_audit'
                      AND policyname = 'tenant_isolation_tenant_param_audit') THEN
        CREATE POLICY tenant_isolation_tenant_param_audit ON tenant_param_audit
            USING (tenant_id::text = current_setting('app.current_tenant_id'));
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 终态对账（fail-closed：任一契约列 / 约束 / 隔离不在 ⇒ 抛错并回滚整份迁移）
--    —— 「跑完了」不等于「落对了」：部分回滚会留下一个看起来在、实际缺列的表
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing TEXT;
BEGIN
    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('id'), ('tenant_id'), ('param_domain'), ('param_key'),
                   ('old_value'), ('new_value'), ('actor_id'), ('actor_name'),
                   ('actor_source'), ('actor_unknown_reason'), ('operation'),
                   ('operation_id'), ('created_at'), ('deleted')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'tenant_param_audit'
                          AND column_name = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V131 终态对账失败：tenant_param_audit 缺列 %', missing;
    END IF;

    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('ck_tenant_param_audit_changed'),
                   ('ck_tenant_param_audit_source'),
                   ('ck_tenant_param_audit_unknown')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V131 终态对账失败：缺约束 %（「一行 = 一次变更」与「未知必带原因」没被 DB 钉住）', missing;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_policies
                    WHERE schemaname = 'public' AND tablename = 'tenant_param_audit') THEN
        RAISE EXCEPTION 'V131 终态对账失败：tenant_param_audit 缺行级租户隔离策略';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = 'tenant_param_audit' AND relrowsecurity) THEN
        RAISE EXCEPTION 'V131 终态对账失败：tenant_param_audit 未启用 ROW LEVEL SECURITY';
    END IF;
END $$;

COMMIT;
