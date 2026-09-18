\pset border 2
\echo '=== 负例候选（唯一不命中新判据：per_sqm 刺绣单）能否做 E2E ==='
SELECT oi.order_id, o.status, o.order_no, oi.quantity,
       (SELECT count(*) FROM processing_orders po WHERE po.order_id = oi.order_id AND po.deleted = 0) AS existing_pos,
       (SELECT string_agg(COALESCE(e->>'name','?')||'/'||COALESCE(e->>'pricingMethod','(无)'), ',')
        FROM jsonb_array_elements(oi.processing_info->'processingItems') e) AS items
FROM order_items oi JOIN orders o ON o.id = oi.order_id
WHERE oi.deleted = 0 AND oi.id = '286229cf25d3201e33c263a1c63e10bf';

\echo ''
\echo '=== 「取值用订单行 quantity」的关键反例（订单 112 / 加工项 per_meter qty=1）完整一行 ==='
SELECT oi.order_id, o.status, oi.quantity AS order_qty, oi.processing_info->>'sellingMethod' AS selling_method,
       (SELECT string_agg(COALESCE(e->>'name','?')||'/'||COALESCE(e->>'pricingMethod','(无)')||'/q='||COALESCE(e->>'quantity','-'), ' | ')
        FROM jsonb_array_elements(oi.processing_info->'processingItems') e) AS items,
       (SELECT count(*) FROM processing_orders po WHERE po.order_id = oi.order_id AND po.deleted = 0) AS existing_pos
FROM order_items oi JOIN orders o ON o.id = oi.order_id
WHERE oi.deleted = 0 AND oi.id = '7e6f2a1cb7ce474534571c03ec746711';

\echo ''
\echo '=== 本次 E2E 已消耗的订单（RED）留痕 ==='
SELECT po.processing_order_no, po.order_id, po.status, po.created_at
FROM processing_orders po WHERE po.order_id = '78d207ac2d30c609d5f68cbc9128ccb6';
