-- 加工项触发工序（用户裁定 2026-09-19，issue #4577）
--
-- ## 用户裁定（原文）
--   「**加工项也触发工序**」「是不是**用户会选择拼几次**，只有选择了这几个特殊选项才会有拼接工序？」→ **是**
--   「**双眼皮在特殊选项中也有说明**」（`双眼皮接高` → 插「接高」）
--
-- ## 本迁移做什么（3 条规则行，按租户种进 `production_route_rules`）
--   | trigger_kind       | trigger_value | action | operation | after_operation | priority |
--   |--------------------|---------------|--------|-----------|-----------------|----------|
--   | `processing_item`  | `花边`        | insert | `花边`    | `三边`          | 270      |
--   | `processing_item`  | `扣环`        | insert | `扣环`    | `三边`          | 280      |
--   | `processing_item`  | `接高`        | insert | `接高`    | `精裁`          | 290      |
--
--   触发键 = 订单行 `processingInfo.processingItems[].name`，**精确相等**
--   （与 `craft` / `option` 同款；`contains` 只存在于存量信号兜底 `firstSignalMatch`，
--    本单**不引入第二处**）。优先级 270/280/290 落在既有 `option` 段（110–260）之后、
--   计件系数档（300）之前 —— 顺序语义由 `priority` 决定，本单**不改**。
--
--   `trigger_kind='processing_item'` **已在 V71 的白名单里**（V71 的 CHECK 覆盖
--   `craft`/`option`/`shaped`/`processing_item`）⇒ 本迁移**不新增 CHECK**、不改表结构。
--
-- ## 刻意**不**建规则行的两个值（防「顺手补齐」）
--   `拼接` / `双眼皮` **不建行**（理由登记在 issue #4577）：拼几次由特殊选项
--   `拼1次/拼2次/拼3次` 表达（各自已有 `option` 规则行），`双眼皮` 的工序由
--   `双眼皮接高` 这条既有 `option` 规则行承载。给它们造行 = 把错误结构化
--   （同一道工序被两条规则重复触发 ⇒ 工人按两遍单价拿钱）。
--
-- ## 幂等 + 不覆盖商家数据（MigrationRunner 要求所有 SQL 可重复执行）
--   **双保险**（同 V83 的教训）：
--   ① `NOT EXISTS` 按**业务键** `(tenant_id, trigger_kind, trigger_value, COALESCE(position,''),
--      action, COALESCE(operation,''))` 去重（对齐 `uk_production_route_rules_tenant_trigger_operation`）
--      ⇒ 商家已自建同键规则时整行跳过，不 UPDATE、不覆盖；
--   ② `ON CONFLICT (id) DO NOTHING` —— 本迁移 id 是**按槽位**派生的
--      （`rr-v84-<tenantId>-<rid>`）⇒ 商家**改名/改键**后重跑时 `NOT EXISTS` 会判「该插」，
--      而槽位 id 仍被那行占着 ⇒ **PK 冲突 ⇒ 整份迁移回滚**（V83 真库实测同款）。
--      ② 把这种情形收敛成**无操作**（语义：**种子只种一次**）。
--
-- ## 🔴 `JOIN (VALUES …) AS r(…)` **必须带 `ON TRUE`**（V83 真库实测 P0）
--   缺 `ON` 子句 ⇒ PostgreSQL 语法错误 ⇒ **整份迁移回滚** + `schema_migrations` 不写
--   ⇒ 每次启动重跑报 ERROR、规则永不落库（#4514 / V74 同族）。仓库既有合法范式 = V79/V83 的 `ON TRUE`。
--
-- ## 目标工序必须在工序库里存在才种（V72 同款护栏）
--   规则引用的逻辑工序在该租户工序库**归一后不存在** ⇒ 不种（否则规则永远插不进来 = 黑洞）。
--   归一 = V72 的 CASE（`-布`/`-纱` 去后缀 / `布三边`/`纱三边` → `三边` / `布帘车被` → `车被`）。
--
-- ## 迁移不可变（issue #4235）
--   本文件发布后**不得再改**。新增迁移须同 PR 跑
--   `python3 tests/unit_ci_workflows/test_migration_immutability.py --write-ledger` 登记指纹。
--
-- ## bootstrap 同步（本路径不跑迁移链）
--   `docs/sql/schema.sql` 已同步同款终态 INSERT（同 V72/V83 的「终态镜像」范式）；
--   漂移由 `tests/unit_ci_workflows/test_processing_item_route_rules_seed.py` 逐值比对守住。

INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action, operation, after_operation, priority, status)
SELECT 'rr-v84-' || t.id || '-' || r.rid, t.id, r.trigger_kind, r.trigger_value,
       NULL, r.action, r.operation, r.after_operation, r.priority, 'active'
  FROM tenants t
  JOIN (VALUES
      ('01', 'processing_item', '花边', 'insert', '花边', '三边', 270),
      ('02', 'processing_item', '扣环', 'insert', '扣环', '三边', 280),
      ('03', 'processing_item', '接高', 'insert', '接高', '精裁', 290)
  ) AS r(rid, trigger_kind, trigger_value, action, operation, after_operation, priority)
    ON TRUE
 WHERE t.deleted = 0
   -- 目标工序必须在该租户工序库里存在（归一后匹配，V72 同款）——否则规则永远插不进来
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
   AND NOT EXISTS (
       SELECT 1 FROM production_route_rules e
        WHERE e.tenant_id = t.id AND e.deleted = 0
          AND e.trigger_kind = r.trigger_kind AND e.trigger_value = r.trigger_value
          AND e.position IS NULL
          AND e.action = r.action AND e.operation = r.operation)
ON CONFLICT (id) DO NOTHING;
