-- 布料基础路线 + 「打包」工序（issue #4529，包 F；用户裁定 2026-09-19）
--
-- ## 一句话
-- ① 新增两道工序：`配料`（单位 = 米，布料单前道）/ `打包`（单位 = 套，**套级**，跨产品形态）；
-- ② 部位价目矩阵补到 **30 逻辑工序 × 4 部位 = 120 行**（第 4 个部位 = `布料`，逐行显式）；
-- ③ 种**第 2 条**基础路线 `布料工序路线`（`positions=["布料"]` / `mainline=["配料","打包"]` /
--    `is_default=FALSE`）；
-- ④ 窗帘主线加 `打包`（**9 → 10 道**，位置 = `外帘打卷` 与 `外帘装袋` 之间）。
--
-- ## 迁移号为什么是 V79
-- V77 = 包 A（#4525，`production_route_rules.customer_unit_price`）、V78 = 包 C（#4452，
-- `processing_items.craft_hint`）已占用。**已发布迁移不可改**：`MigrationRunner` 的台账
-- `schema_migrations` 按**文件名**记、已应用的文件**整份跳过** ⇒ 改旧迁移只对全新库生效、
-- 存量环境永远拿不到（= 「CI 绿、功能静默缺失」，issue #4235）⇒ 一切增量走本文件。
--
-- ## 🔴 为什么必须**按租户循环**（不做 ⇒ 非 1 号租户全量建单 422）
-- 窗帘主线加 `打包` 后，任何**工序库没有 `打包` 行**的租户在实例化时都会命中
-- `missing_operations` ⇒ `resolveRoute` 的 T3 **fail-closed**（#4116 已落码的护栏）
-- ⇒ 该租户**一张加工单也生成不了**（422）。V71 的种子只种 `tenant_id = 1`
-- （与 V54/V56/V58/V59 先例一致），V72 的按租户回填只覆盖**当时已存在**的租户
-- ⇒ 本迁移必须为**每个活跃租户**补：两道工序 + 36 格价目 + 布料路线 + 窗帘主线重建。
--
-- ## 幂等（bootstrap-first：建好终态的库上还会再跑一遍）
-- 一律 `ON CONFLICT … DO NOTHING` + 业务唯一键 `NOT EXISTS` 去重（不覆盖商家改过的行/价/顺序）。
--
-- ## 回滚 SQL（保留于注释；按需手工执行）
-- ```sql
-- UPDATE production_route_templates SET mainline = (mainline - '打包')
--  WHERE is_default AND deleted = 0 AND mainline @> '["打包"]'::jsonb;
-- DELETE FROM production_operation_positions WHERE id LIKE 'opp-v79-%';
-- DELETE FROM production_route_templates   WHERE id LIKE 'rt-v79-%';
-- DELETE FROM production_operations        WHERE id LIKE 'op-v79-%';
-- ```
--
-- ## 与真值源的收敛判据（防第二份口径漂移）
-- 本文件的字面量种子与 `app/production/routing.py` 的 `OPERATION_CATALOG` /
-- `_POSITION_PRICE_ROWS` / `ROUTE_MAINLINE_STEPS` / `FABRIC_MAINLINE_STEPS` 逐行逐值收敛：
-- 守卫 = `tests/unit_ci_workflows/test_production_catalog_seed.py`（按内容发现种子源）
-- + `tests/unit_ci_workflows/test_fabric_route_seed.py`（每租户两条路线 / 一条默认）。

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 两道新工序（1 号租户字面量种子 + 按租户循环）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⚠️ `unit_price` 落 **0** 不是「定价 0」：`production_operations.unit_price` 是
-- `NOT NULL DEFAULT 0`（V49 DDL）⇒ 工序库行只能落 0。「未定价」的真载体是**部位价目行**
-- （`production_operation_positions.unit_price = NULL` 且 `applicable = TRUE`，见本文件 ②）
-- + 本文件 ③ 的 `source = '占位待确认'`（商家在「工序库」自配）。
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, status)
VALUES
  ('op-v79-01', 1, '配料', '后道', NULL, '米', 0, FALSE, FALSE, 36, 'active'),
  ('op-v79-02', 1, '打包', '后道', NULL, '套', 0, FALSE, FALSE, 37, 'active')
ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;

