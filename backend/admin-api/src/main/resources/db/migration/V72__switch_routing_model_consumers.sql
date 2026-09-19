-- 工序路线模型重构 **P2：切消费路径**（issue #4432 = 母单 #4423 的 P2/3）
--
-- ## 一句话
-- 把**消费路径**从旧的「(部位 × 工艺) 展开快照」切到 P1（#4427）建好的新结构；
-- 本迁移负责「切换那一刻存量租户**已有**可读的新结构」+「缺 `craft` 有商户级默认工艺可取」
-- + 「旧规则表退场（软删，不 DROP）」。
--
-- ## 迁移号为什么是 V72
-- V71 已被 P1（#4427）占用。**已发布迁移不可改**：`MigrationRunner` 的台账 `schema_migrations`
-- 按**文件名**记、已应用的文件**整份跳过** ⇒ 改 V71 只对全新库生效、存量环境永远拿不到
-- = 「CI 全绿、功能静默缺失」（issue #4235）。⇒ 一切增量都走本文件。
--
-- ## 🔴 P0：存量租户回填（不做 ⇒ 切换那一刻非 1 号租户全 fail-closed）
-- V71 的种子**只种 `tenant_id = 1`**（与 V54/V56/V58/V59 先例逐字一致）。
-- P2 一旦把消费路径切到新表，`defaultRouteTemplate(tenantId)` 对**任何非 1 号租户**都返回 `null`
-- ⇒ `resolveRoute` T3 fail-closed ⇒ **该租户一张加工单也生成不了（422）**（#4316 同族复发）。
-- ⇒ 本迁移**按租户循环**（`FROM tenants` 范式，同 V29/V32/V43）为**每一个活跃租户**回填三张表。
--
-- **口径（判据 17）：不是「从 1 号租户复制」** —— 1 号租户的价可能已被客户改过，
-- 复刻会把改后的价当成别人的初始价（静默错价 = 错发工资）。本迁移的口径是：
--   · **价目/适用性** ← `production_operation_positions` 的**规范矩阵**（84 行，P1 冻结、逐条溯源到
--     `production_operations.unit_price`；真值源 `routing.py::OPERATION_POSITION_PRICES`）；
--   · **主线/规则/部位集合** ← **该租户自己的** `production_operations`（经逻辑名归一后过滤）——
--     租户库里没有的工序不进他的主线，也不给他种引用不到工序的规则（否则规则永远插不进来，
--     是「规则已落库但永不生效」的黑洞）。
--
-- **幂等（判据 16）**：`ON CONFLICT … DO NOTHING`（`bootstrap-first` 会让迁移在建好终态的库上
-- 再跑一遍）；已在 V71 里种过的 1 号租户**天然跳过已存在行**（同 id 冲突），不产生第二份、不覆盖。
--
-- ## 🔴 商户级默认工艺（规格订正：缺 `craft` **不能**从默认路线取）
-- 重构后**路线模板没有工艺维**（工艺已降为规则触发键）⇒ 缺 `craft` 时「从默认路线取对应维」
-- **在实现上不成立**（母单 #4423 评论「🔴 规格订正」）。⇒ 本迁移建 `production_crafts`
-- （`is_default`），为**每个活跃租户**恰好种一条默认工艺。**形态取②**（新表 + `is_default`）：
-- 形态①「规则表里显式登记一条默认」会需要给 `trigger_kind` 的 CHECK 加一个非业务取值
-- （`craft`/`option`/`shaped`/`processing_item` 之外），语义更绕且与「触发键」概念混淆。
-- ⇒ 缺 `craft` 时取该租户默认工艺，**不写死常量 `韩褶`**（商户只做打孔时会插错工序
-- + 算错计件系数 = 错发工资）。
--
-- ## 🔴 旧规则表退场（§六·补；软删，**表先不 DROP**）
-- P1 已把特殊选项规则**复制**进 `production_route_rules`，但旧的 `production_option_routings` /
-- `production_option_factors` 仍在且有真实消费者 ⇒ 不收口就是**同一份规则两个真值源**。
-- 本迁移：① 规则表补 `factor` 列（V71 **没有**该列）+ 放宽 `action` CHECK 为含 `'factor'`
-- + `operation` 改为可空（平摊档）；② 把旧 `production_option_factors` 的档位**搬进**规则表
-- （`action='factor'`；只软删不搬迁 = 静默丢掉计件系数）；③ 旧两表活跃行软删为 0。
-- **表本身不 DROP**（可回滚），DROP 留待后续独立迁移（届时须确认零消费者）。
--
-- ## 回滚 SQL（保留于注释；按需手工执行）
-- ```sql
-- -- ① 旧规则表复活（软删回退）
-- UPDATE production_option_routings SET deleted = 0 WHERE id LIKE 'por-%';
-- UPDATE production_option_factors  SET deleted = 0 WHERE id LIKE 'pof-%';
-- -- ② 规则表回退到 V71 形态（先删本迁移新增的 factor 档）
-- DELETE FROM production_route_rules WHERE action = 'factor';
-- ALTER TABLE production_route_rules DROP CONSTRAINT IF EXISTS production_route_rules_action_check;
-- ALTER TABLE production_route_rules ADD CONSTRAINT production_route_rules_action_check
--     CHECK (action IN ('insert','remove'));
-- ALTER TABLE production_route_rules ALTER COLUMN operation SET NOT NULL;
-- ALTER TABLE production_route_rules DROP COLUMN IF EXISTS factor;
-- -- ③ 默认工艺表回退
-- DROP TABLE IF EXISTS production_crafts;
-- -- ④ 回填行回退（只删本迁移生成的 id 前缀，不碰 V71 的 opp-v70-* / rt-v70-* / rr-v70-*）
-- DELETE FROM production_operation_positions WHERE id LIKE 'opp-v72-%';
-- DELETE FROM production_route_templates      WHERE id LIKE 'rt-v72-%';
-- DELETE FROM production_route_rules          WHERE id LIKE 'rr-v72-%';
-- ```
--
-- ## 与真值源的收敛判据（防第二份口径漂移）
-- 本文件里的**逻辑名归一 CASE**（旧工序名 → 逻辑工序名）是 `routing.py::OPERATION_LOGICAL_NAMES`
-- 的一次快照，由 `tests/unit_ci_workflows/test_routing_model_p2_consumers.py` +
-- `test_production_catalog_seed.py` 按内容发现并逐行比对（改名/加减行即红）。

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 规则表补列：`factor`（计件系数）+ 放宽 `action` CHECK + `operation` 可空
-- ══════════════════════════════════════════════════════════════════════════════════════
-- V71 的 `production_route_rules` 只有 insert/remove，**没有** `factor` 列；而
-- `OPTION_FACTOR_SCOPES`（计件系数：一分为二 → ×1.7，含 operation_name / curtain_type 限定档、
-- **同选项内后档覆盖前档**）必须有地方存。**不允许**把系数留在旧表（那就是第二份口径）。
ALTER TABLE production_route_rules ADD COLUMN IF NOT EXISTS factor NUMERIC(6,3);

