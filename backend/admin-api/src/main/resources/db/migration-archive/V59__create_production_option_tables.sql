-- 特殊选项 → 条件工序 / 计件系数（issue #4230 Java 侧，v1a）
--
-- ## 背景（取证事实：整条链「设计过但从未接线」）
-- `processing_position_operations.factor` 列自 V49 就存在（注释原文「特殊选项计件系数（如 一分二 ×1.7）」），
-- 计件公式（`ProductionService.aggregate`）也真的乘它，但 `buildPositionPayload` **从不 put factor**
-- ⇒ 落库恒 1.00（实测库里每行都是「系数=1.00」）⇒ 特殊选项对计件工资**零影响** = 少发工人钱。
-- 另一半断链在 ai-agent 侧：`routing.py` 有映射，却「零运行时消费者」，且订单侧从不携带 specialOptions。
--
-- ## 本迁移建的两张表（真值源 = ai-agent 已合并的 `app/production/routing.py`）
-- ① `production_option_routings`：选项 → **条件工序**（插在 `after_operation` 之后）
--    —— 对应 `SPECIAL_OPTION_ROUTINGS`（16 项）；
-- ② `production_option_factors`：选项 → **计件系数**
--    —— 对应 `OPTION_FACTOR_SCOPES`（v1 只种「一分二 ⇒ ×1.7 / 该部位全部工序」一个**实证**档）。
--
-- **不种 `NON_PIECEWORK_OPTIONS`**（余料带回(布)/(纱)）：它们在真值源里是**显式登记的「不计件」**，
-- 不是「忘了映射」；落进本表会把它变成「有映射但系数 1」——两种语义在数据上又混成一种。
--
-- `operation_name` 可空（NULL = 该部位**全部**工序）是**有意留的档位**，不是偷懒：
-- issue #4230 §2.4 的逐工序细算档（车位 ×2.0 / 后道 ×1.0 / 裁剪 ×1.2）是**纯推算**，
-- 而 ×1.7 是唯一**实证**值（真值源 §4 + 行业 ERP）⇒ **不拿推算值覆盖实证值**，v1 不启用、不种值；
-- 结构留着，等客户确认后再细化（不把路堵死）。
--
-- ## 幂等（MigrationRunner 要求所有 SQL 可重复执行）
-- 建表/索引 `IF NOT EXISTS`；种子 `ON CONFLICT (id) DO NOTHING`（冲突目标 = 主键，
-- 因为唯一索引的冲突目标带表达式，不便作为 `ON CONFLICT` 推断目标）。
--
-- ## 三源收敛（防第二份口径漂移）
-- 本文件是 Python 常量的**一次快照**，不是第二份真值源。防漂移由测试守：
-- `backend/admin-api/src/test/java/com/migao/admin/migration/ProductionOptionRoutingMigrationTest.java`
-- 逐行解析本文件的 VALUES 与 `SPECIAL_OPTION_ROUTINGS` / `OPTION_FACTOR_SCOPES` 比对
-- （改名/改值/加减选项即红），并与 `docs/sql/schema.sql` 的终态比对。

