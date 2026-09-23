-- 订单收货——物流类型 / 物流公司两列（issue #4872；用户原话「新增订单时**收货信息**中缺少用户的
-- **常用物流/快递**以及**常用公司**，选择客户后要**默认带出**」）
--
-- ## 一句话
-- `orders` 追加两列，让「这一单实际约定的收货方式」**落在订单上**（此前只在
-- `order_logistics`（发货后才有的行，且 `tracking_no NOT NULL` ⇒ 建单时**无法预建**）
-- 与客户档案 `customer_profiles.default_logistics_type / default_logistics_company` 里）。
--
-- ## 为什么必须是订单列（而不是「发货时再去查客户档案」）
-- ① `order_logistics.tracking_no` 为 `NOT NULL` ⇒ 建单时**建不了**物流行，收货方式无处落；
-- ② 客户档案是**会变的默认值**（客户换了常用快递 ⇒ 历史订单的含义跟着漂移）。
--    （同真值源 §4「历史单按当时口径」纪律：订单是快照，不是视图。）
--
-- ## 值域与缺省
-- `logistics_type` 与 `order_logistics.logistics_type`（V47 / issue #3984）**同词表**：
-- `express` 快递 / `logistics` 物流专线。**未传 ⇒ NULL**（**不设列默认**）—— 服务端**不猜**
-- （`OrderService.createOrder` 只在请求里真的带了值时才 set，null 字段不进 INSERT）。
-- 🔴 **为什么不能给列默认 `'express'`**（issue #4878 独立复核 P1 修正）：下单页的口径是
-- 「**未指定**是真值，客户没录过常用物流时**不编造**「快递」」；一旦列默认 `'express'`，
-- 「商家没选」与「选了快递」在库里**不可区分**，且发货页「订单值优先、缺省回落客户档案」
-- 会被那个幽灵 `express` **永久遮蔽**（客户档案里的「物流专线」再也带不出来）⇒ #4419 的口径
-- 在持久化层被推翻。**NULL 才让「未指定」这一档真的存在。**
-- `logistics_company` 可空：未传 = 没有约定承运商，发货页回落客户档案的常用公司。
--
-- ## 迁移号（**现取**）
-- `ls backend/admin-api/src/main/resources/db/migration | tail` ⇒ 落码时最大 = `V99` ⇒ 本单取 `V100`。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `ADD COLUMN IF NOT EXISTS` + 覆盖式 `COMMENT ON COLUMN` ⇒ 重复执行净效果相同。
--
-- ## 存量行（**如实登记，不粉饰**）
-- 本迁移**不回填**：两列对存量单保持 NULL（= 「当时没约定」的真值）。
-- 为什么不做「从 order_logistics 最近一条回填」：那会把**已发货单的承运商**伪装成
-- 「建单时就约定的收货方式」，而后者的真值在迁移时点**已经不存在**（无法恢复的信息不能编）。
--
-- ## 停止条件（fail-closed）
-- `orders` 表不存在 ⇒ 迁移失败并停下（不 CREATE TABLE 兜底 —— 那会造出一张无外键/无索引的
-- 影子订单表，比失败更危险）。
--
-- ## 回滚（**新迁移，不删本文件**；同 V88 / V89 / V92 的处置）
-- ```sql
-- -- V101__rollback_order_logistics_columns.sql（本单只登记，不落码）
-- -- ALTER TABLE orders DROP COLUMN IF EXISTS logistics_type;
-- -- ALTER TABLE orders DROP COLUMN IF EXISTS logistics_company;
-- ```
-- 回滚会丢什么：建单时录入的两列（存量单本来就没有 ⇒ 只影响回滚之后建立的新单）。
--
-- ## bootstrap 终态同步（同 V99 纪律）
-- `docs/sql/schema.sql` 已同步本文件终态（两列 + 注释）—— 新建库路径**不跑迁移链**，
-- 只写迁移 = 新建库无这两列（#3270 同族）。

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS logistics_type VARCHAR(16);

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS logistics_company VARCHAR(128);

COMMENT ON COLUMN orders.logistics_type IS
    '收货物流类型：express 快递 / logistics 物流专线（与 order_logistics.logistics_type V47/#3984 同词表）。NULL = 建单未传（**不猜**，与下单页「未指定」是真值同口径）；发货页优先读订单、缺省回落 customer_profiles.default_logistics_type（issue #4872）';

COMMENT ON COLUMN orders.logistics_company IS
    '收货物流/快递公司（如「顺丰」「四季安」）。NULL = 建单未传（不猜）；发货页回落 customer_profiles.default_logistics_company（issue #4872）';