-- 放宽 `action` 的 CHECK：允许 'factor'（系数档）。先 DROP 再 ADD（幂等）。
ALTER TABLE production_route_rules DROP CONSTRAINT IF EXISTS production_route_rules_action_check;
ALTER TABLE production_route_rules
    ADD CONSTRAINT production_route_rules_action_check
    CHECK (action IN ('insert', 'remove', 'factor'));

-- `operation` 改为可空：**平摊档**（`operation_name` 为空 = 该部位全部工序）在规则表里就是
-- `operation IS NULL`。语义与 `OPTION_FACTOR_SCOPES` 的「`operation_name` 为空 ⇒ 平摊」逐字一致。
ALTER TABLE production_route_rules ALTER COLUMN operation DROP NOT NULL;

-- 唯一键必须把 `operation` 的 NULL 折叠（同 V71 对 `position` 的 `COALESCE` 处理），
-- 否则「同一触发 + 同一部位限定 + factor 档」会有多行 `operation IS NULL`（Postgres 里 NULL 互不相等）。
DROP INDEX IF EXISTS uk_production_route_rules_tenant_trigger_operation;
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_route_rules_tenant_trigger_operation
    ON production_route_rules (tenant_id, trigger_kind, trigger_value,
                              COALESCE(position, ''), action, COALESCE(operation, ''))
    WHERE deleted = 0;

