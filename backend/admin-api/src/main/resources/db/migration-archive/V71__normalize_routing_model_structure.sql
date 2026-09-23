-- 工序路线模型重构 **P1：纯增量建新结构**（issue #4427 = 母单 #4423 的 P1/3）
--
-- ## 一句话
-- 9 条「(部位 × 工艺) 展开路线」收敛为「**1 条具名主线 + 规则表 + 部位价目**」。
-- 本迁移**只新增**三张表及其种子；**旧表旧行、Java、Python 运行时、前端一字不动**
-- ⇒ **运行时行为零变化**（切消费路径是 P2）。
--
-- ## 为什么是「纯增量」（母单 #4423 §三 冻结）
-- 同一份真值源有**四个投影**（`app/production/routing.py` / SQL 种子 / Java 实例化 /
-- bootstrap `schema.sql`）—— 一次性全改 = 跨三端 + 动工人工资的超大 PR（风险不可控）；
-- 而「先删旧再建新」的中间态会让 Java 读不到工序/路线 ⇒ 建单全 fail-closed。
-- ⇒ 拆法 = **P1 只新增 → P2 切消费 → P3 前端**。
--
-- ## ⚠️ 硬约束（违反即返工）
-- ① **不改** `production_operations` / `production_routings` 的任何列、行、索引。
--    新路线**不能**写进 `production_routings`：它的 `curtain_type` / `craft` 是 `NOT NULL`，
--    且唯一索引 `uk_production_routings_tenant_type_craft` 会与既有 `布帘×韩褶` 行**直接冲突**。
-- ② 迁移号 **V70**（V68/V69 已被并行包占用）。已发布迁移**不可改**：`MigrationRunner` 的台账
--    `schema_migrations` 按**文件名**记、已应用的文件**整份跳过** ⇒ 改 V54/V58/V59 只对全新库
--    生效、存量环境永远拿不到 = 「CI 全绿、功能静默缺失」。
-- ③ 数据**只种 `tenant_id = 1`**（与 V54/V56/V58/V59 先例逐字一致）；非 1 号租户由**开租播种
--    路径**承接（P2 范围）。
--
-- ## 三张新表
-- | 表 | 角色 | 唯一键 |
-- |---|---|---|
-- | `production_operation_positions` | 部位价目 + 适用性（28 道逻辑工序 × 3 部位 = **84 行**） | `(tenant_id, logical_name, position) WHERE deleted = 0` |
-- | `production_route_templates` | 具名路线（主线序列 + 适用帘种 + 默认标记；**1 行**） | `(tenant_id, name)`；另 `(tenant_id) WHERE is_default AND deleted = 0`（每租户 ≤1 默认） |
-- | `production_route_rules` | 规则表（工艺变体 10 + 特殊选项 16 = **26 行**） | `(tenant_id, trigger_kind, trigger_value, COALESCE(position,''), action, operation)` |
--
-- ## 种子数据（冻结；母单 #4423 §二 已实证 **9/9 逐字重建**）
-- · `production_operation_positions`：**84 行**（28 × 3，逐行显式 `applicable`，不留隐式缺省）；
-- · `production_route_templates`：**1 行** —— `窗帘工序路线（默认）`，`is_default = TRUE`，
--   `positions = ["布帘","纱帘","帘头"]`，`mainline` = 落库的 **9 道**（**不含**「工艺槽位」）；
-- · `production_route_rules`：**26 行** = 工艺变体 10（`trigger_kind='craft'`）+ 特殊选项 16
--   （`trigger_kind='option'`，= 旧 `SPECIAL_OPTION_ROUTINGS` **逐条搬迁**，**工序名与锚点都归一
--   为逻辑名** —— `布三边`→`三边`、`布帘车被`→`车被`、`精裁-布`→`精裁`；不归一 ⇒ 锚点在逻辑名
--   序列里找不到 ⇒ 条件工序会**静默追加到末尾**，工序顺序错）。
--
-- ## 单价口径（**不发明任何单价**，可逐条核对）
-- `unit_price` 逐条溯源到既有 `production_operations.unit_price`（= 真值源 `OPERATION_CATALOG`）。
-- 本单实证：同一逻辑工序的**各部位变体单价逐字相同**（7 组变体共 14 道工序两两相等）
-- ⇒ 今天单价是**逻辑工序**的函数，按适用部位展开。本表存在的理由是给真值源 §2【标】
-- 「同一道工序在布/纱/帘头上单价各自不同」**留出载体**，等客户给出分部位价（#4261）再分化。
-- `applicable = FALSE` 的部位行 `unit_price` 落 **NULL**（**明确不做 ⇒ 不报价**；与「没定价」
-- 可区分 —— 这正是 `applicable` 列存在的理由）。
--
-- ## 幂等（`MigrationRunner` 要求所有 SQL 可重复执行）
-- `CREATE TABLE IF NOT EXISTS` / `CREATE UNIQUE INDEX IF NOT EXISTS` / `COMMENT ON` 天然幂等；
-- 种子一律 `ON CONFLICT (id) DO NOTHING`（id 是确定性命名）⇒ 重复执行不产生第二行，也不会
-- 把被软删的行「复活」（软删行仍占主键 ⇒ 冲突即跳过）。
--
-- ## 与真值源的收敛判据（防第二份口径漂移）
-- 本文件是 `app/production/routing.py` 新真值源（`ROUTE_MAINLINE_STEPS` /
-- `OPERATION_POSITION_PRICES` / `ROUTE_RULES`）的**一次快照**，不是第二份真值源。
-- 防漂移由测试守：`tests/unit_ci_workflows/test_production_catalog_seed.py` **按内容**发现本迁移
-- 并把三源（`routing.py` ↔ 本文件 ↔ `docs/sql/schema.sql`）**逐行逐值**比对（改名/改价/加减行即红）。
-- 9/9 逐字重建判据在 `backend/ai-agent-service/tests/test_production/test_route_model_v2.py`。

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 部位价目表（28 道逻辑工序 × 3 部位）
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS production_operation_positions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    logical_name VARCHAR(64) NOT NULL,                -- 逻辑工序名（去部位后缀：精裁/三边/韩褶…）
    position VARCHAR(16) NOT NULL,                    -- 部位：布帘/纱帘/帘头
    unit_price NUMERIC(10,2),                         -- 计件单价（元/单位）；NULL = 该部位明确不做（不报价）
    applicable BOOLEAN NOT NULL DEFAULT TRUE,         -- 该部位是否做这道工序；false = 明确不做（≠「没定价」）
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_operation_positions_tenant_name_position
    ON production_operation_positions (tenant_id, logical_name, position)
    WHERE deleted = 0;

