-- 存量「孤儿矩阵行」一次性清理（issue #4672，跟进 #4665 / PR #4671 的 D 项）。
--
-- ## 一句话
-- 把**工序已软删、矩阵行仍 active** 的 `production_operation_positions` 行**软删**
-- （`deleted = 1` + `updated_at`），使读面（`GET /operation-positions` / `operation-layers`）
-- 与实例化取价侧（`ProcessingOrderService.buildRoute`）**同口径** —— **不动任何历史快照**。
--
-- ## 为什么是「先查后做」而不是「读面静默过滤」（issue #4672 的红线，逐条）
-- 有人会提议「在读面把变体工序已软删的行过滤掉」。**不采用**，三条理由（issue 原文，主会话复核同意）：
--   ① 写面已治住新形态 —— `#4671` 的 `delete` / `deleteDetaching` 在**同一事务**里
--      「判护栏 → 摘格 → 级联软删矩阵行 → 软删工序行」（`matchingCells()` 单一实现，
--      显式写列，影响 0 行则 fail-closed 422）⇒ 新形态不再产生孤儿；
--   ② 该读面（`ProductionOperationQueryService.operationPositions`）**同一份数据也被实例化侧用**
--      （`ProcessingOrderService.buildRoute` 走它取价）⇒ 只给 web 加过滤 = **两处口径分裂**
--      （web 看不见、实例化照取）—— 属静默失效，比「看得见」更危险；
--   ③ 存量孤儿数量当时未查 ⇒ 不敢声称「过滤只会变好」。
-- ⇒ 本单**先查**（真库读数见下），**再在数据层一次性收口**；读面一行不改。
--
-- ## 真库实测（2026-09-20，PG 18.3 / 阿里云 RDS `ai_customer_service`）
-- 活跃租户 3（`1 词元通达` / `20 米高POC演示布艺` / `21 POC彩排5605`）；
-- 活跃矩阵行 91 / 89 / 89；工序库活跃行 36 / 36 / 36，**deleted = 1 的工序行全库仅 1 条**：
--
-- | 租户 | `production_operations`（deleted=1） | 对应活跃矩阵行 | 判定 |
-- |---|---|---|---|
-- | 1 词元通达 | `测试22`（`scope='set'`，`updated_at` 2026-09-20 08:08:03+08） | **2**（`测试22 × 布帘` ¥0.20 / `测试22 × 纱帘` ¥0.30） | **孤儿** |
-- | 20 / 21 | 无 | 0 | 无存量 |
--
-- ⇒ **存量孤儿矩阵行 = 2 条，全在租户 1**。判据命令（本迁移的 `orphans` CTE 即同一份判据）：
-- ```sql
-- SELECT p.id, p.tenant_id, p.logical_name, p.position
--   FROM production_operation_positions p
--  WHERE p.deleted = 0 AND p.status = 'active'
--    AND EXISTS (SELECT 1 FROM production_operations o
--                 WHERE o.tenant_id = p.tenant_id AND o.name = p.logical_name AND o.deleted = 1)
--    AND NOT EXISTS (SELECT 1 FROM production_operations o
--                     WHERE o.tenant_id = p.tenant_id AND o.name = p.logical_name AND o.deleted = 0);
-- ```
--
-- ## 判据口径 = 生产代码 `variantNameOf`，**不自己发明**（逐条对齐）
-- `ProductionOperationQueryService.variantNameOf(logicalName, position, catalog)` 的解析序：
--   ① `VARIANT_NAMES[logicalName][position]` 命中**且**该变体在活跃工序库 ⇒ 用它；
--   ② `position = '帘头'` 且 `VARIANT_NAMES[logicalName]['布帘']` 在活跃库 ⇒ 回落布帘变体；
--   ③ 裸逻辑名（部位无关工序）在活跃库 ⇒ 用它；④ 否则 `null`。
-- `catalog` 的来源 `catalogByName` **只取 `deleted = 0`** ⇒ 「变体工序已软删」= 该格解析不到。
--
-- 🔴 **本迁移只删「期望变体名**曾存在**、现已被软删」的格**（= issue 判据的字面形态）。
-- **不删**「期望变体名**从来不存在**」的格 —— 那是**另一回事**（该 (逻辑名, 部位) 组合从未登记），
-- 且删它有**反效果**：真库实测这类格 **105 条**（帘头占绝大多数，`opp-v70-09 三边 × 帘头` 甚至
-- 带商家显式价 ¥0.10 / `applicable = TRUE`）—— 删它 = **丢掉商家显式配过的价**，
-- 正是本仓最忌的静默失效。这类格已单独登记（见 PR body 的「分叉」节），**不在本单射程**。
-- ⇒ 判据里的 `deleted = 1` 那一半**是承重的**：去掉它就变成「按错误判据清理」（守卫有红证）。
--
-- ## 迁移号（**现取**）
-- `ls backend/admin-api/src/main/resources/db/migration | tail` 现取 ⇒ **V97**
-- （V95 被 #4715 预留、V96 被 #4741 预留；若 push 时 V97 也被占 ⇒ 取下一个空闲号并在 PR body 说明）。
--
-- ## 为什么必须是**新迁移**（不能改 V71 / V88~V94）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记账、已应用的文件**整份跳过**
-- ⇒ 改已发布迁移只对全新库生效、存量环境永远拿不到（=「CI 全绿、功能静默缺失」，issue #4235）；
-- 已发布迁移另被 `tests/unit_ci_workflows/migration_fingerprints.json` 的 sha256 逐字节冻结。
--
-- ## bootstrap 同步：**不需要**（照实登记）
-- `docs/sql/schema.sql` 该路径**不跑迁移链**，但它只种**出厂矩阵格**（V71/V72/V79 形态），
-- 真库实测**没有**任何 `测试22` 一类商家自建格（`grep -c 测试22 docs/sql/schema.sql` = 0）
-- ⇒ bootstrap 终态**结构上不可能**含本迁移要删的孤儿（孤儿只能由「商家自建工序 → 删它」
-- 产生，而 `#4671` 之后那条路径已在写面级联软删）。故本文件**不在 schema.sql 留段落**。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- ① `WHERE p.deleted = 0 AND p.status = 'active'` ⇒ 第二次跑 **0 行**（净效果相同）；
-- ② 对账 CTE 与 UPDATE 共用**同一份** `orphans` 定义 ⇒ 第二次跑对账集合为空、不抛异常
--    （**不是**「按行数等值」—— 那种写法第二次跑必抛，见守卫的红证 ③）。
--
-- ## 红线：**不动历史**（快照表一字不写）
-- 本文件**只写 `production_operation_positions` 的两列**（`deleted` / `updated_at`）：
--   · 工序实例 `processing_position_operations`（含 `operation_name` 旧名快照）**一字不动**；
--   · 报工流水 `production_work_logs` 的 `unit_price` / `factor` **一字不动**
--     ⇒ 历史工资不受影响（工资按报工流水当时落库的值结算，不按矩阵当前价回算）。
-- 核验命令见守卫 `tests/unit_ci_workflows/test_v97_orphan_positions_cleanup.py` 的真库判据。
--
-- ## 回滚（**新迁移，不删 V97**；语义 = 复活本次软删的行）
-- ```sql
-- -- V98__rollback_orphan_positions_cleanup.sql（本单只登记，不落码）
-- UPDATE production_operation_positions
--    SET deleted = 0, updated_at = NOW()
--  WHERE id IN ('f9510cea0c3f16bab579140f479835e1', '335f17c9b20bf3600dab840e53229c9f')
--    AND tenant_id = 1 AND deleted = 1;
-- ```
-- ⚠️ 回滚**按 id 逐条**（不用 `logical_name = '测试22'` 这类业务键）：本次清理的 id 集合已冻结
-- （真库读数 2 条，见上表），按 id 回滚不会误伤日后同名的新行。
--
-- ## 停止条件（触发任一 ⇒ 回滚本迁移，不硬推）
--   · S1：对账 CTE 仍查得到孤儿（`RAISE EXCEPTION`，本文件末尾）⇒ 判据与写语句漂移；
--   · S2：任一活跃租户的**快照表**行数变化（`processing_position_operations` /
--         `production_work_logs`）—— 本文件**只写配置表**；
--   · S3：`./verify-all.sh gate` 或 `python3 -m pytest tests/unit_ci_workflows/ -q` 非零；
--   · S4：清理数 > 真库读数 2 ⇒ 判据被放宽（守卫红证 ③ 钉的正是这一条）。

