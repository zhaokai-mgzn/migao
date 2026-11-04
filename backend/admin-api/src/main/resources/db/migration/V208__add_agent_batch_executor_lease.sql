-- V208 / issue #8285：批次后台 job 的**执行租约**（跨实例 lease / 心跳 / 崩溃回收）
--
-- ## 一句话
-- 给 `agent_batches` 加两列：`executor_id`（实例 + job 标识）与 `heartbeat_at`（执行中定期刷新）。
-- 有了它们，「`status=executing`」才第一次变得**可判定**：活 job 的心跳新鲜 ⇒ 谁都不许动它；
-- 心跳超时 / 为空 ⇒ 上一次执行者已经死了 ⇒ 可以安全回收成 `partial`（可撤销）。
--
-- ## 为什么必须落库（不能只在进程内记）
-- #8283 把批量写改成了进程内线程池 job，并用 `waitForTasksToCompleteOnShutdown` 覆盖滚动发布。
-- 剩下的缺口是 **JVM 崩溃 / 强杀 / 容器被摘**：进程内没有任何东西记得「这批是谁在跑」⇒ 重启后
-- 无法区分「真的还在跑」与「上一次进程已死」；多实例下更危险 —— B 实例做全量回收会**误杀**
-- A 实例正在跑的批次（把还在 apply 的批次标成 partial）。
-- ⇒ 判据必须是**跨进程可见的事实**，而进程内状态在崩溃时就没了 ⇒ 只能落库。
--
-- ## 两列各管什么
-- | 列 | 语义 | 谁写 | 谁读 |
-- |---|---|---|---|
-- | `executor_id` | 执行者标识 = **实例 + job**（`<实例>#<pid>/<job uuid>`，见 `AgentBatchService#newExecutorId`） | claim（`markExecuting` / `markReverting`）与回收（置 NULL） | 终态 CAS 的 fencing 谓词、心跳刷新、回收 |
-- | `heartbeat_at` | 该 executor 最近一次心跳时刻（claim 时即写一次，之后每条明细前刷新） | claim + 心跳刷新 | 回收的时效判定（超时 / 为空 ⇒ 可回收） |
--
-- ## 回收口径（**只**这一条语句，一字不多）
-- `status = 'executing'` **且**（`heartbeat_at` 为 NULL **或** 早于「现在 − 超时」）⇒ 置 `partial`。
--   * **只改批次状态**，一条明细都不碰 ⇒ 不伪造 item 成功（`old_value` 仍是撤销的唯一依据）；
--     回收后的 `partial` 走既有撤销路径**逐条还原**（已成功 apply 的条目照旧还原，未执行的跳过）。
--   * **不覆盖终态**：谓词带 `status = 'executing'` ⇒ `done` / `partial` / `reverted` / `revert_partial`
--     一律 0 行（回收天然幂等：第二次跑时状态已不是 `executing`）。
--   * **不误杀活 job**：活 job 每条明细前刷新 `heartbeat_at`，回收只认「超时」这一件事 ⇒ 心跳新鲜 = 0 行。
--   * 回收时 `executor_id` 置 NULL：既留下「这批已无主」的痕迹，也让**僵尸 job** 的终态写（带
--     `executor_id` fencing 谓词）当场 0 行 —— 回收之后原 job 再也不能把批次改写回 `done`。
--
-- ## 有意不做（照实登记，别读成已解决）
-- * **不承诺精确到条目的自动复原**：`partial` 回收时「已 apply 但 item 状态未落库」的窗口**仍然存在**
--   （与进程内崩溃同族）—— 本单只保证**状态可回收 + 可撤销**。需要精确对账时另开单。
-- * **不改状态机取值域**：`ck_agent_batch_status` 一字不动（回收复用既有的 `partial`，
--   不新增 `recovering` / `abandoned` 之类的新态）。这条对账在下文 ③ 里由判据钉住。
-- * **不改 `N≤50`、两段确认、逐条失败不回滚**（#5314 / #8283 的冻结契约）。
--
-- ## 幂等 + 显式事务（同 V127/V198 口径）
--   `ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` + 终态对账（先判后建）⇒ 可重复执行；
--   `MigrationRunner` 走 `jdbc.execute(整份文件)`，`psql -f` 却逐条 autocommit ⇒ 两条执行路径必须
--   同语义，故**显式** `BEGIN; … COMMIT;`。
--
-- ## bootstrap 终态同步（同 V99/V100/V108/V111/V116/V119/V122/V127/V146 纪律）
--   新建库路径**不跑历史迁移链**：`backend/admin-api/src/main/resources/db/init/schema.sql` 的
--   `CREATE TABLE agent_batches` 已同步这两列。只改一处 ⇒ 新建库缺列 / 存量库缺列。
--   判据 = `backend/admin-api/src/test/java/com/migao/admin/migration/AgentBatchMigrationTest.java`
--   （两源逐列 + 迁移链终态）与同族的 `AgentBatchStatusCasMetaGuardTest`（状态写面必须带谓词）。
--
-- ## 回滚（**有损**，登记在此；新迁移不删本文件）
--   回滚只丢「谁在跑 / 上次心跳」这两个可观测事实（状态机与明细一概不动）⇒ 回滚后跨实例回收失效
--   （退回 #8283 的进程内边界）。存量 `executing` 批次不受影响。
-- ```sql
-- -- BEGIN;
-- -- DROP INDEX IF EXISTS idx_agent_batches_executing_heartbeat;
-- -- ALTER TABLE agent_batches DROP COLUMN IF EXISTS heartbeat_at;
-- -- ALTER TABLE agent_batches DROP COLUMN IF EXISTS executor_id;
-- -- COMMIT;
-- ```
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 前置表存在性（fail-closed：缺表立即停，不兜底建表 —— 会造出无主键的影子表）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'agent_batches') THEN
        RAISE EXCEPTION 'V208 前置表缺失：agent_batches —— 迁移停下（不兜底建表）';
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 两列（租约载体）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE agent_batches
    ADD COLUMN IF NOT EXISTS executor_id VARCHAR(128);

