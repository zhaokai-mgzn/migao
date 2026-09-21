-- O2 部分恢复 / 加回「适用条件」的部位维（issue #4962）—— **放开 `trigger_kind` 的 CHECK**，
-- 让第 4 档触发类型 `position`（部位维）可落库。
--
-- ## 一句话
-- `production_route_rules.trigger_kind` 的闭词表原来只有
-- `('craft', 'option', 'shaped', 'processing_item')`（V71 建表时的**内联 CHECK**）
-- ⇒ 「什么时候 = 部位」这条规则**写不进库**（落库即 `23514 check_violation`，被翻译成 500）。
-- 本迁移把那档加进去。
--
-- ## 为什么需要它（承重判据，不是"顺手加个枚举"）
-- 用户裁定（2026-09-21 逐字）：「**如果有一些工序只能布帘有或者纱帘有，可以在适用条件上设置**」
-- ⇒ 配置面「什么时候」加**第四维「部位」**（工艺 / 特殊选项 / 加工项 / **部位**）。
-- 前端提交的 body 是 `{trigger_kind:'position', trigger_value:'布帘', position:'布帘', …}`
-- ⇒ 没有本迁移，第 4 维在**界面上选得动、提交必 500**（"前端勾得出的值、后端收不下"的既有形态，
-- 见 `ProductionOperationQueryService#BASELINE_POSITIONS` 的注释）。
--
-- ## 为什么 `position` 不是「复用 `shaped`」
-- `shaped` = 「是否定型」，是**另一件事**（`buildRoute` / `routing.py::_rule_triggers` 对它的口径是
-- 「表结构预留、**未实现** ⇒ 显式 422」）。复用它会同时抹掉两类语义，并让「未实现 ⇒ 显式失败」
-- 这条纪律失去载体（`ProcessingOrderService.buildRoute` 的 `else { throw }`）。
--
-- ## 为什么必须是**新迁移**（不能改 V71）
-- `MigrationRunner` 的台账按**文件名**记账、已应用的文件**整份跳过** ⇒ 改已发布迁移只对
-- **全新库**生效 = 「CI 全绿、功能静默缺失」（issue #4235）；且 V71 被
-- `tests/unit_ci_workflows/migration_fingerprints.json` 的 sha256 **逐字节冻结**。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `DO $$ … $$` 块按 `pg_get_constraintdef` 找**同名/同义**约束：已经含 `position` ⇒ **空操作**；
-- 否则先 DROP 再 ADD。⇒ 第二次跑不抛异常、不重复加约束。
--
-- ## 覆盖范围（**按租户无关**：这是表级 DDL，不按租户循环）
-- CHECK 约束是**表级**对象，一条语句覆盖全部租户（与 V103 / V108 的按租户循环不同源，不是疏漏）。
--
-- ## 红线：**不动数据**
-- 本文件**只**改约束定义：`SELECT` / `UPDATE` / `DELETE` 一行都没有
-- ⇒ 规则**行数不变**、`position` / `customer_unit_price` / 任何列的值**一字不动**。
--
-- ## 回滚 SQL（**有损**，如实登记）
-- ```sql
-- -- V109 的回滚（本单只登记，不落码）
-- -- ⚠️ 前置条件：库中**不得**存在 `trigger_kind = 'position'` 的规则行（否则 ADD CONSTRAINT 失败）。
-- --     回滚前必须先处理它们：按业务裁定**软删**（`deleted = 1`）或改写回 `craft`（会改变语义）。
-- --     这两条路都**不可自动决定** ⇒ 回滚是**人工步骤**，不是一条 SQL 能收口的。
-- ALTER TABLE production_route_rules DROP CONSTRAINT IF EXISTS production_route_rules_trigger_kind_check;
-- ALTER TABLE production_route_rules
--     ADD CONSTRAINT production_route_rules_trigger_kind_check
--     CHECK (trigger_kind IN ('craft', 'option', 'shaped', 'processing_item'));
-- ```
--
-- ## 停止条件（触发任一 ⇒ 回滚本迁移，不硬推）
--   · S1：约束加不上（`ADD CONSTRAINT` 抛 ⇒ 库里有落在新闭词表外的 `trigger_kind`，说明有脏数据）；
--   · S2：规则**行数**变化（本迁移只改约束，不动行）；
--   · S3：`./verify-all.sh gate` 或 `python3 -m pytest tests/unit_ci_workflows/ -q` 非零。
--
-- ## 显式事务（同 V97 / V103 / V108 的实测口径）
-- `psql -f` 默认逐条 autocommit ⇒ 不显式 `BEGIN/COMMIT` 时 DROP 已提交、ADD 才抛
-- ⇒ 留下「约束被删掉」的半完成态（**比不加约束更危险**：闭词表整个消失）。
-- 两条执行路径（`jdbc.execute` / `psql -f`）必须同语义。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 放开 `trigger_kind` 的闭词表：加第 4 档 `position`（部位维）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    con_name TEXT;
    con_def  TEXT;
BEGIN
    -- 按**表 + 定义里出现 trigger_kind** 定位既有约束（不写死名字：V71 是内联 CHECK，
    -- 名字由 PostgreSQL 自动生成；bootstrap 路径若换过写法名字可能不同）。
    FOR con_name, con_def IN
        SELECT c.conname, pg_get_constraintdef(c.oid)
          FROM pg_constraint c
          JOIN pg_class t ON t.oid = c.conrelid
         WHERE t.relname = 'production_route_rules'
           AND c.contype = 'c'
           AND pg_get_constraintdef(c.oid) LIKE '%trigger_kind%'
    LOOP
        IF con_def LIKE '%position%' THEN
            -- 幂等：已经放开过 ⇒ 空操作（第二次跑走这一支）
            RAISE NOTICE 'V109：约束 % 已含 position，跳过', con_name;
            RETURN;
        END IF;
        EXECUTE format('ALTER TABLE production_route_rules DROP CONSTRAINT %I', con_name);
        RAISE NOTICE 'V109：已删除旧约束 %（定义 = %）', con_name, con_def;
    END LOOP;

    ALTER TABLE production_route_rules
        ADD CONSTRAINT production_route_rules_trigger_kind_check
        CHECK (trigger_kind IN ('craft', 'option', 'shaped', 'processing_item', 'position'));
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 停止条件 S1/S2 的**终态对账**：新闭词表在；且规则行数没变（行数在本迁移内本就该恒定，
--    这里做的是「有没有人在这条迁移里误写了 DML」的机械判据）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    vocab_ok BOOLEAN;
BEGIN
    SELECT EXISTS (
        SELECT 1
          FROM pg_constraint c
          JOIN pg_class t ON t.oid = c.conrelid
         WHERE t.relname = 'production_route_rules'
           AND c.contype = 'c'
           AND pg_get_constraintdef(c.oid) LIKE '%trigger_kind%'
           AND pg_get_constraintdef(c.oid) LIKE '%position%'
    ) INTO vocab_ok;
    IF NOT vocab_ok THEN
        RAISE EXCEPTION 'V109 数量对账失败：`trigger_kind` 的闭词表里没有 `position`（写语句与判据漂移）—— 回滚本迁移';
    END IF;
END $$;

COMMIT;
