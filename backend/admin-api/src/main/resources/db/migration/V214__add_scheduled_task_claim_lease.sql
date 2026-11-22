-- 到期待办扫描的**原子领取 + 租约**（集群 P0-2 / issue #9019）
--
-- ## 一句话
-- 改前扫描腿是「读出 pending → 写通知 → 改 fired」的纯 read-modify-write（**没有任何占位**）：
-- 两个实例同秒醒来会读到**同一批** pending ⇒ 各写一条站内通知 ⇒ 员工收到重复到点提醒，
-- 且两行最后都是 fired，事后从数据上分辨不出重复发生过。
-- 本迁移给 `scheduled_tasks` 加**领取标记**，让扫描腿把「判定 + 占位 + 取回」并成**一条**原子语句
-- （`claimed_by` / `claimed_at` 只由那条语句写）。
--
-- ## 三样东西（为什么各需一条）
-- ① `claimed_by`：领取者标识（= 实例 id，同时是**终态 CAS 的 fencing token**）——
--    租约被回收后，僵尸实例即使还活着也写不回 fired（否则会把别人的投递结果覆盖成自己的）。
-- ② `claimed_at`：领取时刻 —— 租约判定的**客观事实**（超时 ⇒ 领取者已死，回收成 pending）。
-- ③ 部分索引 `idx_scheduled_tasks_firing_lease`：回收器每分钟只扫 firing 那一小片
--    （与 `idx_scheduled_tasks_due` 同一套「部分索引只覆盖会被扫的那一小片」口径）。
--
-- `status` 因此多一个中间态 `firing`（= 已被某实例领走、尚未终态）。其余取值语义不变：
-- pending / fired / cancelled / failed / dismissed。**只有 pending 会被领取**。
--
-- ## 回滚
-- 代码回滚后这三列/索引**无消费方**，保留无害（列可空；部分索引只覆盖 firing = 0 行）。
-- 若必须回收：先 `UPDATE scheduled_tasks SET status='pending' WHERE status='firing';`
-- 把在飞领取放回（否则旧代码永远扫不到它们），再
--   DROP INDEX IF EXISTS idx_scheduled_tasks_firing_lease;
--   ALTER TABLE scheduled_tasks DROP COLUMN IF EXISTS claimed_by, DROP COLUMN IF EXISTS claimed_at;
--
-- ## 显式事务（与 V187 同款）
-- 迁移链与 `psql -f` 逐条 autocommit 两条执行路径必须同语义 ⇒ 显式 BEGIN/COMMIT。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS claimed_by VARCHAR(64);
ALTER TABLE scheduled_tasks ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_firing_lease
    ON scheduled_tasks (claimed_at)
    WHERE status = 'firing' AND deleted = 0;

COMMENT ON COLUMN scheduled_tasks.claimed_by IS
    '领取者标识（实例 id；终态 CAS 的 fencing token）。只由原子领取语句写；终态后保留作审计痕迹。';
COMMENT ON COLUMN scheduled_tasks.claimed_at IS
    '领取时刻。租约判定的事实源：超过租约超时仍 firing ⇒ 领取实例已死，回收成 pending（通知幂等键兜住重投）。';

COMMIT;