COMMENT ON COLUMN production_route_rules.factor IS
    '计件系数（V72，issue #4432 = 母单 #4423 P2）。仅 action = ''factor'' 时有值：'
    '该档把命中工序的计件系数**覆盖**为它（同一触发内按 priority 升序、**后档覆盖前档**，'
    '与 routing.py::factor_for 的「例外档盖住平摊档」逐字同口径）；多个加系数选项之间**相乘**。'
    '⚠️ 只认规则表登记过的选项：未登记的触发**不得**悄悄改系数（查不到档 ⇒ 保持 1.0）。';
COMMENT ON COLUMN production_route_rules.operation IS
    '要增/删/覆盖系数的**逻辑工序名**（与 OPERATION_LOGICAL_NAMES 值域一致）。'
    'V72 起**可空**：action = ''factor'' 且 operation IS NULL = **平摊档**'
    '（该触发对该部位的全部工序生效），对应 OPTION_FACTOR_SCOPES 的 operation_name 为空档。'
    'action = ''insert''/''remove'' 时仍必填（本迁移末尾加 CHECK 兜底）。';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 商户级默认工艺（`production_crafts`）—— 缺 `craft` 的兜底来源
-- ══════════════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS production_crafts (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id),
    name VARCHAR(64) NOT NULL,                       -- 工艺名（逐字 = ERP 写法；与规则表 trigger_value 同词表）
    is_default BOOLEAN NOT NULL DEFAULT FALSE,       -- 商户级默认工艺；每租户活跃行中**恰好一条**
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_crafts_tenant_name
    ON production_crafts (tenant_id, name)
    WHERE deleted = 0;
-- 不变式：每租户活跃工艺中**恰好一条** is_default（部分唯一索引 ⇒ 第二条默认插不进来）。
CREATE UNIQUE INDEX IF NOT EXISTS uk_production_crafts_tenant_default
    ON production_crafts (tenant_id)
    WHERE is_default AND deleted = 0;

COMMENT ON TABLE production_crafts IS
    '工艺词表 + **商户级默认工艺**（V72，issue #4432 = 母单 #4423 P2）。'
    '存在的理由（规格订正，母单 #4423 评论「🔴 规格订正」）：重构后路线模板**没有工艺维**'
    '（工艺已降为 production_route_rules 的触发键）⇒ 缺 `craft` 时「从默认路线取对应维」'
    '**在实现上不成立**。而工艺决定「插入哪道工序 + 计件系数」⇒ 猜错 = 算错工人工资。'
    '⇒ 改为**一次配置、全局确定**的商户级默认工艺，不依赖每单的字符串匹配。';
COMMENT ON COLUMN production_crafts.is_default IS
    '商户级默认工艺标记（V72，issue #4432）：缺 `craft` 时的兜底来源（判据 22/23）。'
    '不变式：每租户活跃工艺中**恰好一条**（部分唯一索引 uk_production_crafts_tenant_default 保证 ≤1）。'
    '⚠️ 缺默认工艺时**不得静默取常量**：调用方要么 fail-closed，要么取种子默认值 + '
    '在 route_source 上显式标记（判据 23）。';

