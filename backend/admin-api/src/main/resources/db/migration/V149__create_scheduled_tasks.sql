-- 定时任务（用户「预约」）表（V149，issue #6486 包 1）
--
-- ## 一句话
-- 一行 = 一条**在未来某时刻要投递的提醒**（agent 委托或系统派生）。
--
-- ## 为什么单独一张表（三处都已排除，理由逐条）
-- ① **不塞** `after_sales_tickets`：那张表语义是售后工单（`ticket_type` = return/exchange/repair/complaint），
--    没有「服务时段 / 委托语义」；硬塞会污染工单统计口径。
-- ② **不塞** `daily_briefings`：那张表粒度是「租户 × 业务日」（唯一键 `tenant_id` + `biz_date`），
--    与本表的「任意时刻」正交。
-- ③ **不塞** `notifications`：那是**投递记录**（已发出的事实），本表是**待触发计划**（尚未发生）。
--    二者生命周期不同 —— 待办可取消（`status='cancelled'`），已投递的通知不可撤回。
--
-- ## 三件套全是 NOT NULL（本表最硬的一条，别改软）
-- `criterion` / `action_label` / `action_url` 全部 NOT NULL ⇒ **没有处置入口的待办根本建不出来**。
-- 这是把既有主动引擎（`backend/ai-agent-service/app/briefing/proactive.py`）的
-- 「无处置入口 ⇒ **不发**（装配期丢弃）」**前移为建单期拒绝**：
-- 运行期丢弃会让「为什么这条没发」变成**不可见的静默面**；建单期拒绝则当场可归因。
--
-- ## 疲劳控制（读面口径，不在本文件）
-- 只有 `status='pending'` 会被扫描器投递；投递后置 `fired`（不重投）、取消置 `cancelled`、
-- 用户忽略可置 `dismissed`。见 `ScheduledTaskService`。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`；
-- `CREATE POLICY` 无 `IF NOT EXISTS` ⇒ 用 DO 块包裹（与 V133 同款）。
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id           VARCHAR(64) PRIMARY KEY,
    tenant_id    BIGINT NOT NULL REFERENCES tenants(id),
    -- 可配置的任务类型（不写死窗帘语义：本仓定位是「通用行业 SaaS，以布艺为示例场景」）
    task_type    VARCHAR(32) NOT NULL,
    -- 主体（可选）：employee / customer / order —— 为空 = 无特定主体
    subject_type VARCHAR(32),
    subject_id   VARCHAR(64),
    -- 触发时刻（本表相对既有「每日一次」调度的时间轴自由度）
    fire_at      TIMESTAMP WITH TIME ZONE NOT NULL,
    -- ↓ 三件套（NOT NULL = 建单期强制，见文件头「最硬的一条」）
    criterion    TEXT NOT NULL,
    impact       JSONB NOT NULL DEFAULT '{}'::jsonb,
    action_label VARCHAR(64) NOT NULL,
    action_url   VARCHAR(255) NOT NULL,
    payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- user（米宝委托）/ system（规则派生）
    source       VARCHAR(32) NOT NULL,
    -- pending / fired / cancelled / failed / dismissed
    status       VARCHAR(32) NOT NULL DEFAULT 'pending',
    -- 幂等键：同一件事在同一时刻只该提醒一次（见唯一索引）
    dedup_key    VARCHAR(128) NOT NULL,
    fired_at     TIMESTAMP WITH TIME ZONE,
    created_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at   TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted      INTEGER NOT NULL DEFAULT 0
);

-- 扫描器主查询：到期且待投递（部分索引，只覆盖会被扫的那一小片）
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_due
    ON scheduled_tasks (fire_at)
    WHERE status = 'pending' AND deleted = 0;

-- 幂等键（部分唯一索引：软删行不占位，与 uk_worker_page_configs_tenant 同款）
CREATE UNIQUE INDEX IF NOT EXISTS uk_scheduled_tasks_tenant_dedup
    ON scheduled_tasks (tenant_id, dedup_key)
    WHERE deleted = 0;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- 行级租户隔离（与全库同构；`CREATE POLICY` 无 IF NOT EXISTS ⇒ DO 块幂等包裹）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE scheduled_tasks ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_policies
                   WHERE schemaname = 'public' AND tablename = 'scheduled_tasks'
                     AND policyname = 'tenant_isolation_scheduled_tasks') THEN
        CREATE POLICY tenant_isolation_scheduled_tasks ON scheduled_tasks
            USING (tenant_id::text = current_setting('app.current_tenant_id'));
    END IF;
END $$;
