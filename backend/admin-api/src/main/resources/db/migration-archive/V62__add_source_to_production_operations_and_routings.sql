-- provenance 标记 + 行业取值归一（issue #4361 交付物 1/4；收口 #4316）
--
-- ## 为什么需要 provenance 列（本单的诚实性核心）
-- 生产种子（V54 的 30 道工序 + 6 条路线、V56 的 5 道工序、V58 的 3 条纱帘路线）里，
-- **单价全部是占位值**（V54 头注「【默】单价占位，商家可配」）或**行业推算值**
-- （V56 头注「单价为**行业推算**，非实证值」），而这件事**在库里和界面上都看不出来**
-- ⇒ 商家会把「占位单价 × 报工数量」当成工人真实工资基数。
--
-- 叠加 #4343 的实证（客户真实加工单 CSO260915-02615）：`布帘×韩褶`（rt-v54-01）与
-- 真实走线**不符** —— 缺 4 道 / 多 1 道 / `定型→熨烫` **顺序相反** / 6 道工序名库里没有。
-- 用户裁定（2026-09-19）：「照铺，但 provenance 必须在数据与界面上可见，不许静默。」
--
-- ## 冻结映射（照此实现，不得自行扩大/缩小；双向断言由测试守）
-- | 载体 | source | 集合 |
-- |---|---|---|
-- | 工序 | `占位待确认` | V54 的 **30** 道（`op-v54-*`，单价是占位值） |
-- | 工序 | `推算` | V56 的 **5** 道（`op-v56-*`，单价行业推算） |
-- | 路线 | `占位待确认` | V54 的 **6** 条（`rt-v54-*`，**含 布帘×韩褶** —— #4343 已证明不符） |
-- | 路线 | `推算` | V58 的 **3** 条纱帘（`rt-v58-*`，镜像布帘同工艺推导） |
-- | 两者 | `实证` | **当前空集** —— 客户确认 #4261/#4343 后才会有（诚实结论，不是遗漏） |
--
-- 回填按 **id 前缀**认领（不是按名字列表 —— 名字列表会随改名漂移），且只动 `source IS NULL`
-- 的行（幂等；不覆盖商家/模板已写的 source）。**其余行保持 NULL**（不落 `ELSE`）：
-- 未知来源 = 未知，不许冒充「占位待确认」。
--
-- ## 为什么是**新迁移 V62**（不改 V54/V56/V58）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记，已应用的文件**整份跳过**
-- （`applied.contains(filename)` ⇒ `continue`）⇒ 往 V54 里加列会「CI 绿、存量环境永远拿不到」
-- = **绿了但没生效**（本仓库最忌讳的形态）。故 V54/V56/V58/V59/V60 **一字不动**。
-- ⚠️ 版本号 **V62**：V61 已被 #4359（报工计件快照）占用，别抢号。
--
-- ## 为什么同一迁移里也做 `tenants.industry` 归一
-- 「开租按行业套用生产模板」要求 `tenants.industry` 能当**模板键**，而它是**自由文本**
-- （注册页 `type="text"`，placeholder「如：布艺纺织、家居建材、电子商务等」）⇒
-- 存量租户的行业值取不到模板（**静默落空库**）。故与加列同批做一次性映射；
-- 口径与 Java `IndustryCodes.normalize` 逐条一致（两侧一致性由 `IndustryCodesTest` 双向钉）。
--
-- ## 幂等（MigrationRunner 要求所有 SQL 可重复执行）
-- ① `ADD COLUMN IF NOT EXISTS`；
-- ② 回填 `WHERE source IS NULL`（第二次执行影响 0 行）；
-- ③ `CHECK` 约束用 `DO $$ ... IF NOT EXISTS (pg_constraint) ... $$` 守卫；
-- ④ industry 归一 `WHERE industry IS DISTINCT FROM <归一结果>`（第二次执行影响 0 行）。
--
-- ## 与真值源的收敛判据（防第二份口径漂移）
-- 本文件是 Python 常量与既有迁移的**一次快照**，不是第二份真值源。防漂移由测试守：
-- `backend/admin-api/src/test/java/com/migao/admin/migration/ProductionSourceProvenanceMigrationTest.java`
-- （冻结映射集合双向断言）+ `tests/unit_ci_workflows/test_production_catalog_seed.py`
-- （五源逐行逐值：routing.py ↔ V54∪V56∪V58 ↔ production-templates/curtain/seed.json ↔ schema.sql）。

