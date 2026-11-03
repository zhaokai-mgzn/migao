-- V207 / issue #7197 ①：不合格原因字典化（新记录必选字典项，reason 降级为自由补充）
--
-- ## 一句话
--   给 `quality_inspections` 加一列 `reason_code`：**字典项** = 可统计的原因键；
--   `reason`（自由文本）保留为**自由补充**（可空）。
--
-- ## 🔴 口径（不得偏离）
--   · **新记录**：判定 ≠ pass 时 `reason_code` 必填（服务层 `QualityCheckService` 校验，缺 ⇒ 422 具名报错）；
--     取值域 = `QualityReasonDictionary` 的六项（布面污渍 / 布料破洞 / 色差 / 尺寸不符 / 走线不良 / 其它）。
--   · **存量不清洗**：老记录 `reason_code` 保持 NULL、`reason` 原文一字不动 —— **不猜归类、不回填**。
--     读面据 NULL 如实显示「未归类」，绝不把自由文本静默并入某个原因（issue #7197 的前置口径）。
--   · **DB 不设 CHECK 约束**（与 `inspection_result` 同款：约束在服务层，错误码 VALIDATION_ERROR + 逐值文案）
--     —— 保持与既有列同构，避免同一件事两处实现。
--   · **不加索引**：读面目前按 `(tenant_id, order_item_id, inspected_at)` / `(tenant_id, processing_order_id)`
--     取行，原因分布是**内存聚合**（见 `QualityCheckService.stats` 的同族做法）；等真出现「按原因筛选」的
--     慢查询再加，不预先建没被消费的索引。
--
-- ## 幂等 / 可重复执行
--   `ADD COLUMN IF NOT EXISTS` + `COMMENT`（可重复执行）⇒ 第二遍是 no-op。
--   本迁移**不写数据**（存量行一律 NULL）、不改任何既有列 ⇒ 无可回滚的数据面
--   （回滚 = `ALTER TABLE quality_inspections DROP COLUMN IF EXISTS reason_code;`，本项目无 rollback 文件约定，同 V157/V205）。
ALTER TABLE quality_inspections ADD COLUMN IF NOT EXISTS reason_code VARCHAR(32);

COMMENT ON COLUMN quality_inspections.reason_code IS
    '不合格原因字典项（issue #7197 ①）：fabric_stain 布面污渍 / fabric_hole 布料破洞 / color_diff 色差 / '
    'size_mismatch 尺寸不符 / stitching_defect 走线不良 / other 其它；判定 ≠ pass 时**服务层必填**。'
    'NULL = 存量自由文本记录（不清洗、未归类，界面如实显示）';

-- 终态对账（幂等）：列没建出来 ⇒ 当场失败，绝不静默半成品
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'quality_inspections' AND column_name = 'reason_code'
    ) THEN
        RAISE EXCEPTION 'V207 终态对账失败：quality_inspections.reason_code 未建出来';
    END IF;
END $$;