-- 按租户循环（存量租户）：`配料`
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, status)
SELECT 'op-v79-' || t.id || '-01', t.id, '配料', '后道', NULL, '米', 0, FALSE, FALSE, 36, 'active'
  FROM tenants t
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_operations e
        WHERE e.tenant_id = t.id AND e.name = '配料' AND e.deleted = 0)
ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;

-- 按租户循环（存量租户）：`打包`
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, status)
SELECT 'op-v79-' || t.id || '-02', t.id, '打包', '后道', NULL, '套', 0, FALSE, FALSE, 37, 'active'
  FROM tenants t
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_operations e
        WHERE e.tenant_id = t.id AND e.name = '打包' AND e.deleted = 0)
ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 部位价目：补 36 格 ⇒ 84 + 36 = **120 格**（30 逻辑工序 × 4 部位）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 36 = 既有 28 道 × 新增部位 `布料`（**逐行显式 FALSE**：明确不做，不是缺行）+ `配料` × 4
--      + `打包` × 4。
-- ⚠️ **新状态「适用但未定价」**：`配料 × 布料` / `打包 × 4 部位` = `applicable=TRUE` 且
-- `unit_price = NULL`（商家在工序库自配）—— 与「不适用」（`applicable=FALSE`）**必须可区分**
-- （读面 `GET /api/admin/production/operation-positions` 逐行呈现两列）。
INSERT INTO production_operation_positions
    (id, tenant_id, logical_name, position, unit_price, applicable, status)
VALUES
  ('opp-v79-01', 1, '精裁', '布料', NULL, FALSE, 'active'),
  ('opp-v79-02', 1, '裁剪', '布料', NULL, FALSE, 'active'),
  ('opp-v79-03', 1, '三边', '布料', NULL, FALSE, 'active'),
  ('opp-v79-04', 1, '韩褶', '布料', NULL, FALSE, 'active'),
  ('opp-v79-05', 1, '上车布', '布料', NULL, FALSE, 'active'),
  ('opp-v79-06', 1, '打孔', '布料', NULL, FALSE, 'active'),
  ('opp-v79-07', 1, '拼1次', '布料', NULL, FALSE, 'active'),
  ('opp-v79-08', 1, '拼2次', '布料', NULL, FALSE, 'active'),
  ('opp-v79-09', 1, '拼3次', '布料', NULL, FALSE, 'active'),
  ('opp-v79-10', 1, '花边', '布料', NULL, FALSE, 'active'),
  ('opp-v79-11', 1, '铅坠', '布料', NULL, FALSE, 'active'),
  ('opp-v79-12', 1, '接高', '布料', NULL, FALSE, 'active'),
  ('opp-v79-13', 1, '帘头制作', '布料', NULL, FALSE, 'active'),
  ('opp-v79-14', 1, '熨烫', '布料', NULL, FALSE, 'active'),
  ('opp-v79-15', 1, '定型', '布料', NULL, FALSE, 'active'),
  ('opp-v79-16', 1, '复烫', '布料', NULL, FALSE, 'active'),
  ('opp-v79-17', 1, '车被', '布料', NULL, FALSE, 'active'),
  ('opp-v79-18', 1, '外帘打卷', '布料', NULL, FALSE, 'active'),
  ('opp-v79-19', 1, '外帘装袋', '布料', NULL, FALSE, 'active'),
  ('opp-v79-20', 1, '质检', '布料', NULL, FALSE, 'active'),
  ('opp-v79-21', 1, '外帘发货', '布料', NULL, FALSE, 'active'),
  ('opp-v79-22', 1, '绑带', '布料', NULL, FALSE, 'active'),
  ('opp-v79-23', 1, '抱枕', '布料', NULL, FALSE, 'active'),
  ('opp-v79-24', 1, '腰靠垫', '布料', NULL, FALSE, 'active'),
  ('opp-v79-25', 1, 'logo条', '布料', NULL, FALSE, 'active'),
  ('opp-v79-26', 1, '立边', '布料', NULL, FALSE, 'active'),
  ('opp-v79-27', 1, '扣环', '布料', NULL, FALSE, 'active'),
  ('opp-v79-28', 1, '防翘扣', '布料', NULL, FALSE, 'active'),
  ('opp-v79-29', 1, '配料', '布料', NULL, TRUE, 'active'),
  ('opp-v79-30', 1, '配料', '布帘', NULL, FALSE, 'active'),
  ('opp-v79-31', 1, '配料', '纱帘', NULL, FALSE, 'active'),
  ('opp-v79-32', 1, '配料', '帘头', NULL, FALSE, 'active'),
  ('opp-v79-33', 1, '打包', '布帘', NULL, TRUE, 'active'),
  ('opp-v79-34', 1, '打包', '纱帘', NULL, TRUE, 'active'),
  ('opp-v79-35', 1, '打包', '帘头', NULL, TRUE, 'active'),
  ('opp-v79-36', 1, '打包', '布料', NULL, TRUE, 'active')
