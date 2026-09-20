-- 未定价 ≠ 价 0：实例化侧三态落库（issue #4696，P1）
--
-- ## 一句话
-- 「矩阵格未定价（`production_operation_positions.unit_price IS NULL`）」此前在**实例化路径**被
-- 回落到「工序库行价」（`production_operations.unit_price`，V49 DDL = `NOT NULL DEFAULT 0`）
-- ⇒ 落库实例单价 **0 元** ⇒ 报工即按 0 计件（**工人白干且无人知道**），而 V88 的读面
-- （`GET /operation-layers`）**不回落**、判 `unpriced`、界面显示「未定价」⇒ **两处口径不一致**，
-- 且「没定价」与「价本来就是 0」在数据上**不可区分**。
-- 本迁移把「未定价」变成**可落库的一态**（NULL），使三态在数据层可区分：
--
-- | 态 | `processing_position_operations.unit_price` | 语义 |
-- |---|---|---|
-- | 未定价 | `NULL` | 商家还没定价 ⇒ **不得**计件（更不得按 0 计件） |
-- | 价 0 | `0` | 商家**显式**定价为 0 元（有价） |
-- | 有价 | `> 0` | 正常计件单价 |
--
-- ## 为什么是「放开 NULL」而不是「加 price_state 列」
-- ① 读面的真值源（矩阵格）本来就用 `NULL` 表达未定价（V86 的列注释：
--    「NULL = 未定价或明确不做（≠ 0 元，0 是定价为 0 元）」）⇒ 实例快照沿用**同一载体**，
--    两处不引入第二份口径；
-- ② 加冗余标记列 = 两个真值源，必然漂移（且漂移的那一份不会变红）。
-- `production_work_logs.price_state` 是**唯一**必须新增的标记列：报工表上的 `unit_price IS NULL`
-- 在 V61 已被占用为「本列引入之前的存量报工」（聚合按实例回查兜底），不能复用 ⇒ 只能显式标记。
--
-- ## 历史值（红线，issue #4696 判据 4）
-- 本迁移**只改列约束，不改任何一行数据**：
--  · `processing_position_operations` 的存量行（含 `unit_price = 0` 的歧义行）**一字不动** ——
--    它们无法回溯区分「当年未定价被折成 0」与「当年定价 0 元」，**只影响新单**；
--  · `production_work_logs.unit_price` / `factor` 的**历史值一字不动**（V61 快照口径不变）；
--  · 新列 `production_work_logs.price_state` 对存量行留 `NULL` = 「本列引入前」⇒ 聚合走既有回查路径。
--
-- ## 回滚 SQL（保留于注释；按需手工执行）
-- ```sql
-- ALTER TABLE production_work_logs DROP COLUMN IF EXISTS price_state;
-- -- 回滚前必须先把 NULL 归零，否则 `SET NOT NULL` 会失败（这一步会**丢失**「未定价」这一态，
-- -- 即回滚 = 退回到本 issue 要治的静默缺陷；仅在确认业务可接受时执行）：
-- UPDATE processing_position_operations SET unit_price = 0 WHERE unit_price IS NULL;
-- ALTER TABLE processing_position_operations ALTER COLUMN unit_price SET DEFAULT 0;
-- ALTER TABLE processing_position_operations ALTER COLUMN unit_price SET NOT NULL;
-- ```
--
-- ## 停止条件（fail-closed，不静默降级）
-- ① 若 `ALTER COLUMN ... DROP NOT NULL` 因**非本迁移**引入的依赖（视图/生成列/CHECK）失败 ⇒
--    迁移直接报错停下（Flyway 事务回滚），**不**改为「保留 NOT NULL + 用哨兵值」——
--    哨兵值会把缺陷重新引入（任何一个数值哨兵都与「真 0 元」不可区分）；
-- ② 若 `production_work_logs` 已有同名 `price_state` 列且取值域不符 ⇒ 人工介入，**不**静默改名。

-- ── ① 实例快照单价放开 NULL（未定价的真载体）────────────────────────────────────
ALTER TABLE processing_position_operations ALTER COLUMN unit_price DROP NOT NULL;
ALTER TABLE processing_position_operations ALTER COLUMN unit_price DROP DEFAULT;
COMMENT ON COLUMN processing_position_operations.unit_price IS
    '实例快照单价（元/单位，生成时从部位价目矩阵逐字带出）：NULL = **未定价**（商家还没定价）'
    '—— ≠ 0 元（0 是**显式定价为 0 元**，仍是有价）；实例化侧**不得**回落工序库行价'
    '（production_operations.unit_price 是 NOT NULL DEFAULT 0 ⇒ 回落会把「未定价」变成「真 0 元」，'
    '工人白干且无人知道）。调价不影响历史报工（V49/V61 口径）。issue #4696。';

-- ── ② 报工快照的三态标记（唯一必须新增的列）────────────────────────────────────
ALTER TABLE production_work_logs ADD COLUMN IF NOT EXISTS price_state VARCHAR(16);
COMMENT ON COLUMN production_work_logs.price_state IS
    '计件单价三态标记（V90，issue #4696）：priced = 有价（含显式定价 0 元）；'
    'unpriced = **未定价**（unit_price 为 NULL，聚合**不得**按 0 计件，报表必须显式可见 + 给定价入口）；'
    'NULL = 本列引入之前的存量行（V61 口径：按实例回查兜底，历史金额一字不动）。';
