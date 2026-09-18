\pset border 2
\echo '=== 候选单的订单状态/租户（生成加工单需要什么状态？看 #4208 实测是"确认付款"后）==='
SELECT o.id AS order_id, o.order_no, o.status, o.tenant_id, o.payment_status, o.created_at
FROM orders o
WHERE o.id IN ('8614224ecd54374e0cbf33c1cb564958','b8d16613b0f2eae15852e418822f88ff',
               '78d207ac2d30c609d5f68cbc9128ccb6','53be16a1c433bfcdde92acb323a25eec',
               'c9a1aa7d33ba4ec7394c41c0f8b0eecc','c7614f5b2ea89b7af2ad12d2496659c3')
ORDER BY o.created_at DESC;

\echo ''
\echo '=== 13800138000 对应哪个租户 ==='
SELECT u.id, u.phone, u.tenant_id, u.role FROM users u WHERE u.phone = '13800138000' AND u.deleted = 0;

\echo ''
\echo '=== 各租户的订单数（确认候选单归属）==='
SELECT o.tenant_id, count(*) AS n FROM orders o WHERE o.deleted = 0 GROUP BY 1 ORDER BY n DESC;
