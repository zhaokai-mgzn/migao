-- V156 — 计件**结算单**载体（issue #5653，本波交付 = 结算 + 留痕）
--
-- ## 一句话
-- 一行 = 「某租户 × 某期间（`YYYY-MM`）× 某工人」的**应发金额凭证**（**生成即冻结的快照**）。
-- 本轮只有结算单 + 生成/作废留痕；**发放 / 发放状态字段 / 导出 / 与财务域耦合都不在本轮**
-- （用户 2026-10-16 裁定的范围收窄 + 口径裁定，逐字见 issue #5653 的两条评论）。
--
-- ## 为什么新建载体，而不是塞进 `finance_transactions`
-- ① 财务域今天只有 `finance_transactions` + `tenant_payment_qrcodes`，`FinanceService` 对
--    `piecework` / `work_log` / `production` **零匹配**（issue #5653 现状表逐字）；把工资塞进去
--    = 在**未裁定**的口径下把两个域耦合起来（本单最后一条前置明写「是否并入财务域」待裁定）；
-- ② 结算单的语义是**凭证**（生成即冻结、要改就作废重开），分录的语义是**记账**（可冲正）——
--    两者的可变性模型不同，同表会逼出一列「这一行属于哪种可变性」的假区分。
--
-- ## 金额与报表**同源**（本表最重要的一条，别在这里做任何算数）
-- `total_amount` 是生成那一刻 `GET /api/admin/production/piecework/summary?period=…&worker_name=…`
-- 的 `total` 的**逐值**快照；`line_items` 是同一响应 `per_operation` 的三键同源子集
-- （`operation` / `qty` / `amount`）。⇒ 结算侧**不重算**（那是「同一真值两处投影」）。
-- 聚合本身仍只有一份（`ProductionService.aggregate`）。
--
-- ## 「生成即冻结」怎么被机械保证
-- ① **没有改的路径**：本表字段没有任何 UPDATE 金额 / 期间 / 工人的 SQL（`PieceworkSettlementMapper`
--    只有 `insertActiveIfAbsent` 与 `voidActive` 两条写语句；`voidActive` 的 SET 子句只有
--    `voided_at` / `voided_by` / `void_reason` / `updated_at`）；
-- ② **期间唯一性**：部分唯一索引 `uk_piecework_settlements_active`
--    （`tenant_id, period, worker_name` WHERE `voided_at IS NULL AND deleted = 0`）
--    ⇒ 同期间同工人**至多一张生效单**，作废后可以重开（旧行仍在表里 = 留痕）；
-- ③ **原子闸**：生成走 `INSERT … ON CONFLICT (…) WHERE voided_at IS NULL AND deleted = 0 DO NOTHING`
--    ⇒ 并发重复生成**不会**抛 `DuplicateKeyException`（那是 HTTP 500），而是返回 0 行 ⇒ 服务层给具名 409。
--
-- ## 为什么作废用「置 `voided_at`」而不是软删（`deleted = 1`）
-- 留痕要求旧单**可查**（谁 / 何时 / 作废哪个期间×工人 / 为什么）；软删会让它从默认读面消失，
-- 而「作废」在业务上是**一次有意义的动作**，不是「这行不该存在」。⇒ `deleted` 列本表**恒 0**，
-- 保留它只为与仓内既有的 MyBatis-Plus 逻辑删列约定一致（`logic-delete-field: deleted`）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `CREATE TABLE IF NOT EXISTS` / `CREATE UNIQUE INDEX IF NOT EXISTS` ⇒ 第二遍净效果相同。
--
-- ## 回滚（**可执行**，不是散文）
--
-- 下面每一条以 `-- -- ` 开头 = **真的 SQL**（顺序即安全顺序）。⚠️ **有损**：回滚会丢掉已生成的
-- 结算单与作废留痕（那是一段经营账目）⇒ 落地后不要回滚，改往前修。
--
-- -- DROP INDEX IF EXISTS uk_piecework_settlements_active;
-- -- DROP TABLE IF EXISTS piecework_settlements;

BEGIN;

