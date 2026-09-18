-- 工序实例的**主定位键**：`order_item_id` + `position_kind`（issue #4388 / #4373 裁定）
--
-- ## 为什么要有这个迁移（缺陷形态 = 「同名部位只能靠数组位置对齐」）
-- `processing_position_operations` 此前只有 `position_name`（展示名 = 加工产物名[+色号]）+
-- `seq`，索引 `(processing_order_id, position_name, seq)`。而**同商品同色号的两个窗会同名**
-- （`buildPositionPayload` 自述「不靠部位名（同商品同色号的两行会重名）」）⇒ 后果有二：
--   ① **读面把两个部位并成一个**（`ProductionService.buildPositions` 按 `position_name` 分组）——
--      工人扫码/加工单详情看到「一个部位 22 道工序」，而不是「两个部位各 11 道」；
--   ② 算料 `qty` 回填靠**数组位次**对齐（`fillQty` 的 `resolved.get(i) ↔ operationRows.get(i)`），
--      响应一旦重排就是**静默错配**（只有条数校验，没有身份校验）。
-- ⇒ 主定位键改为 `(order_item_id, position_kind)`：`order_item_id` 解决「哪一樘窗的哪一行」，
--   `position_kind` 解决「哪一件帘」（可读定位 + 冗余校验）。
--
-- ## ⚠️ 存量单兼容（**列可空，且必须写明**）
-- 本列引入**之前**生成的实例行没有该值，且**无法可靠回填**：`position_name` 是可读名
-- （如「布艺遮光帘A 米白」），按它反查 `order_items` 只能靠猜（同名商品 + 同色号可有多行、
-- 商品名可改、行可软删）——**猜错比留空更糟**（会把工序/计件归属到错的行）。
-- ⇒ 采取**显式留空 + 读面兜底**：
--   · `order_item_id IS NULL` = **本列引入前的存量行**（不是脏数据，也不是「未实例化」）；
--   · 读面（`ProductionService.buildPositions`）按 `position_name` 兜底分组 ⇒ **存量单行为逐字不变**；
--   · 新生成的实例行一律带 `order_item_id`（`buildSnapshot` 无条件落 `order_items.id` = 主键）。
--
-- ## 为什么**不**加外键
-- `order_items` 与加工单实例的**生命周期不同**（订单行可被软删/订单可被删，而加工单实例是
-- 生产凭据、报工与计件挂在它上面 —— 见 `test_delete_orders_fk_order.py` 同族约束）。
-- 加 FK 会让「删订单/删行」被加工单实例挡住，属净损失 ⇒ 参照完整性由**生成侧**保证
-- （`order_item_id` 只从快照的 `itemId` 取值，而快照来自 `order_items` 本身）。
--
-- ## 幂等（MigrationRunner 要求所有 SQL 可重复执行）
-- `ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` / `COMMENT ON` 均幂等。
--
-- ## bootstrap 终态同步
-- `docs/sql/schema.sql` 已同步本文件的终态（bootstrap 路径**不跑迁移链**）。

-- ── ① 两列（可空；存量行留空 = 明确语义，见上「存量单兼容」）──
ALTER TABLE processing_position_operations ADD COLUMN IF NOT EXISTS order_item_id VARCHAR(36);
ALTER TABLE processing_position_operations ADD COLUMN IF NOT EXISTS position_kind VARCHAR(16);

COMMENT ON COLUMN processing_position_operations.order_item_id IS
    '工序实例主定位键（V68，issue #4388 / #4373 裁定）：指向 order_items.id（一樘窗的一行）。'
    'NULL = 本列引入前的**存量行**（无法可靠回填，不猜）⇒ 读面按 position_name 兜底分组（行为逐字不变）。'
    '不加外键：订单行与加工单实例的生命周期不同（实例是生产凭据，报工/计件挂在它上面）。';
COMMENT ON COLUMN processing_position_operations.position_kind IS
    '部位种类（V68，issue #4388）：布帘/纱帘/帘头（= 快照 curtainType），解决「哪一件帘」的可读定位与冗余校验。'
    'NULL = 存量行（同 order_item_id）。';

-- ── ② 按行归属的查询索引（读面/报工/计件按 order_item_id 归属）──
CREATE INDEX IF NOT EXISTS idx_position_operations_order_item
    ON processing_position_operations (processing_order_id, order_item_id)
    WHERE deleted = 0;
