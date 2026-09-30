-- V142 — 订单「制单人」（issue #5835，用户 2026-09-30 逐字裁定）
--
-- ## 一句话
-- `orders` 加两列：`created_by`（建单操作者的员工 `users.id`）+ `created_by_name`（昵称**快照**）。
-- 列表展示与「按制单人过滤」都用**快照列**，不 join `users`（见下「为什么快照」）。
--
-- ## 用户裁定（原文，2026-09-30）
--   「制单人这个字段可以不用加到订单详情中，但是要加到订单列表中，并且支持根据制单人过滤」
--   + 「存量单（没有制单人）在列表里显示「—」，且不参与「按人」筛选」
--
-- ## 🔴 为什么**不**复用 `orders.user_id`
-- `user_id` 的既有语义 = **下单用户 ID（C 端数据隔离依据）**（`Order.java` 的字段 javadoc；
-- 消费点 = `OrderService.getOrderPage` 的 `wrapper.eq(Order::getUserId, userId)`）。
-- 拿它当制单人会让两件事互相污染：C 端顾客自助下单时 `user_id` = 顾客 ⇒ 他会被算成
-- 「制单人」，「按制单人筛」会筛出 C 端顾客；反之给制单人过滤加条件又会绕坏数据隔离。
-- ⇒ 本迁移**只新增列**，`user_id` 一字不动。
--
-- ## 为什么 `created_by_name` 是**快照**（不是 join 出来的显示名）
-- 改名 / 删号之后，历史单据必须显示**当时的**名字。join `users.nickname` 会让历史失真
-- （同族先例：`agent_batches.created_by` 只存 id；本列存名是为「列表展示 + 模糊筛选」这一读面服务，
-- 而读面不该为了显示一个名字去 join 一张会变的表）。取值口径见
-- `backend/admin-api/src/main/java/com/migao/admin/service/OrderService.java::resolveCurrentOperator`。
--
-- ## 存量单 = NULL（**不回填**）
-- 迁移前建的订单从未采集过这个事实 ⇒ 两列留 NULL。列表显示「—」且**不参与**「按人」筛选
-- （用户裁定）—— 「当时是谁建的」是历史事实，回填就是编一个操作者。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `ADD COLUMN IF NOT EXISTS` + `COMMENT ON COLUMN`（幂等）+ `CREATE INDEX IF NOT EXISTS`
-- ⇒ 第二遍净效果相同。
--
-- ## 不带 FK / 不带 NOT NULL
-- · **不填 FK**（与本仓既有的 `agent_batches.created_by` / `inbound_labels.created_by` 同风格）：
--   员工账号被删（`users.deleted` 软删）不该让订单行不可写；快照列本就自足。
-- · **可空**：取不到操作者（内部服务占位 `internal-service` / 匿名 / C 端自助下单）时两列都不写
--   —— 那是「未采集」，不是「采集失败」（约束写死 NOT NULL 会逼出一个编造的值）。

ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_by VARCHAR(64);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_by_name VARCHAR(64);

COMMENT ON COLUMN orders.created_by IS
    '制单人 = 建单操作者的员工 users.id（issue #5835）。**不是** orders.user_id（那是下单用户 ID / C 端数据隔离依据）。NULL = 未采集（存量单 / 内部服务占位 / 匿名 / C 端自助下单）⇒ 列表显示「—」且不参与按人筛选。不填 FK（同 agent_batches.created_by）';
COMMENT ON COLUMN orders.created_by_name IS
    '制单人姓名**快照**（建单时取 users.nickname，缺失回落 users.username；issue #5835）。列表展示与模糊筛选都用本列 —— 快照避免改名 / 删号后历史失真。NULL = 与 created_by 同时未采集';

-- 模糊筛选用得上（列表按 created_by_name LIKE %值%）
CREATE INDEX IF NOT EXISTS idx_orders_tenant_created_by_name
    ON orders (tenant_id, created_by_name)
    WHERE created_by_name IS NOT NULL AND deleted = 0;
