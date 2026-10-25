-- 订单级「外发加工」标记（issue #7746 的后续单）
--
-- ## 一句话
-- 用户裁定：「外单应该和加急单一样」⇒ 外发单不再只是**派单时**的选择，而是订单上的一个标记：
-- 打了标记的单**不进成批候选**，在智能派单页顶部的「加急 / 外发」区**逐单立即派**，
-- 且派单时**必须**选承接方（加工厂）。
--
-- ## 为什么是订单级（而不是作业单级）
-- 外发是「这单要交给外部加工厂做」的**履约安排**，在作业单生成之前就已成立
-- （#7723 已把「谁做」从作业单移到派单）。写在订单上，才能像加急一样在**入池之前**分流。
--
-- ## 语义（与 is_urgent 同款三态纪律）
-- `BOOLEAN NOT NULL DEFAULT FALSE` ⇒ 无第三态：「未标外发」与「明确不外发」同值；
-- 存量行一律 FALSE（不回填、不猜）。
--
-- ## 与 is_urgent 的关系
-- 两个标记可以同时为真：**加急优先**（进插队区；外发标记仍要求派单时选承接方）。
-- 只有外发时 ⇒ 进 `outsourcedLines`（外发区），同样不参与合并。
--
-- ## bootstrap 终态同步（同 V99/V108/V127/V133/V170/V193 纪律）
-- 新建库路径**不跑历史迁移链** ⇒ `backend/admin-api/src/main/resources/db/init/schema.sql`
-- 已同步本文件终态（列 + 注释 + 部分索引）。只改一处 ⇒ 新建库缺列。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V194__rollback_order_is_outsourced.sql（本单只登记，不落码）
-- -- DROP INDEX IF EXISTS idx_orders_tenant_outsourced;
-- -- ALTER TABLE orders DROP COLUMN IF EXISTS is_outsourced;
-- ```
-- ⚠️ 回滚是**有损**的：已标记外发的订单会一并丢失该标记（派单页不再单独列出它们）。属**有意**。
--
-- ## 显式事务
-- `MigrationRunner` 用 `jdbc.execute(整份文件)`（PG 隐式包一个事务）；`psql -f` 默认逐条 autocommit
-- ⇒ 不显式 BEGIN/COMMIT 会在失败时留下半完成态。两条执行路径必须同语义。
-- ══════════════════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE orders ADD COLUMN IF NOT EXISTS is_outsourced BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN orders.is_outsourced IS
    '订单级外发加工标记（V194）：TRUE = 不进成批候选、进智能派单页「外发区」逐单立即派，且派单时必须选承接方（加工厂）。与 is_urgent 可同时为真（加急优先）。NOT NULL ⇒ 无第三态；存量行 FALSE，不回填。';

CREATE INDEX IF NOT EXISTS idx_orders_tenant_outsourced
    ON orders (tenant_id, created_at)
    WHERE deleted = 0 AND is_outsourced = TRUE;

COMMIT;
