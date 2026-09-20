-- issue #4777 真库核实 —— **纯只读**（全部 SELECT；无任何写语句）。
--
-- 目的：核清「`applicable = TRUE` 的矩阵格，其变体名解析得到吗」，并把 #4672 留下的
-- 「从未登记」格（其口径**不含** `variantNameOf` 的帘头回落）**分类**为
-- 「商家配过价 / 有商家意图」vs「从未配过、也无商家意图」。
--
-- 🔴 本文件**不删任何格**（商家配过的价是资产）。
--
-- 解析口径 = 生产代码 `ProductionOperationQueryService.variantNameOf` 的四步，**逐字对齐**：
--   ① `VARIANT_NAMES[逻辑名][部位]` 命中**且**该变体在活跃工序库 ⇒ 用它；
--   ② `部位 = 帘头` 且 `VARIANT_NAMES[逻辑名][布帘]` 在活跃库 ⇒ 回落布帘变体；
--   ③ 裸逻辑名在活跃库 ⇒ 用它（部位无关工序）；
--   ④ 否则 NULL。
-- ⚠️ `variant_map` 是 Java `variantNames()` 的**逐条字面量**（30 条 = 布帘 21 + 纱帘 7 + 帘头 1 + 布料 1）；
--    与 `tests/unit_ci_workflows/test_v97_orphan_positions_cleanup.py` 的静态比对同源。
-- ⚠️ 「活跃工序库」= `production_operations` 的 `deleted = 0`（**不过滤 status** —— 与
--    `catalogByName` 同口径：路线引用了停用工序时要能指名报缺，而不是当它不存在）。

\pset pager off
\echo '===== 0. 活跃租户 ====='
SELECT t.id AS tenant_id, t.name
  FROM tenants t
 WHERE t.deleted = 0
 ORDER BY t.id;

\echo '===== 1. 每租户活跃矩阵格数（含 #4672 清理后的现状）====='
SELECT p.tenant_id, count(*) AS active_cells
  FROM production_operation_positions p
 WHERE p.deleted = 0 AND p.status = 'active'
 GROUP BY p.tenant_id ORDER BY p.tenant_id;

\echo '===== 2. 🔴 承重判据：applicable = TRUE 的格解析不到变体名（应为 0 行）====='
WITH variant_map(logical_name, position, variant_name) AS (VALUES
    ('精裁',   '布帘', '精裁-布'),   ('裁剪',   '布帘', '裁剪-布'),
    ('三边',   '布帘', '布三边'),    ('韩褶',   '布帘', '韩褶-布'),
    ('上车布', '布帘', '上车布-布'), ('打孔',   '布帘', '打孔-布'),
    ('拼1次',  '布帘', '拼1次-布'),  ('拼2次',  '布帘', '拼2次-布'),
    ('拼3次',  '布帘', '拼3次-布'),  ('花边',   '布帘', '花边-布'),
    ('铅坠',   '布帘', '铅坠-布'),   ('接高',   '布帘', '接高-布'),
    ('熨烫',   '布帘', '熨烫-布'),   ('定型',   '布帘', '定型-布'),
    ('复烫',   '布帘', '复烫-布'),   ('车被',   '布帘', '布帘车被'),
    ('绑带',   '布帘', '绑带-布'),   ('logo条', '布帘', 'logo条-布'),
    ('立边',   '布帘', '立边-布'),   ('扣环',   '布帘', '扣环-布'),
    ('防翘扣', '布帘', '防翘扣-布'),
    ('精裁',   '纱帘', '精裁-纱'),   ('裁剪',   '纱帘', '裁剪-纱'),
    ('三边',   '纱帘', '纱三边'),    ('韩褶',   '纱帘', '韩褶-纱'),
    ('上车布', '纱帘', '上车布-纱'), ('打孔',   '纱帘', '打孔-纱'),
    ('绑带',   '纱帘', '绑带-纱'),
    ('帘头制作', '帘头', '帘头制作'),
    ('裁剪',   '布料', '裁剪-布')
),
resolved AS (
    SELECT p.id, p.tenant_id, p.logical_name, p.position, p.unit_price, p.applicable,
           CASE
             WHEN v.variant_name IS NOT NULL AND EXISTS (
                   SELECT 1 FROM production_operations o
                    WHERE o.tenant_id = p.tenant_id AND o.name = v.variant_name AND o.deleted = 0)
               THEN v.variant_name
             WHEN p.position = '帘头' AND vb.variant_name IS NOT NULL AND EXISTS (
                   SELECT 1 FROM production_operations o
                    WHERE o.tenant_id = p.tenant_id AND o.name = vb.variant_name AND o.deleted = 0)
               THEN vb.variant_name
             WHEN EXISTS (SELECT 1 FROM production_operations o
                           WHERE o.tenant_id = p.tenant_id AND o.name = p.logical_name AND o.deleted = 0)
               THEN p.logical_name
             ELSE NULL
           END AS expected
      FROM production_operation_positions p
      LEFT JOIN variant_map v  ON v.logical_name = p.logical_name AND v.position = p.position
      LEFT JOIN variant_map vb ON vb.logical_name = p.logical_name AND vb.position = '布帘'
     WHERE p.deleted = 0 AND p.status = 'active'
)
SELECT tenant_id, position, logical_name, unit_price, applicable, expected
  FROM resolved
 WHERE applicable IS TRUE AND expected IS NULL
 ORDER BY tenant_id, position, logical_name;

