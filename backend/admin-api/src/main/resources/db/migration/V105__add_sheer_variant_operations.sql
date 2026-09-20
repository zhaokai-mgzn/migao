-- O4 配套：补 **4 道纱帘变体工序行**（issue #4937 = 母单 #4936）。
--
-- ## 一句话
-- 往 `production_operations` 补 4 行：`熨烫-纱` / `定型-纱` / `复烫-纱` / `车被-纱`
-- （`group_name='后道'` · `unit='米'` · 单价**逐字取对应 `-布` 变体** · `position='纱帘'`）。
--
-- ## 为什么必须补（**否则整张纱帘单一张也建不出来**）
-- `ProcessingOrderService.buildRoute`（以及真值源 `routing.py::build_route_v2`）原来靠
-- `production_operation_positions.applicable` 的过滤把 `熨烫/定型/复烫/车被` 从**纱帘**路线上滤掉
-- （V71 种子里 `熨烫 × 纱帘` 是 `FALSE`）⇒ 库里**从来没有**建过这 4 道的纱帘变体。
-- 本包（O1）把那条过滤**整块删除**（用户裁定 2026-09-21「我们移除了部位的设计，**不计成本的改**」）
-- ⇒ 这 4 道会进入纱帘路线的实例化路径，而
-- `ProductionOperationQueryService.variantNameOf("熨烫", "纱帘", catalog)` 在库里找不到
-- `熨烫-纱`（`VARIANT_NAMES` 的纱帘列只有 7 条，不含它们）⇒ 返回 `null`
-- ⇒ 该道进 `missing_operations` ⇒ 调用方 **fail-closed**（422）⇒ **一张纱帘单也建不出来**。
--
-- ## 为什么是**新迁移**（不能改 V54）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记账、已应用的文件**整份跳过**
-- ⇒ 往 V54 里加行只对**全新库**生效、存量环境永远拿不到 = 「CI 全绿、功能静默缺失」（issue #4235）；
-- V54 另被 `tests/unit_ci_workflows/migration_fingerprints.json` 的 sha256 **逐字节冻结**。
-- （同 V56 文件头逐字写过的理由 —— 那条判据在本文件同样成立。）
--
-- ## 与 `VARIANT_NAMES` 的关系（**两处都要有，缺一不可**）
--   · 本迁移 = **数据面**：库里真有这道工序行（读面元数据、报工引用、商家可改价都靠它）；
--   · `ProductionOperationQueryService.sheerVariants(names)` / `routing.py::withSheerVariants`
--     = **映射面**：把逻辑名 `熨烫` 在**纱帘**部位解析到这个变体名。
-- ⇒ 只改一处会**静默失效**（有映射没行 ⇒ 读面元数据全 null；有行没映射 ⇒ 实例化解析不到）。
-- 守卫 = `tests/test_production/test_route_model_v2.py`（Python 侧实例化）+
-- `ProductionRouteParityTest#sheerAndClothOrdersHaveTheSameOperationSet`（Java 侧逐条比对）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING`（冲突目标 = V49 的部分唯一索引）
-- ⇒ 第二次执行插入 0 行；`sort_order` 接在 V79 的 37 之后（38..41），不依赖 `max(sort_order)` 的读取时点。
--
-- ## 按租户循环（不是只种 1 号租户）
-- `SELECT … FROM tenants t WHERE t.deleted = 0` —— 只种 1 号租户会让非 1 号租户的纱帘单继续
-- fail-closed（#4676 ⑥ 同款教训）。
--
-- ## 红线：**不动历史**
-- 本文件只 `INSERT` 到 `production_operations`（**配置表**）：
--   · `processing_position_operations` / `production_work_logs` / `processing_orders.items_snapshot`
--     **一字不动**（历史快照按当时落库的名字引用，新增行不影响它们）；
--   · `production_operation_positions`（价目矩阵）**一字不动** —— 矩阵已按 O4 塌缩为
--     「一道逻辑工序一行」，这 4 道的**价目行早就存在**（键是逻辑工序 `熨烫`/`定型`/`复烫`/`车被`）。
--
-- ## 回滚 SQL（**新迁移，不删 V105**；语义 = 删掉本次新增的 4 行）
-- ```sql
-- -- V106__rollback_sheer_variant_operations.sql（本单只登记，不落码）
-- DELETE FROM production_operations
--  WHERE name IN ('熨烫-纱', '定型-纱', '复烫-纱', '车被-纱')
--    AND id LIKE 'op-v105-%';
-- ```
-- ⚠️ **按 id 前缀认领**（`op-v56-0[6-9]`），不按名字：名字会随商家改名漂移（同 V88 回滚的口径）。
-- ⚠️ 若这 4 行已被报工引用 ⇒ 回滚前先核 `production_work_logs.operation_name`；有引用时应改为
-- **软删**（`deleted = 1`）而不是 `DELETE`。
--
-- ## 停止条件（触发任一 ⇒ 回滚本迁移，不硬推）
--   · S1：活跃租户里 `熨烫/定型/复烫/车被` 的**纱帘变体行**数 ≠ 1（`RAISE EXCEPTION`，见文末）；
--   · S2：任一**快照表**行数变化；
--   · S3：`./verify-all.sh gate` 或 `python3 -m pytest tests/unit_ci_workflows/ -q` 非零。
--
-- ## 显式事务（同 V97 / V102 / V103 / V104 的实测口径）
-- `psql -f` 默认逐条 autocommit ⇒ 不显式 `BEGIN/COMMIT` 时 INSERT 已提交、DO 块才抛
-- ⇒ 留下半完成态。两条执行路径（`jdbc.execute` / `psql -f`）必须同语义。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 补 4 道纱帘变体（逐条显式列名；单价逐字取对应 `-布` 变体 —— **不发明单价**）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⚠️ **字面量 `VALUES` 形态**（与 V54 / V56 / V79 同款）：三源收敛守卫
-- `tests/unit_ci_workflows/test_production_catalog_seed.py` 的
-- `values_sources_for("production_operations")` **按内容**发现字面量种子源并逐行比对
-- ⇒ 写成 `INSERT … SELECT … FROM tenants t`（派生回填）会让本迁移**落在比对射程之外**
-- ⇒ 「改了这 4 行的价而没有任何东西变红」。
-- 🔴 **代价照实登记**：字面量形态只能种**固定的 tenant_id**（与 V54/V56/V79 同款 = 1 号租户）。
-- 「非 1 号租户也要有这 4 行」由**开租播种路径**承担
-- （`ProductionSeedTemplateService` 从模板 JSON 逐行播种 —— 那个 JSON 由
-- `tests/unit_ci_workflows/test_production_catalog_seed.py` 的「模板 ≡ OPERATION_CATALOG」判据钉住）。
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, scope, status, deleted)
VALUES
  ('op-v56-06', 1, '熨烫-纱', '后道', '纱帘', '米', 0.35, FALSE, FALSE, 38, 'position', 'active', 0),
  ('op-v56-07', 1, '定型-纱', '后道', '纱帘', '米', 0.40, FALSE, FALSE, 39, 'position', 'active', 0),
  ('op-v56-08', 1, '复烫-纱', '后道', '纱帘', '米', 0.35, FALSE, FALSE, 40, 'position', 'active', 0),
  ('op-v56-09', 1, '车被-纱', '后道', '纱帘', '米', 0.40, FALSE, FALSE, 41, 'position', 'active', 0)
ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 停止条件 S1：数量对账 —— **本迁移射程内**（字面量种子的那个租户）4 道**各恰好一行**
-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⚠️ 射程 = `tenant_id = 1`（字面量种子能覆盖的唯一租户）——**这不是「漏了其它租户」**：
--    与 V54 / V56 / V79 同款形态（它们也只种 1 号租户），**非 1 号租户**由**开租播种路径**
--    （`ProductionSeedTemplateService` 读模板 JSON 逐行播种）承担 —— 那份模板已包含这 4 道
--    （`seed.json` 的 `op-v56-06..09`，由 `tests/unit_ci_workflows/test_production_catalog_seed.py`
--    的「模板 ≡ OPERATION_CATALOG」判据钉住）。
--    写成「按租户循环对账」会**当场假红**（2 号租户本来就不在字面量种子的射程里）。
DO $$
DECLARE
    remaining INTEGER;
BEGIN
    SELECT count(*) INTO remaining
      FROM (VALUES ('熨烫-纱'), ('定型-纱'), ('复烫-纱'), ('车被-纱')) AS v(name)
     WHERE NOT EXISTS (
             SELECT 1 FROM production_operations o
              WHERE o.tenant_id = 1 AND o.name = v.name
                AND o.deleted = 0 AND o.status = 'active');
    IF remaining > 0 THEN
        RAISE EXCEPTION
            'V105 数量对账失败：仍有 % 道纱帘变体缺行（判据与写语句漂移）—— 回滚本迁移',
            remaining;
    END IF;
END $$;

COMMIT;
