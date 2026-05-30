-- ================================================================
-- 加工项种子数据（窗帘布艺行业）
-- ----------------------------------------------------------------
-- 用途: 2026-05-30 RDS 实例更换后，processing_categories / processing_items 表为空，
--       本脚本补充默认租户 (id=1) 的加工分类与加工项，使前端"加工项管理"页面有可见数据。
-- 关联 Issue: #112
-- 幂等性: 使用 ON CONFLICT DO NOTHING / DO UPDATE，可重复执行。
-- 执行方式:
--   1) 本地: psql -h <host> -U <user> -d <db> -f docs/sql/seed_processing_items.sql
--   2) SAE Job: 通过 SAE 创建一次性 Job，挂载本 SQL 并执行
--      (dev RDS 公网不可达，必须从 VPC 内网执行)
-- 编码: UTF-8
-- ================================================================

BEGIN;

-- ── 加工分类 (processing_categories) ─────────────────────────────
-- 默认租户 id=1，分类 id 使用稳定字符串便于幂等
INSERT INTO processing_categories (id, tenant_id, name, sort_order, status, created_at, updated_at, deleted)
VALUES
  ('proc_cat_punch',     1, '打孔加工', 1, 'active', NOW(), NOW(), 0),
  ('proc_cat_hem',       1, '折边加工', 2, 'active', NOW(), NOW(), 0),
  ('proc_cat_hook',      1, '挂钩加工', 3, 'active', NOW(), NOW(), 0),
  ('proc_cat_shape',     1, '定型加工', 4, 'active', NOW(), NOW(), 0),
  ('proc_cat_craft',     1, '特殊工艺', 5, 'active', NOW(), NOW(), 0),
  ('proc_cat_accessory', 1, '辅料加工', 6, 'active', NOW(), NOW(), 0)
ON CONFLICT (id) DO UPDATE SET
  name = EXCLUDED.name,
  sort_order = EXCLUDED.sort_order,
  status = EXCLUDED.status,
  updated_at = NOW();

-- ── 加工项 (processing_items) ────────────────────────────────────
-- 字段对齐 schema_full.sql:
--   pricing_method ∈ {per_meter, per_piece, per_area, fixed}
--   unit, unit_price, processing_days, options(JSONB), status, deleted

INSERT INTO processing_items
  (id, tenant_id, name, category_id, pricing_method, unit_price, unit,
   min_quantity, max_quantity, description, options, processing_days,
   ai_recommended, status, created_at, updated_at, deleted)
