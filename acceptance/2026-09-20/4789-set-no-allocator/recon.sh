#!/usr/bin/env bash
# 真库核查（#4789）：processing_order_sets 现状 + V92 口径复算。**纯 SELECT，零写**。
# ⚠️ RDS 对本机间歇可用（#4741/#4672 同款）⇒ 重试循环；连不上就如实说明。
set -uo pipefail
ROOT="/Users/guangzhen.zk/ai native/migao"
ENVF="$ROOT/backend/admin-api/.env"
H=$(grep -E '^RDS_HOST=' "$ENVF" | cut -d= -f2-)
P=$(grep -E '^RDS_PORT=' "$ENVF" | cut -d= -f2-)
D=$(grep -E '^RDS_DB=' "$ENVF" | cut -d= -f2-)
U=$(grep -E '^RDS_USER=' "$ENVF" | cut -d= -f2-)
W=$(grep -E '^RDS_PASSWORD=' "$ENVF" | cut -d= -f2-)
export PGPASSWORD="$W"
export PGCONNECT_TIMEOUT=8
SQL=$(cat <<'Q'
\echo '=== A 表是否存在 + 行数 ==='
SELECT count(*) AS sets_total, count(*) FILTER (WHERE deleted=0) AS sets_live,
       count(DISTINCT processing_order_id) AS orders_with_sets
  FROM processing_order_sets;
\echo '=== B set_no 形态分布（id 前缀 = 谁写的）==='
SELECT split_part(id,'-',1)||'-'||split_part(id,'-',2) AS id_prefix, count(*) AS rows
  FROM processing_order_sets GROUP BY 1 ORDER BY 2 DESC;
\echo '=== C 活跃加工单 vs 有套行的加工单（缺口读数）==='
SELECT (SELECT count(*) FROM processing_orders WHERE deleted=0) AS live_pos,
       (SELECT count(DISTINCT processing_order_id) FROM processing_order_sets WHERE deleted=0) AS pos_with_sets;
\echo '=== D 新单（无套行）样例 ==='
SELECT po.processing_order_no, po.status, po.created_at,
       (SELECT count(*) FROM processing_position_operations o WHERE o.processing_order_id=po.id AND o.deleted=0) AS ops,
       (SELECT count(*) FROM processing_position_operations o WHERE o.processing_order_id=po.id AND o.deleted=0 AND o.set_id IS NOT NULL) AS ops_with_set
  FROM processing_orders po WHERE po.deleted=0
   AND NOT EXISTS (SELECT 1 FROM processing_order_sets s WHERE s.processing_order_id=po.id AND s.deleted=0)
 ORDER BY po.created_at DESC LIMIT 5;
\echo '=== E 索引与约束（ON CONFLICT 推断前提）==='
SELECT indexname, indexdef FROM pg_indexes WHERE tablename IN ('processing_order_sets','processing_set_part_tokens') ORDER BY indexname;
\echo '=== F 唯一索引的谓词（pg_get_expr）==='
SELECT c.relname AS index_name, i.indisunique, pg_get_expr(i.indpred, i.indrelid) AS predicate
  FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
 WHERE c.relname IN ('uk_processing_order_sets_index','uk_processing_order_sets_no','uk_set_part_tokens_token','uk_set_part_tokens_part');
\echo '=== G 历史值红线基线（md5）==='
SELECT md5(string_agg(unit_price::text||'|'||coalesce(factor::text,'-'), ',' ORDER BY id)) AS work_logs_md5, count(*) AS rows
  FROM production_work_logs WHERE deleted=0;
SELECT md5(string_agg(total_amount::text, ',' ORDER BY id)) AS orders_total_md5, count(*) AS rows
  FROM orders WHERE deleted=0;
\echo '=== H 部位码载体现状 ==='
SELECT count(*) AS part_tokens_total FROM processing_set_part_tokens;
Q
)
for i in 1 2 3 4 5 6 7 8; do
  if psql -h "$H" -p "$P" -U "$U" -d "$D" -v ON_ERROR_STOP=1 -f - <<<"$SQL" 2>&1; then
    echo "✅ 真库读数成功（第 $i 次尝试）"; exit 0
  fi
  echo "⚠️ 第 $i 次连接失败，重试…" >&2
done
echo "❌ RDS 连续 8 次不可达（本机出口 IP 间歇性不在白名单）—— 如实登记，给运维 SQL" >&2
exit 3
