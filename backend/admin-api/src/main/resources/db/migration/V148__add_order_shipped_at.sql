-- V148 — 订单「发货时刻」`orders.shipped_at`（issue #6262，用户 2026-10-03 逐字裁定 **B**）
--
-- ## 一句话
-- `orders` 加一列 `shipped_at`（timestamptz，可空）：**发货后 N 天自动完成订单**这条定时腿的
-- **判定锚点**。没有它，自动完成就得靠 `join order_logistics` 反推发货时刻 —— 而那条路的锚点
-- **实测不可用**（见下）。
--
-- ## 为什么必须新增一列（不是"按惯例加列"，是现取读数逼出来的）
-- 现取真库读数（2026-10-03，`ai_customer_service`）：
--   · `orders` 里 `status='shipped'` **21** 条；`completed` 7 条 ⇒ 订单正在「已发货」积压。
--   · 这 21 条里 `order_logistics` 有行且 `shipped_at` 非空的只有 **15** 条 ⇒ **6 条查不到发货时刻**。
--   · `order_logistics` 全表 29 行，`shipped_at` 非空仅 **16** ≈ 一半 ⇒ 该列**不是**「发货必写」的事实源。
--   · `order_shipments` 全表 9 行、`shipped_at` 非空 **1** 行 ⇒ 更差（它只覆盖工人发货路）。
-- 根因（读码，`OrderLogisticsWriter.upsert`）：`shipped_at` **只在新建物流行时**写
-- （`OrderLogisticsWriter` 的 insert 分支），更新分支不补 ⇒ 任何「台账行先存在（含测试/导入/建单期）、
-- 之后才发货」的订单，锚点永远为空。⇒ 拿它当锚点会让一部分并发出去的货**永远不自动完成**，
-- 而且**没有任何东西会变红**（静默漏单，正是本单最不能出的错）。
--
-- ## 为什么锚点必须落在 `orders` 这一张表上（而不是 join 出来的投影）
-- 本单的并发安全口径（人工「确认收货」 vs 自动扫描，单机与**集群**同一套代码）要求
-- **一条带谓词的原子 UPDATE**：`WHERE tenant_id=? AND status='shipped' AND shipped_at <= 死线`
-- ⇒ 每一行只会被一个事务改到，另一侧 0 行、静默（不引 Quartz / ShedLock / leader 选举）。
-- 谓词里放不了「另一张表的聚合」⇒ 锚点必须是 `orders` 自己的列。
--
-- ## 谁写它（两条发货路都写，这是本列的完整性前提）
--   ① `OrderService.transitionStatusAtomic`（`to=shipped` 时 set）—— 商家侧
--      `PUT /orders/{id}/status`、agent `order_manage(update_logistics)`、
--      `shipWithLogistics` 三条入口**共用**这一个 CAS；
--   ② `OrderShipmentService.transition`（工人扫码发货路）—— 与 ① 同款条件 UPDATE。
-- 两条路各有一份「写了它」的判据（`OrderShippedAtWriteGuardTest`），漏写任何一条 ⇒ 判红
-- （不是靠注释约定）。
--
-- ## 存量回填（**显式方案**，不是"顺带"）
-- 用 `order_logistics.shipped_at` 回填 —— **只回填它非空的行**（现取可覆盖 21 条里的 **15** 条）。
-- 剩下 **6** 条**保持 NULL**（有意为之）：那 6 条没有任何 durable 发货时刻，回填只能编一个值
-- （`updated_at` / `created_at` 都不是发货时刻：前者被后续任何一次编辑刷过，后者是**下单**时刻，
-- 拿它算「发货后 N 天」会把没发的单判成已满期）。
-- 🔴 **后果逐字登记**：`shipped_at IS NULL` 的行**永远不会**被自动完成（谓词按「满 N 天」的
-- 正向条件取行，NULL 不满足任何比较 ⇒ 不参与）⇒ 这 6 条**只能人工确认收货**，与今天的现状
-- 逐值相同（不是回归，也不是"以后会补上"）。这与本仓既有先例同口径：
--   · `V142` 的 `created_by` / `created_by_name` 存量 = NULL **不回填**「不猜一个操作者」；
--   · `V147` 的 `shipping_method` 存量 = NULL「未采集，不猜不回填」。
-- ⇒ 回填**只搬已存在的事实**（`order_logistics.shipped_at` 那一列的原值），不生成任何新事实。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `ADD COLUMN IF NOT EXISTS` + `UPDATE ... WHERE shipped_at IS NULL`（第二遍无行可改，
-- 且**不会**覆盖已经由发货路写下的真值）+ `COMMENT ON COLUMN` + `CREATE INDEX IF NOT EXISTS`
-- ⇒ 第二遍净效果相同。
--
-- ## 非破坏性（本仓迁移只许加列 / 加索引）
-- 不删列、不改既有列、不设 NOT NULL、不带 FK。可空是**语义**（NULL = 未采集 / 查不到发货时刻），
-- 不是「待补的缺口」。

ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipped_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN orders.shipped_at IS
    '订单**发货时刻**（issue #6262）：= 该单最近一次 shipped 流转发生的时刻，由两条发货路各自的条件 UPDATE 写入（OrderService.transitionStatusAtomic / OrderShipmentService.transition）。用途 = 「发货后 N 天自动完成」定时腿的判定锚点。NULL = 未采集（存量行回填不全 / 从未发货）⇒ 该行**不参与**自动完成，只能人工确认收货。**不是** orders.updated_at（会被后续任何编辑刷新）、也**不是** orders.created_at（那是下单时刻）';

-- 存量回填：只搬 order_logistics.shipped_at 的**已有事实**（不回填 NULL、不猜）
UPDATE orders o
   SET shipped_at = l.shipped_at
  FROM order_logistics l
 WHERE l.order_id = o.id
   AND l.deleted = 0
   AND l.shipped_at IS NOT NULL
   AND o.shipped_at IS NULL;

-- 扫描谓词是 (tenant_id, status, shipped_at)：部分索引只盖在架的单（shipped）
CREATE INDEX IF NOT EXISTS idx_orders_tenant_status_shipped_at
    ON orders (tenant_id, shipped_at)
    WHERE status = 'shipped' AND deleted = 0;
