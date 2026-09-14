-- ============================================================================
-- B 端（米宝）评测补充数据 fixture（#3491 T3.2）
-- ============================================================================
-- 用途：B 端 normal 迁到独立栈（干净库）后，补齐 B 端用例**点名**的业务数据。
--       与 xiaobu_eval_seed.sql **叠加**使用（C 端 seed 先跑，本文件补 B 端专属），
--       workflow 的 seed 步骤在 persona=mibao 时追加执行本文件。
--
-- 为什么需要（B 端首跑 run 34804430769 归因 #3496，56/70）：
--   旧通道打云测试环境（有生产存量数据）→ 迁移独立栈后 14 条阻塞失败，
--   其中多数是**数据层缺口**，不是能力回归。逐条证据：
--     · OR-016  用户「2699系列雪尼尔窗帘面料」→ 实测 product_search(products=0)
--               agent 反复搜 4 轮宣告"库里没有这款商品"（行为合理，缺的是数据）
--     · PR-020  点名加工项「刺绣工艺（自定义 45 元/平方米）」
--     · CU-003  点名客户「张三」（add_tag）；CU-004 更新客户资料
--     · HR-003  点名员工「王五」（停用账号）
--
-- 幂等：ON CONFLICT DO NOTHING / WHERE NOT EXISTS，可重复执行。
-- 仅用于评测栈，**不并入** docs/sql/schema.sql（生产 bootstrap 不应含演示数据）。
-- ============================================================================

-- ── 1. 商品：2699 系列雪尼尔窗帘面料（OR-016 点名）──
-- 名称必须含「2699系列雪尼尔窗帘面料」（用例输入原文）；价格 23.80 取生产同款量级。
-- has_processing=TRUE：OR-016 断言「商品绑定加工项时，confirm 前必须主动询问加工项」——
--   不绑定加工项则该断言的**前提不成立**，用例会退化成"没事发生"（假绿）。
INSERT INTO products
  (id, tenant_id, name, category_id, base_price, description, images, detail_images,
   stock, stock_warning_threshold, status, unit, pricing_type, sku_code,
   stock_deduction_mode, sales_count, sales_amount, has_processing, recommended)
VALUES
  ('prod_eval_2699', 1, '2699系列雪尼尔窗帘面料', 'cat_eval_curtain', 23.80,
   '雪尼尔面料，手感厚实，适合窗帘定制（B 端评测 fixture）',
   '[]'::jsonb, '[]'::jsonb, 1000, 10, 'on_sale', '米', 'per_meter', 'EVAL-2699-28',
   'on_order', 0, 0, TRUE, FALSE)
ON CONFLICT (id) DO NOTHING;

-- 颜色：2699-03 暖米色（用例原文「2699-03暖米色」）
INSERT INTO product_colors (tenant_id, product_id, color_name, main_color_hex, sort_order)
SELECT v.tenant_id, v.product_id, v.color_name, v.hex, v.ord
FROM (VALUES
  (1, 'prod_eval_2699', '2699-03暖米色', '#E8DCC8', 1),
  (1, 'prod_eval_2699', '2699-01本白', '#FAF7F0', 2)
) AS v(tenant_id, product_id, color_name, hex, ord)
WHERE NOT EXISTS (
  SELECT 1 FROM product_colors pc
  WHERE pc.product_id = v.product_id AND pc.color_name = v.color_name
);

INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, selling_method, door_width, price, stock, sku_code)
SELECT 1, pc.product_id, pc.id, pc.color_name, 'bulk_cut', '2.8', p.base_price, 500,
       p.sku_code || '-' || pc.color_name
FROM product_colors pc
JOIN products p ON p.id = pc.product_id
WHERE pc.product_id = 'prod_eval_2699'
  AND NOT EXISTS (
    SELECT 1 FROM product_skus s
    WHERE s.product_id = pc.product_id AND s.color_id = pc.id
      AND s.selling_method = 'bulk_cut' AND s.door_width = '2.8'
  );

-- 商品 ↔ 加工项关联（OR-016 的询问前提）
INSERT INTO product_processing_items (tenant_id, product_id, processing_item_id, custom_price, sort_order)
SELECT 1, v.pid, v.piid, NULL, v.ord
FROM (VALUES
  ('prod_eval_2699', 'pi_eval_punch', 1),
  ('prod_eval_2699', 'pi_eval_hem', 2),
  ('prod_eval_2699', 'pi_eval_iron', 3)
) AS v(pid, piid, ord)
WHERE NOT EXISTS (
  SELECT 1 FROM product_processing_items x
  WHERE x.product_id = v.pid AND x.processing_item_id = v.piid
);

-- ── 2. 加工项：刺绣工艺（PR-020 点名，自定义价 45 元/平方米）──
-- pricing_method 取值集：per_meter / per_set / fixed / per_area（无 per_piece）。
-- 平方米 = per_area；unit_price 给目录基价 30，PR-020 测的是**自定义价 45** 的落库。
INSERT INTO processing_items
  (id, tenant_id, name, category_id, pricing_method, unit_price, unit,
   min_quantity, max_quantity, description, options, ai_recommended, status, deleted)
