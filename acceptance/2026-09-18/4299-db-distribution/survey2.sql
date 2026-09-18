-- issue #4299 真库复核 第 2 轮（只读）：修正第 1 轮 [4]/[5] 的 NULL 分支穿透 + 加「可达 calcInfo 的口径」
-- 背景：buildSnapshot() 对 extractProcessingItems 为空的 order_item 直接 continue
--      ⇒ **只有带非空 processingItems 的 order_items 才可能进加工单/才可能走 calcInfo**。

\pset border 2
\pset format aligned

\echo '=== [A] 修正版：无 sellingMethod 的 566 条，按「能否进 calcInfo」拆开 ==='
SELECT CASE
         WHEN oi.processing_info IS NULL                                THEN 'A1 processing_info 为 NULL（永不进快照）'
         WHEN jsonb_typeof(oi.processing_info->'processingItems') IS DISTINCT FROM 'array'
                                                                        THEN 'A2 无 processingItems 数组（永不进快照）'
         WHEN jsonb_array_length(oi.processing_info->'processingItems') = 0
                                                                        THEN 'A3 processingItems 空数组（永不进快照）'
         WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(oi.processing_info->'processingItems') e
                      WHERE e->>'pricingMethod' = 'per_meter')          THEN 'A4 可达 calcInfo 且有 per_meter 加工项'
         ELSE 'A5 可达 calcInfo 但无 per_meter 加工项'
       END                    AS shape,
       count(*)               AS n
FROM order_items oi
WHERE oi.deleted = 0
  AND COALESCE(oi.processing_info->>'sellingMethod', '(无)') = '(无)'
GROUP BY 1
ORDER BY 1;

\echo ''
\echo '=== [B] 【可达面】只统计「带非空 processingItems」的 order_items：sellingMethod × 有无 per_meter 加工项 ==='
SELECT COALESCE(oi.processing_info->>'sellingMethod', '(无)')            AS selling_method,
       EXISTS (SELECT 1 FROM jsonb_array_elements(oi.processing_info->'processingItems') e
               WHERE e->>'pricingMethod' = 'per_meter')                  AS has_per_meter_item,
       count(*)                                                          AS n_order_items
FROM order_items oi
WHERE oi.deleted = 0
  AND jsonb_typeof(oi.processing_info->'processingItems') = 'array'
  AND jsonb_array_length(oi.processing_info->'processingItems') > 0
GROUP BY 1, 2
ORDER BY n_order_items DESC;

\echo ''
\echo '=== [C] 可达面总计：多少 order_items 会进 calcInfo，其中多少能被 per_meter 判据命中 ==='
SELECT count(*)                                                                    AS reachable_order_items,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(oi.processing_info->'processingItems') e
                                      WHERE e->>'pricingMethod' = 'per_meter'))        AS hit_by_per_meter_item_judge,
       count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM jsonb_array_elements(oi.processing_info->'processingItems') e
                                          WHERE e->>'pricingMethod' = 'per_meter'))    AS miss_keep_fallback
FROM order_items oi
WHERE oi.deleted = 0
  AND jsonb_typeof(oi.processing_info->'processingItems') = 'array'
  AND jsonb_array_length(oi.processing_info->'processingItems') > 0;

\echo ''
\echo '=== [D] 对照：若改用 products.pricing_type 判据，在可达面上的命中数（按 productId 关联）==='
SELECT COALESCE(p.pricing_type, '(商品缺失/软删)')                                  AS pricing_type,
       count(*)                                                                    AS n_order_items,
       count(*) FILTER (WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(oi.processing_info->'processingItems') e
                                      WHERE e->>'pricingMethod' = 'per_meter'))     AS also_has_per_meter_item
FROM order_items oi
LEFT JOIN products p ON p.id = oi.product_id AND p.deleted = 0
WHERE oi.deleted = 0
  AND jsonb_typeof(oi.processing_info->'processingItems') = 'array'
  AND jsonb_array_length(oi.processing_info->'processingItems') > 0
GROUP BY 1
ORDER BY n_order_items DESC;

\echo ''
\echo '=== [E] 未命中 per_meter 判据的那批（要保持 fallback）长什么样 ==='
SELECT oi.id, oi.quantity AS order_qty,
       oi.processing_info->>'sellingMethod' AS selling_method,
       p.pricing_type,
       (SELECT string_agg(DISTINCT COALESCE(e->>'pricingMethod','(无)'), ',')
        FROM jsonb_array_elements(oi.processing_info->'processingItems') e) AS item_pricing_methods,
       (SELECT string_agg(DISTINCT COALESCE(e->>'name','(无名)'), ',')
        FROM jsonb_array_elements(oi.processing_info->'processingItems') e) AS item_names
FROM order_items oi
LEFT JOIN products p ON p.id = oi.product_id AND p.deleted = 0
WHERE oi.deleted = 0
  AND jsonb_typeof(oi.processing_info->'processingItems') = 'array'
  AND jsonb_array_length(oi.processing_info->'processingItems') > 0
  AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements(oi.processing_info->'processingItems') e
                  WHERE e->>'pricingMethod' = 'per_meter')
ORDER BY oi.created_at DESC;

\echo ''
\echo '=== [F] 整卷（full_roll/整卷）单在可达面上的形态 —— 检验「quantity 是否米数」的假设 ==='
SELECT oi.id, oi.quantity AS order_qty,
       COALESCE(oi.processing_info->>'sellingMethod','(无)') AS selling_method,
       (SELECT string_agg(DISTINCT COALESCE(e->>'pricingMethod','(无)')||':'||COALESCE(e->>'quantity','-'), ',')
        FROM jsonb_array_elements(oi.processing_info->'processingItems') e) AS item_pricing_and_qty
FROM order_items oi
WHERE oi.deleted = 0
  AND jsonb_typeof(oi.processing_info->'processingItems') = 'array'
  AND jsonb_array_length(oi.processing_info->'processingItems') > 0
  AND COALESCE(oi.processing_info->>'sellingMethod','') IN ('full_roll','整卷')
ORDER BY oi.created_at DESC;
