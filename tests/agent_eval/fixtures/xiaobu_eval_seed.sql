-- ============================================================================
-- C 端小布评测最小业务数据 fixture（issue #3270）
-- ============================================================================
-- 用途：给**本地/CI docker 验收栈**注入最小业务数据，使依赖商品/加工项的 C 端用例
--       可被真实执行。B 端评测跑生产（有真实数据），C 端跑全新 bootstrap 空库 ——
--       空库下 agent 搜不到商品 → 反复重试 product_search → 从不进入 product_detail，
--       导致 PR-003 等依赖数据的用例必然失败（行为本身合理，缺的是数据）。
--
-- 实测（CI，空库）：PR-003 `tools=[product_search ×3]`，期望 `product_detail` → 0 分
--
-- 幂等：全部 ON CONFLICT DO NOTHING，可重复执行（每次 CI 起栈后都会重放）。
-- 仅用于评测栈，**不并入** docs/sql/schema.sql（生产 bootstrap 不应含演示数据）。
--
-- 覆盖的评测用例：PR-001（商品搜索）/ PR-003（商品详情 ID 解析）/
--                OR-017 / OR-016（下单加工项）/ CH-010（选购下单表单化）
-- ============================================================================

-- ── 1. 商品分类 ──
INSERT INTO categories (id, tenant_id, name, parent_id, level, sort_order, status)
VALUES ('cat_eval_curtain', 1, '窗帘布艺', NULL, 1, 1, 'active')
ON CONFLICT (id) DO NOTHING;

-- ── 2. 加工分类 + 加工项（下单加工项环节所需）──
INSERT INTO processing_categories (id, tenant_id, name, sort_order, status)
VALUES ('pcat_eval_curtain', 1, '窗帘加工', 1, 'active')
ON CONFLICT (id) DO NOTHING;

INSERT INTO processing_items
  (id, tenant_id, name, category_id, pricing_method, unit_price, unit,
   min_quantity, max_quantity, description, options, ai_recommended, status, deleted)
VALUES
  ('pi_eval_punch', 1, '纳米圈打孔', 'pcat_eval_curtain', 'per_meter', 8.00, '米',
   1, 999, '顶部打纳米圈，含罗马圈辅料', '[]'::jsonb, TRUE, 'active', 0),
  ('pi_eval_hem', 1, '韩式波浪折边', 'pcat_eval_curtain', 'per_meter', 12.00, '米',
   1, 999, '韩式褶皱加工，含布带辅料', '[]'::jsonb, TRUE, 'active', 0),
  ('pi_eval_iron', 1, '高温定型', 'pcat_eval_curtain', 'per_meter', 10.00, '米',
   1, 999, '高温定型，褶皱持久', '[]'::jsonb, TRUE, 'active', 0)
ON CONFLICT (id) DO NOTHING;

-- ── 3. 商品：遮光窗帘（PR-003 名称查询 / PR-001 关键词搜索）──
INSERT INTO products
  (id, tenant_id, name, category_id, base_price, description, images, detail_images,
   stock, stock_warning_threshold, status, unit, pricing_type, sku_code,
   stock_deduction_mode, sales_count, sales_amount, has_processing, recommended)
VALUES
  ('prod_eval_blackout', 1, '遮光窗帘', 'cat_eval_curtain', 168.00,
   '高遮光面料，适合卧室与客厅，遮光率 95%，支持散剪与加工定制',
   '[]'::jsonb, '[]'::jsonb, 1000, 10, 'on_sale', '米', 'per_meter', 'EVAL-BLK-28',
   'on_order', 0, 0, TRUE, TRUE),
  ('prod_eval_dark_green', 1, '北欧风窗帘', 'cat_eval_curtain', 128.00,
   '北欧简约风格，棉麻质感，适合客厅与书房',
   '[]'::jsonb, '[]'::jsonb, 800, 10, 'on_sale', '米', 'per_meter', 'EVAL-NRD-28',
   'on_order', 0, 0, TRUE, FALSE)
ON CONFLICT (id) DO NOTHING;

-- ── 4. 颜色 / SKU（选品规格收集所需：colorId + sellingMethod + doorWidth）──
INSERT INTO product_colors (tenant_id, product_id, color_name, main_color_hex, sort_order)
SELECT v.tenant_id, v.product_id, v.color_name, v.hex, v.ord
FROM (VALUES
  (1, 'prod_eval_blackout', '米白', '#F5F0E6', 1),
  (1, 'prod_eval_blackout', '浅灰', '#C8C8C8', 2),
  (1, 'prod_eval_dark_green', '雾霾蓝', '#8FA3B0', 1)
) AS v(tenant_id, product_id, color_name, hex, ord)
WHERE NOT EXISTS (
  SELECT 1 FROM product_colors pc
  WHERE pc.product_id = v.product_id AND pc.color_name = v.color_name
);

INSERT INTO product_skus (tenant_id, product_id, color_id, selling_method, door_width, price, stock, sku_code)
SELECT 1, pc.product_id, pc.id, 'bulk_cut', '2.8', p.base_price, 500,
       p.sku_code || '-' || pc.color_name
FROM product_colors pc
JOIN products p ON p.id = pc.product_id
WHERE pc.product_id IN ('prod_eval_blackout', 'prod_eval_dark_green')
  AND NOT EXISTS (
    SELECT 1 FROM product_skus s
    WHERE s.product_id = pc.product_id AND s.color_id = pc.id
      AND s.selling_method = 'bulk_cut' AND s.door_width = '2.8'
  );

-- ── 5. 商品 ↔ 加工项关联（下单加工项环节的 processing_items 来源）──
INSERT INTO product_processing_items (tenant_id, product_id, processing_item_id, custom_price, sort_order)
SELECT 1, v.pid, v.piid, NULL, v.ord
FROM (VALUES
  ('prod_eval_blackout', 'pi_eval_punch', 1),
  ('prod_eval_blackout', 'pi_eval_hem', 2),
  ('prod_eval_blackout', 'pi_eval_iron', 3),
  ('prod_eval_dark_green', 'pi_eval_punch', 1)
) AS v(pid, piid, ord)
WHERE NOT EXISTS (
  SELECT 1 FROM product_processing_items x
  WHERE x.product_id = v.pid AND x.processing_item_id = v.piid
);