-- ## 🔴 显式事务（本单实测补上，**不是**装饰）
-- `MigrationRunner` 用 `jdbc.execute(整份文件)` 提交 ⇒ PG 把多语句字符串**隐式包成一个事务**，
-- 停止条件抛异常即整份回滚。但 `psql -f` **默认逐条 autocommit** ⇒ UPDATE 已提交、DO 块才抛
-- ⇒ 留下**半完成态**（本单真库判据实测：`psql` 下 `LIMIT 1` 漂移注入后 1 条被删、对账抛异常，
-- 而删除**没有**回滚）。⇒ 本文件**显式** `BEGIN; … COMMIT;`，让两条执行路径**同语义**
-- （`jdbc.execute` 下 PostgreSQL 对「已在事务里」的 `BEGIN` 只发一个 warning，无害）。
-- 守卫红证 `test_v97_reconciliation_blocks_a_partial_write` 钉的就是这条。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- 判据（唯一一份）：期望变体名**曾存在、现已被软删**的活跃矩阵格
-- ══════════════════════════════════════════════════════════════════════════════════════
-- `variant_map` = `ProductionOperationQueryService.VARIANT_NAMES` 的**逐条**字面量
-- （**30 条**显式映射 = 布帘 21 + 纱帘 7 + 帘头 1 + 布料 1；**不推导** ——
--    `布三边` / `布帘车被` 用「逻辑名 + 部位后缀」规则会漏）。
-- ⚠️ `variantNameOf` 的第 2 步「帘头回落布帘」**不在**本表里体现：它只是**回退**，
--    而本判据的 `expected` 取**本表命中值**（帘头未登记 ⇒ 落 `p.logical_name`）——
--    对「变体已软删」这一形态**两者等价**（布帘变体被软删时，`expected` 仍是那个名字）。
WITH variant_map(logical_name, position, variant_name) AS (VALUES
    -- 布帘变体（21 条）
    ('精裁',   '布帘', '精裁-布'),
    ('裁剪',   '布帘', '裁剪-布'),
    ('三边',   '布帘', '布三边'),
    ('韩褶',   '布帘', '韩褶-布'),
    ('上车布', '布帘', '上车布-布'),
    ('打孔',   '布帘', '打孔-布'),
    ('拼1次',  '布帘', '拼1次-布'),
    ('拼2次',  '布帘', '拼2次-布'),
    ('拼3次',  '布帘', '拼3次-布'),
    ('花边',   '布帘', '花边-布'),
    ('铅坠',   '布帘', '铅坠-布'),
    ('接高',   '布帘', '接高-布'),
    ('熨烫',   '布帘', '熨烫-布'),
    ('定型',   '布帘', '定型-布'),
    ('复烫',   '布帘', '复烫-布'),
    ('车被',   '布帘', '布帘车被'),
    ('绑带',   '布帘', '绑带-布'),
    ('logo条', '布帘', 'logo条-布'),
    ('立边',   '布帘', '立边-布'),
    ('扣环',   '布帘', '扣环-布'),
    ('防翘扣', '布帘', '防翘扣-布'),
    -- 纱帘变体（7 条）
    ('精裁',   '纱帘', '精裁-纱'),
    ('裁剪',   '纱帘', '裁剪-纱'),
    ('三边',   '纱帘', '纱三边'),
    ('韩褶',   '纱帘', '韩褶-纱'),
    ('上车布', '纱帘', '上车布-纱'),
    ('打孔',   '纱帘', '打孔-纱'),
    ('绑带',   '纱帘', '绑带-纱'),
    -- 帘头专属（1 条）
    ('帘头制作', '帘头', '帘头制作'),
    -- 布料（第 4 部位，issue #4707 的显式回落）
    ('裁剪',   '布料', '裁剪-布')
)
-- ⚠️ 本表必须与 `ProductionOperationQueryService.variantNames()` **逐条相等**（30 行 × 3 列）：
--    守卫 `tests/unit_ci_workflows/test_v97_orphan_positions_cleanup.py` 的
--    `test_v97_variant_map_matches_production_code` 直接解析那段 Java 源码并**双向比对**
--    （多一条 / 少一条 / 值不同 ⇒ 红）—— 判据漂移不会静默。
--
-- 🔴 写形态用 `MERGE … USING (<LEFT JOIN 派生集>)`，**不用** `UPDATE … FROM variant_map`：
--    `test_migration_references_exist_in_schema.py::_referenced_tables` 把
--    `FROM <标识符>` 读成**表引用**（它不认识 CTE）⇒ 那样写会让「表 `variant_map` 在
--    schema.sql 里不存在」判红。**不**往那份守卫的 `ALLOWLIST_TABLES` 加名字（那是放宽门禁），
--    而是换成**不产生该形态**的等价语句（`USING (<子查询>)` 的 `FROM` 后面紧跟 `(`，
--    守卫显式豁免该形态）。
MERGE INTO production_operation_positions p
USING (
    SELECT p0.id, p0.tenant_id,
           -- 🔴 期望变体名**必须**用 CASE 判「表是否命中」，**不得**写
           --    `COALESCE(v.variant_name, p0.logical_name)` —— LEFT JOIN 未命中时
           --    `v.variant_name` 是 NULL，而 `COALESCE(NULL, NULL)` 仍是 NULL
           --    ⇒ 「表未命中」的格（裸逻辑名工序）**恒假**、判据对它们静默失效 = 空断言
           --    （本单实测：那样写时注入「放宽判据」一行都不多删）。
           --    CASE 按 `v.logical_name` 判命中，命中性不依赖另一侧的列值。
           CASE WHEN v.logical_name IS NULL THEN p0.logical_name ELSE v.variant_name END AS expected
      FROM production_operation_positions p0
      LEFT JOIN variant_map v
             ON v.logical_name = p0.logical_name
            AND v.position = p0.position
     WHERE p0.deleted = 0
       AND p0.status = 'active'
       -- 「期望变体名**曾存在**」（`d.deleted = 1`）—— 判据的承重半边，不得省
       AND EXISTS (
             SELECT 1 FROM production_operations d
              WHERE d.tenant_id = p0.tenant_id
                AND d.name = CASE WHEN v.logical_name IS NULL
                                  THEN p0.logical_name ELSE v.variant_name END
                AND d.deleted = 1)
       -- 且活跃工序库里**没有**这个名字（= 该格解析不到任何变体）
       AND NOT EXISTS (
             SELECT 1 FROM production_operations a
              WHERE a.tenant_id = p0.tenant_id
                AND a.name = CASE WHEN v.logical_name IS NULL
                                  THEN p0.logical_name ELSE v.variant_name END
                AND a.deleted = 0)
) src
   ON p.id = src.id AND p.tenant_id = src.tenant_id
 WHEN MATCHED AND p.deleted = 0 AND p.status = 'active' THEN
      UPDATE SET deleted = 1, updated_at = NOW();

