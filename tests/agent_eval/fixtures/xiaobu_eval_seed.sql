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

-- ============================================================================
-- 6. C 端顾客本人 + 历史订单（issue #3270 —— 数据层缺口，非能力缺陷）
-- ============================================================================
-- 为什么必须有这一段（不是"锦上添花"）：
--   C 端身份由 auth.py 的 DEBUG 降级固定注入 user_id='debug_customer_1'，
--   而全新 bootstrap 空库里**没有任何属于该用户的订单**，于是：
--     ① `customer_address_query` 取"最近一笔有地址的订单" → 永远未命中 →
--        form 无法预填 → agent 只能反复追问/反复重试
--        （实测 CH-010/OR-009/OR-011/OR-014 出现 customer_address_query ×3~4 次空转）；
--     ② `aftersale_create` 的**订单归属校验**（#518）先拉
--        GET /api/admin/agent/orders/mine 再匹配 order_id → 空库必不匹配 →
--        一律返回「该订单不属于您」→ **售后建单在该库里根本不可能成功**
--        （CH-012 实测 4 轮 0 建单）；
--     ③ `customer_order_query` 列表为空 → 顾客说"第一笔订单"无从指代。
--   这三条都是**测量环境缺数据**，不是 agent 能力问题。补数据后才能测得真实能力。
--
-- 幂等：ON CONFLICT DO NOTHING / WHERE NOT EXISTS，可重复执行。
-- 仅用于评测栈，不并入 docs/sql/schema.sql（生产 bootstrap 不应含演示数据）。
-- ============================================================================

-- 6.1 C 端顾客（与 auth.py DEBUG customer 身份 user_id 严格一致）
INSERT INTO users (id, tenant_id, phone, nickname, role, status, deleted)
VALUES ('debug_customer_1', 1, '13800138000', '评测顾客', 'customer', 'active', 0)
ON CONFLICT (id) DO NOTHING;

-- 6.2 历史订单 ×2：一笔已完成（地址预填 + 售后可建单）、一笔已发货（物流查询）
--     user_id 必须是 debug_customer_1 —— 这是 C 端数据隔离的唯一依据。
--     ⚠️ created_at **必须显式给值且两笔不同**：`customer_order_query` 按
--        `ORDER BY created_at DESC` 排序，顾客说「最近那笔/第一笔」时取列表首条。
--        若两笔同刻（NOW() 默认值），顺序不确定 → 用例随机命中不同订单 → 抖动。
--     设定：0001 已完成（较早）→ 0002 已发货（最新，作为「最近一笔」命中），
--     顺带覆盖 skill prompt 里「已发货订单仍可建售后工单」这条历史回归规则。
INSERT INTO orders
  (id, tenant_id, order_no, user_id, customer_name, customer_phone, customer_address,
   total_amount, status, payment_status, stock_deducted, follow_status, remark,
   created_at, updated_at, deleted)
VALUES
  ('ord_eval_0001', 1, 'EVAL-ORD-0001', 'debug_customer_1', '张三', '13800138000',
   '浙江省杭州市西湖区文三路 1 号 1 幢 101 室', 504.00, 'completed', 'paid', TRUE,
   'completed', 'C 端评测 fixture：已完成订单（地址预填 / 售后建单用）',
   TIMESTAMPTZ '2026-08-01 10:00:00+08', TIMESTAMPTZ '2026-08-05 10:00:00+08', 0),
  ('ord_eval_0002', 1, 'EVAL-ORD-0002', 'debug_customer_1', '张三', '13800138000',
   '浙江省杭州市西湖区文三路 1 号 1 幢 101 室', 384.00, 'shipped', 'paid', TRUE,
   'completed', 'C 端评测 fixture：已发货订单（物流查询 / 最近一笔用）',
   TIMESTAMPTZ '2026-09-01 10:00:00+08', TIMESTAMPTZ '2026-09-09 18:00:00+08', 0)
ON CONFLICT (id) DO NOTHING;

-- 6.3 订单明细（列表/详情展示、售后关联商品）
INSERT INTO order_items
  (id, tenant_id, order_id, product_id, product_name, quantity, unit_price,
   width, height, subtotal, deleted)
VALUES
  ('oit_eval_0001', 1, 'ord_eval_0001', 'prod_eval_blackout', '遮光窗帘', 3, 168.00,
   3.00, 2.80, 504.00, 0),
  ('oit_eval_0002', 1, 'ord_eval_0002', 'prod_eval_dark_green', '北欧风窗帘', 3, 128.00,
   3.00, 2.80, 384.00, 0)
ON CONFLICT (id) DO NOTHING;

-- 6.4 物流轨迹（已发货订单的物流查询用例数据源）
INSERT INTO order_logistics
  (id, tenant_id, order_id, logistics_company, tracking_no, status, tracking_info, shipped_at)
SELECT 'olg_eval_0002', 1, 'ord_eval_0002', '顺丰速运', 'SF1234567890123', 'in_transit',
       '[{"time":"2026-09-10 09:00","desc":"快件已从杭州中转场发出"}]'::jsonb,
       TIMESTAMPTZ '2026-09-09 18:00:00+08'
WHERE NOT EXISTS (
  SELECT 1 FROM order_logistics WHERE order_id = 'ord_eval_0002'
);

-- ── 数据核对（CI 日志可见，避免"注入了但没生效"静默）──
DO $$
DECLARE
  v_orders INTEGER;
  v_items  INTEGER;
BEGIN
  SELECT count(*) INTO v_orders FROM orders
   WHERE tenant_id = 1 AND user_id = 'debug_customer_1' AND deleted = 0;
  SELECT count(*) INTO v_items FROM order_items WHERE tenant_id = 1 AND deleted = 0;
  RAISE NOTICE 'C 端评测 fixture 核对: debug_customer_1 订单=% 明细=%', v_orders, v_items;
  IF v_orders < 2 THEN
    RAISE EXCEPTION 'C 端 fixture 注入失败：debug_customer_1 订单数=% (<2)', v_orders;
  END IF;
END $$;
