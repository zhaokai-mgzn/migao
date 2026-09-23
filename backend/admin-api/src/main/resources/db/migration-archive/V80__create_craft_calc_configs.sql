-- 算料公式**租户级配置**表（issue #4528 = 包 E，依赖包 D #4527）
--
-- ## 一句话
-- 用户 2026-09-19 裁定：「我提供的韩折的公式**可能不是行业通用的**，可能得**支持每个商家自定义配置**」
-- ⇒ 把包 D 已做成「可注入 + 默认值」的公式参数（`curtain_calc.DEFAULT_CRAFT_CALC_CONFIG`）
-- 落到**租户级单行配置**上：商家在「工艺配置 → 算料配置」页改口径，算料随之变。
--
-- ## 迁移号为什么是 V80
-- V79 已分配给包 F（#4529）。**已发布迁移不可改**（issue #4235）：`MigrationRunner` 的台账
-- `schema_migrations` 按**文件名**记、已应用的文件**整份跳过** ⇒ 改旧文件只对全新库生效、
-- 存量环境永远拿不到 = 「CI 全绿、功能静默缺失」。一切增量都走本文件。
--
-- ## 🔴 缺行 = 用默认值（**不做开租播种**）
-- 本迁移**不插任何种子行**（YAGNI）：默认值的唯一来源是算料引擎的
-- `DEFAULT_CRAFT_CALC_CONFIG`（`GET /api/internal/production/craft-calc-config`），
-- 再在库里种一份 = **第二份会漂的默认值**（引擎改默认、库里还是旧值 ⇒ 两条路径算不同米数）。
-- ⇒ 读面 `GET /api/admin/production/craft-calc-config` 在**无活跃行**时返回引擎默认值 +
-- `source='default'`；有行才返回商家配置 + `source='stored'`。
--
-- ## 结构化列（不是一整块 JSON）
-- 每个配置键一列：数值列可被 SQL 直接读/审计，JSONB 只用于**嵌套结构**（拼次档位 / 工艺档位）。
-- 列名与引擎配置键**逐字同名**（`per_fold_single` / `margin_single` / …）—— 读写两侧零映射，
-- 映射表就是「第二份键名口径」的滋生地。
--
-- ⚠️ **没有 `default_fabric_width` 列**：设计文档 §4.2 把它列为提案键，但包 D 的**实现里不存在**
-- （门幅是 `build_quote(fabric_width=…)` 的入参，不是配置键）⇒ **以实现为准**，
-- 不凭空加一个没有消费者的配置键（issue #4528 开工要求「以代码事实为准并登记差异」）。
--
-- ## 幂等
-- `CREATE TABLE IF NOT EXISTS` + `CREATE UNIQUE INDEX IF NOT EXISTS`（`bootstrap-first` 会让迁移
-- 在建好终态的库上再跑一遍；`docs/sql/schema.sql` 同 PR 同步该表 —— bootstrap 路径不跑迁移链）。
--
-- ## 回滚 SQL（保留于注释；按需手工执行）
-- ```sql
-- DROP TABLE IF EXISTS craft_calc_configs;
-- ```
--
-- ## 与真值源的收敛判据（防第二份口径漂移）
-- 本文件的列集与**引擎配置键集**必须逐键一致：守卫 =
-- `tests/unit_ci_workflows/test_craft_calc_config_contract.py`（按内容读 `curtain_calc.py`
-- 的 `DEFAULT_CRAFT_CALC_CONFIG` 键集 ↔ 本迁移的列 ↔ `schema.sql` 的列 ↔ Java 实体字段）。

