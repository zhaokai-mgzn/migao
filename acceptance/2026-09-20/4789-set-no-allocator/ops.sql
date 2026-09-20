-- #4789 运维复跑 SQL（云 dev RDS；本机出口 IP 不在白名单 ⇒ 由运维/白名单内机器执行）
-- 用法：
--   psql -h "$RDS_HOST" -U migao_admin -d ai_customer_service -v ON_ERROR_STOP=1 -f ops.sql
-- 全部为**只读** SELECT（无写操作）。

\echo '=== A 套号载体现状：行数 + 谁写的（id 前缀）==='
SELECT count(*) AS sets_total,
       count(*) FILTER (WHERE deleted = 0) AS sets_live,
       count(DISTINCT processing_order_id) AS orders_with_sets
  FROM processing_order_sets;

SELECT split_part(id, '-', 1) || '-' || split_part(id, '-', 2) AS id_prefix,
       count(*) AS rows
  FROM processing_order_sets
 GROUP BY 1 ORDER BY 2 DESC;

\echo '=== B 缺口读数（改前的形态）：活跃加工单 vs 有套行的加工单 ==='
SELECT (SELECT count(*) FROM processing_orders WHERE deleted = 0) AS live_pos,
       (SELECT count(DISTINCT processing_order_id) FROM processing_order_sets WHERE deleted = 0)
           AS pos_with_sets;

\echo '=== C 新单（无套行）样例：这些单的二维码按钮此前是空的 ==='
SELECT po.processing_order_no, po.status, po.created_at,
       (SELECT count(*) FROM processing_position_operations o
         WHERE o.processing_order_id = po.id AND o.deleted = 0) AS ops,
       (SELECT count(*) FROM processing_position_operations o
         WHERE o.processing_order_id = po.id AND o.deleted = 0 AND o.set_id IS NOT NULL)
           AS ops_with_set
  FROM processing_orders po
 WHERE po.deleted = 0
   AND NOT EXISTS (SELECT 1 FROM processing_order_sets s
                    WHERE s.processing_order_id = po.id AND s.deleted = 0)
 ORDER BY po.created_at DESC LIMIT 10;

\echo '=== D 部位码载体现状（改前应为 0 行：全仓零写方）==='
SELECT count(*) AS part_tokens_total,
       count(*) FILTER (WHERE token IS NOT NULL) AS with_token,
       count(*) FILTER (WHERE deleted = 0) AS live
  FROM processing_set_part_tokens;

\echo '=== E 🔴 历史值红线基线（部署前后各跑一次，逐值必须一致）==='
-- 报工快照（unit_price / factor）—— 本单**零命中**这两列（不写、不改）
SELECT md5(string_agg(unit_price::text || '|' || coalesce(factor::text, '-'), ','
                      ORDER BY id)) AS work_logs_md5,
       count(*) AS rows
  FROM production_work_logs WHERE deleted = 0;
-- 订单总额 —— 本单**零命中** orders（不写、不改）
SELECT md5(string_agg(total_amount::text, ',' ORDER BY id)) AS orders_total_md5,
       count(*) AS rows
  FROM orders WHERE deleted = 0;
-- 工序实例快照的**既有列**（本单只新增 set_id/set_no 的写方；既有列一字不动）
SELECT md5(string_agg(id || '|' || coalesce(order_item_id, '-') || '|' || coalesce(position_name, '-')
                      || '|' || coalesce(status, '-'), ',' ORDER BY id)) AS ops_existing_cols_md5,
       count(*) AS rows
  FROM processing_position_operations WHERE deleted = 0;

\echo '=== F 分配器上线后的验收读数（新单应有套行；每单 set_index 连续 1..MAX）==='
SELECT s.tenant_id, s.processing_order_id, count(*) AS live_sets,
       min(s.set_index) AS min_idx, max(s.set_index) AS max_idx
  FROM processing_order_sets s
 WHERE s.deleted = 0
 GROUP BY s.tenant_id, s.processing_order_id
HAVING min(s.set_index) <> 1 OR max(s.set_index) <> count(*)
 ORDER BY 1, 2 LIMIT 20;

\echo '=== G 套号格式与唯一性（V92 停止条件 S1/S4 的线上复算）==='
SELECT count(*) AS bad_format
  FROM processing_order_sets s JOIN processing_orders po ON po.id = s.processing_order_id
 WHERE s.deleted = 0
   AND s.set_no <> po.processing_order_no || '-' || lpad(s.set_index::text, 3, '0');

SELECT count(*) AS duplicate_set_no FROM (
  SELECT s.tenant_id, s.set_no FROM processing_order_sets s WHERE s.deleted = 0
   GROUP BY s.tenant_id, s.set_no HAVING count(*) > 1) AS d;
