-- 排料口径的两个米数 + 当时批次均价（issue #5158；硬要求来自母单 #5159「省料度量」L1）
--
-- ## 一句话
--   `stock_batch_consumptions` 追加三列：`formula_meters`（**行业公式口径**，= 改前的扣减口径）
--   / `planned_meters`（**排料口径**，= 改后的扣减口径）/ `unit_cost`（**当时该批次均价**的快照）。
--   前两列**带符号**（与 `delta` 同向：扣减行为正、回补行为负）⇒ `Σ formula_meters` 与 `Σ(−delta)`
--   是同一件事的两种口径，**差额即排料节省**。
--
-- ## 为什么必须落库，而不是事后重算（#5159 硬约束一「落库不重算」）
--   事后重算会因**口径漂移**给出与当时不一致的数：算料配置（含上下卷边）可被商家随时改，
--   排料器版本会迭代，批次门幅也可能换批次。⇒ 生成那一刻的两个数就是唯一的真相，
--   三个列都必须在**写账那一笔**同时落下（本迁移提供列，写面见
--   `backend/admin-api/src/main/java/com/migao/admin/service/StockBatchConsumptionService.java`）。
--
-- ## 为什么 `unit_cost` 也要落库（#5159 硬约束二「单价用当时该批次的均价」）
--   `saved_amount = saved_meters × 当时该批次均价`。若读面在**查询时**去 join
--   `stock_batches.unit_cost`，则一旦该批次的均价被改（调价/成本订正），**历史单的省钱数会跟着变**
--   —— 那就不是「当时省了多少」，而是「按今天价格折算当时省了多少」（判据 4 的红证形态）。
--   ⇒ 均价随扣减行**快照**落库，读面只做乘法，历史值天然不可变。
--
-- ## 口径（本迁移新增的全部语义）
--   · `formula_meters` = 该行**行业公式口径**米数（= `toStockScaleByCeiling(order_items.quantity)`，
--     与销售账扣减**同源同函数**）。带符号：扣减行 = 正、回补行 = 负（回补行 = 原值的相反数
--     ⇒ 作废后整单两列都净额归零，不必在读面里做「扣减 − 回补」的第二套减法）。
--   · `planned_meters` = 该行**排料口径**米数（A 类完整布并排后应领的米数，同符号语义）。
--     恒等于 `−delta`；单独立列是为了让「两个米数」在账上**逐行自证**
--     （读的人不必知道 `delta` 的符号约定就能读出两个口径 —— #5159 L1 的逐单审计面）。
--   · 不变式（CHECK `ck_batch_consumption_plan_meters`）：`planned_meters <= formula_meters`
--     且两列**同号**。前半句 = 「**只多不少**」的机械判据（排料口径**不得大于**公式口径，
--     否则省数为负 = 排料反而多领）；后半句 = 「扣减行必须两列都正、回补行必须两列都负」
--     —— 少了它，`(+6, −3)` 这种「符号打架」的行也能落库（净额看着对、逐单审计是坏的）。
--   · `unit_cost` = **当时**该批次均价（元/米）快照。NULL = **未知**（本迁移之前的历史行
--     —— 那时没有记录这个数，一律**不回填、不猜**：拿今天的批次价冒充当时价正是本列要防的事）。
--
-- ## 历史行回填（**只回填两个米数，不回填均价**）
--   改前的扣减口径**就是**公式米数 ⇒ 历史行 `formula_meters = planned_meters = −delta`
--   （于是 `saved_meters = 0`，与「本单之前节省恒为 0」的事实一致 —— 不是猜，是那段历史的真实口径）。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
--   · 列：`ADD COLUMN IF NOT EXISTS`；回填：`WHERE … IS NULL` 谓词（第二遍 0 行）；
--   · 约束：`DROP CONSTRAINT IF EXISTS` + 「不存在才 ADD」（`pg_constraint` 判据）；
--   · `SET NOT NULL` 本身幂等（已是 NOT NULL 再设一次不报错）；
--   · 注释：`COMMENT ON` 覆盖式；文末 `DO` 块**终态对账**两遍都成立。
--
-- ## 回滚（**新迁移，不删本文件**）
-- ```sql
-- -- V120__rollback_cutting_plan_meters.sql（本单只登记，不落码）
-- -- ALTER TABLE stock_batch_consumptions DROP COLUMN IF EXISTS formula_meters;
-- -- ALTER TABLE stock_batch_consumptions DROP COLUMN IF EXISTS planned_meters;
-- -- ALTER TABLE stock_batch_consumptions DROP COLUMN IF EXISTS unit_cost;
-- ```
-- **回滚是有损的**：已经发生的「公式口径 vs 排料口径」这件事**回不来**（事后重算会随口径漂移
-- ⇒ 与 #5159 硬约束一冲突）。属**有意**。
--
-- ## bootstrap 终态同步（同 V99/V100/V108/V111/V116 纪律）
-- `docs/sql/schema.sql`（新建库路径**不跑迁移链**）已同步本文件终态。
--
-- ## 停止条件（fail-closed）
--   ① `stock_batch_consumptions`（或它的 `delta` 列）不存在 ⇒ 迁移失败并停下
--      （不 CREATE TABLE 兜底 —— 会造出无外键/无幂等闸的影子表）；
--   ② 终态对账报「列缺失」/「约束缺失」/「约束未禁止 planned > formula」/「NOT NULL 未生效」
--      ⇒ 写语句判据漂移或被部分回滚 ⇒ 回滚本迁移，不硬推。
--
-- ## 显式事务（同 V97/V102/V107/V108/V111/V116 的实测口径）
-- `MigrationRunner` 用 `jdbc.execute(整份文件)` ⇒ PG 隐式包一个事务；而 `psql -f` **默认逐条
-- autocommit** ⇒ 不显式 `BEGIN/COMMIT` 时，中间步骤已提交、`DO` 块才抛 ⇒ 留下**半完成态**。
-- 两条执行路径必须同语义 ⇒ 本文件**显式** `BEGIN; … COMMIT;`。