COMMENT ON TABLE production_operation_positions IS
    '部位价目 + 适用性矩阵（V70，issue #4427 = 母单 #4423 P1）。'
    '一行 = 一道**逻辑工序**（去部位后缀，如 精裁/三边/韩褶）× 一个**部位**（布帘/纱帘/帘头）。'
    '旧模型把部位编码进工序名（精裁-布/精裁-纱、布三边/纱三边）⇒ 单价绑在 35 个名字上；'
    '新模型把部位抽出来做矩阵（28 × 3 = 84 行），同一道工序在不同部位可各自定价。';
COMMENT ON COLUMN production_operation_positions.logical_name IS
    '逻辑工序名（去部位后缀）：与 app/production/routing.py 的 OPERATION_LOGICAL_NAMES 值域一致（28 个）。'
    '⚠️ 它**不是** production_operations.name（那边仍是旧名 精裁-布/布三边…，P1 一字不动）。';
COMMENT ON COLUMN production_operation_positions.unit_price IS
    '计件单价（元/单位，单位见 production_operations.unit）。逐条溯源到 production_operations.unit_price'
    '（本单实证：同一逻辑工序的各部位变体单价逐字相同）⇒ **不发明单价**。'
    'applicable = FALSE 的行落 NULL：明确不做 ⇒ 不报价（与「没定价」可区分）。';
COMMENT ON COLUMN production_operation_positions.applicable IS
    '该部位是否做这道工序（V70，issue #4427）：TRUE = 做（实例化保留）；FALSE = **明确不做**（滤掉）。'
    '存在的理由：把「明确不做」与「没定价」在数据上区分开 —— 前者是本列 FALSE，后者是本列 TRUE + unit_price IS NULL。'
    '例：熨烫 只做布帘（纱帘/帘头 applicable=FALSE）；帘头制作 只做帘头。';

INSERT INTO production_operation_positions
    (id, tenant_id, logical_name, position, unit_price, applicable, status)
