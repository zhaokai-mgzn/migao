-- V147 — `order_logistics` 增列 `shipping_method`：发货方式「物流发货 / 无需物流」开始被记录（issue #6239）
--
-- ## 一句话
-- 前端发货页让用户二选一（`logistics` 物流发货 / `none` 无需物流），提交时一直带着 `shippingMethod`，
-- 而**后端从未读取**（admin-api `src/main` 全仓 `shippingMethod|shipping_method` = 0 命中；本表无此列）
-- ⇒ 用户做了选择、系统把它丢掉：「无需物流」与「物流发货但没填单号」在库里**不可区分**。
-- 本迁移只做一件事：给这张表加一列，让那个已经做出的选择**落得下去**。
--
-- ## 取值与语义（`logistics` / `none`）
-- | 值 | 含义 | 谁写 |
-- |---|---|---|
-- | `logistics` | 物流发货（有承运商 + 运单号） | 发货页选「物流发货」；订单详情「编辑物流」弹窗 |
-- | `none` | **无需物流**（自送 / 自提 / 客户自取） | 发货页选「无需物流」 |
-- | `NULL` | **未采集**（存量行 + 老客户端不发该字段） | 不猜、不回填 |
--
-- ## 为什么可空、**不做回填**（非破坏性）
-- 存量行的用户当时选了什么**没有任何 durable 证据**（当时选择被丢弃，无从复原）⇒
-- 回填只能靠猜（例如「有单号 ⇒ logistics」），那是**造数据**，会把「未采集」伪装成「已采集」。
-- 留 `NULL` 是唯一诚实的选择：读取方把 `NULL` 按「未采集」处理，与前端把 `undefined` 兜底成
-- `'logistics'` 的现状**逐字一致**（回吐面见 `dto/OrderDetailResponse.java` 的 `LogisticsInfo`）。
--
-- ## 为什么不加 CHECK 约束（**有意**，照实登记）
-- 取值白名单是**服务端应用层**的一条 fail-closed 校验（`controller/OrderController.java` 的
-- `updateLogistics`：非 `{logistics, none}` 的**非空**取值 ⇒ 显式拒绝、不静默兜底），
-- 白名单的**单一来源**就在那一处；再加一条同义 CHECK 不会多抓住任何东西，
-- 却会造出第二个需要同步维护的真值点（V146 的教训正是「DB 白名单与代码取值集合长期脱节」）。
-- 本列的写入路径**全部**经该端点，且不存在历史值 ⇒ 约束面与校验面重合，故只在应用层收口。
--
-- ## 与 `db/init/schema.sql` 的关系
-- 新建库走**基线**（`schema.sql`，不跑历史迁移链）⇒ 该文件的 `order_logistics` 必须**同批**加上
-- 同名列，否则「全新安装」与「迁移态」两个终态不一致。本迁移已同步。
--
-- ## 幂等（`MigrationRunner` 要求所有迁移可重复执行）
-- `ADD COLUMN IF NOT EXISTS` ⇒ 第二遍净效果相同。
--
-- ## 回滚（**可执行**，不是散文）：无损失（本列是本单新增，存量全为 NULL）
-- -- ALTER TABLE order_logistics DROP COLUMN IF EXISTS shipping_method;

BEGIN;

ALTER TABLE order_logistics
    ADD COLUMN IF NOT EXISTS shipping_method VARCHAR(16);

COMMENT ON COLUMN order_logistics.shipping_method IS
    '发货方式（V147，issue #6239）：logistics 物流发货 / none 无需物流；NULL = 未采集（存量行 + 老客户端不发该字段，不猜、不回填）。写入路径 = PUT /api/admin/orders/{id}/logistics 的 shippingMethod 键（服务端白名单 fail-closed）；回吐见 dto/OrderDetailResponse.java 的 LogisticsInfo';

COMMIT;