\echo '===== 3. 解析不到变体名的**全部**活跃格（含 applicable = FALSE；对照面）====='
WITH variant_map(logical_name, position, variant_name) AS (VALUES
    ('精裁',   '布帘', '精裁-布'),   ('裁剪',   '布帘', '裁剪-布'),
    ('三边',   '布帘', '布三边'),    ('韩褶',   '布帘', '韩褶-布'),
    ('上车布', '布帘', '上车布-布'), ('打孔',   '布帘', '打孔-布'),
    ('拼1次',  '布帘', '拼1次-布'),  ('拼2次',  '布帘', '拼2次-布'),
    ('拼3次',  '布帘', '拼3次-布'),  ('花边',   '布帘', '花边-布'),
    ('铅坠',   '布帘', '铅坠-布'),   ('接高',   '布帘', '接高-布'),
    ('熨烫',   '布帘', '熨烫-布'),   ('定型',   '布帘', '定型-布'),
    ('复烫',   '布帘', '复烫-布'),   ('车被',   '布帘', '布帘车被'),
    ('绑带',   '布帘', '绑带-布'),   ('logo条', '布帘', 'logo条-布'),
    ('立边',   '布帘', '立边-布'),   ('扣环',   '布帘', '扣环-布'),
    ('防翘扣', '布帘', '防翘扣-布'),
    ('精裁',   '纱帘', '精裁-纱'),   ('裁剪',   '纱帘', '裁剪-纱'),
    ('三边',   '纱帘', '纱三边'),    ('韩褶',   '纱帘', '韩褶-纱'),
    ('上车布', '纱帘', '上车布-纱'), ('打孔',   '纱帘', '打孔-纱'),
    ('绑带',   '纱帘', '绑带-纱'),
    ('帘头制作', '帘头', '帘头制作'),
    ('裁剪',   '布料', '裁剪-布')
),
resolved AS (
    SELECT p.id, p.tenant_id, p.logical_name, p.position, p.unit_price, p.applicable,
           CASE
             WHEN v.variant_name IS NOT NULL AND EXISTS (
                   SELECT 1 FROM production_operations o
                    WHERE o.tenant_id = p.tenant_id AND o.name = v.variant_name AND o.deleted = 0)
               THEN v.variant_name
             WHEN p.position = '帘头' AND vb.variant_name IS NOT NULL AND EXISTS (
                   SELECT 1 FROM production_operations o
                    WHERE o.tenant_id = p.tenant_id AND o.name = vb.variant_name AND o.deleted = 0)
               THEN vb.variant_name
             WHEN EXISTS (SELECT 1 FROM production_operations o
                           WHERE o.tenant_id = p.tenant_id AND o.name = p.logical_name AND o.deleted = 0)
               THEN p.logical_name
             ELSE NULL
           END AS expected
      FROM production_operation_positions p
      LEFT JOIN variant_map v  ON v.logical_name = p.logical_name AND v.position = p.position
      LEFT JOIN variant_map vb ON vb.logical_name = p.logical_name AND vb.position = '布帘'
     WHERE p.deleted = 0 AND p.status = 'active'
)
SELECT position, count(*) AS n, count(*) FILTER (WHERE applicable IS TRUE) AS applicable_true,
       count(*) FILTER (WHERE unit_price IS NOT NULL) AS priced
  FROM resolved WHERE expected IS NULL
 GROUP BY position ORDER BY position;

