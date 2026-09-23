-- 工艺路线商家可配（issue #4308，P1；用户裁定 2026-09-19「支持企业设置工艺路线的自定义」）
--
-- ## 形态裁定（写进库结构，别读成「从零画路线」）
-- 「支持企业设置工艺路线的自定义」= **参数 / 信号 / 序列可配 + 护栏**，不是「自由拖拽的通用编排器」。
-- 证据链见 `docs/design/craft-routing-customization.md`（决策记录）与 issue #4308「背景与裁定」。
--
-- ## 本迁移建/改三样东西
-- ① `production_route_signals`：**信号 → 路线键**的租户级映射（种子 = 迁移前 Java 常量表逐条）。
--    此前映射是 `ProcessingOrderService.CURTAIN_TYPE_KEYWORDS` / `CRAFT_KEYWORDS` 两个
--    `String[][]` 常量 ⇒ 商家每加一个自定义加工项（POC 已建过「POC-加工工艺」这种名字），
--    派生就多一分静默错配，而**改常量要走研发发版**。落库后商家可增删改（写面 = #4308 交付物 3）。
-- ② `production_routing_versions`：路线变更账（沿用 `production_operation_price_versions` 范式）。
--    路线是**计件工资**（Σ 报工数量 × 工序单价）与**完工判定**（必完工序全绿）的唯一输入 ⇒
--    改序列必须留痕，「这条路线昨天是什么样」要答得出。
-- ③ `processing_orders.route_key` / `route_source`：把「这张单**实际走了哪条路线**、这个键是
--    **怎么来的**」落成数据。此前 `RouteKey.source` 只在「路线缺失」的 error 日志里被读一次，
--    成功路径**零可观测** ⇒ 「罗马帘订单拿到布帘·韩褶的 11 道工序」这类错配无数据可查（P1 缺陷）。
--
-- ## `route_source` 四态（冻结口径，与 ProcessingOrderService 逐字一致）
--   `derived`       —— 帘种与工艺**两维都由库中信号映射命中**，且该键的路线在库中存在（实际用了派生路线）；
--   `partial`       —— 只有**一维**命中（另一维取默认值）⇒ 补救动作 = 去「信号映射」**补另一维**；
--   `missing_route` —— 两维都命中但**库中无该路线**（T2，回落默认路线）⇒ 补救动作 = 去「工艺路线」**建路线**；
--   `default`       —— 两维**全不命中**（T1，直接取默认键 布帘×韩褶）⇒ 补救动作 = 去「信号映射」**补信号**。
-- ⚠️ T2 **不并入 `partial`**：两者的**补救动作不同**（建路线 vs 补信号），并成一个值后前端
-- 给不出可行动的提示语 —— 那正是本单要治的「静默 / 不可行动」。取值 13 字符列装得下
-- （最长 `missing_route`）。**不落 `derived` 以外的「已派生」假象**：T1/T2 都不得伪装成
-- 「已派生」（issue #4308 P1 判据原话）。
--
-- ## 两列路线键的分工（`route_key` vs `route_requested_key`）
--   `route_key`           = **实际使用**的键（T1/T2 时 = 默认 `布帘×韩褶`）—— 与真正实例化出的工序对应；
--   `route_requested_key` = **派生出来想用**的键（两维全不命中时 NULL）—— 没有它，`missing_route`
--                           的提示说不出「识别的 X 在库里没有路线」，用户拿不到可行动的下一步。
--
-- ## 信号表的**用途拆分**（为什么一行一个用途，而不是一行同时给帘种+工艺）
-- 迁移前的两张常量表里，「帘头」出现**两次且位次相反**：
--   `CURTAIN_TYPE_KEYWORDS` = 帘头(1) / 纱(2) / 布(3) —— 帘头**最前**（注释原文：避免「帘头纱」被判成纱帘）；
--   `CRAFT_KEYWORDS`        = 韩褶(1) / 打孔(2) / 四爪钩(3) / 四叉钩(4) / 穿杆(5) / 平幔(6) / 帘头(7)
--                             —— 帘头**最后**（它是工艺侧兜底）。
-- **单列 order 无法同时表达这两个位次** ⇒ 本表按**用途**分行（`curtain_type` 非空 = 帘种行，
-- `craft` 非空 = 工艺行），唯一性也按用途拆（同一信号在同一用途下只许一行，跨用途各一行）。
-- 这样「帘头」两行各自保序，派生结果与**迁移前的常量表逐条等价**（等价性由
-- `ProductionRouteSignalMigrationTest.seedParsesToLegacyKeywordTables` 逐条钉住）。
-- ⚠️ 若把两行合成一行（`(tenant_id, signal)` 单唯一键），「帘头」的工艺映射会在同一信号文本里
-- **抢在韩褶/打孔之前**生效 ⇒ 「打孔帘头」这类文本的派生键会从 `帘头×打孔` 变成 `帘头×平幔`
-- （静默改路线 = 静默改工资）。
--
-- ## 幂等（MigrationRunner 要求所有 SQL 可重复执行）
-- 建表/索引 `IF NOT EXISTS`；增列 `ADD COLUMN IF NOT EXISTS`；种子 `ON CONFLICT DO NOTHING`
-- （冲突目标显式写出，与部分唯一索引的谓词一致）。
--
-- ## 幂等与「不改已应用的迁移」（别顺手合并进 V59）
-- `MigrationRunner` 台账按**文件名**记，已应用的文件整份跳过 ⇒ 往老迁移里加行在存量环境**永远不生效**。
-- 故本单所有 DDL 走**新迁移 V60**（V59 已被 #4230 占用；V58 = #4246）。
--
-- ## 与真值源/常量的收敛判据（防第二份口径漂移）
-- 本文件的种子是**迁移前 Java 常量表的一次快照**，不是第二份真值源。防漂移由
-- `ProductionRouteSignalMigrationTest` 守：种子逐行 ↔ 迁移前的常量表（三帘种 3 行 + 七工艺 7 行）↔
-- `docs/sql/schema.sql` 的 bootstrap 终态；`ProductionRoutingCommandServiceTest` /
-- `ProcessingOrderServiceTest` 另守「派生读库而非读常量」。

