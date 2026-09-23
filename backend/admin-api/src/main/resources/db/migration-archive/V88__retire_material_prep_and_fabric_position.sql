-- 公共工序两层模型 · 数据层收敛：`配料` 退场 / 布料主线改 [裁剪,打包] / 保留「裁剪 × 布料」保命格 /
-- 其余布料格退场（issue #4676 = 设计 docs/design/public-operations-and-craft-ui.md 的落码单，用户裁定
-- 「直接开干」）。
--
-- ## 一句话
-- ① `配料` 工序行**软删**；② `配料 × 4 部位` 矩阵行**软删**；③ 布料主线 `["配料","打包"]` →
-- `["裁剪","打包"]`；④ **`裁剪 × 布料` 格 `applicable` 改 TRUE（保命格）**；⑤ 其余**布料格**退场；
-- ⑥ 全部按租户覆盖；⑦ `打包` 的 4 格 + `scope='set'` **一字不动**。
--
-- ## 🔴 为什么 ⑤ 是 **31 格**而不是设计稿写的「35 格」（**口径冲突，照实登记**）
-- 设计 §5.2 ⑤ 的谓词写的是 `position='布料' AND logical_name <> '裁剪'`、F6 写「实际退场 **35 格**」
-- （= V79 的 36 格 − 1 保命格）。但那与**同一份设计**的 ⑦「`打包` 4 格**不动**」**不能同时成立**：
--   · V79 的 36 格 = 既有 28 道 × `布料`（28）+ `配料` × 4 + `打包` × 4；
--   · 36 − 1（`裁剪 × 布料` 保命格）= 35 里**含** `打包 × 布料` 一格；
--   · 而 `打包` 是 **套级交付工序**（`scope='set'`），布料单的部位就是 `布料` ⇒ 删掉这一格后
--     `ProcessingOrderService.buildRoute` 在 `applicableByLogical` 里查不到键 ⇒ 走
--     `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingOrderService.java:1242` 的
--     静默 `continue` ⇒ **布料单只剩 `裁剪` 一道** ⇒ 直接触发**本单自己的停止条件 S1**
--     （布料单实例化工序数 ≠ 2）。这也正是设计 F1 的红线形态（「交付环节的一列价**绝不能用删格实现**」）。
-- ⇒ **以 ⑦ + S1 + F1 为准**：退场 = 36 − 1（保命格）− 4（`打包` 4 格）= **31 格**；
--   保留 = `裁剪 × 布料` + `打包 × {布帘,纱帘,帘头,布料}` = **5 格**。31 + 5 = 36（可机械核验）。
--
-- ## 为什么必须是**新增 V88**（不能改 V79）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记账、已应用的文件**整份跳过** ⇒ 改 V79
-- 只对**全新库**生效，存量环境永远拿不到 = 「CI 全绿、功能静默缺失」（issue #4235）。V79 另被
-- `tests/unit_ci_workflows/migration_fingerprints.json` 的 sha256 逐字节冻结（85 条）⇒ 改它必红。
--
-- ## 幂等（MigrationRunner 硬要求所有迁移可重复执行）
-- 每条 `UPDATE … WHERE deleted = 0`（或 `applicable IS DISTINCT FROM TRUE`）⇒ 第二次执行匹配 0 行，
-- 净效果相同（空操作）。
--
-- ## 🔴 显式写列（issue #4608 纪律）
-- 软删一律 `.set(deleted, 1).set(updated_at, NOW())` —— 与 Java 侧
-- `ProductionOperationCommandService` 的「`setDeleted(1)` 之后再 `updateById`」形态**不同**：
-- 后者会让 MyBatis-Plus 的自动填充把 `updated_at` 覆盖成写入时刻、且漏掉「同一语句里把 deleted 写全」
-- 的可核验性。本迁移逐列写全。
--
-- ## 按租户（issue #4676 ⑥）
-- 五条 DML 全部 `FROM tenants t WHERE t.tenant_id = t.id AND t.deleted = 0` ——
-- 「按租户循环」的 UPDATE 形态（V79 的 `INSERT … SELECT … FROM tenants` 是 INSERT 侧的同款口径）。
-- ⚠️ 只种 1 号租户会让非 1 号租户的 `配料` 留在库里 ⇒ S6（新单实例里出现 `配料`）与
-- ⑤ 的退场都不成立（V79 逐字警告同款）。
--
-- ## 红线：三张快照表**一字不动**（本迁移的 UPDATE 只碰 3 张**配置**表）
--   · `processing_orders.items_snapshot`（加工单快照，生成时固化）
--   · `processing_position_operations`（工序实例快照；⚠️ 与 `production_operation_positions` **名字极像**，
--     本文件**只**写后者 = 部位**矩阵**表，绝不碰前者）
--   · `production_work_logs.unit_price` / `factor`（报工快照；历史工资不回溯）
-- 核验命令（本文件里这三张表名必须**零命中**，`production_operation_positions` 的命中数 = 2）：
--   grep -c "processing_orders\|processing_position_operations\|production_work_logs" V88__*.sql   # ⇒ 0
--   grep -c "production_operation_positions" V88__*.sql                                            # ⇒ 2
--
-- ## 与真值源的关系（**照实登记的跨单依赖**）
-- `backend/ai-agent-service/app/production/routing.py` 的 `FABRIC_MAINLINE_STEPS` / `_POSITION_PRICE_ROWS`
-- 与 `backend/admin-api/src/main/resources/production-templates/curtain/seed.json` **本单不动**
-- （ai-agent 属本单红线；seed.json 被 `tests/unit_ci_workflows/test_production_catalog_seed.py` 的
-- 「模板 ≡ routing.py」判据钉住）⇒ **迁移库的终态**由本文件达成，而**开租播种路径**另在
-- `ProductionSeedTemplateService` 里按本文件的终态**显式覆盖**（见该类的 V88 注释）。
-- 「真值源自身收敛到 36 道工序」属 ai-agent / 文档单，**不在本单**。
--
-- ## 回滚（**新迁移 V89，不删 V88**；语义 = 只让**新单**回旧行为，历史单不回）
-- ```sql
-- -- V89__rollback_material_prep_and_fabric_position.sql（本单只登记，不落码）
-- UPDATE production_operations o SET deleted = 0, updated_at = NOW()
--   FROM tenants t WHERE o.tenant_id = t.id AND t.deleted = 0
--    AND o.id LIKE 'op-v79-%' AND o.deleted = 1;          -- 按 **id 前缀**认领，不按名字（名字会随商家改名漂移）
-- UPDATE production_operation_positions p SET deleted = 0, updated_at = NOW()
--   FROM tenants t WHERE p.tenant_id = t.id AND t.deleted = 0
--    AND p.id LIKE 'opp-v79-%' AND p.deleted = 1;
-- UPDATE production_operation_positions p SET applicable = FALSE, updated_at = NOW()
--   FROM tenants t WHERE p.tenant_id = t.id AND t.deleted = 0
--    AND p.logical_name = '裁剪' AND p.position = '布料' AND p.deleted = 0;
-- UPDATE production_route_templates rt SET mainline = (
--         SELECT jsonb_agg(CASE WHEN elem = '"裁剪"'::jsonb THEN '"配料"'::jsonb ELSE elem END ORDER BY ord)
--           FROM jsonb_array_elements(rt.mainline) WITH ORDINALITY AS e(elem, ord)),
--        updated_at = NOW()
--   FROM tenants t WHERE rt.tenant_id = t.id AND t.deleted = 0
--    AND rt.name = '布料工序路线' AND rt.deleted = 0
--    AND rt.mainline @> '["裁剪"]'::jsonb AND NOT (rt.mainline @> '["配料"]'::jsonb);
-- ```
-- ⚠️ **回滚不能复原的东西（如实登记）**：V88 生效期间**新建**的布料单已按 `["裁剪","打包"]` 实例化
-- ⇒ 回滚后这些单的**实例快照不会自动变回** `配料`。回滚的语义是「让**新单**回到旧行为」，
-- **不是**「让历史单回到旧行为」。

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① `配料` 工序行软删（`production_operations`）—— 行业里它对应「物料分配」，不在车间三段里
-- ══════════════════════════════════════════════════════════════════════════════════════
UPDATE production_operations o
   SET deleted = 1,
       updated_at = NOW()
  FROM tenants t
 WHERE o.tenant_id = t.id
   AND t.deleted = 0
   AND o.name = '配料'
   AND o.deleted = 0;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② `配料 × 4 部位` 矩阵行软删（`production_operation_positions`）