-- 每个活跃租户恰好一条默认工艺。
-- 口径：**优先 `韩褶`**（V54 起的事实默认、`routing.py::DEFAULT_CRAFT`，也是绝大多数商户的主工艺）
-- —— 但只在该租户工序库里确实有「韩褶」这道工序时取它；否则退到规范工艺词表里**第一个**该租户
-- 确实有工序的工艺；一个都没有（空库租户）⇒ 落 `韩褶` 作为种子默认。
-- ⚠️ 绝不静默取常量：这里的取值会落库、可在「工艺配置」里改（判据 23 要求「不得静默」）。
INSERT INTO production_crafts (id, tenant_id, name, is_default, status)
SELECT 'pc-v72-' || t.id, t.id,
       COALESCE(
           (SELECT c.name
              FROM unnest(ARRAY['韩褶', '打孔', '四爪钩', '穿杆', '平幔']) WITH ORDINALITY AS c(name, ord)
             WHERE EXISTS (
                 SELECT 1 FROM production_operations o
                  WHERE o.tenant_id = t.id AND o.deleted = 0 AND o.status = 'active'
                    AND (CASE
                             WHEN o.name LIKE '%-布' THEN left(o.name, length(o.name) - 2)
                             WHEN o.name LIKE '%-纱' THEN left(o.name, length(o.name) - 2)
                             WHEN o.name = '布三边' THEN '三边'
                             WHEN o.name = '纱三边' THEN '三边'
                             WHEN o.name = '布帘车被' THEN '车被'
                             WHEN o.name = '帘头制作' THEN '帘头制作'
                             WHEN o.name = '上车布-布' THEN '上车布'
                             WHEN o.name = '上车布-纱' THEN '上车布'
                             ELSE o.name END) = c.name)
             ORDER BY c.ord LIMIT 1),
           '韩褶'),
       TRUE, 'active'
  FROM tenants t
 WHERE t.deleted = 0
ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 按租户回填 `production_operation_positions`（部位价目 + 适用性）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 口径：规范矩阵（84 行）落到**每个活跃租户**；`applicable` / `unit_price` 逐字取规范矩阵
-- （P1 已实证「同一逻辑工序的各部位变体单价逐字相同」⇒ 不发明单价）。
-- id 用 `opp-v72-<tenant>-<logical>-<position>` 的确定性命名（幂等 + 可回滚）。
-- ⚠️ 三重去重：① `ON CONFLICT (id)`；② `NOT EXISTS` 按**业务唯一键** `(tenant_id, logical_name, position)`
--    —— 1 号租户在 V71 已种过同一批（id 是 `opp-v70-*`），只按 id 去重会让它**重复一份**
--    （V71 的部分唯一索引 `uk_production_operation_positions_tenant_name_position` 会当场报错，
--    而"绕过索引"的写法会造出重复价目行 ⇒ 取价不确定）；③ 租户自己已有该 `(逻辑工序, 部位)` 行则跳过
--    （不覆盖商家改过的价 —— 与「不回填覆盖」同口径）。
INSERT INTO production_operation_positions
    (id, tenant_id, logical_name, position, unit_price, applicable, status)
SELECT 'opp-v72-' || t.id || '-' || p.logical_name || '-' || p.position,
       t.id, p.logical_name, p.position, p.unit_price, p.applicable, 'active'
  FROM tenants t
  JOIN production_operation_positions p
    ON p.tenant_id = 1 AND p.deleted = 0 AND p.id LIKE 'opp-v70-%'
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_operation_positions e
        WHERE e.tenant_id = t.id AND e.logical_name = p.logical_name
          AND e.position = p.position AND e.deleted = 0)
ON CONFLICT (id) DO NOTHING;

