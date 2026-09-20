-- O4 / 三：**价目矩阵物理去部位** —— `production_operation_positions` 按 `(tenant_id, logical_name)`
-- **塌缩为一行**，幸存行 `position` 写中性值 `通用`，其余**软删**（issue #4937 = 母单 #4936；
-- 用户裁定 2026-09-21「这个必须要改，我们移除了部位的设计，**不计成本的改**」）。
--
-- ## 一句话
-- 矩阵的键曾是 `(逻辑工序, 部位)`（30 × 4 = **120 行**/租户）。部位退场 ⇒ **每个逻辑工序只留一行**：
--   ① 幸存行 = 与 `ProductionOperationQueryService#collapseToLogical` **同一套**选行规则；
--   ② 幸存行 `position := '通用'`（部位维已退场，该列**仅作历史载体**）+ `applicable := TRUE`；
--   ③ 其余行 `deleted := 1` + `updated_at := NOW()`（**软删，不物理删** —— 退场事实必须留痕）。
--
-- ## 选行规则（**逐档与 Java / Python 同序**，不得改名换序）
-- 1. `applicable IS TRUE` 优先（`FALSE` = 当年「该部位明确不做」，其 `unit_price` 一律 `NULL`
--    ⇒ 优先它会把**有价**的工序判成未定价：`帘头制作` 布帘格 `(NULL, FALSE)` vs 帘头格 `(2.0, TRUE)`）；
-- 2. 其中 `position = '布帘'` 优先（用户裁定「取布帘价」；
--    常量 = `COLLAPSE_PRICE_SOURCE_POSITION` / Java `ProductionOperationQueryService.COLLAPSE_PRICE_SOURCE_POSITION`）；
-- 3. 再按 `position` 字典序（`COALESCE(position,'')`）；
-- 4. 最后按 `id` 升序（`COALESCE(id,'')`）。
-- ⚠️ Java 的末档是 `blankSafe(id)` 字典序（`String.compareTo`），SQL 的 `id` 排序按 collation
-- ⇒ 本迁移用 `id COLLATE "C"`（**逐字节**序）对齐 `String.compareTo`，避免在非 C collation 的库上
-- 选出与 Java **不同**的幸存行（那会让「同一张单在迁移前后取到不同的价」）。
-- ⚠️ 本迁移执行时点**在 V102 之后** ⇒ 全部存活行的 `applicable` 已是 `TRUE`
-- ⇒ 第 1 档不再区分任何行，真正的决胜档是 2/3/4（**但这 4 档必须写全**：
-- 迁移链可被单独重放到 V103 的库上、也可能被 `flyway` 之外的工具按文件名乱序执行）。
--
-- ## 为什么必须**软删**而不是物理删
--   · `production_operation_position_price_versions`（V86）按 `position_row_id` 指向矩阵行
--     —— 物理删会让**调价历史**指向不存在的行（审计链断裂）；
--   · V88 / V89 / V97 的退场事实也靠 `deleted = 1` 表达（本仓既有口径）；
--   · 回滚要能「复活」这些行（见文末回滚 SQL）。
--
-- ## 与 V88「保命格」的关系（**照实登记一处口径差异**）
-- V88 ④ 曾把 `裁剪 × 布料` 的 `applicable` 翻成 `TRUE`（保命格：存量未实例化布料单补生成工序时
-- 按**当前配置**重算，删它会静默少一道）。本迁移的塌缩会让 `裁剪` 的幸存行变成 **`裁剪 × 布帘`**
-- （布帘列优先）⇒ 那一格转 `deleted = 1`。
-- 🔴 **这不是丢功能**：V88 保命格存在的唯一理由是「`buildRoute` 在矩阵里查不到该 `(逻辑工序, 部位)` 键
-- ⇒ 静默 `continue`」—— 而本包（O1）**同时删掉了那道闸** ⇒ 键查不到不再过滤任何东西
-- ⇒ 保命格要保的那件事已由**代码结构**保证，不再需要靠数据兜底。
--   · 价不丢：`裁剪` 的价由幸存行（布帘列 ¥0.40）承载，与 V88 保命格的价（`NULL` = 未定价）**不同**
--     —— 但 `裁剪` 在 `(布帘, *)` 的所有路线里本来就走 ¥0.40（`collapseToLogical` 的既有口径），
--     空矩阵的布料单走 `FABRIC_MAINLINE_STEPS = ["裁剪","打包"]`，取到的正是 ¥0.40 / NULL。
--
-- ## 为什么必须是**新迁移**（不能改 V71 / V72 / V79 / V88 / V89 / V97）
-- `MigrationRunner` 的台账按**文件名**记账、已应用的文件**整份跳过** ⇒ 改已发布迁移只对
-- **全新库**生效 = 「CI 全绿、功能静默缺失」（issue #4235）；它们另被
-- `tests/unit_ci_workflows/migration_fingerprints.json` 的 sha256 **逐字节冻结**。
--
-- ## bootstrap 同步（`docs/sql/schema.sql`）
-- 该文件**不跑迁移链**（`docker-entrypoint-initdb.d`）⇒ 必须**一次给全终态**：本迁移落地的同一批
-- 行的 `deleted` 已在 `schema.sql` 的矩阵种子段里**直接写成终态**（同一份 120 行字面量，
-- 90 行 `deleted = 1`、30 行存活且 `position = '通用'` / `applicable = TRUE`）。
-- 守卫 = `tests/unit_ci_workflows/test_deposition_total_migration.py` 的
-- `test_bootstrap_matches_migration_chain_terminal_state`（真库跑迁移链 + 解析 schema.sql 逐行比对）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- ① `WHERE p.deleted = 0` ⇒ 第二次跑时，第一轮软删的行不再进候选，但**幸存行仍是同一批**
--    （幸存判据只看存活行 ⇒ 收敛到不动点）；
-- ② 幸存行写 `position='通用'` 后，第 2/3 档对「同一逻辑工序」只剩它自己 ⇒ 仍是它；
-- ③ 对账 CTE 与写语句**共用**同一份判据 ⇒ 第二次跑对账集合为空、不抛异常
--    （**不是**「按行数等值」—— 那种写法第二次跑必抛）。
--
-- ## 红线：**不动历史与工资**
-- 本文件只写 `production_operation_positions` 的三列（`position` / `deleted` / `updated_at`）
-- 外加 `applicable` 的收敛：
--   · `unit_price` **一字不动**（塌缩只选行，不改价 —— 落价是 V102 与买价确认的事）；
--   · 工序实例 `processing_position_operations` / 报工流水 `production_work_logs` /
--     加工单快照 `processing_orders.items_snapshot` **一字不动**；
--   · `production_operation_position_price_versions`（V86 调价账）**一字不动** —— 幸存行的
--     `id` 不变 ⇒ 账目仍指向同一行。
--
-- ## 回滚 SQL（**新迁移，不删 V104**；语义 = 复活本次软删的行）
-- ⚠️ **回滚是部分有损的**：软删的行可以按 `id` 复活，但**幸存行的 `position` 已被改成 `通用`**
-- ⇒ 回滚**必须**把它改回原部位（原值可从 `production_operation_positions` 的**已软删同名行**
-- 或 V71/V79 的种子字面量复原；本仓口径 = 种子字面量）。
-- ```sql
-- -- V106__rollback_deposition_matrix.sql（本单只登记，不落码）
-- -- ① 复活本次软删的行（除 V102/V103 之前的既有软删 —— 那些是 V88/V89/V97 的退场记录）
-- UPDATE production_operation_positions p
--    SET deleted = 0, updated_at = NOW()
--   FROM tenants t
--  WHERE p.tenant_id = t.id AND t.deleted = 0
--    AND p.deleted = 1
--    AND p.id NOT IN (SELECT id FROM production_operation_positions WHERE deleted = 1 AND updated_at < '本迁移执行时刻');
-- -- ② 幸存行的 `position` 由 `通用` 改回原部位（值从 V71/V79 的种子字面量复原；
-- --    逐行映射见 docs/sql/schema.sql 的矩阵种子段 —— 那里是同一份 120 行）
-- UPDATE production_operation_positions p
--    SET position = m.position, updated_at = NOW()
--   FROM (VALUES ('精裁','布帘'), ('裁剪','布帘'), ('三边','布帘'), ('韩褶','布帘'), ('上车布','布帘'),
--                ('打孔','布帘'), ('拼1次','布帘'), ('拼2次','布帘'), ('拼3次','布帘'), ('花边','布帘'),
--                ('铅坠','布帘'), ('接高','布帘'), ('帘头制作','布帘'), ('熨烫','布帘'), ('定型','布帘'),
--                ('复烫','布帘'), ('车被','布帘'), ('外帘打卷','布帘'), ('外帘装袋','布帘'), ('质检','布帘'),
--                ('外帘发货','布帘'), ('绑带','布帘'), ('抱枕','布帘'), ('腰靠垫','布帘'), ('logo条','布帘'),
--                ('立边','布帘'), ('扣环','布帘'), ('防翘扣','布帘'), ('配料','布帘'), ('打包','布帘')) AS m(logical_name, position)
--  WHERE p.logical_name = m.logical_name AND p.tenant_id = t.id AND p.deleted = 0
--    AND p.position = '通用';
-- ```
-- ⚠️ **回滚不能复原的东西（如实登记）**：V102 抹掉的「哪一格当年是 `applicable = FALSE`」这一信息
-- **不可逆**（回滚只能按 V71/V79 的种子重算，见 V102 的回滚 SQL 注释）。
--
-- ## 停止条件（触发任一 ⇒ 回滚本迁移，不硬推）
--   · S1：对账 CTE 仍查得到非幸存行（`RAISE EXCEPTION`，见文末）⇒ 判据与写语句漂移；
--   · S2：任一活跃租户的**快照表**行数变化（`processing_position_operations` / `production_work_logs`）；
--   · S3：任一活跃租户的 `production_operation_position_price_versions` 行数变化；
--   · S4：某个 `(tenant_id, logical_name)` 的存活行数 **≠ 1**（塌缩没收敛）；
--   · S5：`./verify-all.sh gate` 或 `python3 -m pytest tests/unit_ci_workflows/ -q` 非零。
--
-- ## 显式事务（同 V97 / V102 / V103 的实测口径）
-- `psql -f` 默认逐条 autocommit ⇒ 不显式 `BEGIN/COMMIT` 时 UPDATE 已提交、DO 块才抛
-- ⇒ 留下半完成态。两条执行路径（`jdbc.execute` / `psql -f`）必须同语义。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- 判据（唯一一份）：每个 `(tenant_id, logical_name)` 的**幸存行**
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 写成一张**物化的**临时结果（`CREATE TEMP TABLE`）而不是在两处各写一遍窗口函数：
--   · 写语句与对账块**共用同一份**幸存行集合 ⇒ 「判据漂移」不可能只漂一半；
--   · 对账不再需要重算窗口函数（`V97` 的教训：两处重述判据时，对账只能抓「写语句漏做」，
--     抓不到「两处一起用错判据」—— 这里靠**共享一份物化结果**把那个缺口关掉）。
CREATE TEMP TABLE _v104_survivors ON COMMIT DROP AS
SELECT ranked.id,
       ranked.tenant_id,
       ranked.logical_name
  FROM (
        SELECT p.id,
               p.tenant_id,
               p.logical_name,
               ROW_NUMBER() OVER (
                   PARTITION BY p.tenant_id, p.logical_name
                   ORDER BY (p.applicable IS TRUE) DESC,                       -- ① 适用行优先
                            (p.position = '布帘') DESC,                         -- ② 布帘列优先
                            COALESCE(p.position, '') COLLATE "C" ASC,           -- ③ position 字典序
                            COALESCE(p.id, '') COLLATE "C" ASC                 -- ④ id 升序（逐字节）
               ) AS rn
          FROM production_operation_positions p
          JOIN tenants t ON t.id = p.tenant_id AND t.deleted = 0
         WHERE p.deleted = 0
       ) ranked
 WHERE ranked.rn = 1;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 非幸存行**软删**（`deleted = 1` + `updated_at`，**不物理删** —— 调价账 V86 仍指向它们）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⚠️ 显式写列 + 显式写全（issue #4608 纪律）：不写 `deleted = deleted` 那类恒等式，
