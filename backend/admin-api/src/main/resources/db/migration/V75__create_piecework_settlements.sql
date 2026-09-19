-- 计件工资**结算单**（issue #4483 = 母单 #4347 §二.4；真值源 §4）
--
-- ## 为什么需要这一层（病根）
--
-- 真值源 §4 只到「**工资报表 = 报工事件聚合**（按人/按期/按单下钻）」——
-- 报表回答「这段时间挣了多少」，但**回答不了「这笔钱结了没有」**。
-- 没有「结算」这一步，工资可以被**事后静默改写**：
-- 报工行是可增可改的（补报/返工/重新实例化都会动聚合口径），
-- 而**已经发出去的钱**不该跟着变。
--
-- ⇒ 本迁移引入两层：
--   ① `production_piecework_settlements` —— 结算单（期 × 人），金额**快照**；
--   ② `production_piecework_settlement_lines` —— 逐笔明细（真值源 §4「逐笔可追溯」）。
--
-- ## 锁定语义（本层的核心，不能省）
--
-- `status='settled'` 之后，该 `(tenant_id, period, worker)` 的报工**不得再被改动**；
-- 补报走**调整单**（新记录 + 留痕），**不回改历史** ——
-- 与既有纪律「快照冻结、不回算历史工资」（V61 / issue #4351）同源。
-- 守卫落在**报工入口**（`ProductionService.report`）：命中已结算期 ⇒ 拒绝并指名期次。
--
-- ## 不加审批环节（用户裁定 2026-09-19）
--
-- 「先做到**可核对**」—— `draft → settled` 由财务/管理**一步确认**即可，
-- 不引入多级审批状态机（那会带来「确认后改价/改配置」的回算边界，工作量与风险都显著更大）。
--
-- ## 幂等（MigrationRunner 要求所有 SQL 可重复执行）
--
-- `CREATE TABLE IF NOT EXISTS` / `CREATE UNIQUE INDEX IF NOT EXISTS` / `COMMENT ON` 天然幂等。
-- 唯一键 `(tenant_id, period, worker_key)` WHERE deleted = 0 ⇒ 同一个人同一期**只有一张结算单**
-- （重复结算 = 同一笔钱发两次，必须由**数据不变式**挡住，不能只靠应用层判重）。

CREATE TABLE IF NOT EXISTS production_piecework_settlements (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- 结算期（YYYY-MM）。与既有 pieceworkSummary 的 period 同口径（自然月）
    period VARCHAR(7) NOT NULL,
    -- 工人标识：worker_id 可空（存量报工可能没有 id）⇒ 以 worker_key 兜底（= worker_id 或姓名）
    worker_id VARCHAR(64),
    worker_key VARCHAR(128) NOT NULL,
    worker_name VARCHAR(128),
    -- 金额快照（结算那一刻聚合出来的值；此后报工再变也不回改本行）
    amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    qty NUMERIC(12,2) NOT NULL DEFAULT 0,
    line_count INTEGER NOT NULL DEFAULT 0,
    -- draft = 已生成待确认；settled = 已确认并**锁定**
    status VARCHAR(16) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'settled')),
    settled_at TIMESTAMP WITH TIME ZONE,
    settled_by VARCHAR(64),
    remark VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);

-- 同一租户 + 同一期 + 同一人 ⇒ 只有一张活跃结算单（挡「同一笔钱结算两次」）
CREATE UNIQUE INDEX IF NOT EXISTS uk_piecework_settlements_tenant_period_worker
    ON production_piecework_settlements (tenant_id, period, worker_key)
    WHERE deleted = 0;

-- 锁定判据要按 (tenant, period) 查（报工入口每次都要判）⇒ 给它一个索引
CREATE INDEX IF NOT EXISTS idx_piecework_settlements_tenant_period
    ON production_piecework_settlements (tenant_id, period)
    WHERE deleted = 0;

COMMENT ON TABLE production_piecework_settlements IS
    '计件工资结算单（V75，issue #4483 = #4347 §二.4）。一层「把报表金额冻结成应付工资」的对象：'
    'settled 后该期该人的报工不得再改（补报走调整单）。不加审批环节（用户裁定：先做到可核对）。';
COMMENT ON COLUMN production_piecework_settlements.period IS
    '结算期 YYYY-MM（自然月），与既有 pieceworkSummary 的 period 同口径。';
COMMENT ON COLUMN production_piecework_settlements.worker_key IS
    '工人唯一键（worker_id 非空取它，否则取 worker_name）—— 唯一索引用它，'
    '避免「同一个工人因缺 id 被结算两次」。';
COMMENT ON COLUMN production_piecework_settlements.amount IS
    '金额**快照**（结算那一刻的聚合值）。此后报工再变也不回改本行 —— '
    '与 V61 的报工快照同源纪律：钱一旦确定就不许被事后静默改写。';
COMMENT ON COLUMN production_piecework_settlements.status IS
    'draft = 已生成待确认；settled = 已确认并**锁定**（该期报工不可再改）。';

CREATE TABLE IF NOT EXISTS production_piecework_settlement_lines (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    settlement_id VARCHAR(64) NOT NULL REFERENCES production_piecework_settlements(id),
    -- 逐笔可追溯：指回报工行（真值源 §4）
    work_log_id VARCHAR(64) NOT NULL,
    processing_order_id VARCHAR(64),
    operation_name VARCHAR(128),
    work_date DATE,
    -- 该笔的金额快照（与报工行的 unit_price/factor 快照同源：金额在报工那一刻已固化）
    amount NUMERIC(12,2) NOT NULL DEFAULT 0,
    qty NUMERIC(12,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);

-- 同一张结算单里同一笔报工只能出现一次（重复行 = 金额被重复计入）
CREATE UNIQUE INDEX IF NOT EXISTS uk_piecework_settlement_lines_settlement_worklog
    ON production_piecework_settlement_lines (settlement_id, work_log_id)
    WHERE deleted = 0;

CREATE INDEX IF NOT EXISTS idx_piecework_settlement_lines_settlement
    ON production_piecework_settlement_lines (settlement_id)
    WHERE deleted = 0;

COMMENT ON TABLE production_piecework_settlement_lines IS
    '结算明细（V75，issue #4483）：逐笔指回 production_work_logs，'
    '满足真值源 §4「逐笔可追溯」—— 结算金额必须能拆回每一笔报工。';
COMMENT ON COLUMN production_piecework_settlement_lines.work_log_id IS
    '指回 production_work_logs.id（逐笔可追溯的锚点）。';
COMMENT ON COLUMN production_piecework_settlement_lines.amount IS
    '该笔金额快照（报工行的 unit_price/factor 在报工那一刻已固化，此处只做结算期归属）。';
