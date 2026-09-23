-- 补种 V79 在**真库**上漏掉的布料种子（issue #4685）—— 按租户 + **显式 `::numeric`** + 幂等 +
-- **不覆盖商家已改**。
--
-- ## 一句话
-- `V79__seed_fabric_route_and_packing_operation.sql` 的**按租户派生块**在真库上必然报
-- `字段 "unit_price" 的类型为 numeric, 但表达式的类型为 text` —— `JOIN (VALUES (…, NULL, …))`
-- 的 `unit_price` 列**整列都是 NULL** ⇒ PostgreSQL 把该列推断成 `text`，而目标列是
-- `NUMERIC(10,2)`，且 `text → numeric` **不是赋值转换**（explicit-only）⇒ 整文件**单事务回滚**。
-- 后果（真库实测 2026-09-20，PG 18.3 / 阿里云 RDS `ai_customer_service`）：
-- `schema_migrations` 里 **V80~V87 都在、唯独 V79 缺席**（`MigrationRunner` 对内容类失败是
-- 「跳过这一条、继续跑后面的」，`MigrationRunner:185`）⇒ **1 号租户与非 1 号租户一律没有**
-- `打包` 工序 / 布料价目格 / `布料工序路线`。
--
-- ## 用户原始问题逐字（本单的修复理由）
-- > 「我想制定**纯布料**的工序路线，应该如何设置」+ 截图「新建路线」的「适用帘种」只有
-- > 布帘/纱帘/帘头；页面显示「工艺路线 **共 1 条**」。
-- 真库实测与截图**逐条吻合**：3 个活跃租户（`1` / `20` / `21`）的 `production_operations` 里
-- `配料` / `打包` 各 **0** 行；`production_operation_positions` 的 `position='布料'` **0** 行；
-- `布料工序路线` **0** 行；每租户恰好 **1** 条路线（窗帘默认，`positions=["布帘","纱帘","帘头"]`）。
--
-- ## 为什么必须是**新迁移**（不能改 V79）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记账、已应用的文件**整份跳过**
-- ⇒ 改 V79 只对全新库生效、存量环境永远拿不到（=「CI 绿、功能静默缺失」，issue #4235）；
-- V79 另被 `tests/unit_ci_workflows/migration_fingerprints.json` 的 sha256 逐字节冻结 ⇒ 改它必红。
--
-- ## 目标终态 = **V88 之后**的口径（V88 已合并，是既有终态；本文件**不重放中间态**）
-- ① 每活跃租户补 `打包` 工序（`scope='set'` 套级 / `source='占位待确认'`）；
-- ② 每活跃租户补 **5 格**价目（= V88 之后**存活**的布料相关格）：
--    `裁剪 × 布料`（**保命格**，`applicable=TRUE`）+ `打包 × {布帘,纱帘,帘头,布料}`（4 格，全 TRUE）；
-- ③ 每活跃租户补 `布料工序路线`（`positions=["布料"]` / `mainline=["裁剪","打包"]` / `is_default=FALSE`）；
-- ④ 每活跃租户的**默认**窗帘主线补 `打包`（插在 `外帘装袋` **之前**，9 → 10 道）。
--
-- ⚠️ **为什么不种 `配料`**：`V88`（issue #4676）已让 `配料` 退场（工序行 + 4 格矩阵软删 +
-- 布料主线元素替换）。本文件**直接落终态** ⇒ 不种 `配料`、也不需要重放 V88 的 ①②（本文件
-- 根本没有 `配料` 的写入）；V88 的 ④（`裁剪 × 布料` 改 TRUE）由本文件 ② 的**落值**直接达成。
--
-- ⚠️ **为什么 ② 是 5 格而不是 36 格**：36 格是 V79 的**中间态**（28 道既有工序 × 布料 +
-- `配料` × 4 + `打包` × 4），其中 31 格由 V88 ⑤ 退场、4 格由 ② 保留、1 格是保命格
-- （31 + 5 = 36，可机械核验）。真库上这 36 格**从未写入** ⇒ 直接落 **5 格存活集**即达终态
-- （少写 31 条注定要被软删的行，语义等价且幂等更简单）。
--
-- ## 迁移号
-- `ls backend/admin-api/src/main/resources/db/migration | tail` **现取** ⇒ **V89**
-- （V90 保留给 #4696）。若 push 时 V89 已被占 ⇒ 用下一个空闲号并在 PR body 说明。
--
-- ## 🔴 类型显式（**本单的核心**）
-- ② 的派生 `VALUES` 列表里 `unit_price` **逐行显式** `NULL::numeric`、`applicable` 显式
-- `TRUE::boolean` —— 不写就复现 V79 的推断坑（红证：把 `::numeric` 去掉 ⇒ 真库报
-- `column "unit_price" is of type numeric but expression is of type text`）。
-- ① 的 `unit_price` 写 `0::numeric`（DDL 是 `NUMERIC(10,2) NOT NULL DEFAULT 0`）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- 三条 INSERT 一律 **业务唯一键 `NOT EXISTS`** + **`ON CONFLICT … DO NOTHING`**（冲突目标 =
-- 主键 / V49 的部分唯一索引）⇒ 第二次执行匹配 0 行、净效果相同；④ 的 `UPDATE` 以
-- `NOT (mainline @> '["打包"]'::jsonb)` 为守卫 ⇒ 已含 `打包` 的整条跳过。
--
-- ## 不覆盖商家已改的数据（红线）
-- 三条 INSERT 全部以业务唯一键 `NOT EXISTS` 去重 ⇒ **已存在的行一律不写**：商家改过的
-- 价 / 适用性 / 自建行（含自建的 `打包` 工序行、自建的布料路线）**一字不动**。
-- 本文件**没有任何**针对既有行的 `SET unit_price` / `SET applicable`；唯一的 `UPDATE`（④）
-- 是主线的**手术式插入**（保留商家改过的顺序与删减，只把 `打包` 插到 `外帘装袋` 之前）。
--
-- ## 与真值源的收敛
-- 本文件落的终态与 `backend/admin-api/src/main/java/com/migao/admin/service/
-- ProductionSeedTemplateService.java`（开租播种，`FABRIC_MAINLINE_STEPS = ["裁剪","打包"]` /
-- `FABRIC_KEEP_APPLICABLE_LOGICAL = "裁剪"` / `RETIRED_LOGICAL_NAMES = {"配料"}`）逐项一致 ——
-- 「存量租户走迁移链、新租户走开租播种」两条路径必须落同一个终态，否则同一种单在两类租户上
-- 工序数不同。静态守卫 = `tests/unit_ci_workflows/test_v89_fabric_seed_backfill.py`。
--
-- ## 回滚（**新迁移，不删 V89**；语义 = 让**新单**回旧行为，历史单不回）
-- ```sql
-- -- V90__rollback_fabric_seed_backfill.sql（本单只登记，不落码 —— V90 留给 #4696）
-- -- ① 主线去掉 `打包`（只动默认路线）
-- UPDATE production_route_templates rt SET mainline = (
--         SELECT jsonb_agg(elem ORDER BY ord)
--           FROM jsonb_array_elements(rt.mainline) WITH ORDINALITY AS e(elem, ord)
--          WHERE elem <> '"打包"'::jsonb),
--        updated_at = NOW()
--   FROM tenants t
--  WHERE rt.tenant_id = t.id AND t.deleted = 0
--    AND rt.deleted = 0 AND rt.is_default AND rt.mainline @> '["打包"]'::jsonb;
-- -- ② 布料路线软删（按 id 前缀认领，不按名字 —— 名字会随商家改名漂移）
-- UPDATE production_route_templates rt SET deleted = 1, updated_at = NOW()
--   FROM tenants t WHERE rt.tenant_id = t.id AND t.deleted = 0
--    AND rt.id LIKE 'rt-v79-%' AND rt.deleted = 0;
-- -- ③ 5 格矩阵行软删
-- UPDATE production_operation_positions p SET deleted = 1, updated_at = NOW()
--   FROM tenants t WHERE p.tenant_id = t.id AND t.deleted = 0
--    AND p.id LIKE 'opp-v79-%' AND p.deleted = 0;
-- -- ④ `打包` 工序行软删
-- UPDATE production_operations o SET deleted = 1, updated_at = NOW()
--   FROM tenants t WHERE o.tenant_id = t.id AND t.deleted = 0
--    AND o.id LIKE 'op-v79-%' AND o.deleted = 0;
-- ```
-- ⚠️ **回滚不能复原的东西（如实登记）**：本迁移生效期间**新建**的布料单已按
-- `["裁剪","打包"]` 实例化 ⇒ 回滚后这些单的**实例快照不会自动变回**（`processing_position_operations`
-- 是本文件的**红线外**表，一字未动）。回滚的语义是「让新单回到旧行为」，**不是**「让历史单回到旧行为」。
--
-- ## 停止条件（出现任一条即停手，不回滚 V89、另开单）
-- S1 布料单实例化工序数 ≠ 2（`裁剪` / `打包` 各一道）；
-- S2 `布料工序路线` 在某租户消失（删它会让 `routeTemplateFor` 返回 null ⇒ T2 回落窗帘 10 道，
--    布料单**多出**一堆窗帘工序 —— 比缺路线更糟）；
-- S3 `打包` 在某部位单里消失（交付环节少一道 ⇒ 少发工资）；
-- S4 商家已改过的价 / 适用性 / 自建行被覆盖（核法：改前记 `(tenant_id, logical_name, position)`
--    → `unit_price` / `applicable`，重跑后逐行比对）；
-- S5 重复执行净效果不同（核法：跑两遍，逐表 `count(*)` + 全行指纹一致）。
--
-- ## 🔴 红线：三张快照表**一字不动**（本文件的 DML 只碰 3 张**配置**表）
--   · `processing_orders.items_snapshot`（加工单快照）
--   · `processing_position_operations`（工序实例快照；⚠️ 与 `production_operation_positions`
--     **名字极像**，本文件**只**写后者 = 部位**矩阵**表）
--   · `production_work_logs.unit_price` / `factor`（报工快照；历史工资不回溯）
-- 机械核验（前两张表名 + 报工表在本文件里必须**零命中**）：
--   grep -c "processing_orders\|processing_position_operations\|production_work_logs" V89__*.sql   # ⇒ 0

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① `打包` 工序（每活跃租户）—— 套级交付工序，布料主线与窗帘主线的第 10 道都引用它
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 逐值 = V79 的 `打包` 行（`后道` / 无部位 / `套` / 价 0 / 非必完 / 非开始标记 / sort 37），
-- 另把 V79 用**后续 UPDATE** 补的两列**显式写进列清单**（issue #4608 纪律）：
--   · `scope='set'`（V79 ④）—— 一樘「布 + 纱」的订单里 `打包` 只落一次、**不双付**；
--   · `source='占位待确认'`（V79 ③）—— 单价是占位值这件事必须在**数据上可见**。
-- ⚠️ `unit_price` 落 **0** 不是「定价 0」：DDL 是 `NUMERIC(10,2) NOT NULL DEFAULT 0`，
--    工序库行只能落 0；「未定价」的真载体是**部位价目行**（② 的 `unit_price IS NULL` +
--    `applicable = TRUE`）。
-- 幂等：业务唯一键 `(tenant_id, name) WHERE deleted = 0` 的 `NOT EXISTS` + 同款 `ON CONFLICT`。
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, status, scope, source)
SELECT 'op-v79-' || t.id || '-02',
       t.id, '打包', '后道', NULL, '套', 0::numeric,
       FALSE, FALSE, 37, 'active', 'set', '占位待确认'
  FROM tenants t
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_operations e
        WHERE e.tenant_id = t.id AND e.name = '打包' AND e.deleted = 0)
ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 部位价目矩阵：补 **5 格**（= V88 之后存活的布料相关格）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 逐格说明（与 V88 的头注算术一致：36 − 31 退场 − 1 保命格 + 1 保命格 = 5）：
--   · `裁剪 × 布料` —— **保命格**：未实例化的存量布料单走「补生成工序」时会按当前配置重算，
--     缺这一格 ⇒ `buildRoute` 的 `applicableByLogical` 查不到键 ⇒ **静默 `continue`** ⇒
--     布料单只剩 `打包` 一道（不报错、少一道活、少一笔计件钱）。
--   · `打包 × {布帘,纱帘,帘头,布料}` —— 交付工序在**每个部位**的唯一载体：缺任一格 ⇒
--     该部位单少一道（`scope='set'` 只保证不双付，不保证存在）。
-- 全部 `unit_price = NULL` + `applicable = TRUE` = 「**适用但未定价**」（商家在「工序库」自配）；
-- 与「不适用」（`applicable = FALSE`）**必须可区分**。
--
-- 🔴 **类型显式**：`VALUES` 列表里 `unit_price` 整列都是 NULL ⇒ 不显式转型就会被推断成 `text`
--    （这正是 V79 在真库上报错的那一处）；`applicable` 同理显式 `::boolean`。
-- 幂等：业务唯一键 `(tenant_id, logical_name, position) WHERE deleted = 0` 的 `NOT EXISTS`
-- + `ON CONFLICT (id) DO NOTHING`。
-- 按租户：`FROM tenants t WHERE t.deleted = 0`（与 V72/V79/V88 同款口径）。
INSERT INTO production_operation_positions
    (id, tenant_id, logical_name, position, unit_price, applicable, status)
