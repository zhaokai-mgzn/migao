-- V160 — 订单「收款时刻」`orders.paid_at` + 「完成（收货）时刻」`orders.received_at`（issue #7078）
--
-- ## 一句话
-- `orders` 加两列（timestamptz，可空），把**已经发生、却无处落地**的两个时刻落库：
-- `paid_at` = 该单**确认收款**的时刻（`pending → confirmed`）；`received_at` = 该单进入 `completed` 的时刻。
--
-- ## 为什么必须新增列（不是"按惯例加列"，是用户真机读数逼出来的）
-- 2026-10-17 用户真机截图（订单 `20261016769570012`，库内状态 `confirmed`）：状态引导第 1 步是
-- 「已付款 ✓」，而同屏「基础信息」的 **支付时间 / 支付交易号** 都是 `-` ⇒ 用户判定「状态引导和实际的不一致」。
-- 读源定位：`OrderDetailResponse` 全文**只有一处**时间键（`LogisticsInfo.shippedAt`），既没有
-- `paidAt` / `paymentNo` / `receivedAt`，也没有顶层 `shippedAt`；`orders` 表也没有对应列
-- ⇒ 那几行**恒为 `-`**，与订单走到哪一步无关 —— 与 #6882「屏幕面读后端未下发的字段（幽灵字段）」同类，
-- 那一包只清了**行级**字段（货号 / 颜色 / 门幅）。
-- 引导第 1 步的勾本身是**从状态推出来的**（`OrderProgressSteps.getStepStates()` 只看 `status`，
-- 不读任何支付记录）⇒ 「已付款 ✓」与「支付时间 -」必然同屏自相矛盾。
-- 用户同日裁定 **A：补真值**（① 发货时间透出已落库的 `shipped_at`；② 支付时间真采集；
-- ③ 确认收货时间真采集；④ 支付交易号**先不上屏** —— 系统没有在线支付交易号的真值源）。
--
-- ## 谁写（每列都有具名的写入点；摘掉任一处 ⇒ 判红，不是靠注释约定）
--   · `paid_at` —— **只在** `OrderService.transitionStatusAtomic` 的 `pending → confirmed` 这条边上写，
--     用**期望前驱**（`expectedStatus`）限定 ⇒ `producing → confirmed`（作废加工单退回待发货那条**回退边**）
--     **不写**，否则「支付时间」会被一次回退动作顶成当天。
--   · `received_at` —— 两条完成路**各写一次**：① 商家「确认收货」走 `transitionStatusAtomic`（`to=completed`）；
--     ② 发货后 N 天**自动完成**走 `OrderMapper.autoCompleteShippedOrders` 自己的条件 UPDATE
--     （那条腿**不经** `transitionStatusAtomic` ⇒ 漏写就会静默留空，正是本列最危险的退化形态）。
--     判据 = `OrderPaidAndReceivedAtWriteGuardTest`（含判别力自证：四种坏形态各自判红）。
--   · `shipped_at` **不在**本迁移内（V148 已有列）：本单只把它**透出**到详情响应，不新建、不回填。
--
-- ## 存量回填（**只搬已存在的事实**，与 V148 同口径）
--   · `paid_at`：从 `finance_transactions` 取该订单**最早一笔** `type='income'`（`status='success'`、未删除）
--     的时刻（`occurred_at` 缺则回落 `created_at`）—— 那是 `confirmPayment` 当时写下的真值
--     （全仓 `income` 流水的**唯一**写入点 = `OrderService.confirmPayment` 的「订单确认收款」）。
--   · `received_at`：**不回填**。存量 `completed` 单没有任何 durable 的完成时刻
--     （`order_logistics.delivered_at` 是**买家签收**，不是「确认收货」；拿它顶上是**生成新事实**）。
--     🔴 后果逐字登记：存量已完成单该行**仍显示 `-`**（= 未采集），**不是**「以后会补上」。
--   · `payment_no`（支付交易号）：**不建列** —— 无真值源，该行已从屏幕撤下（前端类型面同步删除）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- `ADD COLUMN IF NOT EXISTS` + `UPDATE ... WHERE paid_at IS NULL`（第二遍无行可改，
-- 且**不会**覆盖已由写入点落下的真值）+ `COMMENT ON COLUMN` ⇒ 第二遍净效果相同。
--
-- ## 非破坏性（本仓迁移只许加列 / 加索引）
-- 不删列、不改既有列、不设 NOT NULL、不带 FK、**不建索引**（两列都不参与任何扫描谓词）。
-- 可空是**语义**（NULL = 未采集），不是「待补的缺口」。

ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS received_at TIMESTAMP WITH TIME ZONE;

COMMENT ON COLUMN orders.paid_at IS
    '订单**收款时刻**（issue #7078）= 该单 pending → confirmed（确认收款）发生的时刻，由 OrderService.transitionStatusAtomic 在「新态 confirmed + 期望前驱 pending」这条边上写入（回退边 producing → confirmed 不写）。NULL = 未采集（存量无收款流水 / 从未确认收款）⇒ 屏幕显示「-」，不猜。**不是** orders.updated_at（会被后续任何编辑刷新），也**不是** created_at（那是下单时刻）';

COMMENT ON COLUMN orders.received_at IS
    '订单**完成（收货）时刻**（issue #7078）= 该单进入 completed 的时刻，两条完成路各写一次：① 商家「确认收货」= OrderService.transitionStatusAtomic（to=completed）；② 发货后 N 天自动完成 = OrderMapper.autoCompleteShippedOrders 的条件 UPDATE。⇒ 自动完成的单本列 = **自动完成时刻**（不是买家点确认的时刻），列名口径已在判据里登记。NULL = 未采集（存量 completed 单不回填）⇒ 屏幕显示「-」，不猜';

-- 存量回填：只搬 finance_transactions 里**已经存在**的收款事实（不生成任何新事实）
UPDATE orders o
   SET paid_at = t.first_paid_at
  FROM (SELECT order_id, MIN(COALESCE(occurred_at, created_at)) AS first_paid_at
          FROM finance_transactions
         WHERE type = 'income'
           AND status = 'success'
           AND deleted = 0
           AND order_id IS NOT NULL
         GROUP BY order_id) t
 WHERE t.order_id = o.id
   AND o.paid_at IS NULL;