COMMENT ON COLUMN production_operation_positions.unit_price IS
    '计件单价（元/单位，单位见 production_operations.unit）。逐条溯源到 production_operations.unit_price'
    '（P1 实证：同一逻辑工序的各部位变体单价逐字相同）⇒ **不发明单价**。'
    'applicable = FALSE 的行落 NULL：明确不做 ⇒ 不报价（与「没定价」可区分）。'
    '⚠️ V72（issue #4432）按租户回填本表：口径 = 规范矩阵（不是从 1 号租户复制 —— 判据 17）。';

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 按租户回填 `production_route_templates`（具名默认路线）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- `mainline` = 该租户工序库归一后的逻辑名序列 ∩ 规范主线顺序；`positions` = 规范三部位
-- （与 V71 种子的 1 号租户行逐字一致 ⇒ 1 号租户天然跳过，不产生第二份）。
-- ⚠️ 规范主线顺序（9 道，不含「工艺槽位」）来自 routing.py::ROUTE_MAINLINE_STEPS（P1 冻结）。
INSERT INTO production_route_templates
    (id, tenant_id, name, is_default, positions, mainline, status)
SELECT 'rt-v72-' || t.id, t.id, '窗帘工序路线（默认）', TRUE,
       '["布帘", "纱帘", "帘头"]'::jsonb,
       COALESCE(
           (SELECT jsonb_agg(s.step ORDER BY s.ord)
              FROM unnest(ARRAY['精裁', '三边', '熨烫', '定型', '复烫', '车被',
                                '外帘打卷', '外帘装袋', '外帘发货']) WITH ORDINALITY AS s(step, ord)
             WHERE s.step IN (
                 SELECT CASE
                     WHEN o.name LIKE '%-布' THEN left(o.name, length(o.name) - 2)
                     WHEN o.name LIKE '%-纱' THEN left(o.name, length(o.name) - 2)
                     WHEN o.name = '布三边' THEN '三边'
                     WHEN o.name = '纱三边' THEN '三边'
                     WHEN o.name = '布帘车被' THEN '车被'
                     WHEN o.name = '帘头制作' THEN '帘头制作'
                     WHEN o.name = '上车布-布' THEN '上车布'
                     WHEN o.name = '上车布-纱' THEN '上车布'
                     ELSE o.name END
                   FROM production_operations o
                  WHERE o.tenant_id = t.id AND o.deleted = 0 AND o.status = 'active')),
           '["精裁", "三边", "熨烫", "定型", "复烫", "车被", "外帘打卷", "外帘装袋", "外帘发货"]'::jsonb),
       'active'
  FROM tenants t
 WHERE t.deleted = 0
   -- 业务唯一键 `(tenant_id, name) WHERE deleted = 0`：1 号租户在 V71 已有同名路线（`rt-v70-01`），
   -- 只按 id 去重会撞 `uk_production_route_templates_tenant_name` ⇒ 这里按业务键去重（不覆盖商家改名/改序列）。
   AND NOT EXISTS (
       SELECT 1 FROM production_route_templates e
        WHERE e.tenant_id = t.id AND e.name = '窗帘工序路线（默认）' AND e.deleted = 0)
ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑤ 按租户回填 `production_route_rules`（工艺变体 10 + 特殊选项 16 + 计件系数档）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 工艺变体（`trigger_kind='craft'`，10 条 = V71 逐条搬迁，工序名与锚点都是**逻辑名**）；
-- ② 特殊选项（`trigger_kind='option'`，16 条 = 旧 SPECIAL_OPTION_ROUTINGS 逐条搬迁，同样归一到逻辑名）。
-- 过滤：该租户工序库里**归一后存在**该逻辑工序才种（否则规则永远插不进来 = 黑洞）。
INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action, operation, after_operation, priority, status)
SELECT 'rr-v72-' || t.id || '-' || r.rid, t.id, r.trigger_kind, r.trigger_value,
       r.position, r.action, r.operation, r.after_operation, r.priority, 'active'
  FROM tenants t
  JOIN (VALUES
      ('01', 'craft', '韩褶', NULL, 'insert', '韩褶', '三边', 10),
      ('02', 'craft', '韩褶', '布帘', 'insert', '上车布', '韩褶', 20),
      ('03', 'craft', '打孔', NULL, 'insert', '打孔', '三边', 30),
      ('04', 'craft', '四爪钩', NULL, 'insert', '上车布', '三边', 40),
      ('05', 'craft', '四爪钩', NULL, 'remove', '定型', NULL, 50),
      ('06', 'craft', '四爪钩', NULL, 'remove', '复烫', NULL, 60),
      ('07', 'craft', '穿杆', NULL, 'remove', '定型', NULL, 70),
      ('08', 'craft', '穿杆', NULL, 'remove', '复烫', NULL, 80),
      ('09', 'craft', '平幔', NULL, 'insert', '帘头制作', '三边', 90),
      ('10', 'craft', '平幔', NULL, 'remove', '复烫', NULL, 100),
      ('11', 'option', '拼1次', NULL, 'insert', '拼1次', '三边', 110),
      ('12', 'option', '拼2次', NULL, 'insert', '拼2次', '三边', 120),
      ('13', 'option', '拼3次', NULL, 'insert', '拼3次', '三边', 130),
      ('14', 'option', '加花边', NULL, 'insert', '花边', '三边', 140),
      ('15', 'option', '加铅块', NULL, 'insert', '铅坠', '三边', 150),
      ('16', 'option', '接高', NULL, 'insert', '接高', '精裁', 160),
      ('17', 'option', '双眼皮接高', NULL, 'insert', '接高', '精裁', 170),
      ('18', 'option', '余料做绑带', NULL, 'insert', '绑带', '车被', 180),
      ('19', 'option', '布绑带', NULL, 'insert', '绑带', '车被', 190),
      ('20', 'option', '余料做帘头', NULL, 'insert', '帘头制作', '三边', 200),
      ('21', 'option', '抱枕', NULL, 'insert', '抱枕', '外帘打卷', 210),
      ('22', 'option', '纱绑带', NULL, 'insert', '绑带', '车被', 220),
      ('23', 'option', '加logo条', NULL, 'insert', 'logo条', '三边', 230),
      ('24', 'option', '加立边', NULL, 'insert', '立边', '三边', 240),
      ('25', 'option', '扣环', NULL, 'insert', '扣环', '三边', 250),
      ('26', 'option', '防翘扣', NULL, 'insert', '防翘扣', '三边', 260)
  ) AS r(rid, trigger_kind, trigger_value, position, action, operation, after_operation, priority)
    ON TRUE
 WHERE t.deleted = 0
   AND EXISTS (
       SELECT 1 FROM production_operations o
        WHERE o.tenant_id = t.id AND o.deleted = 0 AND o.status = 'active'
          AND (CASE
                   WHEN o.name LIKE '%-布' THEN left(o.name, length(o.name) - 2)
                   WHEN o.name LIKE '%-纱' THEN left(o.name, length(o.name) - 2)
                   WHEN o.name = '布三边' THEN '三边'
                   WHEN o.name = '纱三边' THEN '三边'
                   WHEN o.name = '布帘车被' THEN '车被'
                   WHEN o.name = '帘头制作' THEN '帘头制作'
                   WHEN o.name = '上车布-布' THEN '上车布'
                   WHEN o.name = '上车布-纱' THEN '上车布'
                   ELSE o.name END) = r.operation)
   -- 业务唯一键 `(tenant_id, trigger_kind, trigger_value, COALESCE(position,''), action, COALESCE(operation,''))`
   -- ⇒ 1 号租户在 V71 已种过同一批 26 条（`rr-v70-*`），只按 id 去重会撞唯一索引。
   AND NOT EXISTS (
       SELECT 1 FROM production_route_rules e
        WHERE e.tenant_id = t.id AND e.deleted = 0
          AND e.trigger_kind = r.trigger_kind AND e.trigger_value = r.trigger_value
          AND COALESCE(e.position, '') = COALESCE(r.position, '')
          AND e.action = r.action AND e.operation = r.operation)