VALUES
  -- ── 打孔加工 ──
  ('proc_item_punch_nano',  1, '纳米圈打孔', 'proc_cat_punch', 'per_meter',  8.00, '米',  1, 999,
   '窗帘顶部纳米圈打孔加工，适用于罗马杆安装',
   '[{"name":"圈色","values":["银色","金色","黑色"],"default":"银色"}]'::jsonb,
   2, true, 'active', NOW(), NOW(), 0),

  ('proc_item_punch_claw',  1, '四爪钩打孔', 'proc_cat_punch', 'per_piece',  2.00, '个',  1, 999,
   '四爪钩打孔加工，适用于轨道安装',
   '[{"name":"钩型","values":["普通","加强"],"default":"普通"}]'::jsonb,
   1, true, 'active', NOW(), NOW(), 0),

  ('proc_item_punch_s',     1, '韩式S钩打孔', 'proc_cat_punch', 'per_piece',  3.00, '个',  1, 999,
   '韩式S钩打孔加工，造型美观',
   '[]'::jsonb,
   1, true, 'active', NOW(), NOW(), 0),

  -- ── 折边加工 ──
  ('proc_item_hem_single',  1, '单折边',     'proc_cat_hem',   'per_meter',  5.00, '米',  1, 999,
   '窗帘单层折边处理',
   '[]'::jsonb,
   1, true, 'active', NOW(), NOW(), 0),

  ('proc_item_hem_double',  1, '双折边',     'proc_cat_hem',   'per_meter',  8.00, '米',  1, 999,
   '窗帘双层折边处理，更加平整美观',
   '[]'::jsonb,
   2, true, 'active', NOW(), NOW(), 0),

  ('proc_item_hem_wrap',    1, '包边处理',   'proc_cat_hem',   'per_meter', 10.00, '米',  1, 999,
   '窗帘边缘包边处理，提升质感',
   '[{"name":"包边布料","values":["同色","撞色"],"default":"同色"}]'::jsonb,
   2, true, 'active', NOW(), NOW(), 0),

  -- ── 挂钩加工 ──
  ('proc_item_hook_claw',   1, '四爪钩安装',   'proc_cat_hook', 'per_piece', 1.50, '个',  1, 999,
   '四爪钩安装，适用于轨道式窗帘杆',
   '[]'::jsonb,
   1, true, 'active', NOW(), NOW(), 0),

  ('proc_item_hook_s',      1, 'S钩安装',     'proc_cat_hook', 'per_piece', 2.00, '个',  1, 999,
   'S型挂钩安装，简洁易用',
   '[]'::jsonb,
   1, true, 'active', NOW(), NOW(), 0),

  ('proc_item_hook_roman',  1, '罗马杆环安装', 'proc_cat_hook', 'per_piece', 3.00, '个',  1, 999,
   '罗马杆环安装，适用于罗马杆窗帘',
   '[]'::jsonb,
   1, true, 'active', NOW(), NOW(), 0),

  -- ── 定型加工 ──
  ('proc_item_shape_normal', 1, '普通定型',   'proc_cat_shape', 'per_meter',  6.00, '米',     1, 999,
   '普通蒸汽定型处理，保持窗帘垂感',
   '[]'::jsonb,
   3, true, 'active', NOW(), NOW(), 0),

  ('proc_item_shape_high',   1, '高温定型',   'proc_cat_shape', 'per_meter', 10.00, '米',     1, 999,
   '高温定型处理，效果持久不变形',
   '[]'::jsonb,
   5, true, 'active', NOW(), NOW(), 0),

  ('proc_item_shape_iron',   1, '免烫定型',   'proc_cat_shape', 'per_area',  15.00, '平方米', 1, 999,
   '免烫定型处理，洗后免烫自然垂顺',
   '[]'::jsonb,
   3, true, 'active', NOW(), NOW(), 0),

  -- ── 特殊工艺 ──
  ('proc_item_craft_lg',     1, 'LG工艺',     'proc_cat_craft', 'fixed',    50.00, '件',     1, 999,
   'LG特殊加工工艺，提升窗帘整体品质',
   '[]'::jsonb,
   7, true, 'active', NOW(), NOW(), 0),

  ('proc_item_craft_emb',    1, '刺绣工艺',   'proc_cat_craft', 'per_area', 30.00, '平方米', 1, 999,
   '精美刺绣加工，可定制花纹图案',
   '[]'::jsonb,
   10, true, 'active', NOW(), NOW(), 0),

  ('proc_item_craft_print',  1, '印花工艺',   'proc_cat_craft', 'per_area', 20.00, '平方米', 1, 999,
   '数码印花加工，色彩丰富图案清晰',
   '[]'::jsonb,
   5, true, 'active', NOW(), NOW(), 0),

  -- ── 辅料加工 ──
  ('proc_item_acc_lead',     1, '铅坠安装',   'proc_cat_accessory', 'per_meter', 3.00, '米', 1, 999,
   '窗帘底部铅坠安装，增加垂感',
   '[]'::jsonb,
   1, true, 'active', NOW(), NOW(), 0),

  ('proc_item_acc_velcro',   1, '魔术贴安装', 'proc_cat_accessory', 'per_meter', 4.00, '米', 1, 999,
   '魔术贴安装，方便拆卸清洗',
   '[]'::jsonb,
   1, true, 'active', NOW(), NOW(), 0),

  ('proc_item_acc_valance',  1, '窗幔制作',   'proc_cat_accessory', 'fixed',    80.00, '件', 1, 999,
   '窗幔定制制作，提升窗帘装饰效果',
   '[]'::jsonb,
   5, true, 'active', NOW(), NOW(), 0)
ON CONFLICT (id) DO UPDATE SET
  name             = EXCLUDED.name,
  category_id      = EXCLUDED.category_id,
  pricing_method   = EXCLUDED.pricing_method,
  unit_price       = EXCLUDED.unit_price,
  unit             = EXCLUDED.unit,
  description      = EXCLUDED.description,
  options          = EXCLUDED.options,
  processing_days  = EXCLUDED.processing_days,
  status           = EXCLUDED.status,
  updated_at       = NOW();

COMMIT;

-- 验证查询
-- SELECT name, status FROM processing_categories WHERE tenant_id = 1 ORDER BY sort_order;
-- SELECT name, pricing_method, unit_price, unit FROM processing_items WHERE tenant_id = 1 ORDER BY category_id, name;