--    也不走 MyBatis-Plus 的 `updateById`（它会把逻辑删除字段从 SET 子句剔除 ⇒ 静默 no-op）。
UPDATE production_operation_positions p
   SET deleted = 1,
       updated_at = NOW()
 WHERE p.deleted = 0
   AND NOT EXISTS (SELECT 1 FROM _v104_survivors s
                    WHERE s.id = p.id AND s.tenant_id = p.tenant_id);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 幸存行：`position := '通用'`（中性值；该列**仅作历史载体**）+ `applicable := TRUE`
-- ══════════════════════════════════════════════════════════════════════════════════════
-- `unit_price` **一字不动**（塌缩只选行，不改价）。
UPDATE production_operation_positions p
   SET position = '通用',
       applicable = TRUE,
       updated_at = NOW()
  FROM _v104_survivors s
 WHERE p.id = s.id
   AND p.tenant_id = s.tenant_id
   AND p.deleted = 0
   AND (p.position IS DISTINCT FROM '通用' OR p.applicable IS DISTINCT FROM TRUE);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 停止条件 S1 / S4：数量对账 —— **同一份判据**必须查不到任何行，否则整份迁移回滚
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    not_collapsed INTEGER;
    multi_row     INTEGER;
    bad_position  INTEGER;
BEGIN
    -- S1：仍存在「同一逻辑工序有多个存活行」或「幸存行的 position 不是通用」
    SELECT count(*) INTO not_collapsed
      FROM production_operation_positions p
      JOIN tenants t ON t.id = p.tenant_id AND t.deleted = 0
     WHERE p.deleted = 0
       AND NOT EXISTS (SELECT 1 FROM _v104_survivors s
                        WHERE s.id = p.id AND s.tenant_id = p.tenant_id);
    IF not_collapsed > 0 THEN
        RAISE EXCEPTION
            'V104 数量对账失败：仍有 % 条存活矩阵行不是幸存行（判据与写语句漂移）—— 回滚本迁移',
            not_collapsed;
    END IF;

    -- S4：塌缩没收敛（某逻辑工序仍有多行存活 或 幸存行未写中性部位）
    SELECT count(*) INTO multi_row
      FROM (
        SELECT p.tenant_id, p.logical_name
          FROM production_operation_positions p
          JOIN tenants t ON t.id = p.tenant_id AND t.deleted = 0
         WHERE p.deleted = 0
         GROUP BY p.tenant_id, p.logical_name
        HAVING count(*) <> 1
      ) bad;
    IF multi_row > 0 THEN
        RAISE EXCEPTION
            'V104 塌缩未收敛：% 个 (租户, 逻辑工序) 的存活行数 ≠ 1 —— 回滚本迁移',
            multi_row;
    END IF;

    -- S5（issue #4937 去部位化的终态核验）：**结果态不得再有 `applicable IS NOT TRUE` 的存活行**。
    -- 这条是 V102 的收口 —— V102 只把「已是 TRUE」的行认领，`FALSE` 的那批靠本迁移的塌缩软删带走
    -- （V102 **不能**一刀切置 TRUE：那会抹掉本迁移 ① 档所需的信号，`帘头制作` 的 ¥2.00 会丢）。
    SELECT count(*) INTO bad_position
      FROM production_operation_positions p
      JOIN tenants t ON t.id = p.tenant_id AND t.deleted = 0
     WHERE p.deleted = 0
       AND p.applicable IS NOT TRUE;
    IF bad_position > 0 THEN
        RAISE EXCEPTION
            'V104 终态核验失败：仍有 % 条存活行的 `applicable` 不是 TRUE'
            '（V102 的收敛没跑 / 被单独回滚）—— 回滚本迁移', bad_position;
    END IF;

    SELECT count(*) INTO bad_position
      FROM production_operation_positions p
      JOIN tenants t ON t.id = p.tenant_id AND t.deleted = 0
     WHERE p.deleted = 0
       AND p.position IS DISTINCT FROM '通用';
    IF bad_position > 0 THEN
        RAISE EXCEPTION
            'V104 幸存行的 position 不是中性值「通用」（% 条）—— 回滚本迁移',
            bad_position;
    END IF;
END $$;

COMMIT;