ALTER TABLE agent_batches
    ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN agent_batches.executor_id IS
    '执行者标识 = 实例 + job（<实例>#<pid>/<job uuid>，V208 / issue #8285）：claim 时写、回收时置 NULL；终态 CAS 用它做 fencing 谓词 ⇒ 被回收的僵尸 job 写不回终态';
COMMENT ON COLUMN agent_batches.heartbeat_at IS
    '该 executor 最近一次心跳时刻（V208 / issue #8285）：claim 时写一次、执行中每条明细前刷新；回收判据 = status=executing 且（为 NULL 或早于 现在−超时）';

-- 回收的取数面：只扫 executing 行（部分索引 ⇒ 与「按状态回收」的谓词同形）
CREATE INDEX IF NOT EXISTS idx_agent_batches_executing_heartbeat
    ON agent_batches (heartbeat_at)
    WHERE status = 'executing';

COMMENT ON INDEX idx_agent_batches_executing_heartbeat IS
    '崩溃回收取数用（V208 / issue #8285）：只索引 executing 行（活跃批次是个小集合），按 heartbeat_at 判时效';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 终态对账（fail-closed：任一列 / 索引不在，或状态机白名单被悄悄改了 ⇒ 抛错并回滚整份迁移）
--    —— 「跑完了」不等于「落对了」：部分回滚会留下一个看起来在、实际缺列的表
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing TEXT;
    status_def TEXT;
BEGIN
    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('executor_id'), ('heartbeat_at')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'agent_batches'
                          AND column_name = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V208 终态对账失败：agent_batches 缺列 %（跨实例回收会退化成「猜」）', missing;
    END IF;

    -- 类型必须能装下 `OffsetDateTime`（timestamptz）+ 实例标识；写成别的类型会在运行期静默截断/错位
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'agent_batches'
                      AND column_name = 'heartbeat_at'
                      AND data_type = 'timestamp with time zone') THEN
        RAISE EXCEPTION 'V208 终态对账失败：agent_batches.heartbeat_at 不是 TIMESTAMP WITH TIME ZONE';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND indexname = 'idx_agent_batches_executing_heartbeat') THEN
        RAISE EXCEPTION 'V208 终态对账失败：缺索引 idx_agent_batches_executing_heartbeat（回收会退化成全表扫）';
    END IF;

    -- 🔴 状态机**不许**被本迁移改动：取值域仍是六个（回收复用 partial，不新增中间态）
    SELECT pg_get_constraintdef(oid) INTO status_def
      FROM pg_constraint WHERE conname = 'ck_agent_batch_status';
    IF status_def IS NULL THEN
        RAISE EXCEPTION 'V208 终态对账失败：ck_agent_batch_status 缺失（状态机没被 DB 钉住）';
    END IF;
    IF status_def NOT LIKE '%preview%' OR status_def NOT LIKE '%executing%'
       OR status_def NOT LIKE '%done%' OR status_def NOT LIKE '%partial%'
       OR status_def NOT LIKE '%reverted%' OR status_def NOT LIKE '%revert_partial%' THEN
        RAISE EXCEPTION 'V208 终态对账失败：状态机取值域不再是六个（收到 %）', status_def;
    END IF;
    IF status_def LIKE '%recovering%' OR status_def LIKE '%abandoned%' OR status_def LIKE '%stale%' THEN
        RAISE EXCEPTION 'V208 终态对账失败：状态机被扩了新态（收到 %）—— 回收复用 partial，不新增取值', status_def;
    END IF;
END $$;

COMMIT;
