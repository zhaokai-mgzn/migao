-- 入库明细行新增「卷数」（issue #7709，用户裁定 2026-10-25）
--
-- ## 一句话
-- 入库米数 = **卷数 × 卷长**，由服务端一处换算（`InboundOrderService.metersOfRolls` 建单面、
-- `InboundOrderService.storedMeters` 读面 / 过账面）；`inbound_order_items.quantity` 从此**恒为米数**，
-- 本列只记「几卷」这一个**外部事实**。
--
-- ## 为什么必须有这一列（用户 2026-10-25 三张截图逐字读数）
-- 入库单 `RK-20261024-0001` 两行都是「数量 1 / 卷长 70」，而系统把它记成 **1 米**：
--   · 批次余量 `PC-20261024-0001/0002` 的「入库米数 = 1、剩余米数 = 1」；
--   · 库存流水两条 `入库过账` 是「变动 +1、变动前 0、变动后 1」；
--   · 下单随即报「需要 6.3 米，当前仅剩 1.0 米」。
-- 根因：明细行只有 `quantity` + `roll_length_m` 两列，**没有「卷数」这个判别器** ⇒
-- 服务端只在 `source=photo`（工人拍照入库，issue #6812）时乘卷长，采购/期初单直接把 `quantity`
-- 当米数；于是换算只能靠**客户端自觉**（issue #7646 的前端自乘）—— 客户端不乘就少记 70 倍。
--
-- ## 口径（本列落地之后）
--   · `roll_count` 有值 ⇒ 入库米数 = `roll_count × roll_length_m`（服务端算，客户端的 quantity 不采信）；
--   · `roll_count` 为空 ⇒ `quantity` 本身就是米数（散剪 / 尾料按米录入，`> 0` 且 0.1 米粒度）；
--   · 工人拍照单恒非空（它的 `quantity` 本来就是卷数 ⇒ 建单时映射进本列）。
--
-- ## 幂等 / 回滚
-- `ADD COLUMN IF NOT EXISTS` ⇒ 重跑 0 变化（`MigrationRunner` 要求迁移可重复执行）。
-- 回滚：
-- ```sql
-- ALTER TABLE inbound_order_items DROP COLUMN IF EXISTS roll_count;
-- ```
-- 新列无下游依赖（没有任何索引 / 约束 / 外键引用它），且存量行的 `quantity` 一直是米数口径
-- ⇒ 丢列不改变任何一笔账。
--
-- ## 边界（如实登记，不粉饰）
-- - **不修历史**：用户 2026-10-25 裁定「历史一律不动，只修以后」⇒ 本文件**不碰**任何已有单据 /
--   批次 / 台账 / SKU 库存；已按 1 米过账的行保持原值，由用户在「批次盘点」里实盘修正
--   （`reason=manual` + `note LIKE '库存盘点：%'` 是 V190 认可的真实单据口径）；
-- - 历史拍照行（`source=photo` 且 `roll_count IS NULL`）的 `quantity` 仍是**卷数** ⇒ 读面由
--   `InboundOrderService.storedMeters` 兼容（乘卷长），本列**不回填**；
-- - 不给 `stock_batches` 加同名列：批次余量的口径是**米**（V111「一行 = 一个批次」），
--   卷数只属于单据行（一批次可能来自 N 卷，记在批次上会与「一行 = 一个批次」冲突）。

ALTER TABLE inbound_order_items ADD COLUMN IF NOT EXISTS roll_count INTEGER;

COMMENT ON COLUMN inbound_order_items.roll_count IS
    '卷数（外部事实）：与 roll_length_m 一起决定入库米数 = roll_count * roll_length_m（服务端唯一换算点，issue #7709）。NULL = 按米录入（quantity 本身就是米数）；本列落地后新写的 photo 单（工人拍照）恒非空。quantity 一列恒为米数';

COMMENT ON COLUMN inbound_order_items.roll_length_m IS
    '每卷米数（卷长）：与 roll_count 一起决定入库米数（= roll_count * roll_length_m，issue #7709）。只填它不填卷数时仍是「仅记录 / 打印卷标」，不参与换算（#5034）';
