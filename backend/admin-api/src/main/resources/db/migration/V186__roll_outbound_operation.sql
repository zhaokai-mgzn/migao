-- 整卷布料单「出库」独立工序（issue #7523，用户裁定 2026-10-23）
--
-- ## 一句话
-- 散剪卖布 = `裁剪 → 打包`；整卷卖布 = **`出库 → 打包`**（不裁剪 —— 工人按卷/批次拣货出库）。
-- 用户三点裁定：① 出库做**独立工序**（不并进打包、不新增出库单实体）；② **批次号即卷号**
-- （不新增逐卷编号/逐卷表）；③ 发货守卫维持（作业单 completed 才能发货）。
--
-- ## 为什么是「规则」而不是「第二张路线模板」
-- `production_route_templates` 的选取键 = 部位（`布料`），整卷/散剪是**同一个部位**的产品形态差异
-- ⇒ 两张同名同部位的模板会让 `routeTemplateFor` 出现歧义。规则表本来就是「同一主线上的条件工序」，
-- 且 2026-09-21（issue #4962）起已支持按触发增删 ⇒ 售卖方式作为**第四种触发**（`sales_form`）落在这里。
-- 顺序敏感：先 `insert 出库 after 裁剪`、再 `remove 裁剪` ⇒ 主线 = `出库 → 打包`；
-- 反过来会先把锚点删掉，导致出库被追加到末尾（`打包 → 出库`，工序顺序错）。
--
-- ## 为什么 `position` 留空
-- 本触发**只对布料产品形态生效**（`ProcessingOrderService#buildRoute` 与
-- `routing.py::build_route_v2` 同款分派：布料单只吃 `sales_form` 规则，窗帘单不吃）。
-- 写 `position='布料'` 是第二份口径（#4937 / O2 已把「部位限定」收敛到唯一那一条韩褶规则）。
--
-- ## 幂等
-- 四条写面都按**业务唯一键** `NOT EXISTS` + `ON CONFLICT` 去重：重复执行匹配 0 行、净效果相同
-- （`MigrationRunner` 要求迁移可重复执行）。商家已改过的行一律不覆盖（没有 `SET` 既有业务列）。
--
-- ## 回滚（登记，不落码）
-- ```sql
-- -- ① 规则软删（按 id 前缀认领）
-- UPDATE production_route_rules SET deleted = 1, updated_at = NOW()
--  WHERE id LIKE 'rr-v186-%' AND deleted = 0;
-- -- ② 价目行软删
-- UPDATE production_operation_positions SET deleted = 1, updated_at = NOW()
--  WHERE id LIKE 'opp-v186-%' AND deleted = 0;
-- -- ③ 工序行软删（历史快照不变 —— 已生成单的工序实例是本文件红线外的表）
-- UPDATE production_operations SET deleted = 1, updated_at = NOW()
--  WHERE id LIKE 'op-v186-%' AND deleted = 0;
-- ```
-- ⚠️ 回滚的语义是「让**新单**回到 `裁剪 → 打包`」，**不是**让历史单回退（快照表一字不动）。
--
-- ## 红线：三张快照表一字不动
--   · processing_orders.items_snapshot
--   · processing_position_operations
--   · production_work_logs（unit_price / factor）
-- 本文件只写三张**配置**表（production_operations / production_operation_positions /
-- production_route_rules）。

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ① 规则触发类型：新增 `sales_form`（售卖方式：full_roll 整卷 / bulk_cut 散剪）
-- ══════════════════════════════════════════════════════════════════════════════════════
ALTER TABLE production_route_rules DROP CONSTRAINT IF EXISTS production_route_rules_trigger_kind_check;
ALTER TABLE production_route_rules
    ADD CONSTRAINT production_route_rules_trigger_kind_check
    CHECK (trigger_kind IN ('craft', 'option', 'shaped', 'processing_item', 'position', 'sales_form'));

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ② 工序「出库」（每活跃租户一条；单位 = 卷）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- 字面量行（1 号租户）—— 静态守卫（tests/unit_ci_workflows/test_production_catalog_seed.py）
-- 按 `VALUES` 字面量与 `routing.py::OPERATION_CATALOG` 逐值比对，派生块不在其射程内。
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, status)
VALUES
  ('op-v186-01', 1, '出库', '后道', NULL, '卷', 0, FALSE, FALSE, 42, 'active')
ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;