BEGIN;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 前置表/列存在性（fail-closed：缺表立即停，不兜底建表）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    missing TEXT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'stock_batch_consumptions') THEN
        RAISE EXCEPTION 'V119 前置表缺失：stock_batch_consumptions —— 迁移停下（不兜底建表）';
    END IF;
    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('delta'), ('reason'), ('processing_order_no')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'stock_batch_consumptions'
                          AND column_name = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V119 前置列缺失：% —— 迁移停下（本表形态与 V116 不一致）', missing;
    END IF;
END $$;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 追加三列（先可空 —— 存量行还没有值）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE stock_batch_consumptions
    ADD COLUMN IF NOT EXISTS formula_meters NUMERIC(12,1);
ALTER TABLE stock_batch_consumptions
    ADD COLUMN IF NOT EXISTS planned_meters NUMERIC(12,1);
-- 与 stock_batches.unit_cost 逐字同型（NUMERIC(12,4)，V111）
ALTER TABLE stock_batch_consumptions
    ADD COLUMN IF NOT EXISTS unit_cost NUMERIC(12,4);

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 历史行回填：改前的扣减口径**就是**公式米数 ⇒ 两列同值、saved 恒为 0（**不猜均价**）
-- ══════════════════════════════════════════════════════════════════════════════════════
UPDATE stock_batch_consumptions
   SET formula_meters = -delta,
       planned_meters = -delta
 WHERE formula_meters IS NULL OR planned_meters IS NULL;

-- 两列自此必填（写面漏写 ⇒ 当场失败，不会静默落一行「答不出省了多少」的账）
ALTER TABLE stock_batch_consumptions ALTER COLUMN formula_meters SET NOT NULL;
ALTER TABLE stock_batch_consumptions ALTER COLUMN planned_meters SET NOT NULL;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 不变式（写进约束，不只写在 Java 里 —— 同 V111/V116 对 reason 的纪律）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS ck_batch_consumption_plan_meters;
ALTER TABLE stock_batch_consumptions
    ADD CONSTRAINT ck_batch_consumption_plan_meters
    CHECK (planned_meters <= formula_meters AND formula_meters * planned_meters >= 0);

ALTER TABLE stock_batch_consumptions DROP CONSTRAINT IF EXISTS ck_batch_consumption_unit_cost;
ALTER TABLE stock_batch_consumptions
    ADD CONSTRAINT ck_batch_consumption_unit_cost
    CHECK (unit_cost IS NULL OR unit_cost >= 0);

COMMENT ON COLUMN stock_batch_consumptions.formula_meters IS
    '行业公式口径米数（= toStockScaleByCeiling(order_items.quantity)，与销售账扣减同源同函数）；'
    '带符号：扣减行 = 正、回补行 = 负（回补行 = 原值相反数 ⇒ 作废后整单净额归零）'
    '（V119，issue #5158）';
