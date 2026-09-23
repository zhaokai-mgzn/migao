-- ══════════════════════════════════════════════════════════════════════════════
-- V121 — 修 ck_batch_consumption_plan_meters 的**符号不对称**（issue #5182）
--
-- ## 病（真库实测，本单 AutoBatchDispatchRealDbTest 复现）
--
-- V119 写下的不变式是 `planned_meters <= formula_meters AND formula_meters * planned_meters >= 0`。
-- 前半句是为**扣减行**（两列都正）写的「排料口径只多不少」，但两列在**回补行**上是负的
-- （V119 的口径：回补行 = 原值的相反数 ⇒ 作废后净额归零），而 `p <= f` 在取相反数后
-- **方向翻转**：原行 (formula=6, planned=3) 满足 3 <= 6；回补行 (−6, −3) 则是 −3 <= −6 = **假**。
--
-- ⇒ 后果：**只要这一行真的省过料（planned < formula），它的回补行就违反 CHECK**
-- （SQLSTATE 23514，`ck_batch_consumption_plan_meters`）。也就是：
-- 加工单作废 / 订单取消联动回补，在「排料省过米」的单上**必然失败**。
-- 而本仓 SQL 迁移链上**没有任何真库判据**覆盖过「带节省的行被回补」这一形态
-- （既有 reverse 用例全在 Mockito 面），所以它一直没被任何东西变红。
--
-- 不修的话，阶段 2b-3（#5182）的自动成批派单正好**每次都落在**这个形态上
-- （成批的意义就是跨订单成组省料 ⇒ 回补必炸）⇒ 用户裁定「不能损失客户」在这一格上不成立。
--
-- ## 修法（只改符号口径，不改任何米数语义）
--
-- 把前半句写成**绝对值**形式：`abs(planned_meters) <= abs(formula_meters)`。
--   · 扣减行（两列都正）⇒ 与旧表达式**逐字等价**（abs(x) = x）；
--   · 回补行（两列都负）⇒ 真正的「只多不少」= |应领| <= |公式|（旧式要求的是 ≥，方向反了）。
-- 后半句（两列同号）**一字未动** —— 符号打架的行仍然落不了库。
--
-- 存量行**全部**满足新式（可证，不是经验判断）：旧式在负行上要求 |planned| >= |formula|，
-- 而回补行是扣减行的相反数、扣减行满足 |planned| <= |formula| ⇒ 存量回补行满足
-- |planned| <= |formula|，正是新式。故 ADD CONSTRAINT 不会因存量数据失败。
-- ══════════════════════════════════════════════════════════════════════════════

BEGIN;

ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS ck_batch_consumption_plan_meters;
ALTER TABLE stock_batch_consumptions
    ADD CONSTRAINT ck_batch_consumption_plan_meters
    CHECK (abs(planned_meters) <= abs(formula_meters) AND formula_meters * planned_meters >= 0);

COMMENT ON CONSTRAINT ck_batch_consumption_plan_meters ON stock_batch_consumptions IS
    '排料口径「只多不少」（取绝对值 ⇒ 扣减行与回补行同一口径）且两列同号（扣减都正 / 回补都负）。'
    'V121（issue #5182）修 V119 原表达式的符号不对称：负行上 p <= f 的方向会翻转，'
    '导致「省过料的行的回补行」必然违反本约束。';

-- 终态对账：写错谓词必须当场停（回滚本迁移），而不是留一个「看着在、其实没钉住」的约束
DO $$
DECLARE
    constraint_def TEXT;
BEGIN
    SELECT pg_get_constraintdef(c.oid) INTO constraint_def
      FROM pg_constraint c
     WHERE c.conname = 'ck_batch_consumption_plan_meters'
       AND c.conrelid = 'stock_batch_consumptions'::regclass;
    IF constraint_def IS NULL THEN
        RAISE EXCEPTION 'V121 终态对账失败：ck_batch_consumption_plan_meters 约束不存在 —— 回滚本迁移';
    END IF;
    IF constraint_def NOT LIKE '%abs(planned_meters)%' THEN
        RAISE EXCEPTION 'V121 终态对账失败：约束未改成绝对值口径（回补行仍会炸）实际 = %'
            ' —— 回滚本迁移', constraint_def;
    END IF;
    IF constraint_def NOT LIKE '%formula_meters * planned_meters%' THEN
        RAISE EXCEPTION 'V121 终态对账失败：约束未钉住「两列同号」（扣减都正/回补都负）实际 = %'
            ' —— 回滚本迁移', constraint_def;
    END IF;
END $$;

COMMIT;