-- ── ① 信号 → 路线键（租户级，商家可配）──
CREATE TABLE IF NOT EXISTS production_route_signals (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    signal VARCHAR(64) NOT NULL,                     -- 信号关键字（命中方式 = 文本 contains，与迁移前常量表同口径）
    curtain_type VARCHAR(16),                        -- 命中后给出的帘种（NULL = 本行不参与帘种扫描）
    craft VARCHAR(16),                               -- 命中后给出的工艺（NULL = 本行不参与工艺扫描）
    priority INT NOT NULL DEFAULT 0,                 -- **用途内**扫描序（越小越先；不是全局序，见文件头「用途拆分」）
    status VARCHAR(16) NOT NULL DEFAULT 'active',    -- active / disabled
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0,
    -- 一行至少给出一维，否则这行是死数据（既不改帘种也不改工艺，白白参与扫描）
    CONSTRAINT ck_production_route_signals_has_target
        CHECK (curtain_type IS NOT NULL OR craft IS NOT NULL)
);
-- 唯一性按**用途**拆（见文件头「用途拆分」）：同一信号在同一用途下只许一行，跨用途各一行。
-- 普通唯一索引做不到 —— 「帘头」在两个用途下都要存在。
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_route_signals_tenant_signal_curtain
    ON production_route_signals (tenant_id, signal)
    WHERE deleted = 0 AND curtain_type IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_route_signals_tenant_signal_craft
    ON production_route_signals (tenant_id, signal)
    WHERE deleted = 0 AND craft IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_production_route_signals_tenant_priority
    ON production_route_signals (tenant_id, priority)
    WHERE deleted = 0;
COMMENT ON TABLE production_route_signals IS
    '信号 → 路线键映射（V60，issue #4308）：派生加工单路线时按 priority 扫描本表；种子 = 迁移前 ProcessingOrderService 的两张常量关键字表；商家可增删改';
COMMENT ON COLUMN production_route_signals.priority IS
    '**用途内**扫描序（不是全局序）：帘种行与工艺行各自排序，因为「帘头」在两个用途里位次相反（帘种最前、工艺最后）';
COMMENT ON COLUMN production_route_signals.curtain_type IS
    '命中的帘种（NULL = 本行不参与帘种扫描）；填 `帘头` 会派生 production_routings.curtain_type';
COMMENT ON COLUMN production_route_signals.craft IS
    '命中的工艺（NULL = 本行不参与工艺扫描）；「帘头」在工艺侧映射到 `平幔`（库里只有 帘头×平幔 一条路线）';

