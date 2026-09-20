-- O2 / 二：**规则级 `position`（部位限定）退场** —— 存量行的值清空为 `NULL`
-- （issue #4937 = 母单 #4936；用户裁定 2026-09-21「我们移除了部位的设计，**不计成本的改**」）。
--
-- ## 一句话
-- `production_route_rules.position` 的**值全部清空**（`deleted = 0` 的行）。**列保留**
-- （历史载体；它同时是**部分唯一索引** `uk_production_route_rules_tenant_trigger_operation`
-- 的成员 —— 见 `docs/sql/schema.sql` 的 `COALESCE(position,'')`），但**不再有任何消费者**：
-- 本包同批删掉了「怎么展开路线」的**两份实现**里的那两处筛选
-- （Java `ProcessingOrderService.buildRoute` / `insertConditionalOperations`；
-- Python 真值源 `app/production/routing.py::build_route_v2`）。
--
-- ## 为什么必须把值也改掉（而不是只删代码）
-- 只删代码不改值 ⇒ 库里留着一条**永不生效**的筛选条件 ⇒ 「规则已落库但永不生效」正是本仓
-- 明令要显式失败的形态（见 `routing.py::_rule_triggers` 对 `shaped` 触发类型的处理）。
-- 值清空后，「这条规则限哪个部位」这句话**在数据上不可表达** —— 与「部位退场」同语义，
-- 不会给下一个人留下「看起来还生效」的假象。
--
-- ## 为什么必须是**新迁移**（不能改 V71 / V72 / V84 / V93）
-- `MigrationRunner` 的台账按**文件名**记账、已应用的文件**整份跳过** ⇒ 改已发布迁移只对
-- **全新库**生效 = 「CI 全绿、功能静默缺失」（issue #4235）；且它们被
-- `tests/unit_ci_workflows/migration_fingerprints.json` 的 sha256 **逐字节冻结**。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `WHERE r.deleted = 0 AND r.position IS NOT NULL` ⇒ 第二次跑匹配 **0 行**（空操作）。
--
-- ## 覆盖范围（**按租户循环**，不是只改 1 号租户）
-- `FROM tenants t WHERE r.tenant_id = t.id AND t.deleted = 0` —— V71 / V72 / V84 / V93 四条
-- 种子路径都按租户种行；只改 1 号租户会让非 1 号租户的旧值留在库里（#4676 ⑥ 同款教训）。
--
-- ## 红线：**不动历史与对客账**
-- 本文件**只写 `production_route_rules` 的 `position` / `updated_at` 两列**：
--   · `customer_unit_price`（元/套）**一字不动** —— 它是对客那本账，与「部位」无关；
--   · `operation` / `after_operation` / `priority` / `action` / `trigger_*` **一字不动**
--     ⇒ 规则的**触发**与**落位**语义完全不变（本迁移只删「部位限定」这一层筛选）；
--   · 工序实例 / 报工流水 / 加工单快照 **一字不动**。
--
-- ## 回滚 SQL（**新迁移，不删 V103**；语义 = 还原 V71 种子的**唯一一条**部位限定）
-- ⚠️ **回滚是有损的**：V71 的 26 条种子里**只有一条**带 `position`（`韩褶 → insert 上车布`，
-- `position = '布帘'`）；V84 / V93 的加工项规则**全部不限部位**。⇒ 回滚只需还原那一条。
-- ```sql
-- -- V106__rollback_clear_route_rule_positions.sql（本单只登记，不落码）
-- UPDATE production_route_rules r
--    SET position = '布帘', updated_at = NOW()
--   FROM tenants t
--  WHERE r.tenant_id = t.id
--    AND t.deleted = 0
--    AND r.deleted = 0
--    AND r.trigger_kind = 'craft'
--    AND r.trigger_value = '韩褶'
--    AND r.action = 'insert'
--    AND r.operation = '上车布'
--    AND r.position IS NULL;
-- ```
--
-- ## 停止条件（触发任一 ⇒ 回滚本迁移，不硬推）
--   · S1：任一活跃租户仍有 `position IS NOT NULL` 的存活行（`RAISE EXCEPTION`，见文末）；
--   · S2：任一活跃租户的规则**行数**变化（本迁移只清一列的值，不删行）；
--   · S3：`customer_unit_price` 发生变化（对客账本迁移不得触碰）；
--   · S4：`./verify-all.sh gate` 或 `python3 -m pytest tests/unit_ci_workflows/ -q` 非零。
--
-- ## 显式事务（同 V97 / V102 的实测口径）
-- `psql -f` 默认逐条 autocommit ⇒ 不显式 `BEGIN/COMMIT` 时 UPDATE 已提交、DO 块才抛
-- ⇒ 留下半完成态。两条执行路径（`jdbc.execute` / `psql -f`）必须同语义。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 清空**存活**规则的 `position`
-- ══════════════════════════════════════════════════════════════════════════════════════
UPDATE production_route_rules r
   SET position = NULL,
       updated_at = NOW()
  FROM tenants t
 WHERE r.tenant_id = t.id
   AND t.deleted = 0
   AND r.deleted = 0
   AND r.position IS NOT NULL;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 停止条件 S1：数量对账 —— **同一份判据**必须查不到任何行，否则整份迁移回滚
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    remaining INTEGER;
BEGIN
    SELECT count(*) INTO remaining
      FROM production_route_rules r
      JOIN tenants t ON t.id = r.tenant_id AND t.deleted = 0
     WHERE r.deleted = 0
       AND r.position IS NOT NULL;
    IF remaining > 0 THEN
        RAISE EXCEPTION
            'V103 数量对账失败：仍有 % 条存活规则的 position 不为 NULL（判据与写语句漂移）—— 回滚本迁移',
            remaining;
    END IF;
END $$;

COMMIT;