ON CONFLICT (id) DO NOTHING;

-- 按租户循环（存量租户）：同一份 36 格。口径与 V72 ③ 逐字一致 —— 规范矩阵落到每个活跃租户，
-- 三重去重（`ON CONFLICT (id)` + 业务唯一键 `(tenant_id, logical_name, position)` + 不覆盖商家改过的行）。
INSERT INTO production_operation_positions
    (id, tenant_id, logical_name, position, unit_price, applicable, status)
SELECT 'opp-v79-' || t.id || '-' || v.logical_name || '-' || v.position,
       t.id, v.logical_name, v.position, v.unit_price, v.applicable, 'active'
  FROM tenants t
  JOIN (VALUES
      ('精裁', '布料', NULL, FALSE),
      ('裁剪', '布料', NULL, FALSE),
      ('三边', '布料', NULL, FALSE),
      ('韩褶', '布料', NULL, FALSE),
      ('上车布', '布料', NULL, FALSE),
      ('打孔', '布料', NULL, FALSE),
      ('拼1次', '布料', NULL, FALSE),
      ('拼2次', '布料', NULL, FALSE),
      ('拼3次', '布料', NULL, FALSE),
      ('花边', '布料', NULL, FALSE),
      ('铅坠', '布料', NULL, FALSE),
      ('接高', '布料', NULL, FALSE),
      ('帘头制作', '布料', NULL, FALSE),
      ('熨烫', '布料', NULL, FALSE),
      ('定型', '布料', NULL, FALSE),
      ('复烫', '布料', NULL, FALSE),
      ('车被', '布料', NULL, FALSE),
      ('外帘打卷', '布料', NULL, FALSE),
      ('外帘装袋', '布料', NULL, FALSE),
      ('质检', '布料', NULL, FALSE),
      ('外帘发货', '布料', NULL, FALSE),
      ('绑带', '布料', NULL, FALSE),
      ('抱枕', '布料', NULL, FALSE),
      ('腰靠垫', '布料', NULL, FALSE),
      ('logo条', '布料', NULL, FALSE),
      ('立边', '布料', NULL, FALSE),
      ('扣环', '布料', NULL, FALSE),
      ('防翘扣', '布料', NULL, FALSE),
      ('配料', '布料', NULL, TRUE),
      ('配料', '布帘', NULL, FALSE),
      ('配料', '纱帘', NULL, FALSE),
      ('配料', '帘头', NULL, FALSE),
      ('打包', '布帘', NULL, TRUE),
      ('打包', '纱帘', NULL, TRUE),
      ('打包', '帘头', NULL, TRUE),
      ('打包', '布料', NULL, TRUE)
  ) AS v(logical_name, position, unit_price, applicable)
    ON TRUE
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_operation_positions e
        WHERE e.tenant_id = t.id AND e.logical_name = v.logical_name
          AND e.position = v.position AND e.deleted = 0)
ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ provenance：两道新工序标 `占位待确认`（单价是占位值/未定价这件事必须**在数据上可见**）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 口径 = V62 的按 **id 前缀**认领（不是按名字列表 —— 名字列表会随改名漂移）。
-- ⚠️ 设计稿写 `source='待确认'`，而 DDL 的 CHECK 只允许 `('占位待确认','推算','实证')`
-- ⇒ **以代码事实为准**落 `占位待确认`（否则本迁移直接违反 CHECK 而报错）。
UPDATE production_operations
SET source = CASE
        WHEN id LIKE 'op-v79-%' THEN '占位待确认'
    END
WHERE source IS NULL
  AND id LIKE 'op-v79-%';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 工序作用域：`打包` = **套级**（`scope='set'`：一单一套一次，不按部位展开）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 口径与 V67（三道外帘工序）逐字一致。为什么必须落库而不是硬编码工序名：Java 侧