-- ── ① 选项 → 条件工序（插在 after_operation 之后；sort_order 与真值源字典序一致）──
CREATE TABLE IF NOT EXISTS production_option_routings (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    option_name VARCHAR(32) NOT NULL,                -- 特殊选项名（真值源 §1 的 19 项之一）
    operation_name VARCHAR(64) NOT NULL,             -- 条件工序名（production_operations.name）
    after_operation VARCHAR(64) NOT NULL,            -- 插在它之后（routing.py `_insert_after` 的锚点）
    sort_order INT NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'active',    -- active / disabled
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_option_routings_tenant_option_op
    ON production_option_routings (tenant_id, option_name, operation_name)
    WHERE deleted = 0;
COMMENT ON TABLE production_option_routings IS
    '特殊选项 → 条件工序（V59，issue #4230）：实例化时把 operation_name 插到 after_operation 之后；真值源 = routing.py SPECIAL_OPTION_ROUTINGS';
COMMENT ON COLUMN production_option_routings.after_operation IS
    '锚点工序名（不是序号）：锚点不在该部位路线中时按真值源口径追加到末尾（routing.py _insert_after 同款）';

-- ── ② 选项 → 计件系数（operation_name NULL = 该部位全部工序）──
CREATE TABLE IF NOT EXISTS production_option_factors (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    option_name VARCHAR(32) NOT NULL,
    operation_name VARCHAR(64),                      -- NULL = 该部位全部工序（平摊档）；非空 = 逐工序例外档
    factor NUMERIC(6,2) NOT NULL DEFAULT 1,          -- 乘在工序实例 factor 上
    source VARCHAR(16) NOT NULL DEFAULT '推算',       -- 实证 / 推算（真值源标注口径，商家可配版本化）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
-- 唯一性用**表达式索引**（COALESCE(operation_name,'')）：NULL 在普通唯一索引里互不相等，
-- 不加 COALESCE 就能插进多行「同选项同平摊档」⇒ 系数取值不确定（静默失真）。
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_option_factors_tenant_option_op
    ON production_option_factors (tenant_id, option_name, COALESCE(operation_name, ''))
    WHERE deleted = 0;
COMMENT ON TABLE production_option_factors IS
    '特殊选项 → 计件系数（V59，issue #4230）：operation_name NULL = 该部位全部工序（平摊档），非空 = 逐工序例外档（例外档盖住平摊档）；真值源 = routing.py OPTION_FACTOR_SCOPES';
COMMENT ON COLUMN production_option_factors.operation_name IS
    'NULL = 该部位全部工序（v1 只种这一档）；结构保留逐工序档位是为了不把路堵死（issue #4230 §2.4，待客户确认后再细化）';

-- ── 种子（tenant_id=1；逐字抄自 routing.py，**不自行另定值**）──
INSERT INTO production_option_routings
    (id, tenant_id, option_name, operation_name, after_operation, sort_order, status)
VALUES
  ('opt-rt-01', 1, '拼1次',      '拼1次-布',  '布三边',   1, 'active'),
  ('opt-rt-02', 1, '拼2次',      '拼2次-布',  '布三边',   2, 'active'),
  ('opt-rt-03', 1, '拼3次',      '拼3次-布',  '布三边',   3, 'active'),
  ('opt-rt-04', 1, '加花边',     '花边-布',   '布三边',   4, 'active'),
  ('opt-rt-05', 1, '加铅块',     '铅坠-布',   '布三边',   5, 'active'),
  ('opt-rt-06', 1, '接高',       '接高-布',   '精裁-布',  6, 'active'),
  ('opt-rt-07', 1, '双眼皮接高', '接高-布',   '精裁-布',  7, 'active'),
  ('opt-rt-08', 1, '余料做绑带', '绑带-布',   '布帘车被', 8, 'active'),
  ('opt-rt-09', 1, '布绑带',     '绑带-布',   '布帘车被', 9, 'active'),
  ('opt-rt-10', 1, '余料做帘头', '帘头制作',  '布三边',  10, 'active'),
  ('opt-rt-11', 1, '抱枕',       '抱枕',      '外帘打卷', 11, 'active'),
  ('opt-rt-12', 1, '纱绑带',     '绑带-纱',   '布帘车被', 12, 'active'),
  ('opt-rt-13', 1, '加logo条',   'logo条-布', '布三边',  13, 'active'),
  ('opt-rt-14', 1, '加立边',     '立边-布',   '布三边',  14, 'active'),
  ('opt-rt-15', 1, '扣环',       '扣环-布',   '布三边',  15, 'active'),
  ('opt-rt-16', 1, '防翘扣',     '防翘扣-布', '布三边',  16, 'active')
ON CONFLICT (id) DO NOTHING;

INSERT INTO production_option_factors
    (id, tenant_id, option_name, operation_name, factor, source)
VALUES
  ('opt-fa-01', 1, '一分二', NULL, 1.7, '实证')
ON CONFLICT (id) DO NOTHING;
