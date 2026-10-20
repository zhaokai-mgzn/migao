-- ================================================================
-- 数据保留期清理（**人工执行**，不是定时任务）—— 2026-10-20
-- ================================================================
--
-- ## 为什么有这份文件
--
-- `audit_logs` / `notifications` 是只增不减的表：前者每个写动作一条、后者每个业务事件一条，
-- 且通知中心前端每 30s 轮询一次未读数（`frontend/admin-web/src/components/layout/NotificationBell.tsx`）。
-- 索引只能让「取最近 N 条」变快，**挡不住表无限增长**（索引体积 / VACUUM / 备份窗口都会跟着涨）。
-- 生产站上线前必须有一条「多久以前的数据可以删」的明确口径，且**由人执行**。
--
-- ## 为什么不是定时任务（铁律 10）
--
-- 本仓禁止新增「无人值守的删除/破坏性动作」的 schedule/cron（判据写错时没人来得及拦）。
-- 这里提供的是**可复核、可先看数、可分片**的脚本：由运维/值班人**显式执行**；
-- 若要在运维自己的调度系统里跑，那是他们的值守面，不在本仓管辖范围内。
--
-- ## 用法
--
--   # ① 先看量（只读，默认 mode=count）
--   psql "$DATABASE_URL" -f deploy/ops/db-retention.sql
--
--   # ② 再删（mode=purge；保留期可改）
--   psql "$DATABASE_URL" -f deploy/ops/db-retention.sql -v mode=purge -v audit_days=365 -v notify_days=180
--
--   # ③ 表很大时分片（按日期区间，逐片执行；区间端点自己按 count 的读数选）
--   psql "$DATABASE_URL" -c "DELETE FROM audit_logs WHERE created_at < timestamptz '2026-01-01' AND created_at >= timestamptz '2025-10-01'"
--
-- 默认保留期：`audit_logs` 365 天 / `notifications` 180 天（合规审计通常要求 ≥6 个月，
-- 本仓没有更长的法定要求；两个值都可被 `-v` 覆盖）。
--
-- ## 执行前必读
--
-- 1. **不要在业务高峰跑**：DELETE 产生活元组与 WAL ⇒ 建议低峰 + 盯复制延迟；
-- 2. **不可逆**：执行前确认快照/PITR 窗口覆盖执行时段；
-- 3. 清完建议 `VACUUM (ANALYZE)` 两张表（或等 autovacuum，但大表最好主动跑一次）。
--
-- ## 口径
--
-- · 两张表的 `created_at` 都是 `TIMESTAMPTZ`，按「当前时刻 - N 天」比较；
-- · **不按 `deleted` 过滤**：保留期是时间口径，与软删无关；
-- · **只清这两张**：`session_messages`（会话历史）与 `stock_ledger_entries`（库存台账）
--   是业务事实（追溯/对账），清理由业务方单独裁定，不在这里替人决定。

\if :{?mode}
\else
  \set mode count
\endif
\if :{?audit_days}
\else
  \set audit_days 365
\endif
\if :{?notify_days}
\else
  \set notify_days 180
\endif

\echo '── 保留期读数（mode=' :mode ', audit_days=' :audit_days ', notify_days=' :notify_days '）──'

SELECT 'audit_logs' AS table_name,
       COUNT(*) AS rows_past_retention,
       MIN(created_at) AS oldest
  FROM audit_logs
 WHERE created_at < now() - (:audit_days || ' days')::interval
UNION ALL
SELECT 'notifications',
       COUNT(*),
       MIN(created_at)
  FROM notifications
 WHERE created_at < now() - (:notify_days || ' days')::interval;

-- psql 的 `\if` 只认布尔值（不认字符串比较）⇒ 先把 mode 折成两个 bool
SELECT (:'mode' = 'purge') AS do_purge, (:'mode' = 'count') AS do_count \gset

\if :do_purge
DELETE FROM audit_logs
 WHERE created_at < now() - (:audit_days || ' days')::interval;
DELETE FROM notifications
 WHERE created_at < now() - (:notify_days || ' days')::interval;
\echo '── purge 完成；建议接着跑：VACUUM (ANALYZE) audit_logs; VACUUM (ANALYZE) notifications; ──'
\endif

\if :do_count
\echo '── count 模式（未删除任何行）。要执行删除：-v mode=purge ──'
\endif
