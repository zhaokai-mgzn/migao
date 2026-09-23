-- 加工费组合定价 + 版本账（V68，issue #4386，P1）
--
-- ## 用户裁定（2026-09-19，写进库结构，别读成「每个加工项一个价」）
-- 「缺乏**加工费的管理模块**。」
-- 「**不是每个加工项收取一个费用**，而且通常是组合」
-- 「选**韩褶 + 打孔**是一种收费，如果还要求定型，那**韩褶 + 打孔 + 定型又是一个价格**」
-- 「选配完的一个商品**只会收取一种加工费**，然后根据米算出这个商品的加工费」
-- 「这个加工费组合是要**系统根据选配结果自己计算**的，**不可能**是用户直接告诉」
--
-- ⇒ **两个时刻、两个角色**：
--   商家在**配置时**自行组合并定价（本表 = 那个写面，权限 processing:manage）；
--   系统在**下单时**按选配结果匹配组合 → 取价 → × 加工费米数 → **一个数**。
--   顾客 / AI agent 只能**选配**，不得告知组合、也不得告知金额。
--
-- ## 反推现状（本单补的是「组合费用」这一层，它此前**表都没有**）
--   `processing_items`（加工项目录）            ✅ 有
--   `product_processing_items`（商品↔加工项）   ✅ 有（#4371 会让它整条退场 —— 本表**无商品维度**，故不依赖它）
--   `processing_rules`（可组合性：互斥/必选…）  ⚠️ 表在、**全仓 0 代码引用**（KNOWN-03）—— 本单**不落码**
--   **组合费用（价格）**                        ❌ 此前**表都没有** ⇒ 本迁移补上
--   下单侧计价今天两边都是 **Σ 加工项 × 数量**（前端自算 + OrderService.sumProcessingFee 服务端重算）
--   —— **正是被用户否掉的形态**。本单**不接线**（见 issue #4386「不做」），只交付商家配置面。
--
-- ## `composition_key` 的归一化口径（**冻结**，判据 2 双向钉住）
--   ① 逐项 trim；② 丢空项；③ **去重**；④ 按 **Unicode 码点升序**排序；⑤ 以 `+` 连接。
--   ⇒ `韩褶+打孔+定型` ≡ `定型+打孔+韩褶` ≡ `打孔+定型+韩褶`（同一个 key，**同一个价**）。
--
-- 为什么必须与书写顺序无关：同一笔钱建出两行 ⇒ 下单匹配命中哪一行取决于扫描顺序
--   ⇒ 同一份选配在两次下单拿到**两个价**（不可复现的定价 = 不可复现的订单金额）。
-- 为什么**不**用「加工项目录的 sort_order 序」：那会让 key 随**加工项表的改动**漂移 ——
--   商家调一下排序，已成交组合的 key 就变了 ⇒ 历史订单匹配不上自己的价。纯内容序是唯一
--   在数据变更下仍稳定的选择。（两侧一致性由 `ProcessingFeeCombinationCommandServiceTest`
--   的 `compositionKeyIsOrderIndependent` 与 Java `compositionKey()` 双向钉住。）
--
-- ## 为什么不建「穷举幂集」（n 个特征 → 2ⁿ 组合）
--   用户否掉了「要求商家穷举」：本表只维护**实际会卖**的组合，没维护到的由
--   `GET /api/admin/production/processing-fee-gaps` 暴露为缺口（同 #4308 的 routing-gaps 处置）。
--   ⚠️ **不静默套默认价**：未命中组合的处置（`fee_source=unpriced` + 可行动提示）属**接线**，
--   不在本单（issue #4386「不做」已登记）。
--
-- ## 为什么是**新迁移 V68**（不改 V1..V63 任何一个字）
--   `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记，已应用的文件**整份跳过**
--   ⇒ 往老迁移里加表在存量环境**永远不生效**（「CI 绿、功能静默缺失」）。
--   ⚠️ 版本号 **V68**（**改过一次号**，如实登记）：本迁移初版为 **V66**，与并行包 #4398 的
--      `V66__decouple_product_processing_items.sql` **撞号**。`tests/unit_ci_workflows/
--      test_migration_version_uniqueness.py` 实测判红并给出处置口径：「**后合入者改名到下一个
--      空闲版本号**」（#3812 约定；**禁止**往 `KNOWN_DUPLICATE_VERSIONS` 加条目放行）。
--      #4398 先合入 ⇒ 本包让号：V66 → V68（V67 已被 `V67__add_scope_to_production_operations.sql`
--      占用）。**改名安全**（#3812 口径）：`MigrationRunner` 仅以**文件名**判「已执行」
--      （`applied.contains(filename)`），且本迁移全部 DDL 幂等
--      （`CREATE TABLE/INDEX IF NOT EXISTS` + `DO $$ ... pg_constraint ... $$` 守卫）
--      ⇒ 新号首跑是幂等空操作。**本文件除版本号与注释外，内容一字未改。**
--
-- ## 幂等（MigrationRunner 要求所有 SQL 可重复执行）
--   建表/索引 `IF NOT EXISTS`；CHECK 用 `DO $$ ... pg_constraint ... $$` 守卫
--   （PostgreSQL 的 `ADD CONSTRAINT` 没有 `IF NOT EXISTS`）。
--
-- ## 与 schema.sql 的收敛
--   `docs/sql/schema.sql` 是**全新库的一次性 bootstrap**（该路径**不跑迁移链**）⇒ 同款终态
--   必须同步写进该文件，否则 bootstrap 建库后 admin-api 查询 500（形态见 #3270）。

-- ── ① 组合 → 加工费单价（元/米）──
CREATE TABLE IF NOT EXISTS processing_fee_combinations (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    -- 归一化后的选配特征集合（`+` 连接，如 `韩褶+打孔+定型`）—— **取价的匹配键**。
    -- 与书写顺序无关（见文件头「归一化口径」）；256 装得下（特征名单个 ≤128，实际组合 ≤5 项）。
    composition_key VARCHAR(256) NOT NULL,
    -- 归一化后的特征名有序列表（与 composition_key **同源**，展示用；不单独维护第二份口径）
    items JSONB NOT NULL DEFAULT '[]',
    -- 加工费单价（**元/米**）：组合价 × 加工费米数 = 该商品这一个数。CHECK ≥ 0（负单价会把订单算成负数）。
    unit_price DECIMAL(10, 2) NOT NULL,
    -- active / disabled（停用 = **保留行**，不物理删：要能回答「昨天这个组合什么价」）
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    sort_order INT NOT NULL DEFAULT 0,
    -- provenance 口径（与 `production_operations.source` / V62 同词表）：实证 / 推算 / 占位待确认。
    -- NULL = 来源未知（商家自建行），**不许**读成「占位待确认」。
    source VARCHAR(16),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0,
    CONSTRAINT ck_processing_fee_combinations_unit_price CHECK (unit_price >= 0),
    CONSTRAINT ck_processing_fee_combinations_key_not_blank CHECK (btrim(composition_key) <> '')
);
-- 唯一键 = (tenant_id, composition_key) WHERE deleted = 0 —— **同一组合不重复定价**。
-- 写面另有一道同口径的 409 护栏（先撞护栏 ⇒ 给可行动建议；撞到这里 = 500，是缺陷）。
CREATE UNIQUE INDEX IF NOT EXISTS uk_processing_fee_combinations_tenant_key
    ON processing_fee_combinations (tenant_id, composition_key)
    WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_processing_fee_combinations_tenant_status
    ON processing_fee_combinations (tenant_id, status, sort_order)
    WHERE deleted = 0;
COMMENT ON TABLE processing_fee_combinations IS
    '加工费组合定价（V68，issue #4386）：一行 = 一组选配特征 → 一个加工费单价（元/米）。'
    '用户裁定「不是每个加工项收取一个费用，而且通常是组合」「选配完的一个商品只会收取一种加工费」'
    '⇒ 下单侧按选配结果匹配本表取价，× 加工费米数 = 一个数。不是穷举幂集：只维护实际会卖的组合，'
    '缺口由 GET /api/admin/production/processing-fee-gaps 暴露。';
COMMENT ON COLUMN processing_fee_combinations.composition_key IS
    '归一化后的选配特征集合（trim → 丢空 → 去重 → 按 Unicode 码点升序 → `+` 连接）。'
    '与书写顺序无关：`韩褶+打孔+定型` ≡ `定型+打孔+韩褶`（否则同一笔钱建出两行 ⇒ 取价不可复现）。'
    '唯一键 = (tenant_id, composition_key) WHERE deleted = 0。';
COMMENT ON COLUMN processing_fee_combinations.items IS
    '归一化后的特征名有序列表，与 composition_key **同源**（展示用）；不单独维护第二份口径。';
COMMENT ON COLUMN processing_fee_combinations.unit_price IS
    '加工费单价（元/米）：组合价 × 加工费米数 = 该商品这一个数。CHECK >= 0 —— 负单价会把订单金额算成负数。';
COMMENT ON COLUMN processing_fee_combinations.source IS
    'provenance 口径来源（V68，issue #4386；与 production_operations.source / V62 同词表）：'
    '实证 / 推算 / 占位待确认。NULL = 来源未知（商家自建/历史行），不许读成「占位待确认」。';

-- ── ② 组合定价**版本账**（与 production_routing_versions（#4308）同构）──
CREATE TABLE IF NOT EXISTS processing_fee_combination_versions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    combination_id VARCHAR(64) NOT NULL REFERENCES processing_fee_combinations(id),
    -- 冗余存键（组合行被停用/改名后，历史账仍答得出「当时是哪一组」）
    composition_key VARCHAR(256) NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL,              -- 本次变更后的单价（元/米）
    status VARCHAR(16) NOT NULL DEFAULT 'active',    -- 本次变更后的状态
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_processing_fee_combination_versions_combination
    ON processing_fee_combination_versions (combination_id, created_at DESC)
    WHERE deleted = 0;
COMMENT ON TABLE processing_fee_combination_versions IS
    '加工费组合定价版本账（V68，issue #4386）：单价**真的变了**才追加一行（同值重复提交是幂等空操作）；'
    '当前价 = 最新版本行。加工费单价是订单金额的直接输入，改价必须留痕 —— 「这个组合昨天什么价」要答得出。';
COMMENT ON COLUMN processing_fee_combination_versions.composition_key IS
    '冗余存的归一化组合键：组合行被停用/改名后，历史账仍答得出「当时是哪一组」。';
