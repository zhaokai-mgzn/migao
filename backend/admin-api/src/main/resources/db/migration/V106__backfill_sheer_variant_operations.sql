-- 补 **4 道纱帘变体工序行** —— **按租户循环 backfill 存量多租户**
-- （issue #4937 = 母单 #4936；本文件是 review 指出的**真缺口**的修复）。
--
-- ## 一句话
-- 对**每一个**「已有 4 个 `-布` 变体（`熨烫-布` / `定型-布` / `复烫-布` / `布帘车被`）
-- 但缺 4 个 `-纱` 变体」的活跃租户，补那 4 行（单价**逐字取对应 `-布` 变体** —— 不发明单价）。
--
-- ## 为什么必须有本文件（**`V105` 单独不够**）
-- `V105` 是**字面量种子（只种 `tenant_id = 1`）**（它要留在三源收敛守卫的比对射程里，见该文件头）。
-- 而 `V54` / `V56` / `V79` 的工序种子**同样只种 1 号租户** —— 非 1 号租户的工序库来自
-- **开租播种**（`ProductionSeedTemplateService`，模板里这 4 行是**本包才补上**的）或
-- `V91` 的 backfill（**早于本包**，不含这 4 行）。
-- ⇒ 存量非 1 号租户在 `applicable` 过滤退场后**必然**走 `熨烫/定型/复烫/车被`，
--   而库里没有它们的纱帘变体 ⇒ `variantNameOf` 返回 `null` ⇒ **该租户的每一张纱帘单都 422**。
-- ⇒ 这不是「少一行数据」，是**把非 1 号租户的纱帘下单能力打掉** ⇒ 必须按租户补。
--
-- ## 形态**照 `V91__backfill_baseline_operations_for_empty_catalogs.sql`**（同一范式，不发明第二套）
-- `INSERT … SELECT … FROM tenants t CROSS JOIN (SELECT … UNION ALL SELECT …) AS r` + 逐行 `NOT EXISTS`。
--
-- ## 🔴 为什么用 `UNION ALL SELECT` 而不是派生表行值构造 / CTE
-- （V91 文件头逐字写过的两个坑，本文件同样适用）
--   ① **派生表行值构造**（`CROSS JOIN (` + 行值关键字 + ` …)`）：
--      `tests/unit_ci_workflows/test_production_catalog_seed.py` 的 `parse_seed` 用
--      「`INSERT INTO <table>` … 该关键字」抓种子行 ⇒ 会把**派生表里**的那一段当成种子行
--      （列数不符 ⇒ **假红**）。
--      🔴 **本注释里也绝不能写出那个关键字**（实测踩过）：`parse_seed` 的正则含 `[^;]*?`
--      （可跨行），注释里的那个词会被当成**真语句的一部分**，让本迁移被判成「字面量种子源」
--      且解析出错误的行 ⇒ `test_seed_matches_python_catalog` 直接红。
--   ② **CTE**（`WITH x AS (` + 同关键字 + ` …)`）：
--      `tests/unit_ci_workflows/test_migration_references_exist_in_schema.py` 把 `FROM <标识符>`
--      一律当表名做存在性校验 ⇒ CTE 名会被判「表不存在」（同样假红）。
--   ⇒ `UNION ALL SELECT` 两个坑都不踩。
--
-- ## 🔴 类型显式（**V79 的真库事故教训**，V91 同款）
-- `unit_price` 逐行 `::numeric`、`sort_order` 逐行 `::integer` —— 不写就复现 V79 的推断坑
-- （派生表整列 NULL 被推断成 `text`，而 `text → numeric` **不是赋值转换**
-- ⇒ 整文件单事务回滚、`schema_migrations` 里该版本永久缺席）。
--
-- ## 命名规则（**不可复用 1 号租户的确定性 id**）
-- `id = 'op-v106-' || <tenant_id> || '-' || <一位序号>`（与 V91 的 `op-v91-<tenant_id>-NN` 同款）。
-- ⚠️ **不得**给别的租户复用 `op-v56-06..09`（那是 1 号租户的 id，会撞 `id` 主键）；
-- `uk_production_operations_tenant_name` 是 `(tenant_id, name)` 的部分唯一索引 ⇒ **名字**天然按租户
-- 唯一，而 **id** 必须自带租户段。
--
-- ## 闸门：**只在「4 个 `-布` 变体齐全 且 4 个 `-纱` 变体全缺（未软删）」时补**
--   · 前者 = 该租户的工序库确实有这套基线（**不无中生有**：工序库从未种过的租户**一行都不插**；
--     那类租户由 `V91` 先补基线，之后本迁移再补这 4 道 —— 顺序由版本号 91 → 106 保证）；
--   · 后者 = **幂等闸**（已补过的租户整块跳过；1 号租户被 `V105` 种过 ⇒ 这里自动跳过）；
--   · **不覆盖商家改动**：本文件**没有任何** `UPDATE` / `DELETE`，`NOT EXISTS` 按
--     `(tenant_id, name) WHERE deleted = 0`（对齐 V49 的部分唯一索引）。商家改过这 4 行的价
--     ⇒ 行已存在 ⇒ 本迁移不碰。
--   · 🔴 **软删行永久不动**（红线）：闸门只数 `deleted = 0`，而本文件**从不**把任何行置
--     `deleted = 0` ⇒ 商家/历史软删的那一行**一字不动**（不会被「复活」）。
--     ⚠️ **已知边界，照实登记**：若某租户「4 行里有 1 行已被软删、其余 3 行在」⇒
--     ① 的闸门整块跳过（`count(*) = 3 ≠ 0`）而 ② 的对账判 `count(DISTINCT …) = 3 ≠ 4`
--     ⇒ **整份迁移回滚**（fail-loud：让它红在下一次 `verify-all` / 部署上，
--     而不是把该租户的下单能力留成死状态）。补那一行的正确做法是**新开一条迁移**
--     （单行 `NOT EXISTS` + 不碰软删行），不在本文件射程内。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- ① 闸门（4 个 `-纱` 全缺）⇒ 已补过的租户整块跳过；
-- ② 逐行 `NOT EXISTS`（业务唯一键）；
-- ③ `ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING` 兜底。
-- ⇒ 第二次执行匹配 0 行、净效果相同。
--
-- ## bootstrap（`docs/sql/schema.sql`）的边界（**照实登记**）
-- 该文件是 `docker-entrypoint-initdb.d` 的**单租户建库脚本**（只种 `tenant_id = 1`），
-- 且该栈**不跑迁移链** ⇒ 它只需种 1 号租户那 4 行（已种）。
-- **存量多租户 / 非 1 号租户由本迁移的循环覆盖** —— 两者的受众不重叠，
-- 不需要（也不应该）让 bootstrap 去循环。
--
-- ## 为什么是**新迁移**（不能改 V54 / V56 / V105）
-- `MigrationRunner` 的台账按**文件名**记账、已应用的文件**整份跳过** ⇒ 改已发布迁移只对
-- **全新库**生效 = 「CI 全绿、功能静默缺失」（issue #4235）；它们另被
-- `tests/unit_ci_workflows/migration_fingerprints.json` 的 sha256 **逐字节冻结**。
--
-- ## 回滚 SQL（**新迁移，不删 V106**；语义 = 撤掉本次 backfill 的行）
-- ```sql
-- -- V107__rollback_sheer_variant_backfill.sql（本单只登记，不落码）
-- UPDATE production_operations o SET deleted = 1, updated_at = NOW()
--   FROM tenants t
--  WHERE o.tenant_id = t.id AND t.deleted = 0
--    AND o.id LIKE 'op-v106-%' AND o.deleted = 0;
-- ```
-- ⚠️ **回滚后这些租户的纱帘单会重新 fail-closed 422**（回到缺陷）—— 仅在确认业务可接受时执行。
-- ⚠️ 若这 4 行已被报工引用（`production_work_logs.operation_name`），回滚**必须**用软删
-- （`deleted = 1`，上面就是软删）而不是 `DELETE`。
--
-- ## 停止条件（触发任一 ⇒ 回滚本迁移，不硬推）
--   · S1：存在「4 个 `-布` 齐 且 4 个 `-纱` 缺」的活跃租户（`RAISE EXCEPTION`，见文末）；
--   · S2：任一**快照表**行数变化（本文件只写 1 张**配置**表）；
--   · S3：某租户的工序库行数因本迁移**减少**（本文件只有 `INSERT`，出现即异常）；
--   · S4：重复执行净效果不同（跑两遍逐表 `count(*)` + 全行指纹一致）；
--   · S5：`./verify-all.sh gate` 或 `python3 -m pytest tests/unit_ci_workflows/ -q` 非零。
--
-- ## 🔴 红线：三张快照表**一字不动**（本文件的 DML 只碰 1 张**配置**表）
--   · `processing_orders.items_snapshot`（加工单快照）
--   · `processing_position_operations`（工序实例快照；⚠️ 与 `production_operation_positions`
--     **名字极像**，本文件**两张都不写**）
--   · `production_work_logs.unit_price` / `factor`（报工快照；历史工资不回溯）
--
-- ## 显式事务（同 V91 / V97 / V102 / V103 / V104 的实测口径）
-- `psql -f` 默认逐条 autocommit ⇒ 不显式 `BEGIN/COMMIT` 时 INSERT 已提交、DO 块才抛
-- ⇒ 留下半完成态。两条执行路径（`jdbc.execute` / `psql -f`）必须同语义。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 按租户 backfill（4 行 × 每个「`-布` 齐 且 `-纱` 全缺」的活跃租户）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 形态与 V91 同款：**1 条 `INSERT … SELECT`**，4 行由 `CROSS JOIN (SELECT … UNION ALL …) AS r` 提供
-- （清单只写一份 ⇒ 闸门与逐行守卫都不需要第二份名单）。
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, status, deleted, scope)
SELECT 'op-v106-' || t.id::text || '-' || r.seq::text,
       t.id, r.name, '后道', '纱帘', '米', r.unit_price,
       FALSE, FALSE, r.sort_order, 'active', 0, 'position'
  FROM tenants t
  CROSS JOIN (
      -- 第一行带列别名（`UNION ALL` 的类型也由它钉住：`::numeric` / `::integer` 逐行显式）
      SELECT '熨烫-纱' AS name, 0.35::numeric AS unit_price, 38 AS sort_order, 1 AS seq
      UNION ALL SELECT '定型-纱', 0.40::numeric, 39, 2
      UNION ALL SELECT '复烫-纱', 0.35::numeric, 40, 3
      UNION ALL SELECT '车被-纱', 0.40::numeric, 41, 4
  ) AS r
 WHERE t.deleted = 0
   -- 闸门①：4 个 `-布` 变体**齐全**（不无中生有 —— 工序库从未种过的租户交给 V91）
   AND (SELECT count(*) FROM production_operations s
         WHERE s.tenant_id = t.id AND s.deleted = 0
           AND s.name IN ('熨烫-布', '定型-布', '复烫-布', '布帘车被')) = 4
   -- 闸门②（幂等）：4 个 `-纱` 变体**全缺**（按 `deleted = 0` 计，与 ② 的对账**同口径**）
   AND (SELECT count(*) FROM production_operations d
         WHERE d.tenant_id = t.id AND d.deleted = 0
           AND d.name IN ('熨烫-纱', '定型-纱', '复烫-纱', '车被-纱')) = 0
   -- 逐行去重（业务唯一键；`ON CONFLICT` 兜底）
   AND NOT EXISTS (SELECT 1 FROM production_operations e
                    WHERE e.tenant_id = t.id AND e.name = r.name AND e.deleted = 0)
ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 停止条件 S1：数量对账 —— **同一份判据**必须查不到任何租户，否则整份迁移回滚
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 判据与 ① 的闸门**逐字同源**（同样的两个 `count(*)`）：判据若漂移，本块当场抓出。
-- ⚠️ 判据写成「**四元组**计数」而不是「4 个 name 分开查」：后者在**部分补种**时会漏报
-- （只补了 1 道也算「有」）⇒ 那正是「把下单能力打掉」的形态。
DO $$
DECLARE
    remaining INTEGER;
BEGIN
    SELECT count(*) INTO remaining
      FROM tenants t
     WHERE t.deleted = 0
       AND (SELECT count(*) FROM production_operations s
             WHERE s.tenant_id = t.id AND s.deleted = 0
               AND s.name IN ('熨烫-布', '定型-布', '复烫-布', '布帘车被')) = 4
       AND (SELECT count(DISTINCT a.name) FROM production_operations a
             WHERE a.tenant_id = t.id AND a.deleted = 0 AND a.status = 'active'
               AND a.name IN ('熨烫-纱', '定型-纱', '复烫-纱', '车被-纱')) <> 4;
    IF remaining > 0 THEN
        RAISE EXCEPTION
            'V106 数量对账失败：仍有 % 个活跃租户「有 4 个 -布 变体但 4 个 -纱 变体不全」'
            '（判据与写语句漂移 ⇒ 该租户的纱帘单一律 422）—— 回滚本迁移',
            remaining;
    END IF;
END $$;

COMMIT;