-- 按租户循环（存量租户）：已存在同名工序 ⇒ 不写（不覆盖商家自建行）
INSERT INTO production_operations
    (id, tenant_id, name, group_name, position, unit, unit_price,
     is_must_finish, is_start_marker, sort_order, status)
SELECT 'op-v186-' || t.id, t.id, '出库', '后道', NULL, '卷', 0, FALSE, FALSE, 42, 'active'
  FROM tenants t
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_operations e
        WHERE e.tenant_id = t.id AND e.name = '出库' AND e.deleted = 0)
ON CONFLICT (tenant_id, name) WHERE deleted = 0 DO NOTHING;

-- provenance / scope：与 V79 的 op-v79-* 同口径（`占位待确认` = 价未定、商家可配；position 级）
UPDATE production_operations o
   SET source = '占位待确认',
       scope = 'position',
       updated_at = NOW()
  FROM tenants t
 WHERE o.tenant_id = t.id
   AND t.deleted = 0
   AND o.name = '出库'
   AND o.deleted = 0
   AND o.id LIKE 'op-v186-%'
   AND (o.source IS NULL OR o.source = '');

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ③ 价目矩阵：`出库 × 4 部位`（布料 = 适用但未定价；三个窗帘部位显式 FALSE）
-- ══════════════════════════════════════════════════════════════════════════════════════
-- ⚠️ `unit_price` 逐行显式 `NULL::numeric`（V89 的实测坑：整列 NULL 会被推断成 text ⇒ 真库 42804）
INSERT INTO production_operation_positions
    (id, tenant_id, logical_name, position, unit_price, applicable, status)
VALUES
  ('opp-v186-01', 1, '出库', '布料', NULL, TRUE, 'active'),
  ('opp-v186-02', 1, '出库', '布帘', NULL, FALSE, 'active'),
  ('opp-v186-03', 1, '出库', '纱帘', NULL, FALSE, 'active'),
  ('opp-v186-04', 1, '出库', '帘头', NULL, FALSE, 'active')
ON CONFLICT DO NOTHING;

INSERT INTO production_operation_positions
    (id, tenant_id, logical_name, position, unit_price, applicable, status)
SELECT 'opp-v186-' || t.id || '-' || p.position,
       t.id, '出库', p.position, NULL::numeric, p.applicable, 'active'
  FROM tenants t,
       (VALUES
           ('布料', TRUE::boolean),
           ('布帘', FALSE::boolean),
           ('纱帘', FALSE::boolean),
           ('帘头', FALSE::boolean)
       ) AS p(position, applicable)
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_operation_positions e
        WHERE e.tenant_id = t.id AND e.logical_name = '出库'
          AND e.position = p.position AND e.deleted = 0)
ON CONFLICT DO NOTHING;

-- ══════════════════════════════════════════════════════════════════════════════════════
-- ④ 售卖方式规则（每活跃租户 2 条）：整卷 ⇒ 出库 → 打包
-- ══════════════════════════════════════════════════════════════════════════════════════
INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action,
     operation, after_operation, priority, status)
VALUES
  ('rr-v186-01', 1, 'sales_form', 'full_roll', NULL, 'insert', '出库', '裁剪', 270, 'active'),
  ('rr-v186-02', 1, 'sales_form', 'full_roll', NULL, 'remove', '裁剪', NULL, 280, 'active')
ON CONFLICT DO NOTHING;

INSERT INTO production_route_rules
    (id, tenant_id, trigger_kind, trigger_value, position, action,
     operation, after_operation, priority, status)
SELECT 'rr-v186-' || t.id || '-' || r.rid, t.id, r.trigger_kind, r.trigger_value, r.position,
       r.action, r.operation, r.after_operation, r.priority, 'active'
  FROM tenants t
  JOIN (VALUES
      ('01', 'sales_form', 'full_roll', NULL, 'insert', '出库', '裁剪', 270),
      ('02', 'sales_form', 'full_roll', NULL, 'remove', '裁剪', NULL, 280)
  ) AS r(rid, trigger_kind, trigger_value, position, action, operation, after_operation, priority) ON TRUE
 WHERE t.deleted = 0
   AND NOT EXISTS (
       SELECT 1 FROM production_route_rules e
        WHERE e.tenant_id = t.id
          AND e.trigger_kind = r.trigger_kind
          AND e.trigger_value = r.trigger_value
          AND e.action = r.action
          AND e.operation = r.operation
          AND e.deleted = 0)
ON CONFLICT DO NOTHING;
