-- 规则级 `position`（部位限定）**回归** —— 把种子里那一条部位限定写回（issue #4962）
-- （父单 #4936；上一单 #4937 的 O2 曾把该维整体清空，本文件只**有界地**回填一条）。
--
-- ## 一句话
-- `production_route_rules.position` 这条**唯一**带部位限定的种子规则
-- （`craft` / `韩褶` / `insert` / `上车布` / 锚点 `韩褶`）在**每个活跃租户**上写回
-- `position = '布帘'`（`deleted = 0` 且 `position IS NULL` 的行）。
--
-- ## 为什么只写回**一条**（而不是把 V103 整体撤销）
-- V71 的 26 条规则种子里**只有一条**带 `position`（`rr-v70-02`，逐字见该文件）；
-- V84 / V93 的加工项规则**全部不限部位**；V103 把全部存活行的该列清成了 `NULL`
-- ⇒ 「回归」的**有界**语义就是：只把那一条的值拿回来。其余规则仍一律 `NULL`（= 不限部位）。
--
-- ## 为什么必须是**新迁移**（不能改 V71 / V103）
-- `MigrationRunner` 的台账按**文件名**记账、已应用的文件**整份跳过** ⇒ 改已发布迁移
-- 只对**全新库**生效 = 「CI 全绿、功能静默缺失」（issue #4235）；且它们被
-- `tests/unit_ci_workflows/migration_fingerprints.json` 的 sha256 **逐字节冻结**。
-- 同理**不能**改 V103：它已经跑过的库不会重放，改它等于什么都没发生。
--
-- ## 覆盖范围（**按租户循环**，不是只改 1 号租户）
-- `FROM tenants t WHERE r.tenant_id = t.id AND t.deleted = 0` —— 1 号租户的那条来自 V71，
-- 非 1 号租户的同形规则来自 V93（`rr-v93-<tenant>-02`）⇒ 只改 1 号租户会让
-- 存量多租户的部位限定**永远拿不回来**（#4676 ⑥ 同款教训）。两者由**形态判据**统一覆盖
-- （不按 `id` 字面量匹配：id 前缀因租户而异，新开租的播种路径还会另起 id）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- 写语句的闸 = `r.position IS NULL` ⇒ **第二次跑匹配 0 行**（空操作，净效果一字不变）。
-- 该闸同时是**「不覆盖商家意图」闸**：某行若已被人工/商家写成非 `NULL` 值，
-- 本迁移**放过它**（不把商家的值改写成 `布帘`）。
--
-- ## 红线：**只写两列，不动对客账、不动行数**
-- 本文件**只写 `production_route_rules` 的 `position` / `updated_at` 两列**：
--   · `customer_unit_price`（元/套）**一字不动** —— 它是对客那本账，与「部位」无关；
--   · `trigger_kind` / `trigger_value` / `action` / `operation` / `after_operation` /
--     `priority` / `status` **一字不动** ⇒ 规则的**触发**与**落位**语义完全不变；
--   · **行数不变**（无 `INSERT` / 无 `DELETE` / 无 `deleted` 翻转）；
--   · **已软删行**（`deleted = 1`）**一字不动** —— 那是「商家当时这么配过」的留痕；
--   · 工序实例 / 报工流水 / 加工单快照 / 调价账 **一字不动**。
--
-- ## 回滚 SQL（**新迁移，不删 V108**；语义 = 把本迁移写回的那个值再清回 `NULL`，同 V103 的方向）
-- ```sql
-- -- V110__rollback_restore_route_rule_positions.sql（本单只登记，不落码；落码时须带显式 BEGIN/COMMIT）
-- UPDATE production_route_rules r
--    SET position = NULL,
--        updated_at = NOW()
--   FROM tenants t
--  WHERE r.tenant_id = t.id
--    AND t.deleted = 0
--    AND r.deleted = 0
--    AND r.position = '布帘'
--    AND r.trigger_kind = 'craft'
--    AND r.trigger_value = '韩褶'
--    AND r.action = 'insert'
--    AND r.operation = '上车布'
--    AND r.after_operation = '韩褶';
-- ```
-- ⚠️ 回滚谓词用 `r.position = '布帘'`（**不是** V103 那样的一刀切 `IS NOT NULL`）：
-- 一刀切会把 V108 之后商家自己写在**别的**规则上的部位一并清掉 —— 那是本迁移射程外的数据。
--
-- ## 不可复原项（回滚是**有损**的，照实登记）
-- 回滚按「形态 + 值 = `'布帘'`」清空 ⇒ **无法区分**「本迁移写回的值」与
-- 「V108 之前就被人工/运维写成同值的同形态行」—— 两者在库里**逐字相同**，
-- 回滚会把后者一起清掉。⇒ 若某行在 V108 之前被人工写过 `position`，
-- **回滚后那一条信息不可复原**（只能从该行的 `updated_at` 或库外审计日志推断）。
--
-- ## 停止条件（触发任一 ⇒ 回滚本迁移，不硬推）
--   · S1：任一活跃租户仍有「应写回而 `position` 仍为 `NULL`」的存活行（`RAISE EXCEPTION`，见文末）；
--   · S2：任一活跃租户的规则**行数**变化（本迁移只改一列的值，不增删行）；
--   · S3：`customer_unit_price` 发生变化（对客账本迁移不得触碰）；
--   · S4：`./verify-all.sh gate` 或 `python3 -m pytest tests/unit_ci_workflows/ -q` 非零。
--
-- ## 显式事务（同 V97 / V102 / V103 / V107 的实测口径）
-- `psql -f` 默认逐条 autocommit ⇒ 不显式 `BEGIN/COMMIT` 时写语句已提交、对账块才抛
-- ⇒ 留下半完成态（一部分租户拿到值、另一部分没有）。两条执行路径
-- （`jdbc.execute(整份文件)` / `psql -f 整份文件`）必须同语义。
--
-- ## bootstrap（`docs/sql/schema.sql`，**不跑迁移链**）
-- 该文件是 `docker-entrypoint-initdb.d` 的一次性建库脚本 ⇒ 它必须**自己就是终态**：
-- 本文件写回的那条字面量已在 `docs/sql/schema.sql` 的 `rr-v70-02` 行同步为 `'布帘'`
-- （两个路径的终态由 `tests/unit_ci_workflows/test_restore_route_rule_positions_migration.py`
-- 逐值比对，少同步任一侧即红）。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 写回**那一条**部位限定（按租户循环；只认 `position IS NULL` 的行）
--    `GET DIAGNOSTICS` 把本轮命中行数打出来（= 幂等闸的可观测读数：第二遍必须是 0）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    claimed INTEGER;
BEGIN
    UPDATE production_route_rules r
       SET position = '布帘',
           updated_at = NOW()
      FROM tenants t
     WHERE r.tenant_id = t.id
       AND t.deleted = 0
       AND r.deleted = 0
       AND r.position IS NULL
       AND r.trigger_kind = 'craft'
       AND r.trigger_value = '韩褶'
       AND r.action = 'insert'
       AND r.operation = '上车布'
       AND r.after_operation = '韩褶';
    GET DIAGNOSTICS claimed = ROW_COUNT;
    RAISE NOTICE 'V108 写回行数 claimed_rows=%', claimed;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 停止条件 S1：终态对账 —— 用**与写语句同一份判据**（逐字同谓词）必须查不到任何行
