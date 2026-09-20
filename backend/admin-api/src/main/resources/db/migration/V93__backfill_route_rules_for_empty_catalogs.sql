-- 补种「规则被 `EXISTS (production_operations …)` 整批静默跳过」的租户的**出厂规则**
-- （issue #4714，P0 静默缺陷·第二层根因的**规则半边**）。
--
-- ## 一句话
-- `V72__switch_routing_model_consumers.sql` ⑤ 的按租户规则回填带了一道**工序库护栏**
-- （`EXISTS (SELECT 1 FROM production_operations … 归一后 = r.operation)`）⇒ 租户的工序库为空时
-- **整批规则被静默跳过**（`V84` 的 3 条 `processing_item` 规则同款护栏、同款后果）。
-- ⇒ 韩褶 / 打孔 / 四爪钩 / 穿杆 / 平幔 / 特殊选项（拼几次 / 花边 / 扣环 / 接高…）的工序
-- **静默不出现** = **少一道活、少一笔计件钱**，且**不报错**（本仓最忌的静默错误形态）。
--
-- ## 真库实测（2026-09-20，PG 18.3 / 阿里云 RDS `ai_customer_service`，与 #4707 的核实同批）
-- | 租户 | `production_route_rules` | `production_operations` | 判定 |
-- |---|---|---|---|
-- | 1 词元通达 | **29**（26 + 3） | 36 | 健康 |
-- | 20 米高POC演示布艺 | **0** | **0** | 整批规则被跳过 |
-- | 21 POC彩排5605 | **0** | **0** | 整批规则被跳过 |
--
-- 逐条差集（租户 20 相对租户 1）实测 = **29 条**，一条不缺：工艺变体 10（`craft`）+ 特殊选项 16
-- （`option`）+ 加工项 3（`processing_item`）。本机临时 PG 集群上的**可重放复现**见
-- `tests/unit_ci_workflows/test_v93_route_rules_backfill.py` 的 `test_before_v93_*`（红证）。
--
-- ## 🔴 本迁移**只补规则**；工序库由 **V91**（issue #4707）补
-- 规则引用的逻辑工序在该租户工序库里没有行 ⇒ 实例化时 `variantNameOf` 返回 `null` ⇒
-- 该道进 `missing_operations` ⇒ **fail-closed 422**（`ProcessingOrderService.insertConditionalOperations`）。
-- ⇒ 只补规则、不补工序库，会把「静默少活」换成「建单报错」——**报错可发现，但仍不可用**。
-- 同批的 **V91**（issue #4707，`V91__backfill_baseline_operations_for_empty_catalogs.sql`）
-- 为**从未种过基线工序**的租户补 36 道工序 ⇒ 两单合起来才是完整终态：
--   `V91 补工序库` + `本文件补规则` ⇒ 条件工序真的能插进来、真的能计件。
-- ⚠️ 本文件**不重复** V91 的职责（不写 `production_operations`），也**不**因为「工序库可能还空着」
-- 而保留那道护栏 —— 保留它 = 本缺陷原地复发（静默跳过）。
--
-- ## 为什么必须是**新迁移**（不能改 V72 / V84）
-- `MigrationRunner` 的台账 `schema_migrations` 按**文件名**记账、已应用的文件**整份跳过**
-- ⇒ 改 V72/V84 只对全新库生效、存量环境永远拿不到（=「CI 全绿、功能静默缺失」，issue #4235）；
-- 已发布迁移另被 `tests/unit_ci_workflows/migration_fingerprints.json` 的 sha256 逐字节冻结。
--
-- ## 迁移号
-- `ls backend/admin-api/src/main/resources/db/migration | tail` **现取** ⇒ **V93**
-- （**V91 被 #4707 占用、V92 被 #4698-⓪ 预留**；若 push 时 V93 也被占 ⇒ 取下一个空闲号并在 PR body 说明）。
--
-- ## 出厂真值 = **29 条** = `V71` 的 26 条（21 `insert` + 5 `remove`）∪ `V84` 的 3 条
-- 逐条逐值与下列三处**同一份出厂知识**（任一处漂移即红，守卫
-- `tests/unit_ci_workflows/test_v93_route_rules_backfill.py` 按**内容**发现本文件并逐值比对）：
--   ① `V71__normalize_routing_model_structure.sql` ③ 的 26 行字面量种子（`craft` 10 + `option` 16）；
--   ② `V84__seed_processing_item_route_rules.sql` 的 3 行（`processing_item`，priority 270/280/290）；
--   ③ `docs/sql/schema.sql` 的 bootstrap 终态（该路径**不跑迁移链**）。
-- ⚠️ 本文件**不新增**任何规则（不是第 30 条的口子）：它就是上面两份种子的**按租户重放**。
-- `priority` / `after_operation` / `position` 逐字沿用 —— 顺序语义（升序生效、锚点先后）一字未动。
--
-- ## 为什么**不**把它写成字面量 `VALUES` 种子（形态取舍，照实登记）
-- `tests/unit_ci_workflows/test_production_catalog_seed.py::values_sources_for` 把
-- 「`INSERT INTO <表> … VALUES`（VALUES 在 FROM 之前）」认成**字面量种子源**并参与
-- 「≡ `routing.py::ROUTE_RULES` 的 26 条」三源逐值比对 ⇒ 本文件若写成字面量，会把自己
-- 追加进那条射程、把 26 条判据撑成 55 条（**假红**）。
-- 本文件与 V72 ⑤ / V84 同形（`INSERT … SELECT … FROM tenants t JOIN (VALUES …) AS r(…) ON TRUE`
-- = **派生**语句）⇒ 不进字面量射程，由本单的守卫按**内容**发现并逐值比对。
--
-- ## 幂等（`MigrationRunner` 硬要求所有迁移可重复执行）
-- ① `NOT EXISTS` 按**业务唯一键** `(tenant_id, trigger_kind, trigger_value, COALESCE(position,''),
--    action, COALESCE(operation,''))` 去重（对齐 `uk_production_route_rules_tenant_trigger_operation`）
--    ⇒ 商家已自建同键规则 / 1 号租户 V71∪V84 已种过的行**整行跳过**，不 UPDATE、不覆盖；
-- ② `ON CONFLICT (id) DO NOTHING` —— 本迁移 id 按**槽位**派生（`rr-v93-<tenantId>-<rid>`）
--    ⇒ 商家**改名 / 改键 / 软删**后重跑时 `NOT EXISTS` 会判「该插」，而槽位 id 仍被那行占着
--    ⇒ **PK 冲突 ⇒ 整份迁移回滚**（V83 真库实测同款）。② 把这种情形收敛成**无操作**
--    （语义：**种子只种一次，不复活商家改名/软删过的行**）。
--
-- ## 不覆盖商家已改（红线）
-- 本文件**没有任何** `UPDATE` / `DELETE`：唯一的写语句是 `INSERT … SELECT … WHERE NOT EXISTS`。
-- 商家删过 / 改过某条规则 ⇒ 该业务键已有行（含**软删行**也占主键槽位）⇒ 本迁移不碰它。
--
-- ## 🔴 `JOIN (VALUES …) AS r(…)` **必须带 `ON TRUE`**（V83 真库实测 P0）
-- 缺 `ON` 子句 ⇒ PostgreSQL 语法错误 ⇒ **整份迁移回滚** + `schema_migrations` 不写
-- ⇒ 每次启动重跑报 ERROR、规则永不落库（#4514 / V74 同族）。仓库既有合法范式 = V79/V83/V84 的 `ON TRUE`。
--
-- ## 🔴 类型显式（V79 真库事故的教训）
-- `position` / `after_operation` 的 `NULL` 逐行显式 `NULL::varchar`，`priority` 显式 `::integer`
-- —— `JOIN (VALUES …)` 里整列 NULL 会被 PostgreSQL 推断成 `text`，而 `text → varchar` 之外的
-- 隐式转换不成立时整文件单事务回滚（V79 的 `unit_price` 事故同款）。
--
-- ## 停止条件（触发任一 ⇒ 回滚本迁移，不硬推）
--   · S1：`SELECT count(*) FROM production_route_rules WHERE tenant_id = 20 AND deleted = 0`
--         实测 ≠ **29**（该租户工序库非空且已被商家增删规则时，29 是**下界**不是等值 ——
--         判据改看「29 条出厂键是否**逐条**存在」，见守卫的逐值比对）；
--   · S2：任一活跃租户的**快照表**行数变化（`processing_orders.items_snapshot` /
--         `processing_position_operations` / `production_work_logs`）—— 本文件**只写配置表**；
--   · S3：`./verify-all.sh gate` 或 `python3 -m pytest tests/unit_ci_workflows/ -q` 非零；
--   · S4：**V91 未合入**而本迁移先上 ⇒ 规则补了但工序库仍空 ⇒ 条件工序 422（**可发现**，
--         但不可用）⇒ 两单必须**同批或 V91 先**发布（本单在 PR body 登记该顺序依赖）。
--
-- ## 回滚（**新迁移，不删 V93**；语义 = 撤掉本次补种的行）
-- ```sql
-- -- V94__rollback_route_rules_backfill.sql（本单只登记，不落码）
-- DELETE FROM production_route_rules WHERE id LIKE 'rr-v93-%';
-- ```
-- ⚠️ 只删本迁移生成的 id 前缀；**不碰** `rr-v70-*`（V71）/ `rr-v72-*`（V72）/ `rr-v84-*`（V84）
-- 与商家自建行。历史加工单不受影响：规则只在**建单那一刻**参与实例化，快照表不回算。
--
-- ## bootstrap 同步（`docs/sql/schema.sql` 该路径不跑迁移链）
-- `docs/sql/schema.sql` 已同步同款**派生**回填（同 V72/V83/V84 的「终态镜像」范式）；
-- 漂移由本单的守卫逐值比对守住。

INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action,
     operation, after_operation, priority, status)
SELECT 'rr-v93-' || t.id || '-' || r.rid, t.id, r.trigger_kind, r.trigger_value,
       r.position, r.action, r.operation, r.after_operation, r.priority, 'active'
  FROM tenants t
  JOIN (VALUES
      -- ① 工艺变体 10 条（`craft`）—— 逐条 = V71 ③ 的 `rr-v70-01..10`
      ('01', 'craft', '韩褶',   NULL::varchar, 'insert', '韩褶',     '三边',  10::integer),
      ('02', 'craft', '韩褶',   '布帘'::varchar, 'insert', '上车布', '韩褶',  20::integer),
      ('03', 'craft', '打孔',   NULL::varchar, 'insert', '打孔',     '三边',  30::integer),
      ('04', 'craft', '四爪钩', NULL::varchar, 'insert', '上车布',   '三边',  40::integer),
      ('05', 'craft', '四爪钩', NULL::varchar, 'remove', '定型',     NULL::varchar, 50::integer),
      ('06', 'craft', '四爪钩', NULL::varchar, 'remove', '复烫',     NULL::varchar, 60::integer),
      ('07', 'craft', '穿杆',   NULL::varchar, 'remove', '定型',     NULL::varchar, 70::integer),
      ('08', 'craft', '穿杆',   NULL::varchar, 'remove', '复烫',     NULL::varchar, 80::integer),
      ('09', 'craft', '平幔',   NULL::varchar, 'insert', '帘头制作', '三边',  90::integer),
      ('10', 'craft', '平幔',   NULL::varchar, 'remove', '复烫',     NULL::varchar, 100::integer),
      -- ② 特殊选项 16 条（`option`）—— 逐条 = V71 ③ 的 `rr-v70-11..26`
      ('11', 'option', '拼1次',      NULL::varchar, 'insert', '拼1次',     '三边', 110::integer),
      ('12', 'option', '拼2次',      NULL::varchar, 'insert', '拼2次',     '三边', 120::integer),
      ('13', 'option', '拼3次',      NULL::varchar, 'insert', '拼3次',     '三边', 130::integer),
      ('14', 'option', '加花边',     NULL::varchar, 'insert', '花边',      '三边', 140::integer),
      ('15', 'option', '加铅块',     NULL::varchar, 'insert', '铅坠',      '三边', 150::integer),
      ('16', 'option', '接高',       NULL::varchar, 'insert', '接高',      '精裁', 160::integer),
      ('17', 'option', '双眼皮接高', NULL::varchar, 'insert', '接高',      '精裁', 170::integer),
      ('18', 'option', '余料做绑带', NULL::varchar, 'insert', '绑带',      '车被', 180::integer),
      ('19', 'option', '布绑带',     NULL::varchar, 'insert', '绑带',      '车被', 190::integer),
      ('20', 'option', '余料做帘头', NULL::varchar, 'insert', '帘头制作',  '三边', 200::integer),
      ('21', 'option', '抱枕',       NULL::varchar, 'insert', '抱枕',      '外帘打卷', 210::integer),
      ('22', 'option', '纱绑带',     NULL::varchar, 'insert', '绑带',      '车被', 220::integer),
      ('23', 'option', '加logo条',   NULL::varchar, 'insert', 'logo条',    '三边', 230::integer),
      ('24', 'option', '加立边',     NULL::varchar, 'insert', '立边',      '三边', 240::integer),
      ('25', 'option', '扣环',       NULL::varchar, 'insert', '扣环',      '三边', 250::integer),
      ('26', 'option', '防翘扣',     NULL::varchar, 'insert', '防翘扣',    '三边', 260::integer),
      -- ③ 加工项触发 3 条（`processing_item`）—— 逐条 = V84（用户裁定 issue #4577）
      ('27', 'processing_item', '花边', NULL::varchar, 'insert', '花边', '三边', 270::integer),
      ('28', 'processing_item', '扣环', NULL::varchar, 'insert', '扣环', '三边', 280::integer),
      ('29', 'processing_item', '接高', NULL::varchar, 'insert', '接高', '精裁', 290::integer)
  ) AS r(rid, trigger_kind, trigger_value, position, action, operation, after_operation, priority)
    ON TRUE
 WHERE t.deleted = 0
   -- 业务唯一键 `(tenant_id, trigger_kind, trigger_value, COALESCE(position,''), action,
   -- COALESCE(operation,''))` —— 对齐 uk_production_route_rules_tenant_trigger_operation。
   -- 🔴 **本迁移刻意不带工序库护栏**（V72 ⑤ / V84 的 `EXISTS (production_operations …)`）：
   --    那道护栏正是本缺陷的成因（工序库为空 ⇒ 整批规则静默跳过）。工序库由 V91 补。
   AND NOT EXISTS (
       SELECT 1 FROM production_route_rules e
        WHERE e.tenant_id = t.id AND e.deleted = 0
          AND e.trigger_kind = r.trigger_kind AND e.trigger_value = r.trigger_value
          AND COALESCE(e.position, '') = COALESCE(r.position, '')
          AND e.action = r.action
          AND COALESCE(e.operation, '') = COALESCE(r.operation, ''))
ON CONFLICT (id) DO NOTHING;