SELECT 'opp-v79-' || t.id || '-' || v.logical_name || '-' || v.position,
       t.id, v.logical_name, v.position, v.unit_price, v.applicable, 'active'
  FROM tenants t
  JOIN (VALUES
      ('裁剪', '布料', NULL::numeric, TRUE::boolean),
      ('打包', '布帘', NULL::numeric, TRUE::boolean),
      ('打包', '纱帘', NULL::numeric, TRUE::boolean),
      ('打包', '帘头', NULL::numeric, TRUE::boolean),
      ('打包', '布料', NULL::numeric, TRUE::boolean)
  ) AS v(logical_name, position, unit_price, applicable)
    ON TRUE
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_operation_positions e
        WHERE e.tenant_id = t.id
          AND e.logical_name = v.logical_name
          AND e.position = v.position
          AND e.deleted = 0)
ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ `布料工序路线`（每活跃租户，`is_default = FALSE`）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 主线 = 规范布料主线 `["裁剪","打包"]` **字面量**（= `V88` ③ 之后的终态 /
-- `ProductionSeedTemplateService.FABRIC_MAINLINE_STEPS` / `schema.sql` 三处逐字一致）。
-- ⚠️ **为什么不像 V79 ⑤ 那样「∩ 该租户自己的工序库」**（有意取舍，照实登记）：
--    V79 ⑤ 的写法是 `ARRAY['配料','打包']` ∩ 工序库、`COALESCE(…, 规范值)`。放到**终态**上它会
--    退化成 `["打包"]`（`配料` 已退场 ⇒ 交集只剩 1 步，`jsonb_agg` 非 NULL ⇒ **回落分支不触发**）
--    ⇒ 给商家种出一条**只剩 1 道**的布料路线 ⇒ 直接触发本单的停止条件 **S1**
--    （设计 F1 红线：交付环节绝不能用「少一道」实现）。而且对**健康**租户（工序库有
--    `裁剪-布`/`裁剪-纱`）交集恰好等于规范值 ⇒ 那段逻辑**从不产生差异**（YAGNI）。
-- ⇒ 落**字面量规范主线**：两步都引用得到 ⇒ 正常实例化 2 道；若某租户工序库确实缺 `裁剪`
--    （真库实测：租户 20/21 的 `production_operations` **0 行**），实例化走 T3 fail-closed 并
--    **指名报缺 `裁剪`** —— 这是**可见**的失败，比静默少一道好。
-- 幂等：业务唯一键 `(tenant_id, name) WHERE deleted = 0` 的 `NOT EXISTS` + `ON CONFLICT (id)`。
INSERT INTO production_route_templates
    (id, tenant_id, name, is_default, positions, mainline, status)