CREATE TABLE IF NOT EXISTS piecework_settlements (
    id           VARCHAR(64) PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenants(id),
    -- 期间键 YYYY-MM（跨月隔离的唯一键成分；服务端解析校验后落库，不接受任意文本）
    period       VARCHAR(7) NOT NULL,
    worker_name  VARCHAR(64) NOT NULL,
    -- 应发金额（元）= 生成那一刻 piecework/summary 的 total（逐值快照，不在本表重算）
    total_amount NUMERIC(14,2) NOT NULL,
    -- 明细快照（该工人在该期间的按工序读数；每项 {operation, qty, amount}）
    line_items   JSONB NOT NULL DEFAULT '[]'::jsonb,
    generated_by VARCHAR(64),
    generated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    -- 作废留痕（NULL = 仍然有效）；作废不物理删、不软删
    voided_at    TIMESTAMP WITH TIME ZONE,
    voided_by    VARCHAR(64),
    void_reason  TEXT,
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted      INTEGER NOT NULL DEFAULT 0
);

-- 活跃单唯一（部分唯一索引：作废行与软删行不占位 ⇒ 作废后可重开、旧行仍留痕）
CREATE UNIQUE INDEX IF NOT EXISTS uk_piecework_settlements_active
    ON piecework_settlements (tenant_id, period, worker_name)
    WHERE voided_at IS NULL AND deleted = 0;

-- 列表面（按租户 × 期间读）
CREATE INDEX IF NOT EXISTS idx_piecework_settlements_tenant_period
    ON piecework_settlements (tenant_id, period, worker_name);

COMMENT ON TABLE piecework_settlements IS
    '计件结算单（V156，issue #5653）：一行 = 某租户 × 某期间(YYYY-MM) × 某工人的应发金额凭证（生成即冻结）。金额与 line_items 逐值来自 piecework/summary 的同一次读数（结算侧不重算）。作废 = 置 voided_at 留痕（不物理删、不软删）；活跃单在同租户同期间同工人上唯一 ⇒ 要改就作废重开。本轮不做：发放状态字段 / 发放动作 / 导出 / 与财务域耦合';
COMMENT ON COLUMN piecework_settlements.total_amount IS
    '应发金额（元，NUMERIC(14,2)）= 生成那一刻 GET /production/piecework/summary 的 total 的逐值快照；服务端计算，前端不参与';
COMMENT ON COLUMN piecework_settlements.line_items IS
    '明细快照（JSONB 数组，每项 {operation, qty, amount}）= 同一次 piecework/summary 响应 per_operation 的同源子集；只读不改';
COMMENT ON COLUMN piecework_settlements.voided_at IS
    '作废时刻（NULL = 生效中）。作废只置本列 + voided_by + void_reason —— 金额/期间/工人/明细一字不动（「作废 ≠ 改写」由 SQL 文本机械保证）';

-- 终态对账：写错列名 / 漏建唯一索引 / 谓词写漏必须**当场停**，
-- 而不是留一个「看着在、其实没钉住」的迁移（本仓迁移写错了不会重跑 ⇒ 静态判据是唯一出口）
DO $$
DECLARE
    column_type TEXT;
    index_def TEXT;
BEGIN
    SELECT data_type INTO column_type
      FROM information_schema.columns
     WHERE table_name = 'piecework_settlements' AND column_name = 'total_amount';
    IF column_type IS NULL THEN
        RAISE EXCEPTION 'V156 终态对账失败：piecework_settlements.total_amount 列不存在 —— 回滚本迁移';
    END IF;

    SELECT indexdef INTO index_def FROM pg_indexes
     WHERE indexname = 'uk_piecework_settlements_active'
       AND tablename = 'piecework_settlements';
    IF index_def IS NULL THEN
        RAISE EXCEPTION 'V156 终态对账失败：uk_piecework_settlements_active 不存在 —— 回滚本迁移';
    END IF;
    IF index_def NOT LIKE '%UNIQUE%' THEN
        RAISE EXCEPTION 'V156 终态对账失败：uk_piecework_settlements_active 不是唯一索引（实际 = %）'
            ' —— 回滚本迁移', index_def;
    END IF;
    -- 谓词两条都要在：漏 voided_at IS NULL ⇒ 作废后**永远不能重开**（期间唯一性把历史单也锁住）；
    -- 漏 deleted = 0 ⇒ 该索引对软删行零约束力（同族形态：V155 的部分唯一索引注记）
    IF index_def NOT LIKE '%voided_at IS NULL%' OR index_def NOT LIKE '%deleted = 0%' THEN
        RAISE EXCEPTION 'V156 终态对账失败：部分唯一索引谓词不完整（实际 = %）—— 回滚本迁移', index_def;
    END IF;
END $$;

COMMIT;