COMMENT ON COLUMN stock_batch_consumptions.planned_meters IS
    '排料口径米数（A 类完整布并排后应领的米数）= 本行实际扣减口径，恒等于 -delta；'
    '带符号同 formula_meters。约束 ck_batch_consumption_plan_meters 保证 planned <= formula（只多不少）'
    '（V119，issue #5158）';
COMMENT ON COLUMN stock_batch_consumptions.unit_cost IS
    '**当时**该批次均价（元/米）快照（源 stock_batches.unit_cost）。'
    'saved_amount = (formula_meters - planned_meters) * unit_cost —— 均价随行快照 ⇒ '
    '事后改批次均价**不会**改掉历史单的这个数（V119，issue #5158；#5159 硬约束二）。'
    'NULL = 未知（V119 之前的历史行，一律不回填、不猜）';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑤ 终态对账（**两遍都必须成立** ⇒ 既是幂等自证，也是「判据漂移」的停止条件）
-- ══════════════════════════════════════════════════════════════════════════════════════
DO $$
DECLARE
    n              INTEGER;
    missing        TEXT;
    constraint_def TEXT;
    not_null_cnt   INTEGER;
    bad_rows       INTEGER;
BEGIN
    -- ① 三列必须在
    SELECT string_agg(c, ', ') INTO missing
      FROM (VALUES ('formula_meters'), ('planned_meters'), ('unit_cost')) AS v(c)
     WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = 'stock_batch_consumptions'
                          AND column_name = v.c);
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'V119 终态对账失败：缺列 % —— 回滚本迁移', missing;
    END IF;

    -- ② 两个米数必须 NOT NULL（漏了 ⇒ 「答不出省了多少」的账能静默落库）
    SELECT count(*) INTO not_null_cnt
      FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'stock_batch_consumptions'
       AND column_name IN ('formula_meters', 'planned_meters')
       AND is_nullable = 'NO';
    IF not_null_cnt <> 2 THEN
        RAISE EXCEPTION 'V119 终态对账失败：formula_meters/planned_meters 未同时 NOT NULL（实际 % 列）'
            ' —— 回滚本迁移', not_null_cnt;
    END IF;

    -- ③ 「只多不少」约束必须在，且必须**同时**钉住两件事
    SELECT pg_get_constraintdef(oid) INTO constraint_def
      FROM pg_constraint
     WHERE conname = 'ck_batch_consumption_plan_meters'
       AND conrelid = 'stock_batch_consumptions'::regclass;
    IF constraint_def IS NULL THEN
        RAISE EXCEPTION 'V119 终态对账失败：ck_batch_consumption_plan_meters 约束不存在 —— 回滚本迁移';
    END IF;
    IF constraint_def NOT LIKE '%planned_meters <= formula_meters%' THEN
        RAISE EXCEPTION 'V119 终态对账失败：约束未禁止「排料口径 > 公式口径」（省数为负）实际 = %'
            ' —— 回滚本迁移', constraint_def;
    END IF;
    IF constraint_def NOT LIKE '%formula_meters * planned_meters%' THEN
        RAISE EXCEPTION 'V119 终态对账失败：约束未钉住「两列同号」（扣减都正/回补都负）实际 = %'
            ' —— 回滚本迁移', constraint_def;
    END IF;

    -- ④ 均价约束必须在（负成本 = 负的省钱数，读面会看不出是坏数据）
    SELECT count(*) INTO n
      FROM pg_constraint
     WHERE conname = 'ck_batch_consumption_unit_cost'
       AND conrelid = 'stock_batch_consumptions'::regclass;
    IF n = 0 THEN
        RAISE EXCEPTION 'V119 终态对账失败：ck_batch_consumption_unit_cost 约束不存在 —— 回滚本迁移';
    END IF;

    -- ⑤ 存量行必须全部回填（回填谓词写错 ⇒ 老账的省数读不出来且没人发现）
    SELECT count(*) INTO bad_rows
      FROM stock_batch_consumptions
     WHERE formula_meters IS NULL OR planned_meters IS NULL;
    IF bad_rows <> 0 THEN
        RAISE EXCEPTION 'V119 终态对账失败：仍有 % 行未回填两个米数 —— 回滚本迁移', bad_rows;
    END IF;
END $$;

COMMIT;