SELECT 'rt-v79-' || t.id,
       t.id,
       '布料工序路线',
       FALSE,
       '["布料"]'::jsonb,
       '["裁剪", "打包"]'::jsonb,
       'active'
  FROM tenants t
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_route_templates e
        WHERE e.tenant_id = t.id AND e.name = '布料工序路线' AND e.deleted = 0)
ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 默认窗帘主线补 `打包`（9 → 10 道，插在 `外帘装袋` **之前**）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 依据（V79 ⑥ 逐字保留）：ERP 加工单实证 `外帘打包 › 外帘装箱 › 外帘发货`，`外帘装袋`
-- ≈ ERP 的 `外帘装箱` ⇒ **打包在装袋之前**。⚠️ 照实登记：#4343 明确登记过这两道的对应关系
-- **未能确定** ⇒ 本顺序是**按 ERP 顺序推断**、**待客户确认**（不假装定论）。
-- 为什么本文件必须做：V79 的 ⑥ 与 ①②③ 在**同一个文件、同一个事务**里 ⇒ V79 回滚时
-- 这一条也一并丢失。终态真值（`routing.py::ROUTE_MAINLINE_STEPS` / `schema.sql` /
-- `ProductionSeedTemplateService.ROUTE_MAINLINE_STEPS`）都是 **10 道含 `打包`** ⇒ 不补则
-- 「存量租户 9 道 vs 新租户 10 道」永久分裂。
-- 形态（**手术式插入**，不是整条重建）：保留商家已改过的主线顺序/删减，只把 `打包` 插到
-- `外帘装袋` **之前**（该锚点不存在 ⇒ 追加末尾，与 `_insert_after` 同款兜底）。
-- 幂等：`NOT (mainline @> '["打包"]'::jsonb)`（已有则整条跳过）。
UPDATE production_route_templates rt
   SET mainline = (
           SELECT jsonb_agg(elem ORDER BY ord)
             FROM (
                 SELECT elem, ord::numeric AS ord
                   FROM jsonb_array_elements(rt.mainline) WITH ORDINALITY AS e(elem, ord)
                 UNION ALL
                 SELECT '"打包"'::jsonb,
                        COALESCE((SELECT MIN(ord)::numeric
                                    FROM jsonb_array_elements(rt.mainline) WITH ORDINALITY AS a(elem2, ord)
                                   WHERE elem2 = '"外帘装袋"'::jsonb), 10000) - 0.5
             ) AS s
       ),
       updated_at = NOW()
  FROM tenants t
 WHERE rt.tenant_id = t.id
   AND t.deleted = 0
   AND rt.deleted = 0
   AND rt.is_default
   AND NOT (rt.mainline @> '["打包"]'::jsonb);