-- `ProcessingOrderService.buildPositionPayload` 的去重判据是**库里带出的 `scope`**
-- （`keepsSetLevel`）—— 一樘「布 + 纱」的订单里 `打包` 只落一次，**不双付**（#4408 实证形态：
-- 页面路径 14 道/¥3.00 vs 米宝路径 17 道/¥6.00）。
-- ⚠️ `配料` **不是**套级（它按**米**计、按部位算料）—— 标成套级会少发工人钱。
UPDATE production_operations
SET scope = 'set'
WHERE name IN ('打包');

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑤ 第 2 条基础路线：`布料工序路线`（每租户**两条**路线：窗帘默认 + 布料非默认）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 1 号租户字面量种子（终态与 `schema.sql` 逐字一致）
INSERT INTO production_route_templates
    (id, tenant_id, name, is_default, positions, mainline, status)
VALUES
  ('rt-v79-01', 1, '布料工序路线', FALSE,
   '["布料"]'::jsonb,
   '["配料", "打包"]'::jsonb,
   'active')
ON CONFLICT (id) DO NOTHING;

-- 按租户循环（存量租户）：主线 = 规范布料主线（`routing.py::FABRIC_MAINLINE_STEPS`）
-- ∩ **该租户自己的**工序库（与 V72 ④ 同款口径：库里没有的工序不进他的主线，也不给他种
-- 引用不到工序的路线）。业务唯一键 `(tenant_id, name)` 去重 ⇒ 1 号租户天然跳过。
INSERT INTO production_route_templates
    (id, tenant_id, name, is_default, positions, mainline, status)
SELECT 'rt-v79-' || t.id, t.id, '布料工序路线', FALSE,
       '["布料"]'::jsonb,
       COALESCE(
           (SELECT jsonb_agg(s.step ORDER BY s.ord)
              FROM unnest(ARRAY['配料', '打包']) WITH ORDINALITY AS s(step, ord)
             WHERE s.step IN (
                 SELECT CASE
                     WHEN o.name LIKE '%-布' THEN left(o.name, length(o.name) - 2)
                     WHEN o.name LIKE '%-纱' THEN left(o.name, length(o.name) - 2)
                     WHEN o.name = '布三边' THEN '三边'
                     WHEN o.name = '纱三边' THEN '三边'
                     WHEN o.name = '布帘车被' THEN '车被'
                     WHEN o.name = '帘头制作' THEN '帘头制作'
                     WHEN o.name = '上车布-布' THEN '上车布'
                     WHEN o.name = '上车布-纱' THEN '上车布'
                     ELSE o.name END
                   FROM production_operations o
                  WHERE o.tenant_id = t.id AND o.deleted = 0 AND o.status = 'active')),
           '["配料", "打包"]'::jsonb),
       'active'
  FROM tenants t
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_route_templates e
        WHERE e.tenant_id = t.id AND e.name = '布料工序路线' AND e.deleted = 0)
ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑥ 窗帘主线加 `打包`（9 → 10 道）：插在 `外帘打卷` 与 `外帘装袋` **之间**
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 位置依据（issue #4529 第 3 条评论）：ERP 加工单实证 `外帘打包 › 外帘装箱 › 外帘发货`，
-- `外帘装袋` ≈ ERP 的 `外帘装箱` ⇒ **打包在装袋之前**。
-- ⚠️ **照实登记**：#4343 明确登记过这两道的对应关系**未能确定** ⇒ 本顺序是**按 ERP 顺序推断**、
-- **待客户确认**（不假装定论）。
--
-- 形态（**手术式插入**，不是整条重建）：保留商家已改过的主线顺序/删减，只把 `打包` 插到
-- `外帘装袋` **之前**（该锚点不存在 ⇒ 追加末尾，与 `_insert_after` 同款兜底）。
-- 幂等：`NOT (mainline @> '["打包"]'::jsonb)`（已有则整条跳过）。
UPDATE production_route_templates
SET mainline = (
        SELECT jsonb_agg(elem ORDER BY ord)
          FROM (
              SELECT elem, ord::numeric AS ord
                FROM jsonb_array_elements(mainline) WITH ORDINALITY AS e(elem, ord)
              UNION ALL
              SELECT '"打包"'::jsonb,
                     COALESCE((SELECT MIN(ord)::numeric
                                 FROM jsonb_array_elements(mainline) WITH ORDINALITY AS a(elem2, ord)
                                WHERE elem2 = '"外帘装袋"'::jsonb), 10000) - 0.5
          ) AS s
      ),
    updated_at = NOW()
WHERE deleted = 0
  AND is_default
  AND NOT (mainline @> '["打包"]'::jsonb);