\echo '===== 4. #4672 的「从未登记」口径（**不含**帘头回落 = V97 的 variant_map）分类 ====='
-- 口径逐字 = V97 的 `expected`（`v.logical_name IS NULL ⇒ 裸逻辑名`）+ 「活跃库里没有」。
WITH variant_map(logical_name, position, variant_name) AS (VALUES
    ('精裁',   '布帘', '精裁-布'),   ('裁剪',   '布帘', '裁剪-布'),
    ('三边',   '布帘', '布三边'),    ('韩褶',   '布帘', '韩褶-布'),
    ('上车布', '布帘', '上车布-布'), ('打孔',   '布帘', '打孔-布'),
    ('拼1次',  '布帘', '拼1次-布'),  ('拼2次',  '布帘', '拼2次-布'),
    ('拼3次',  '布帘', '拼3次-布'),  ('花边',   '布帘', '花边-布'),
    ('铅坠',   '布帘', '铅坠-布'),   ('接高',   '布帘', '接高-布'),
    ('熨烫',   '布帘', '熨烫-布'),   ('定型',   '布帘', '定型-布'),
    ('复烫',   '布帘', '复烫-布'),   ('车被',   '布帘', '布帘车被'),
    ('绑带',   '布帘', '绑带-布'),   ('logo条', '布帘', 'logo条-布'),
    ('立边',   '布帘', '立边-布'),   ('扣环',   '布帘', '扣环-布'),
    ('防翘扣', '布帘', '防翘扣-布'),
    ('精裁',   '纱帘', '精裁-纱'),   ('裁剪',   '纱帘', '裁剪-纱'),
    ('三边',   '纱帘', '纱三边'),    ('韩褶',   '纱帘', '韩褶-纱'),
    ('上车布', '纱帘', '上车布-纱'), ('打孔',   '纱帘', '打孔-纱'),
    ('绑带',   '纱帘', '绑带-纱'),
    ('帘头制作', '帘头', '帘头制作'),
    ('裁剪',   '布料', '裁剪-布')
),
v97 AS (
    SELECT p.id, p.tenant_id, p.logical_name, p.position, p.unit_price, p.applicable,
           CASE WHEN v.logical_name IS NULL THEN p.logical_name ELSE v.variant_name END AS expected
      FROM production_operation_positions p
      LEFT JOIN variant_map v ON v.logical_name = p.logical_name AND v.position = p.position
     WHERE p.deleted = 0 AND p.status = 'active'
)
SELECT count(*) AS never_registered_total,
       count(*) FILTER (WHERE unit_price IS NOT NULL OR applicable IS TRUE) AS merchant_intent,
       count(*) FILTER (WHERE unit_price IS NULL AND applicable IS NOT TRUE) AS no_intent
  FROM v97 r
 WHERE NOT EXISTS (SELECT 1 FROM production_operations o
                    WHERE o.tenant_id = r.tenant_id AND o.name = r.expected AND o.deleted = 0);

