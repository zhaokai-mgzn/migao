-- 工序实例增列 qty_source（issue #4208 Java 接线）
--
-- ## 为什么需要这一列
-- 应做数量的真值源是算料引擎（ai-agent `app/production/routing.py::_qty_for`）。引擎**只产出**
-- `fabric_meters`（用料米数）与 `pleat_count`（折数）；`panels`（幅）/`set_count`（套）/`holes`（孔）
-- 是 routing.py 已显式登记的**待补键**（引擎暂未产出）⇒ 那几类工序的应做数量会落**兜底 1**。
-- 没有本列时，「算料输出 12.3」与「兜底 1」在库里长得一模一样 ⇒ 排查时无法区分
-- 「引擎算出来的」与「引擎没答、系统占位的」，而本单要治的缺陷（应做数量退化成订单数量）
-- 恰恰就是被这种**静默**掩盖的。
--
-- 取值三态（与端点 `qty_source_by_operation` 逐字同口径，见
-- `app/api/internal.py::operation_qty` 的 docstring）：
--   ① 键名（`fabric_meters` / `pleat_count` / `holes`）= 该键**直接供数**（算料输出）
--   ② `<键名>_x6` = 「孔」类无 holes 时按每米 6 孔的**行业口径估算**（有依据，不是占位值）
--   ③ `fallback` = **真兜底 1**（无键可读 / 引擎不认识的工序或单位 / panels・set_count 待补键）
--
-- ## 幂等
-- `ADD COLUMN IF NOT EXISTS`（MigrationRunner 要求所有 SQL 可重复执行）。
-- 存量行留 NULL = 「本列引入之前的旧实例」，与 `fallback` 可区分（不回填、不猜）。
--
-- ## 三源收敛
-- 迁移列 / Java 实体 `ProcessingPositionOperation.qtySource` / bootstrap `docs/sql/schema.sql`
-- 三处同口径，由 `ProductionPositionOperationQtySourceMigrationTest` 守。

ALTER TABLE processing_position_operations
    ADD COLUMN IF NOT EXISTS qty_source VARCHAR(32);

COMMENT ON COLUMN processing_position_operations.qty_source IS
    '应做数量的口径来源（V57，issue #4208）：键名=fabric_meters/pleat_count/holes 直接供数；<键名>_x6=每米 6 孔估算；fallback=真兜底 1；NULL=本列引入前的旧实例';
