\pset border 2
\echo '=== ① 活跃租户 ==='
SELECT id, name, industry FROM tenants WHERE deleted = 0 ORDER BY id;
\echo '=== ② 三道工序 scope × source（活跃租户，本单核心读数）==='
SELECT t.id AS tenant_id, o.name, o.scope, o.source,
       CASE WHEN o.scope='position' THEN 'DOUBLE-PAY' ELSE 'ok' END AS verdict
  FROM tenants t JOIN production_operations o ON o.tenant_id=t.id AND o.deleted=0
 WHERE t.deleted=0 AND o.name IN ('外帘打卷','外帘装袋','外帘发货') ORDER BY t.id,o.name;
\echo '=== ③ 汇总：活跃租户里 position / set 各多少行 ==='
SELECT o.scope, count(*) AS rows, count(DISTINCT o.tenant_id) AS tenants
  FROM tenants t JOIN production_operations o ON o.tenant_id=t.id AND o.deleted=0
 WHERE t.deleted=0 AND o.name IN ('外帘打卷','外帘装袋','外帘发货') GROUP BY o.scope ORDER BY o.scope;
\echo '=== ④ source 分布（能否区分「播种 vs 商家自建」）==='
SELECT source, count(*) AS rows, count(DISTINCT tenant_id) AS tenants,
       count(*) FILTER (WHERE id LIKE 'op-v54-%' OR id LIKE 'op-v56-%' OR id LIKE 'op-v79-%') AS id_prefixed
  FROM production_operations WHERE deleted=0 GROUP BY source ORDER BY source NULLS FIRST;
\echo '=== ⑤ 配料 / 打包 的 scope（对照，本单不动）==='
SELECT o.tenant_id, o.name, o.scope, o.source
  FROM tenants t JOIN production_operations o ON o.tenant_id=t.id AND o.deleted=0
 WHERE t.deleted=0 AND o.name IN ('配料','打包') ORDER BY o.tenant_id, o.name;
\echo '=== ⑥ 商家自建候选（source IS NULL）行 ==='
SELECT count(*) AS null_source_rows FROM production_operations WHERE deleted=0 AND source IS NULL;
\echo '=== ⑦ 报工历史计件指纹（红线基线：本单前后必须一字不动）==='
SELECT count(*) AS rows,
       md5(string_agg(id||'|'||coalesce(unit_price::text,'NULL')||'|'||coalesce(factor::text,'NULL'), ',' ORDER BY id)) AS fingerprint
  FROM production_work_logs WHERE deleted=0;
\echo '=== ⑧ 实例快照侧：外帘三道在同单里出现次数 ==='
SELECT tenant_id, operation_name, count(*) AS n, count(DISTINCT order_id) AS orders
  FROM processing_position_operations WHERE deleted=0 AND operation_name IN ('外帘打卷','外帘装袋','外帘发货')
 GROUP BY 1,2 ORDER BY 1,2;