ON CONFLICT (id) DO NOTHING;

-- ③ 计件系数档（`action='factor'`）—— 旧 `production_option_factors` 的档位**搬进**规则表。
-- 「同选项内后档覆盖前档」由 `priority` 升序 + 后写覆盖保证（`sort_order` 是旧表的顺序位，
-- 直接映射为 `priority`；无 `sort_order` 的行落默认 100）。
-- `operation_name` 为空 = **平摊档**（`operation` 落 NULL）；非空 = 逐工序例外档（归一为逻辑名）。
INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action, operation, after_operation,
     priority, factor, status)
SELECT 'rr-v72-' || t.id || '-f-' || f.id, t.id, 'option', f.option_name, NULL, 'factor',
       CASE
           WHEN f.operation_name IS NULL THEN NULL
           WHEN f.operation_name LIKE '%-布' THEN left(f.operation_name, length(f.operation_name) - 2)
           WHEN f.operation_name LIKE '%-纱' THEN left(f.operation_name, length(f.operation_name) - 2)
           WHEN f.operation_name = '布三边' THEN '三边'
           WHEN f.operation_name = '纱三边' THEN '三边'
           WHEN f.operation_name = '布帘车被' THEN '车被'
           WHEN f.operation_name = '帘头制作' THEN '帘头制作'
           WHEN f.operation_name = '上车布-布' THEN '上车布'
           WHEN f.operation_name = '上车布-纱' THEN '上车布'
           ELSE f.operation_name END,
       NULL,
       COALESCE(f.sort_order, 100),
       f.factor,
       'active'
  FROM tenants t
  JOIN production_option_factors f ON f.tenant_id = t.id AND f.deleted = 0
 WHERE t.deleted = 0
   -- 业务唯一键同 ⑤① 的形态（`COALESCE(operation,'')` 折叠平摊档的 NULL）。
   AND NOT EXISTS (
       SELECT 1 FROM production_route_rules e
        WHERE e.tenant_id = t.id AND e.deleted = 0
          AND e.trigger_kind = 'option' AND e.trigger_value = f.option_name
          AND e.position IS NULL AND e.action = 'factor'
          AND COALESCE(e.operation, '') = COALESCE(
              CASE
                  WHEN f.operation_name IS NULL THEN NULL
                  WHEN f.operation_name LIKE '%-布' THEN left(f.operation_name, length(f.operation_name) - 2)
                  WHEN f.operation_name LIKE '%-纱' THEN left(f.operation_name, length(f.operation_name) - 2)
                  WHEN f.operation_name = '布三边' THEN '三边'
                  WHEN f.operation_name = '纱三边' THEN '三边'
                  WHEN f.operation_name = '布帘车被' THEN '车被'
                  WHEN f.operation_name = '帘头制作' THEN '帘头制作'
                  WHEN f.operation_name = '上车布-布' THEN '上车布'
                  WHEN f.operation_name = '上车布-纱' THEN '上车布'
                  ELSE f.operation_name END, ''))
ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑥ 旧规则表退场（软删；**表先不 DROP**，可回滚）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 已被 `production_route_rules` 取代（issue #4423 P2 / #4432）。软删而非 DELETE：
-- 保留审计与回滚能力；DROP 留待后续独立迁移（届时须确认零消费者）。
UPDATE production_option_routings
   SET deleted = 1, updated_at = NOW()
 WHERE deleted = 0;

UPDATE production_option_factors
   SET deleted = 1, updated_at = NOW()
 WHERE deleted = 0;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⑦ 兜底 CHECK：insert / remove 的 `operation` 仍必填（只有 factor 档可空）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE production_route_rules DROP CONSTRAINT IF EXISTS production_route_rules_operation_required_check;
ALTER TABLE production_route_rules
    ADD CONSTRAINT production_route_rules_operation_required_check
    CHECK (action = 'factor' OR operation IS NOT NULL);

ALTER TABLE production_route_rules DROP CONSTRAINT IF EXISTS production_route_rules_factor_present_check;
ALTER TABLE production_route_rules
    ADD CONSTRAINT production_route_rules_factor_present_check
    CHECK (action <> 'factor' OR factor IS NOT NULL);