VALUES
  ('pi_eval_embroidery', 1, '刺绣工艺', 'pcat_eval_curtain', 'per_area', 30.00, '平方米',
   1, 999, '刺绣工艺加工，按面积计价（B 端评测 fixture，PR-020 自定义价用例）',
   '[]'::jsonb, TRUE, 'active', 0)
ON CONFLICT (id) DO NOTHING;

-- 关联到 B 端常用商品（建品/下单时可选到）
INSERT INTO product_processing_items (tenant_id, product_id, processing_item_id, custom_price, sort_order)
SELECT 1, v.pid, 'pi_eval_embroidery', NULL, v.ord
FROM (VALUES
  ('prod_eval_2699', 4),
  ('prod_eval_blackout', 4)
) AS v(pid, ord)
WHERE NOT EXISTS (
  SELECT 1 FROM product_processing_items x
  WHERE x.product_id = v.pid AND x.processing_item_id = 'pi_eval_embroidery'
);

-- ── 3. 客户：张三（CU-003 打标签 / CU-004 更新资料 点名）──
INSERT INTO customer_profiles
  (id, tenant_id, wechat_nickname, phone, vip_level, customer_status, source_channel,
   r_score, f_score, m_score, rfm_total_score, total_orders, total_consumption)
VALUES
  ('cust_eval_zhangsan', 1, '张三', '13800138000', 'normal', 'active', 'wechat_mini',
   3, 3, 3, 9, 0, 0.00)
ON CONFLICT (id) DO NOTHING;

-- 标签：VIP2 / 活跃（CU-003 输入「给张三加VIP2活跃标签」——标签需已存在才能挂）
INSERT INTO customer_tags (id, tenant_id, name, color, tag_type, description)
VALUES
  ('tag_eval_vip2', 1, 'VIP2', '#faad14', 'manual', 'B 端评测 fixture：VIP2 客户标签'),
  ('tag_eval_active', 1, '活跃', '#52c41a', 'manual', 'B 端评测 fixture：活跃客户标签')
ON CONFLICT (id) DO NOTHING;

-- ── 4. 员工：王五（HR-003 停用账号 点名）──
-- 员工 = users 账号 + agent_employees 档案（employee_manage 列表按此模型查询）。
INSERT INTO users (id, tenant_id, phone, nickname, role, status, deleted)
VALUES ('debug_employee_wangwu', 1, '13700137000', '王五', 'employee', 'active', 0)
ON CONFLICT (id) DO NOTHING;

INSERT INTO agent_employees (id, tenant_id, user_id, name, phone, status, skills, deleted)
VALUES ('emp_eval_wangwu', 1, 'debug_employee_wangwu', '王五', '13700137000', 'offline', '[]'::jsonb, 0)
ON CONFLICT (id) DO NOTHING;

-- ============================================================================
-- 数据核对（CI 日志可见，避免"注入了但没生效"静默）
-- ============================================================================
DO $$
DECLARE
  v_prod   INTEGER;
  v_colors INTEGER;
  v_assoc  INTEGER;
  v_pi     INTEGER;
  v_cust   INTEGER;
  v_emp    INTEGER;
BEGIN
  SELECT count(*) INTO v_prod   FROM products          WHERE id = 'prod_eval_2699' AND deleted = 0;
  SELECT count(*) INTO v_colors FROM product_colors    WHERE product_id = 'prod_eval_2699';
  SELECT count(*) INTO v_assoc  FROM product_processing_items WHERE product_id = 'prod_eval_2699';
  SELECT count(*) INTO v_pi     FROM processing_items  WHERE id = 'pi_eval_embroidery' AND deleted = 0;
  SELECT count(*) INTO v_cust   FROM customer_profiles WHERE id = 'cust_eval_zhangsan';
  SELECT count(*) INTO v_emp    FROM agent_employees   WHERE id = 'emp_eval_wangwu' AND deleted = 0;
  RAISE NOTICE 'B 端评测 fixture 核对: 2699商品=% 颜色=% 加工项关联=% 刺绣工艺=% 客户张三=% 员工王五=%',
    v_prod, v_colors, v_assoc, v_pi, v_cust, v_emp;
  IF v_prod < 1 OR v_colors < 1 OR v_assoc < 1 THEN
    RAISE EXCEPTION 'B 端 fixture 注入失败：2699 商品/颜色/加工项关联 缺失（prod=% colors=% assoc=%）',
      v_prod, v_colors, v_assoc;
  END IF;
  IF v_cust < 1 OR v_emp < 1 THEN
    RAISE EXCEPTION 'B 端 fixture 注入失败：客户张三=% 员工王五=%', v_cust, v_emp;
  END IF;
END $$;

-- ============================================================================
-- Phase 2 TODO（#3496 剩余失败）：AS-003/AS-004/PG-013 依赖**含加工项的历史订单**，
-- 需按 6.x 的 orders/order_items 模式补 B 端种子订单（含加工项关联）。
-- 另有 HR-003 的真实失败形态是 `employee_manage!权限不足` —— 属**独立栈 debug 身份
-- 的角色权限配置缺口**（非种子问题），需在栈侧给 debug admin 身份补员工管理权限。
-- ============================================================================