VALUES
  ('opp-v70-01', 1, '精裁', '布帘', 0.4, TRUE, 'active'),
  ('opp-v70-02', 1, '精裁', '纱帘', 0.4, TRUE, 'active'),
  ('opp-v70-03', 1, '精裁', '帘头', 0.4, TRUE, 'active'),
  ('opp-v70-04', 1, '裁剪', '布帘', 0.4, TRUE, 'active'),
  ('opp-v70-05', 1, '裁剪', '纱帘', 0.4, TRUE, 'active'),
  ('opp-v70-06', 1, '裁剪', '帘头', 0.4, TRUE, 'active'),
  ('opp-v70-07', 1, '三边', '布帘', 0.4, TRUE, 'active'),
  ('opp-v70-08', 1, '三边', '纱帘', 0.4, TRUE, 'active'),
  ('opp-v70-09', 1, '三边', '帘头', 0.4, TRUE, 'active'),
  ('opp-v70-10', 1, '韩褶', '布帘', 0.4, TRUE, 'active'),
  ('opp-v70-11', 1, '韩褶', '纱帘', 0.4, TRUE, 'active'),
  ('opp-v70-12', 1, '韩褶', '帘头', 0.4, TRUE, 'active'),
  ('opp-v70-13', 1, '上车布', '布帘', 0.5, TRUE, 'active'),
  ('opp-v70-14', 1, '上车布', '纱帘', 0.5, TRUE, 'active'),
  ('opp-v70-15', 1, '上车布', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-16', 1, '打孔', '布帘', 0.15, TRUE, 'active'),
  ('opp-v70-17', 1, '打孔', '纱帘', 0.15, TRUE, 'active'),
  ('opp-v70-18', 1, '打孔', '帘头', 0.15, TRUE, 'active'),
  ('opp-v70-19', 1, '拼1次', '布帘', 0.8, TRUE, 'active'),
  ('opp-v70-20', 1, '拼1次', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-21', 1, '拼1次', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-22', 1, '拼2次', '布帘', 1.2, TRUE, 'active'),
  ('opp-v70-23', 1, '拼2次', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-24', 1, '拼2次', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-25', 1, '拼3次', '布帘', 1.6, TRUE, 'active'),
  ('opp-v70-26', 1, '拼3次', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-27', 1, '拼3次', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-28', 1, '花边', '布帘', 0.6, TRUE, 'active'),
  ('opp-v70-29', 1, '花边', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-30', 1, '花边', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-31', 1, '铅坠', '布帘', 0.3, TRUE, 'active'),
  ('opp-v70-32', 1, '铅坠', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-33', 1, '铅坠', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-34', 1, '接高', '布帘', 1.0, TRUE, 'active'),
  ('opp-v70-35', 1, '接高', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-36', 1, '接高', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-37', 1, '帘头制作', '布帘', NULL, FALSE, 'active'),
  ('opp-v70-38', 1, '帘头制作', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-39', 1, '帘头制作', '帘头', 2.0, TRUE, 'active'),
  ('opp-v70-40', 1, '熨烫', '布帘', 0.35, TRUE, 'active'),
  ('opp-v70-41', 1, '熨烫', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-42', 1, '熨烫', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-43', 1, '定型', '布帘', 0.4, TRUE, 'active'),
  ('opp-v70-44', 1, '定型', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-45', 1, '定型', '帘头', 0.4, TRUE, 'active'),
  ('opp-v70-46', 1, '复烫', '布帘', 0.35, TRUE, 'active'),
  ('opp-v70-47', 1, '复烫', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-48', 1, '复烫', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-49', 1, '车被', '布帘', 0.4, TRUE, 'active'),
  ('opp-v70-50', 1, '车被', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-51', 1, '车被', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-52', 1, '外帘打卷', '布帘', 1.0, TRUE, 'active'),
  ('opp-v70-53', 1, '外帘打卷', '纱帘', 1.0, TRUE, 'active'),
  ('opp-v70-54', 1, '外帘打卷', '帘头', 1.0, TRUE, 'active'),
  ('opp-v70-55', 1, '外帘装袋', '布帘', 1.0, TRUE, 'active'),
  ('opp-v70-56', 1, '外帘装袋', '纱帘', 1.0, TRUE, 'active'),
  ('opp-v70-57', 1, '外帘装袋', '帘头', 1.0, TRUE, 'active'),
  ('opp-v70-58', 1, '质检', '布帘', 1.5, TRUE, 'active'),
  ('opp-v70-59', 1, '质检', '纱帘', 1.5, TRUE, 'active'),
  ('opp-v70-60', 1, '质检', '帘头', 1.5, TRUE, 'active'),
  ('opp-v70-61', 1, '外帘发货', '布帘', 1.0, TRUE, 'active'),
  ('opp-v70-62', 1, '外帘发货', '纱帘', 1.0, TRUE, 'active'),
  ('opp-v70-63', 1, '外帘发货', '帘头', 1.0, TRUE, 'active'),
  ('opp-v70-64', 1, '绑带', '布帘', 0.5, TRUE, 'active'),
  ('opp-v70-65', 1, '绑带', '纱帘', 0.5, TRUE, 'active'),
  ('opp-v70-66', 1, '绑带', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-67', 1, '抱枕', '布帘', 2.0, TRUE, 'active'),
  ('opp-v70-68', 1, '抱枕', '纱帘', 2.0, TRUE, 'active'),
  ('opp-v70-69', 1, '抱枕', '帘头', 2.0, TRUE, 'active'),
  ('opp-v70-70', 1, '腰靠垫', '布帘', 2.0, TRUE, 'active'),
  ('opp-v70-71', 1, '腰靠垫', '纱帘', 2.0, TRUE, 'active'),
  ('opp-v70-72', 1, '腰靠垫', '帘头', 2.0, TRUE, 'active'),
  ('opp-v70-73', 1, 'logo条', '布帘', 0.6, TRUE, 'active'),
  ('opp-v70-74', 1, 'logo条', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-75', 1, 'logo条', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-76', 1, '立边', '布帘', 0.5, TRUE, 'active'),
  ('opp-v70-77', 1, '立边', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-78', 1, '立边', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-79', 1, '扣环', '布帘', 0.3, TRUE, 'active'),
  ('opp-v70-80', 1, '扣环', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-81', 1, '扣环', '帘头', NULL, FALSE, 'active'),
  ('opp-v70-82', 1, '防翘扣', '布帘', 0.2, TRUE, 'active'),
  ('opp-v70-83', 1, '防翘扣', '纱帘', NULL, FALSE, 'active'),
  ('opp-v70-84', 1, '防翘扣', '帘头', NULL, FALSE, 'active')
ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 具名路线模板（主线 + 适用帘种 + 默认标记）
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS production_route_templates (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(128) NOT NULL,                       -- 路线总名（用户可命名，如「窗帘工序路线（默认）」）
    is_default BOOLEAN NOT NULL DEFAULT FALSE,        -- 回落链终点；每租户活跃路线中恰好一条
    positions JSONB NOT NULL DEFAULT '[]'::jsonb,     -- 适用帘种集合，如 ["布帘","纱帘","帘头"]
    mainline JSONB NOT NULL DEFAULT '[]'::jsonb,      -- 主线有序工序名（**逻辑名**，不展开工艺变体）
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_route_templates_tenant_name
    ON production_route_templates (tenant_id, name)
    WHERE deleted = 0;
-- 不变式 I2：每租户活跃路线中**恰好一条** is_default（部分唯一索引 ⇒ 第二条默认插不进来）。
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_route_templates_tenant_default
    ON production_route_templates (tenant_id)
    WHERE is_default AND deleted = 0;

COMMENT ON TABLE production_route_templates IS
    '具名工艺路线（V70，issue #4427 = 母单 #4423 P1）。'
    '旧模型：production_routings 用 (curtain_type, craft) 当路线键 ⇒ 9 条「展开快照」，'
    '商家改一道工序要改 8 遍。新模型：路线 = **一条具名主线**（positions 说明它适用哪些帘种）'
    '+ production_route_rules 的变体规则。⚠️ P1 只建新表，旧表 production_routings 一字不动。';
COMMENT ON COLUMN production_route_templates.name IS
    '路线总名（用户可命名）。母单 #4423 裁定 M3：**只改路线总名，工序名不能改**。'
    '唯一键 (tenant_id, name) WHERE deleted = 0 ⇒ 同租户活跃路线不得重名。';
COMMENT ON COLUMN production_route_templates.is_default IS
    '默认路线标记（母单 #4423 裁定 M4）：回落链的终点。'
    '不变式 I1：每租户活跃路线 ≥ 1；I2：活跃路线中**恰好一条** is_default'
    '（由部分唯一索引 uk_production_route_templates_tenant_default 保证 ≤1）。'
    '删除口径：默认路线不可直接删（先设另一条为默认）；最后一条不可删 —— 该口径属 P2（本迁移只建结构与种子）。';
COMMENT ON COLUMN production_route_templates.positions IS
    '适用帘种集合（JSONB 数组，取值域同 production_operation_positions.position：布帘/纱帘/帘头）。'
    '实例化时按订单部位匹配 positions；无匹配则回落 is_default 的那一条。';
COMMENT ON COLUMN production_route_templates.mainline IS
    '主线有序工序名（JSONB 数组，**逻辑工序名**，与 OPERATION_LOGICAL_NAMES 值域一致）。'
    '⚠️ 只存**主线**：工艺变体（韩褶/打孔/穿杆/四爪钩）与特殊选项的增删由 production_route_rules 决定，'
    '不展开进本列 —— 这正是「9 条展开路线 → 1 条主线」的收敛点。'
    '「工艺槽位」不落库（它只表示「打褶那一道插在这里」，由规则表按工艺插入）。';

INSERT INTO production_route_templates
    (id, tenant_id, name, is_default, positions, mainline, status)
VALUES
  ('rt-v70-01', 1, '窗帘工序路线（默认）', TRUE,
   '["布帘", "纱帘", "帘头"]'::jsonb,
   '["精裁", "三边", "熨烫", "定型", "复烫", "车被", "外帘打卷", "外帘装袋", "外帘发货"]'::jsonb,
   'active')
ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 规则表（工艺变体 10 + 特殊选项 16 = 26 条）
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS production_route_rules (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    trigger_kind VARCHAR(24) NOT NULL CHECK (trigger_kind IN ('craft', 'option', 'shaped', 'processing_item')),
    trigger_value VARCHAR(64) NOT NULL,               -- 工艺名 / 特殊选项名（逐字 = ERP 写法；它是 join key）
    position VARCHAR(16),                             -- 部位限定；NULL = 不限
    action VARCHAR(16) NOT NULL CHECK (action IN ('insert', 'remove')),
    operation VARCHAR(64) NOT NULL,                   -- 逻辑工序名（增/删的那一道）
    after_operation VARCHAR(64),                      -- insert 锚点（逻辑工序名）；NULL = 追加末尾
    priority INTEGER NOT NULL DEFAULT 100,            -- **升序生效**（同序按声明顺序）
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
-- 同一触发（+部位限定+动作）对同一道工序只允许一条规则；position 可空 ⇒ 用 COALESCE 折叠 NULL。
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_route_rules_tenant_trigger_operation
    ON production_route_rules (tenant_id, trigger_kind, trigger_value,
                              COALESCE(position, ''), action, operation)
    WHERE deleted = 0;

COMMENT ON TABLE production_route_rules IS
    '工艺路线**规则表**（V70，issue #4427 = 母单 #4423 P1）：触发（工艺/选项/…）× 部位限定 → 增删工序。'
    '形态与既有 SPECIAL_OPTION_ROUTINGS 同构 ⇒ 工艺变体与特殊选项**统一进同一张表**（= #4365 阶段 2 目标）。'
    '26 行 = 工艺变体 10（craft）+ 特殊选项 16（option，旧 SPECIAL_OPTION_ROUTINGS 逐条搬迁）。'
    '⚠️ P1 只建表 + 种行：消费方（Java 实例化 / build_route_v2 接线）在 P2，今天**零消费者**。';
COMMENT ON COLUMN production_route_rules.trigger_kind IS
    '触发类型（V70）：craft = 工艺变体（韩褶/打孔/四爪钩/穿杆/平幔）；option = 下单勾选的特殊选项；'
    'shaped = 是否定型；processing_item = 加工项触发器。'
    '⚠️ P1 **只种 craft / option 两种**（母单冻结的 26 行）—— shaped / processing_item 是表结构预留，'
    '没有种子行；build_route_v2 遇到未实现的触发类型**显式抛错**（不静默忽略）。';
COMMENT ON COLUMN production_route_rules.trigger_value IS
    '触发值。⚠️ **逐字 = ERP 写法**（issue #4389 裁定 R-e）：它是「订单选配 → 车间工序」的 join key，'
    '错一个字 ⇒ 查不到 ⇒ 条件工序静默不加（少发工人钱）。例：一分为二 / 余料带回-布 / 加logo条。';
COMMENT ON COLUMN production_route_rules.position IS
    '部位限定（布帘/纱帘/帘头）；NULL = 不限部位。例：韩褶 在布帘上还要多插一道「上车布」'
    '⇒ 该规则的 position = 布帘（纱帘×韩褶 就不插）。';
COMMENT ON COLUMN production_route_rules.operation IS
    '要增/删的**逻辑工序名**（与 OPERATION_LOGICAL_NAMES 值域一致）。'
    '⚠️ 搬迁旧 SPECIAL_OPTION_ROUTINGS 时必须归一（拼1次-布→拼1次、布帘车被→车被、精裁-布→精裁），'
    '否则锚点在逻辑名序列里找不到 ⇒ 条件工序被静默追加到末尾。';
COMMENT ON COLUMN production_route_rules.after_operation IS
    'insert 的锚点（逻辑工序名）：把 operation 插在它**之后**；锚点不在序列中 ⇒ 追加末尾'
    '（与既有 routing._insert_after 同款）。remove 规则该列为 NULL。';
COMMENT ON COLUMN production_route_rules.priority IS
    '生效顺序（**升序**，同序按声明顺序）。⚠️ 顺序敏感：'
    '「韩褶 + 布帘 insert 上车布 after 韩褶」必须排在「韩褶 insert 韩褶 after 三边」之后，'
    '否则锚点「韩褶」还不存在 ⇒ 上车布被追加到末尾（工序顺序错）。本迁移用 10/20/…/260 的确定序号。';

INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action,
     operation, after_operation, priority, status)
VALUES
  ('rr-v70-01', 1, 'craft', '韩褶', NULL, 'insert', '韩褶', '三边', 10, 'active'),
  ('rr-v70-02', 1, 'craft', '韩褶', '布帘', 'insert', '上车布', '韩褶', 20, 'active'),
  ('rr-v70-03', 1, 'craft', '打孔', NULL, 'insert', '打孔', '三边', 30, 'active'),
  ('rr-v70-04', 1, 'craft', '四爪钩', NULL, 'insert', '上车布', '三边', 40, 'active'),
  ('rr-v70-05', 1, 'craft', '四爪钩', NULL, 'remove', '定型', NULL, 50, 'active'),
  ('rr-v70-06', 1, 'craft', '四爪钩', NULL, 'remove', '复烫', NULL, 60, 'active'),
  ('rr-v70-07', 1, 'craft', '穿杆', NULL, 'remove', '定型', NULL, 70, 'active'),
  ('rr-v70-08', 1, 'craft', '穿杆', NULL, 'remove', '复烫', NULL, 80, 'active'),
  ('rr-v70-09', 1, 'craft', '平幔', NULL, 'insert', '帘头制作', '三边', 90, 'active'),
  ('rr-v70-10', 1, 'craft', '平幔', NULL, 'remove', '复烫', NULL, 100, 'active'),
  ('rr-v70-11', 1, 'option', '拼1次', NULL, 'insert', '拼1次', '三边', 110, 'active'),
  ('rr-v70-12', 1, 'option', '拼2次', NULL, 'insert', '拼2次', '三边', 120, 'active'),
  ('rr-v70-13', 1, 'option', '拼3次', NULL, 'insert', '拼3次', '三边', 130, 'active'),
  ('rr-v70-14', 1, 'option', '加花边', NULL, 'insert', '花边', '三边', 140, 'active'),
  ('rr-v70-15', 1, 'option', '加铅块', NULL, 'insert', '铅坠', '三边', 150, 'active'),
  ('rr-v70-16', 1, 'option', '接高', NULL, 'insert', '接高', '精裁', 160, 'active'),
  ('rr-v70-17', 1, 'option', '双眼皮接高', NULL, 'insert', '接高', '精裁', 170, 'active'),
  ('rr-v70-18', 1, 'option', '余料做绑带', NULL, 'insert', '绑带', '车被', 180, 'active'),
  ('rr-v70-19', 1, 'option', '布绑带', NULL, 'insert', '绑带', '车被', 190, 'active'),
  ('rr-v70-20', 1, 'option', '余料做帘头', NULL, 'insert', '帘头制作', '三边', 200, 'active'),
  ('rr-v70-21', 1, 'option', '抱枕', NULL, 'insert', '抱枕', '外帘打卷', 210, 'active'),
  ('rr-v70-22', 1, 'option', '纱绑带', NULL, 'insert', '绑带', '车被', 220, 'active'),
  ('rr-v70-23', 1, 'option', '加logo条', NULL, 'insert', 'logo条', '三边', 230, 'active'),
  ('rr-v70-24', 1, 'option', '加立边', NULL, 'insert', '立边', '三边', 240, 'active'),
  ('rr-v70-25', 1, 'option', '扣环', NULL, 'insert', '扣环', '三边', 250, 'active'),
  ('rr-v70-26', 1, 'option', '防翘扣', NULL, 'insert', '防翘扣', '三边', 260, 'active')
ON CONFLICT (id) DO NOTHING;
