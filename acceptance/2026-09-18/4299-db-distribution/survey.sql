-- issue #4299 真库取值分布复核（只读；云 dev 库 ai_customer_service）
-- 目的：① 复核上一会话的 sellingMethod 分布读数；② 为「加工项 pricingMethod」判据取真实分布。
-- 运行：bash run.sh（凭据从 backend/admin-api/.env 读取，不落盘）

\pset border 2
\pset format aligned

\echo '=== [1] order_items.processing_info.sellingMethod 取值分布 ==='
SELECT COALESCE(processing_info->>'sellingMethod', '(无)') AS selling_method,
       count(*) AS n
FROM order_items
WHERE deleted = 0
GROUP BY 1
ORDER BY n DESC;

\echo ''
\echo '=== [2] order_items 总数 / 带 processing_info / 带 processingItems 的口径对照 ==='
SELECT count(*)                                                        AS order_items_total,
       count(*) FILTER (WHERE processing_info IS NOT NULL)             AS has_processing_info,
       count(*) FILTER (WHERE jsonb_typeof(processing_info->'processingItems') = 'array'
                          AND jsonb_array_length(processing_info->'processingItems') > 0)
                                                                       AS has_processing_items
FROM order_items
WHERE deleted = 0;

\echo ''
\echo '=== [3] 【判据关键】processing_info.processingItems[].pricingMethod 取值分布（按加工项条目展开）==='
SELECT COALESCE(item->>'pricingMethod', '(无)') AS pricing_method,
       count(*)                                 AS n_items,
       count(DISTINCT oi.id)                    AS n_order_items
FROM order_items oi
CROSS JOIN LATERAL jsonb_array_elements(oi.processing_info->'processingItems') AS item
WHERE oi.deleted = 0
  AND jsonb_typeof(oi.processing_info->'processingItems') = 'array'
GROUP BY 1
ORDER BY n_items DESC;

\echo ''
\echo '=== [4] 【(无) 那批的形状】无 sellingMethod 的 order_items：有没有可用 pricingMethod ==='
SELECT CASE
         WHEN jsonb_typeof(oi.processing_info->'processingItems') <> 'array' THEN '无 processingItems'
         WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(oi.processing_info->'processingItems') e
                      WHERE e->>'pricingMethod' = 'per_meter')             THEN '有 per_meter 加工项'
         WHEN EXISTS (SELECT 1 FROM jsonb_array_elements(oi.processing_info->'processingItems') e
                      WHERE e ? 'pricingMethod')                           THEN '有 pricingMethod 但非 per_meter'
         ELSE '有 processingItems 但无 pricingMethod 键'
       END                                   AS shape,
       count(*)                              AS n
FROM order_items oi
WHERE oi.deleted = 0
  AND COALESCE(oi.processing_info->>'sellingMethod', '(无)') = '(无)'
GROUP BY 1
ORDER BY n DESC;

\echo ''
\echo '=== [5] 交叉表：sellingMethod × 是否有 per_meter 加工项（看判据覆盖是否互相印证）==='
SELECT COALESCE(oi.processing_info->>'sellingMethod', '(无)') AS selling_method,
       EXISTS (SELECT 1 FROM jsonb_array_elements(oi.processing_info->'processingItems') e
               WHERE e->>'pricingMethod' = 'per_meter')           AS has_per_meter_item,
       count(*)                                                   AS n
FROM order_items oi
WHERE oi.deleted = 0
  AND jsonb_typeof(oi.processing_info->'processingItems') = 'array'
GROUP BY 1, 2
ORDER BY n DESC;

\echo ''
\echo '=== [6] 对照项：products.pricing_type 分布（用户原选 (B) 的字段）==='
SELECT COALESCE(pricing_type, '(无)') AS pricing_type, count(*) AS n
FROM products
WHERE deleted = 0
GROUP BY 1
ORDER BY n DESC;

\echo ''
\echo '=== [7] processing_orders.items_snapshot 的 sellingMethod 分布（复核 bulk_cut ×31）==='
SELECT COALESCE(elem->>'sellingMethod', '(无)') AS selling_method, count(*) AS n
FROM processing_orders po
CROSS JOIN LATERAL jsonb_array_elements(po.items_snapshot) AS elem
WHERE po.deleted = 0
  AND jsonb_typeof(po.items_snapshot) = 'array'
GROUP BY 1
ORDER BY n DESC;

\echo ''
\echo '=== [8] 抽样：有 per_meter 加工项的单，看 quantity 与加工项 quantity 是否一致（判据取值口径）==='
SELECT oi.id,
       oi.quantity                                    AS order_qty,
       oi.processing_info->>'sellingMethod'           AS selling_method,
       item->>'name'                                  AS item_name,
       item->>'pricingMethod'                         AS item_pricing,
       item->>'quantity'                              AS item_qty
FROM order_items oi
CROSS JOIN LATERAL jsonb_array_elements(oi.processing_info->'processingItems') AS item
WHERE oi.deleted = 0
  AND item->>'pricingMethod' = 'per_meter'
ORDER BY oi.created_at DESC
LIMIT 15;