-- ⚠️ 表名必须写全：`production_operation_positions`（部位**矩阵**）≠ `processing_position_operations`
--    （工序**实例**快照，红线不动）。
-- ══════════════════════════════════════════════════════════════════════════════════════
UPDATE production_operation_positions p
   SET deleted = 1,
       updated_at = NOW()
  FROM tenants t
 WHERE p.tenant_id = t.id
   AND t.deleted = 0
   AND p.logical_name = '配料'
   AND p.deleted = 0;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 布料主线 `["配料","打包"]` → `["裁剪","打包"]`（手术式元素替换，**不是**整条重建）
-- 为什么手术式：布料路线可能被商家改过顺序/加过工序 ⇒ 整条重建会覆盖商家配置（V79 ⑥ 同款取舍）。
-- 幂等：`mainline @> '["配料"]'`（还有 `配料` 才动）+ `NOT (mainline @> '["裁剪"]')`（已有 `裁剪` 则跳过）。
-- 用户裁定逐字：「布料单该用 **裁剪**」（#4673 评论；F5 已把早期「配料是公共工序」改判掉）。
-- ⚠️ `布料工序路线` 模板本身**必须保留**（`positions=["布料"]`）：删它会让 `routeTemplateFor`
--    返回 null ⇒ T2 回落默认路线（窗帘 10 道）⇒ 布料单**多出**一堆窗帘工序（更糟，见设计 §5.3 ②）。
-- ══════════════════════════════════════════════════════════════════════════════════════
UPDATE production_route_templates rt
   SET mainline = (
           SELECT jsonb_agg(
                      CASE WHEN elem = '"配料"'::jsonb THEN '"裁剪"'::jsonb ELSE elem END
                      ORDER BY ord)
             FROM jsonb_array_elements(rt.mainline) WITH ORDINALITY AS e(elem, ord)
       ),
       updated_at = NOW()
  FROM tenants t
 WHERE rt.tenant_id = t.id
   AND t.deleted = 0
   AND rt.name = '布料工序路线'
   AND rt.deleted = 0
   AND rt.mainline @> '["配料"]'::jsonb
   AND NOT (rt.mainline @> '["裁剪"]'::jsonb);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 🔴 **保命格**：`裁剪 × 布料` 的 `applicable` 改 **TRUE**