--    ⚠️ 判据形态说明（防下一个人把它改成「按行数等值」）：
--    这里问的是「还有没有行**仍处于等待写回的状态**」，而不是「写了几行」。
--    前者在第二遍执行时天然为 0（幂等迁移的可重复执行前提）；后者在第二遍必然不相等
--    ⇒ 写成「按行数等值」会让**第二次执行必抛**，那正是 `MigrationRunner` 明令禁止的形态。
--    它的判别力在于**判据漂移**：写语句的谓词被改窄（漏改某类行）而这里没同步 ⇒ 剩余行 > 0 ⇒ 整份回滚。
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    remaining INTEGER;
BEGIN
    SELECT count(*) INTO remaining
      FROM production_route_rules r
      JOIN tenants t ON t.id = r.tenant_id AND t.deleted = 0
     WHERE r.deleted = 0
       AND r.position IS NULL
       AND r.trigger_kind = 'craft'
       AND r.trigger_value = '韩褶'
       AND r.action = 'insert'
       AND r.operation = '上车布'
       AND r.after_operation = '韩褶';
    IF remaining > 0 THEN
        RAISE EXCEPTION 'V108 终态对账失败：仍有 % 条存活规则命中「应写回而 position 仍为 NULL」的判据（判据与写语句漂移）—— 回滚本迁移', remaining;
    END IF;
END $$;

COMMIT;