-- ── ① 加列（两表各一；VARCHAR(16) 够放三个中文取值）──
ALTER TABLE production_operations ADD COLUMN IF NOT EXISTS source VARCHAR(16);
ALTER TABLE production_routings ADD COLUMN IF NOT EXISTS source VARCHAR(16);

COMMENT ON COLUMN production_operations.source IS
    'provenance 口径来源（V62，issue #4361）：实证 / 推算 / 占位待确认。'
    '占位待确认 = 单价是占位值（V54 的 30 道）；推算 = 单价为行业推算（V56 的 5 道）；'
    '实证 = 当前空集（客户确认 #4261/#4343 后才会有）。NULL = 来源未知（商家自建/历史行），'
    '不许读成「占位待确认」。';
COMMENT ON COLUMN production_routings.source IS
    'provenance 口径来源（V62，issue #4361）：实证 / 推算 / 占位待确认。'
    '占位待确认 = V54 的 6 条（含 布帘×韩褶 —— #4343 已证明与客户真实加工单不符）；'
    '推算 = V58 的 3 条纱帘（镜像布帘同工艺推导）；实证 = 当前空集。'
    'NULL = 来源未知（商家自建/历史行）。';

-- ── ② 回填：工序（按 id 前缀认领；其余保持 NULL）──
UPDATE production_operations
SET source = CASE
        WHEN id LIKE 'op-v54-%' THEN '占位待确认'
        WHEN id LIKE 'op-v56-%' THEN '推算'
    END
WHERE source IS NULL
  AND (id LIKE 'op-v54-%' OR id LIKE 'op-v56-%');

-- ── ③ 回填：路线（按 id 前缀认领；其余保持 NULL）──
UPDATE production_routings
SET source = CASE
        WHEN id LIKE 'rt-v54-%' THEN '占位待确认'
        WHEN id LIKE 'rt-v58-%' THEN '推算'
    END
WHERE source IS NULL
  AND (id LIKE 'rt-v54-%' OR id LIKE 'rt-v58-%');

-- ── ④ 枚举约束（防自由文本 source 悄悄进来）──
-- 用 DO 块守卫：PostgreSQL 的 `ADD CONSTRAINT` 没有 `IF NOT EXISTS`，直接写不幂等。
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'production_operations_source_check'
    ) THEN
        ALTER TABLE production_operations
            ADD CONSTRAINT production_operations_source_check
            CHECK (source IS NULL OR source IN ('占位待确认', '推算', '实证'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'production_routings_source_check'
    ) THEN
        ALTER TABLE production_routings
            ADD CONSTRAINT production_routings_source_check
            CHECK (source IS NULL OR source IN ('占位待确认', '推算', '实证'));
    END IF;
END $$;

-- ── ⑤ 存量 tenants.industry 自由文本一次性归一为受控 code（curtain / other）──
-- 口径与 Java `IndustryCodes.normalize` 逐条一致（别名表 + 形态归一：去空白/分隔符/转小写）。
-- 幂等：`WHERE industry IS DISTINCT FROM <归一结果>` ⇒ 第二次执行影响 0 行。
-- 空值不动（`industry IS NULL` ⇒ CASE 落到 NULL ⇒ IS DISTINCT FROM 为真 ⇒ 会写 NULL 等于不写；
-- 显式加 `industry IS NOT NULL` 避免无意义的全表写）。
UPDATE tenants
SET industry = CASE
        WHEN lower(regexp_replace(industry, '[\s/、,，·\-_]+', '', 'g')) IN (
            'curtain', '布艺', '窗帘', '布艺窗帘', '窗帘布艺', '布艺纺织', '纺织',
            '窗帘行业', '布艺行业', '布艺窗帘行业', '窗帘布艺行业',
            '软装', '布艺软装', '窗帘店', '窗帘加工', '窗帘布艺加工',
            '家居布艺', '遮光帘', '窗帘定制'
        ) THEN 'curtain'
        ELSE 'other'
    END
WHERE industry IS NOT NULL
  AND industry IS DISTINCT FROM CASE
        WHEN lower(regexp_replace(industry, '[\s/、,，·\-_]+', '', 'g')) IN (
            'curtain', '布艺', '窗帘', '布艺窗帘', '窗帘布艺', '布艺纺织', '纺织',
            '窗帘行业', '布艺行业', '布艺窗帘行业', '窗帘布艺行业',
            '软装', '布艺软装', '窗帘店', '窗帘加工', '窗帘布艺加工',
            '家居布艺', '遮光帘', '窗帘定制'
        ) THEN 'curtain'
        ELSE 'other'
    END;
