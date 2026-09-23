-- 必完（`is_must_finish`）概念整体退场 —— 存量工序库行的值收敛为 `FALSE`（列**不删**）
-- （issue #4961。用户裁定原话（逐字）：「**完工 = 全部工序全绿**」⇒ 「必完工序」这一档没了。）
--
-- ## 一句话
-- `production_operations.is_must_finish` 的 `TRUE` 语义退场：
--   ① 存量**存活行**的值一律收敛为 `FALSE`（幂等谓词见下）；
--   ② 列注释改成「历史载体：必完概念已退场」（`COMMENT ON COLUMN`）；
--   ③ 列本身**保留**（**不** DROP）：历史留痕、读面**冻结键集**（`is_must_finish` 键仍在响应里，
--      只是恒 `false`）、以及 `docs/sql/schema.sql` 的 bootstrap 终态都仍带该列 ——
--      删列会让「bootstrap-first」与「迁移链」两条路径的 schema 分叉。
--
-- ## 为什么**不**按租户循环（issue 正文写的是「按租户循环」；这里说明为什么不循环也满足其意图）
-- `production_operations.is_must_finish` 是**全局目录属性**：它是「工序库里这道工序在**任何**租户下
-- 是否算必完」的开关，而终态取值口径对**全部租户完全同构** —— 每个租户的每一行都必须是 `FALSE`，
-- **不存在**「某些租户保留 `TRUE`」这种终态。⇒ 一条**不带租户过滤**的 UPDATE 天然覆盖全部租户：
--   · 它一次命中全表存活行，**含未来新建租户的行**（播种侧
--     `backend/admin-api/src/main/java/com/migao/admin/service/ProductionSeedTemplateService.java`
--     与模板 `backend/admin-api/src/main/resources/production-templates/curtain/seed.json` 已恒 false）；
--   · 反过来，写成 `JOIN tenants` 或 `tenant_id = 1` **更弱**：会漏掉 `tenants` 表里缺席的租户行，
--     以及非 1 号租户 —— 那正是 V102/V104 **必须**按租户循环的原因（它们的判据**按租户分化**：
--     每个租户的存活价目矩阵行不同）；本迁移没有这个分化，故不需要。
-- ⇒ 「按租户循环」在此描述的是**效果**（每个租户都被覆盖），不是写法。**无需按租户循环**：
--   本迁移用「全局一条 UPDATE + 文末终态对账（存活行不得再有非 FALSE 值）」达成同一效果，
--   覆盖面**严格更大**，且覆盖面由对账块**机械核验**（不靠人读注释）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- 谓词 = `WHERE deleted = 0 AND is_must_finish IS DISTINCT FROM FALSE`
--   · `IS DISTINCT FROM FALSE` 同时命中 `TRUE` 与 `NULL`（后者是「从未被设置过」的第三态）；
--   · 第二遍执行时全部存活行已是 `FALSE` ⇒ 匹配 **0 行**、净效果相同（这就是本文件的幂等闸）；
--   · **不用** `<> FALSE`：它对 `NULL` 求值为 `NULL`（既不真也不假）⇒ `NULL` 行永远改不到、也不留痕。
-- ⚠️ 因此本文件**不能**抄 V102 那种「`GET DIAGNOSTICS claimed = 0` ⇒ 抛异常」的空跑自证
--   （第二遍**合法地**认领 0 行，照抄会让第二次执行必失败）。空跑自证改由文末的**终态对账**承担：
--   它两遍都成立，而「写语句判据漂移 / 只改了一部分行」会让它当场抛并整份回滚。
--
-- ## 红线：不动历史 / 不动快照表
-- 本文件**只写 `production_operations` 的两列**（`is_must_finish` / `updated_at`）：
--   · 工序实例快照 `processing_position_operations`（它也有 `is_must_finish` 列）**一字不动**；
--   · 报工流水 `production_work_logs` **一字不动**；
--   · 加工单快照 `processing_orders.items_snapshot` **一字不动**
--     ⇒ 历史工资与历史实例不受影响（工资按报工流水**当时**落库的值结算，不按目录当前值回算）。
--   · `deleted = 1`（已软删）行**不碰**：那批行的 `is_must_finish` 是「商家当时这么配过」的留痕，
--     且软删行不参与任何读面/判定（读面一律过滤 `deleted = 0`）。
--
-- ## 回滚 SQL（**新迁移，不删 V107**）
-- ```sql
-- -- V108__rollback_retire_must_finish_flag.sql（本单只登记，不落码）
-- -- ⚠️ **回滚是有损的**（本迁移的不可复原项，照实登记）：
-- --   ① 「哪几道工序当年被**商家手动**设成必完」这一信息已被本迁移抹平 —— 只能按**种子口径**还原
-- --      （种子口径里 `TRUE` 只有一道：`外帘装袋`，见
-- --      `backend/admin-api/src/main/resources/db/migration/V54__seed_production_operations.sql`）；
-- --   ② 商家改过的那些行**不可逐行还原**（改前值相同、来源不可区分）；
-- --   ③ 代码侧（完工判据、写面 422、读面恒 false）不在本迁移的回滚半径内 —— 只回滚数据会让
-- --      「库里有 TRUE 但没有任何代码读它」，属半完成态 ⇒ 数据回滚必须与代码回滚同批。
-- UPDATE production_operations
--    SET is_must_finish = TRUE,
--        updated_at = NOW()
--  WHERE deleted = 0
--    AND name = '外帘装袋';
-- -- 列注释一并还原：
-- COMMENT ON COLUMN production_operations.is_must_finish IS '必完工序：全绿才可打包 → 订单自动完工';
-- ```
--
-- ## 停止条件（触发任一 ⇒ 回滚本迁移，不硬推）
--   · S1：对账块报「仍有存活行的 `is_must_finish` 不是 FALSE」（写语句判据漂移 / 被部分回滚）；
--   · S2：任一**快照表**（`processing_position_operations` / `production_work_logs` /
--         `processing_orders.items_snapshot`）的行数或内容变化；
--   · S3：`./verify-all.sh gate` 或 `python3 -m pytest tests/unit_ci_workflows -q --tb=short` 非零。
--
-- ## 显式事务（同 V97 / V102 的实测口径）
-- `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条
-- autocommit** ⇒ 不显式 `BEGIN/COMMIT` 时，UPDATE 已提交、DO 块才抛 ⇒ 留下**半完成态**。
-- 两条执行路径必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 存量**存活行**：`is_must_finish` 收敛为 FALSE（列保留；已软删行不碰）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⚠️ 显式写 `updated_at`（issue #4608 纪律：不用 MyBatis-Plus 的 NOT_NULL 策略那套 ——
--    它会把 `null` 字段从 SET 子句剔除 ⇒ 静默 no-op，本仓踩过）。
-- ⚠️ **不**按租户过滤：该列是全局目录属性，见文件头「为什么不按租户循环」。
UPDATE production_operations
   SET is_must_finish = FALSE,
       updated_at = NOW()
 WHERE deleted = 0
   AND is_must_finish IS DISTINCT FROM FALSE;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 列注释 → 「历史载体」（「概念已退场」这件事必须在**库里**可见，而不只在代码注释里）
-- ══════════════════════════════════════════════════════════════════════════════════════
COMMENT ON COLUMN production_operations.is_must_finish IS
    '历史载体：必完概念已退场（issue #4961：完工 = 全部工序全绿）；值恒 FALSE';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    remaining      INTEGER;
    column_present INTEGER;
BEGIN
    -- ① 列必须仍在（**先判这条**）：本迁移只许改值 + 改注释，**不许** DROP 列 ——
    --    列是历史载体，且读面冻结键集与 `docs/sql/schema.sql` 的 bootstrap 终态都仍带它。
    --    ⚠️ 先判列存在性，是为了让这条护栏**可被单独注入打红**：若先去数「非 FALSE 的行」，
    --    列一旦被删，报错来自「列不存在」的 SQL 错（判据在场的证据就丢了）。
    SELECT count(*) INTO column_present
      FROM information_schema.columns
     WHERE table_name = 'production_operations'
       AND column_name = 'is_must_finish';
    IF column_present = 0 THEN
        RAISE EXCEPTION
            'V107 红线被破：production_operations.is_must_finish 列不存在 —— 只许改值 + 改注释，不许 DROP 列 —— 回滚本迁移';
    END IF;

    -- ② 终态：存活行不得再有「非 FALSE」的值（`NULL` 也算 —— 它是「从未被设置过」的第三态）
    SELECT count(*) INTO remaining
      FROM production_operations
     WHERE deleted = 0
       AND is_must_finish IS DISTINCT FROM FALSE;
    IF remaining > 0 THEN
        RAISE EXCEPTION
            'V107 数量对账失败：仍有 % 条存活行的 is_must_finish 不是 FALSE（写语句判据漂移 / 被部分回滚）—— 回滚本迁移',
            remaining;
    END IF;
END $$;

COMMIT;