CREATE TABLE IF NOT EXISTS craft_calc_configs (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- ── 公式参数（列名 = 引擎配置键，逐字同名）──
    per_fold_single NUMERIC(6,3) NOT NULL DEFAULT 0.25,        -- 单色每折吃布（米）
    per_fold_mixed_times JSONB NOT NULL DEFAULT '{"1": 0.65, "2": 1.2}'::jsonb,  -- 拼次 → 每折吃布（米）
    margin_single NUMERIC(6,3) NOT NULL DEFAULT 0.2,           -- 单开余量（米）
    margin_multi NUMERIC(6,3) NOT NULL DEFAULT 0.3,            -- 多开余量（米）
    min_fullness NUMERIC(6,3) NOT NULL DEFAULT 1.5,            -- 褶倍下限（行业美学红线，护栏）
    tiers JSONB NOT NULL DEFAULT
        '{"standard": {"fullness": 2.0, "label": "标准工艺"}, "economy": {"fullness": 1.8, "label": "经济工艺"}}'::jsonb,
    default_formula VARCHAR(16) NOT NULL DEFAULT 'pleat',      -- 兜底公式：pleat 韩折公式 / fullness 褶倍数公式
    side_margin NUMERIC(6,3) NOT NULL DEFAULT 0.3,             -- 定宽买高上下卷边（米）
    meters_rounding_step NUMERIC(6,3) NOT NULL DEFAULT 0.1,    -- 用料向上进位步长（米）
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);

-- 租户级**单行**（部分唯一索引：软删行不占位 ⇒ 删了还能重建）
CREATE UNIQUE INDEX IF NOT EXISTS uk_craft_calc_configs_tenant
    ON craft_calc_configs (tenant_id)
    WHERE deleted = 0;

COMMENT ON TABLE craft_calc_configs IS
    '算料公式**租户级配置**（V80，issue #4528 = 包 E）。单行/租户，**缺行 = 用引擎默认值**'
    '（source=''default''）—— 不做开租播种：默认值唯一来源是算料引擎 '
    'curtain_calc.DEFAULT_CRAFT_CALC_CONFIG（GET /api/internal/production/craft-calc-config），'
    '库里再种一份 = 第二份会漂的默认值。';
COMMENT ON COLUMN craft_calc_configs.per_fold_single IS
    '单色每折吃布（米）。引擎默认 0.25（纸表口径）。护栏：必须 > 0（0/负 ⇒ 写面 422，不静默回退默认值）。';
COMMENT ON COLUMN craft_calc_configs.per_fold_mixed_times IS
    '拼色「拼次 → 每折吃布（米）」映射（JSONB，键 = 正整数拼次的**字符串形态**，'
    '如 {"1": 0.65, "2": 1.2} —— JSON 对象键恒为字符串，算料端点入口归一为 int）。'
    '护栏：非空、键为正整数、值 > 0。未登记的拼次**不得**静默退回单色系数（少算用料），'
    '由算料端点显式报缺口。';
COMMENT ON COLUMN craft_calc_configs.min_fullness IS
    '褶倍下限（护栏，行业美学红线）。引擎默认 1.5。**可配但不可关**：写面护栏要求 >= 引擎默认值'
    '（= 行业红线），低于它 ⇒ 422 + 逐条理由 —— 下限被关掉 = 用料不足且无人知道。';
COMMENT ON COLUMN craft_calc_configs.tiers IS
    '工艺档位（JSONB：{档位名: {fullness, label}}）。护栏：非空、每档 fullness > 0 且 >= min_fullness。';
COMMENT ON COLUMN craft_calc_configs.default_formula IS
    '兜底用料公式：pleat（韩折公式＝折数法，默认）/ fullness（褶倍数公式＝倍数法）。'
    '⚠️ 它只是**工艺推导表缺失时的兜底**（韩褶/打孔由 craft 推导，见 curtain_calc.resolve_craft_rule），'
    '不是恒定生效的默认值。护栏：必须在枚举内。';
COMMENT ON COLUMN craft_calc_configs.meters_rounding_step IS
    '用料米数**向上进位**步长（米），引擎默认 0.1。护栏：必须 > 0（截断/四舍五入 = 抹零，issue #4527 判据 3）。';
COMMENT ON COLUMN craft_calc_configs.status IS
    '配置行状态（范式同 production_crafts，V72）。读面按 deleted = 0 取行，不按 status 过滤'
    '（本包无停用语义 —— 不留一个没有消费者的过滤条件，将来要停用时再显式接线）。';
