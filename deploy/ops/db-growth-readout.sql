-- ================================================================
-- 只增表**体量 / 最老行年龄**读数（**只读**）—— issue #8218 P1-11，2026-10-31
-- ================================================================
--
-- ## 这是什么
--
-- 「**多久没清了**」与「**表多大**」的读数面。配套读数器：
--
--   python3 scripts/db_growth_readout.py     # 三态 rc 0/1/3；期望阈值与告警口径见下
--
-- 期望阈值 / 告警口径的**真值源**：`docs/deployment/production-deployment.md` 的 §5.3。
--
-- ## 🔴 本文件**只有 SELECT**（不做删除）
--
-- 删除仍是**人工执行** `deploy/ops/db-retention.sql`（先 count 看量，再低峰 purge）——
-- 铁律 10：不新增无人值守的删除 / 破坏性动作。
-- 只读性是**机械判据**（不是口头承诺）：可执行面（剥掉 SQL 注释后）出现任何
-- DML / DDL 动词（INSERT / UPDATE / DELETE / TRUNCATE / DROP / ALTER / CREATE …）⇒
-- `tests/unit_ci_workflows/test_ops_readouts.py` 判红。
--
-- ## 用法
--
--   # ① 人看（table 形态）
--   psql "$DATABASE_URL" -f deploy/ops/db-growth-readout.sql
--
--   # ② 读数器用（CSV 形态，喂 --from-csv 可离线复核）
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --csv -f deploy/ops/db-growth-readout.sql > /tmp/db-growth.csv
--   python3 scripts/db_growth_readout.py --from-csv /tmp/db-growth.csv
--
-- ## 口径
--
-- · `total_bytes` = `pg_total_relation_size`（表 + 索引 + TOAST；索引体积正是"无界增长"的代价之一）；
-- · `oldest_age_days` = `now() - min(created_at)` 的天数（**在库里算**，避免本机时钟 / 时区参与判定）；
-- · 两表的保留期（期望上界）：`audit_logs` 365 天 / `notifications` 180 天（与 `deploy/ops/db-retention.sql` 同源）；
-- · 空表 ⇒ `oldest_age_days` 为 NULL（不是 0；缺值不得当成"刚清过"）。

SELECT 'audit_logs' AS table_name,
       pg_total_relation_size('audit_logs') AS total_bytes,
       count(*) AS row_count,
       min(created_at) AS oldest_created_at,
       round(EXTRACT(EPOCH FROM (now() - min(created_at))) / 86400.0, 1) AS oldest_age_days
  FROM audit_logs
UNION ALL
SELECT 'notifications',
       pg_total_relation_size('notifications'),
       count(*),
       min(created_at),
       round(EXTRACT(EPOCH FROM (now() - min(created_at))) / 86400.0, 1)
  FROM notifications
ORDER BY table_name;
