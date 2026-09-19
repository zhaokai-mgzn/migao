\pset pager off
\echo '=== [1] products.status 取值分布（V4 目标列）==='
SELECT status, count(*) AS rows FROM products GROUP BY status ORDER BY rows DESC;

\echo '=== [2] 是否仍有 in_warehouse 存量行（V4 若未生效则可能 >0）==='
SELECT count(*) AS in_warehouse_rows FROM products WHERE status = 'in_warehouse';

\echo '=== [3] users.position 分布：NULL/空 vs 有值（V3 目标列）==='
SELECT
  count(*) AS total_users,
  count(*) FILTER (WHERE position IS NULL) AS position_null,
  count(*) FILTER (WHERE position = '') AS position_empty,
  count(*) FILTER (WHERE position IS NOT NULL AND position <> '') AS position_filled
FROM users WHERE deleted = 0;

\echo '=== [4] users: position 为空的行，其 role 是什么（V3 的回填源）==='
SELECT role, count(*) AS rows,
       count(*) FILTER (WHERE position IS NULL OR position = '') AS pos_blank
FROM users WHERE deleted = 0 GROUP BY role ORDER BY rows DESC LIMIT 20;

\echo '=== [5] schema_migrations 中 V2/V3/V4/V41 是否记为已应用 ==='
SELECT version FROM schema_migrations WHERE version LIKE 'V2__%' OR version LIKE 'V3__%' OR version LIKE 'V4__%' OR version LIKE 'V41%' ORDER BY version;

\echo '=== [6] schema_migrations 总行数 ==='
SELECT count(*) AS applied_migrations FROM schema_migrations;

\echo '=== [7] users.position 列是否存在及其类型 ==='
SELECT column_name, data_type, character_maximum_length, is_nullable
FROM information_schema.columns WHERE table_name='users' AND column_name='position';