-- ══════════════════════════════════════════════════════════════════════════════════════
-- 停止条件 S1：数量对账 —— 清理后**同一份判据**必须查不到任何行，否则整份迁移回滚
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 判据与写语句**共用**上面那份 `variant_map` + 同一个 `EXISTS / NOT EXISTS` 形态
-- （`WITH … UPDATE` 的 CTE 只作用于该语句，故此处**重述**判据 —— 两处漂移会被本 DO 块当场抓出，
-- 这是**故意**的冗余；`test_v97_has_count_reconciliation_stop_condition` 与真库红证钉住它）。
DO $$
DECLARE
    remaining INTEGER;
BEGIN
    WITH variant_map(logical_name, position, variant_name) AS (VALUES
        ('精裁',   '布帘', '精裁-布'),
        ('裁剪',   '布帘', '裁剪-布'),
        ('三边',   '布帘', '布三边'),
        ('韩褶',   '布帘', '韩褶-布'),
        ('上车布', '布帘', '上车布-布'),
        ('打孔',   '布帘', '打孔-布'),
        ('拼1次',  '布帘', '拼1次-布'),
        ('拼2次',  '布帘', '拼2次-布'),
        ('拼3次',  '布帘', '拼3次-布'),
        ('花边',   '布帘', '花边-布'),
        ('铅坠',   '布帘', '铅坠-布'),
        ('接高',   '布帘', '接高-布'),
        ('熨烫',   '布帘', '熨烫-布'),
        ('定型',   '布帘', '定型-布'),
        ('复烫',   '布帘', '复烫-布'),
        ('车被',   '布帘', '布帘车被'),
        ('绑带',   '布帘', '绑带-布'),
        ('logo条', '布帘', 'logo条-布'),
        ('立边',   '布帘', '立边-布'),
        ('扣环',   '布帘', '扣环-布'),
        ('防翘扣', '布帘', '防翘扣-布'),
        ('精裁',   '纱帘', '精裁-纱'),
        ('裁剪',   '纱帘', '裁剪-纱'),
        ('三边',   '纱帘', '纱三边'),
        ('韩褶',   '纱帘', '韩褶-纱'),
        ('上车布', '纱帘', '上车布-纱'),
        ('打孔',   '纱帘', '打孔-纱'),
        ('绑带',   '纱帘', '绑带-纱'),
        ('帘头制作', '帘头', '帘头制作'),
        ('裁剪',   '布料', '裁剪-布')
    )
    SELECT count(*) INTO remaining
      FROM production_operation_positions p
      LEFT JOIN variant_map v
             ON v.logical_name = p.logical_name AND v.position = p.position
     WHERE p.deleted = 0
       AND p.status = 'active'
       AND EXISTS (SELECT 1 FROM production_operations d
                    WHERE d.tenant_id = p.tenant_id
                      AND d.name = CASE WHEN v.logical_name IS NULL
                                        THEN p.logical_name ELSE v.variant_name END
                      AND d.deleted = 1)
       AND NOT EXISTS (SELECT 1 FROM production_operations a
                        WHERE a.tenant_id = p.tenant_id
                          AND a.name = CASE WHEN v.logical_name IS NULL
                                            THEN p.logical_name ELSE v.variant_name END
                          AND a.deleted = 0);
    IF remaining > 0 THEN
        RAISE EXCEPTION
            'V97 数量对账失败：软删后仍有 % 条孤儿矩阵行（判据与写语句漂移）—— 回滚本迁移', remaining;
    END IF;
END $$;

COMMIT;