\echo '===== 4b. 上表按租户 / 部位 / 逻辑名分布（merchant_intent 明细）====='
WITH variant_map(logical_name, position, variant_name) AS (VALUES
    ('精裁',   '布帘', '精裁-布'),   ('裁剪',   '布帘', '裁剪-布'),
    ('三边',   '布帘', '布三边'),    ('韩褶',   '布帘', '韩褶-布'),
    ('上车布', '布帘', '上车布-布'), ('打孔',   '布帘', '打孔-布'),
    ('拼1次',  '布帘', '拼1次-布'),  ('拼2次',  '布帘', '拼2次-布'),
    ('拼3次',  '布帘', '拼3次-布'),  ('花边',   '布帘', '花边-布'),
    ('铅坠',   '布帘', '铅坠-布'),   ('接高',   '布帘', '接高-布'),
    ('熨烫',   '布帘', '熨烫-布'),   ('定型',   '布帘', '定型-布'),
    ('复烫',   '布帘', '复烫-布'),   ('车被',   '布帘', '布帘车被'),
    ('绑带',   '布帘', '绑带-布'),   ('logo条', '布帘', 'logo条-布'),
    ('立边',   '布帘', '立边-布'),   ('扣环',   '布帘', '扣环-布'),
    ('防翘扣', '布帘', '防翘扣-布'),
    ('精裁',   '纱帘', '精裁-纱'),   ('裁剪',   '纱帘', '裁剪-纱'),
    ('三边',   '纱帘', '纱三边'),    ('韩褶',   '纱帘', '韩褶-纱'),
    ('上车布', '纱帘', '上车布-纱'), ('打孔',   '纱帘', '打孔-纱'),
    ('绑带',   '纱帘', '绑带-纱'),
    ('帘头制作', '帘头', '帘头制作'),
    ('裁剪',   '布料', '裁剪-布')
),
v97 AS (
    SELECT p.id, p.tenant_id, p.logical_name, p.position, p.unit_price, p.applicable,
           CASE WHEN v.logical_name IS NULL THEN p.logical_name ELSE v.variant_name END AS expected
      FROM production_operation_positions p
      LEFT JOIN variant_map v ON v.logical_name = p.logical_name AND v.position = p.position
     WHERE p.deleted = 0 AND p.status = 'active'
)
SELECT r.tenant_id, r.position, r.logical_name, r.unit_price, r.applicable, r.expected
  FROM v97 r
 WHERE NOT EXISTS (SELECT 1 FROM production_operations o
                    WHERE o.tenant_id = r.tenant_id AND o.name = r.expected AND o.deleted = 0)
   AND (r.unit_price IS NOT NULL OR r.applicable IS TRUE)
 ORDER BY r.tenant_id, r.position, r.logical_name;

\echo '===== 5. 每租户活跃工序库（36 道基线；解析源）====='
SELECT o.tenant_id, count(*) AS active_ops,
       string_agg(o.name, ', ' ORDER BY o.name) AS names
  FROM production_operations o
 WHERE o.deleted = 0
 GROUP BY o.tenant_id ORDER BY o.tenant_id;

\echo '===== 6. 🔴 历史值指纹（production_work_logs 的 unit_price / factor）====='
SELECT tenant_id, count(*) AS rows,
       md5(string_agg(id || ':' || coalesce(unit_price::text, 'N') || ':' || coalesce(factor::text, 'N'),
                      '|' ORDER BY id)) AS price_factor_md5
  FROM production_work_logs
 GROUP BY tenant_id ORDER BY tenant_id;

\echo '===== 7. 🔴 快照表指纹（processing_position_operations）====='
SELECT tenant_id, count(*) AS rows
  FROM processing_position_operations
 GROUP BY tenant_id ORDER BY tenant_id;

\echo '===== 8. 帘头格全量（价格 + 可解析性，逐条）====='
SELECT p.tenant_id, p.logical_name, p.unit_price, p.applicable,
       (SELECT string_agg(o.name, ',') FROM production_operations o
         WHERE o.tenant_id = p.tenant_id AND o.deleted = 0
           AND o.name IN (p.logical_name, p.logical_name || '-布', '布' || p.logical_name)) AS candidates
  FROM production_operation_positions p
 WHERE p.deleted = 0 AND p.status = 'active' AND p.position = '帘头'
 ORDER BY p.tenant_id, p.logical_name;