-- ── ② 工艺路线变更账（沿用 production_operation_price_versions 范式）──
CREATE TABLE IF NOT EXISTS production_routing_versions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    routing_id VARCHAR(64) NOT NULL REFERENCES production_routings(id),
    curtain_type VARCHAR(16) NOT NULL,               -- 冗余存键（路线行若被软删/改名，历史账仍答得出「当时是哪条」）
    craft VARCHAR(16) NOT NULL,
    operations JSONB NOT NULL DEFAULT '[]',          -- 本次变更后的工序名有序序列（seq 天然 = 下标+1）
    operation_count INT NOT NULL DEFAULT 0,          -- 工序道数（报表/对账少解析一次 JSON）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_routing_versions_routing
    ON production_routing_versions (routing_id, created_at DESC)
    WHERE deleted = 0;
COMMENT ON TABLE production_routing_versions IS
    '工艺路线版本账（V60，issue #4308）：每次改序列追加一行，「当前 = 最新版本行」；路线是计件工资与完工判定的唯一输入，改动必须留痕';
COMMENT ON COLUMN production_routing_versions.operations IS
    '本次变更后的工序名有序序列；seq 不单独存 —— 它就是数组下标 + 1（写面归一化为 1..N）';

-- ── ③ 加工单落「实际走的路线」+「想走的路线」+「怎么来的」（P1：静默回落必须可观测）──
ALTER TABLE processing_orders ADD COLUMN IF NOT EXISTS route_key VARCHAR(32);
ALTER TABLE processing_orders ADD COLUMN IF NOT EXISTS route_requested_key VARCHAR(32);
ALTER TABLE processing_orders ADD COLUMN IF NOT EXISTS route_source VARCHAR(16);
COMMENT ON COLUMN processing_orders.route_key IS
    '本单**实际使用**的路线键「帘种×工艺」（V60，issue #4308）；T1/T2 时 = 默认 布帘×韩褶；多部位订单取最需关注的那一条（default > missing_route > partial > derived）';
COMMENT ON COLUMN processing_orders.route_requested_key IS
    '本单**派生出来想用**的路线键（V60，issue #4308）；两维全不命中（route_source=default）时 NULL —— missing_route 的提示靠它说出「识别的 X 在库里没有路线」';
COMMENT ON COLUMN processing_orders.route_source IS
    '路线键来源（V60，issue #4308）：derived 两维均由库中信号命中且路线存在 / partial 只命中一维（补信号）/ missing_route 派生键库中无路线（建路线）/ default 两维全不命中（补信号）';

-- ── ④ 种子：迁移前两张常量关键字表**逐条**落库（3 帘种 + 7 工艺 = 10 行，不增不减）──
-- 逐行抄自 9673df68 的 ProcessingOrderService：
--   CURTAIN_TYPE_KEYWORDS = {帘头→帘头, 纱→纱帘, 布→布帘}      （priority = 数组下标+1）
--   CRAFT_KEYWORDS        = {韩褶→韩褶, 打孔→打孔, 四爪钩→四爪钩, 四叉钩→四爪钩,
--                             穿杆→穿杆, 平幔→平幔, 帘头→平幔}  （priority = 数组下标+1）
-- ⚠️ 顺序即语义（「帘头」在帘种表最前 / 在工艺表最后），不得为了好看重排。
INSERT INTO production_route_signals
    (id, tenant_id, signal, curtain_type, craft, priority, status)
VALUES
  ('sig-v60-01', 1, '帘头', '帘头', NULL,   1, 'active'),
  ('sig-v60-02', 1, '纱',   '纱帘', NULL,   2, 'active'),
  ('sig-v60-03', 1, '布',   '布帘', NULL,   3, 'active'),
  ('sig-v60-04', 1, '韩褶', NULL,   '韩褶',  1, 'active'),
  ('sig-v60-05', 1, '打孔', NULL,   '打孔',  2, 'active'),
  ('sig-v60-06', 1, '四爪钩', NULL, '四爪钩', 3, 'active'),
  ('sig-v60-07', 1, '四叉钩', NULL, '四爪钩', 4, 'active'),
  ('sig-v60-08', 1, '穿杆', NULL,   '穿杆',  5, 'active'),
  ('sig-v60-09', 1, '平幔', NULL,   '平幔',  6, 'active'),
  ('sig-v60-10', 1, '帘头', NULL,   '平幔',  7, 'active')
ON CONFLICT DO NOTHING;