-- 依据（设计 F3 + §5.3）：**未实例化**的存量布料单走「补生成工序」
-- （`POST /api/admin/production/orders/{orderId}/instantiate` 空 body ⇒
-- `ProductionController.withDerivedPositions` ⇒ `derivePositionPayload`）时**会按当前配置重算**
-- ⇒ 删这一格会让存量单**静默少一道工序**（`buildRoute` 查不到键 ⇒ 静默 `continue`，**不报错**）。
-- ⚠️ 这一格**不是**「界面列」的载体（界面口径见设计 §4.3），而是**实例化路径**的载体。
-- ⚠️ 单价仍是 `NULL`（「适用但未定价」）⇒ 实例化时按设计 F1 回落
--    `production_operations.unit_price`（`裁剪-布` = 0.4，非 0）；「未定价 ≠ 0」语义见 F4/U6 登记。
-- ══════════════════════════════════════════════════════════════════════════════════════
UPDATE production_operation_positions p
   SET applicable = TRUE,
       updated_at = NOW()
  FROM tenants t
 WHERE p.tenant_id = t.id
   AND t.deleted = 0
   AND p.logical_name = '裁剪'
   AND p.position = '布料'
   AND p.deleted = 0
   AND p.applicable IS DISTINCT FROM TRUE;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑤ 其余**布料格**退场（31 格 = 36 − 1 保命格 − 4 打包格；逐条见文件头）
-- 谓词 = `position='布料'`（28 格）+ ② 的 `配料 × {布帘,纱帘,帘头}`（3 格）⇒ 31 格。
-- ⑦ 的排除项写在这里（`logical_name NOT IN ('裁剪','打包')`）：`裁剪 × 布料` 是保命格、
-- `打包 × 布料` 是**交付工序在布料单上的唯一载体**（删 ⇒ 布料单少一道 ⇒ S1 红）。
-- ⚠️ 本谓词**只覆盖 `position='布料'`** ⇒ `布帘/纱帘/帘头` 的格（含交付工序 3 格）**一律不动**
--    —— 这正是设计 F1 红线（「删格」会让交付工序在纱帘/帘头单里消失 ⇒ 少发工资）的机械护栏。
-- ══════════════════════════════════════════════════════════════════════════════════════
UPDATE production_operation_positions p
   SET deleted = 1,
       updated_at = NOW()
  FROM tenants t
 WHERE p.tenant_id = t.id
   AND t.deleted = 0
   AND p.position = '布料'
   AND p.logical_name NOT IN ('裁剪', '打包')
   AND p.deleted = 0;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑦ `打包` 的 4 格 + `scope='set'` **一字不动** —— 本文件**没有**任何针对 `打包` 的语句。
-- 机械核验：`grep -n "'打包'" V88__*.sql` 只应命中注释与 ⑤ 的排除列表（`NOT IN`），
-- 不得出现在任何 `SET` 的目标侧。
-- ══════════════════════════════════════════════════════════════════════════════════════
