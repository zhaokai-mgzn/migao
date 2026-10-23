-- 算料配置：拼色主布余量（单开 / 多开）独立成参数（issue #7560，用户 2026-10-23）
--
-- ## 一句话
-- 纸质「韩折下料速查表」的拼色两列（单开 0.15 / 对开 0.20）与单色两列（0.20 / 0.30）**各自一套**。
-- 用户逐字：「单开和对开的参数不太一样，在参数上要体现出来」⇒ 不做「单色余量 − 固定扣减」的推导，
-- 落成两个与 `margin_single` / `margin_multi` **并列**的配置列（列名 = 算料引擎配置键，逐字同名）。
--
-- ## 为什么是 NOT NULL DEFAULT
-- 缺行 = 用引擎默认值（`DEFAULT_CRAFT_CALC_CONFIG`）；有行的租户在加列后必须拿到与引擎一致的读数
-- ⇒ 默认值 = 纸表读数（0.15 / 0.20），存量行零回归。
--
-- ## 幂等
-- `ADD COLUMN IF NOT EXISTS` + 覆盖式 `COMMENT` ⇒ 重复执行净效果相同（`MigrationRunner` 要求可重复执行）。
--
-- ## 回滚（登记，不落码）
-- ```sql
-- ALTER TABLE craft_calc_configs DROP COLUMN IF EXISTS margin_mixed_single;
-- ALTER TABLE craft_calc_configs DROP COLUMN IF EXISTS margin_mixed_multi;
-- ```

BEGIN;

ALTER TABLE craft_calc_configs
    ADD COLUMN IF NOT EXISTS margin_mixed_single NUMERIC(6,3) NOT NULL DEFAULT 0.15;

ALTER TABLE craft_calc_configs
    ADD COLUMN IF NOT EXISTS margin_mixed_multi NUMERIC(6,3) NOT NULL DEFAULT 0.20;

COMMENT ON COLUMN craft_calc_configs.margin_mixed_single IS
    '拼色单开余量（米）。引擎默认 0.15（纸表「主布拼色」单开列）；与 margin_single 并列的独立参数，不是推导值。';

COMMENT ON COLUMN craft_calc_configs.margin_mixed_multi IS
    '拼色多开余量（米）。引擎默认 0.20（纸表「主布拼色对开」列）；与 margin_multi 并列的独立参数。';

-- 终态对账：两列必须真的在（加列语句被注释 / 被跳过 ⇒ 当场抛，不留半成品）
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'craft_calc_configs' AND column_name = 'margin_mixed_single'
    ) OR NOT EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'craft_calc_configs' AND column_name = 'margin_mixed_multi'
    ) THEN
        RAISE EXCEPTION 'V188 终态对账失败：craft_calc_configs 缺少 margin_mixed_single / margin_mixed_multi';
    END IF;
END $$;

COMMIT;
