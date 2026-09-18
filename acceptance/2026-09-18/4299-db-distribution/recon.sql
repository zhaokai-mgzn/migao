\pset border 2
\echo '=== 上一会话的红证单：JG-20260918-3967 ==='
SELECT po.id, po.processing_order_no, po.order_id, po.status, po.created_at
FROM processing_orders po WHERE po.processing_order_no = 'JG-20260918-3967';

\echo ''
\echo '=== 该加工单的工序实例（红证现场：米类 qty / qty_source）==='
SELECT ppo.seq, ppo.operation_name, ppo.unit, ppo.qty, ppo.qty_source, ppo.position_name
FROM processing_position_operations ppo
JOIN processing_orders po ON po.id = ppo.processing_order_id
WHERE po.processing_order_no = 'JG-20260918-3967' AND ppo.deleted = 0
ORDER BY ppo.seq;

\echo ''
\echo '=== 该加工单对应的订单行（看 processing_info 的加工项 pricingMethod）==='
SELECT oi.id, oi.quantity, oi.processing_info->>'sellingMethod' AS selling_method,
       (SELECT string_agg(COALESCE(e->>'name','?')||'/'||COALESCE(e->>'pricingMethod','(无)')||'/q='||COALESCE(e->>'quantity','-'), ' | ')
        FROM jsonb_array_elements(oi.processing_info->'processingItems') e) AS items
FROM processing_orders po JOIN order_items oi ON oi.order_id = po.order_id AND oi.deleted = 0
WHERE po.processing_order_no = 'JG-20260918-3967';

\echo ''
\echo '=== 可复用的候选单：带 per_meter 加工项、且还没生成过加工单的订单 ==='
SELECT oi.order_id, oi.id AS item_id, oi.quantity, oi.processing_info->>'sellingMethod' AS selling_method,
       (SELECT count(*) FROM processing_orders po WHERE po.order_id = oi.order_id AND po.deleted = 0) AS existing_pos
FROM order_items oi
WHERE oi.deleted = 0
  AND jsonb_typeof(oi.processing_info->'processingItems') = 'array'
  AND EXISTS (SELECT 1 FROM jsonb_array_elements(oi.processing_info->'processingItems') e
              WHERE e->>'pricingMethod' = 'per_meter')
ORDER BY existing_pos, oi.created_at DESC
LIMIT 12;
