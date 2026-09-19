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
-- has_processing 列已随 #4371 解耦删除（V66 迁移 DROP COLUMN）：加工项是店铺级目录，
-- 「该商品是否绑了加工项」不再有语义 ⇒ OR-016 的询问前提改为「店铺加工项目录非空」
-- （见下方 processing_items 种子），不再依赖商品侧的信号位。
INSERT INTO products
  (id, tenant_id, name, category_id, base_price, description, images, detail_images,
   stock, stock_warning_threshold, status, unit, pricing_type, sku_code,
   stock_deduction_mode, sales_count, sales_amount, recommended)
VALUES
  ('prod_eval_2699', 1, '2699系列雪尼尔窗帘面料', 'cat_eval_curtain', 23.80,
   '雪尼尔面料，手感厚实，适合窗帘定制（B 端评测 fixture）',
   '[]'::jsonb, '[]'::jsonb, 1000, 10, 'on_sale', '米', 'per_meter', 'EVAL-2699-28',
   'on_order', 0, 0, FALSE)
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

-- ── 商品 ↔ 加工项关联：**已随 #4371 解耦删除** ──
-- 旧写法往 `product_processing_items` 写「prod_eval_2699 ↔ pi_eval_punch/hem/iron」，
-- 作为 OR-016「商品绑定加工项 ⇒ 必须主动询问加工项」的**前提**。
-- 解耦后加工项是**店铺级目录**（与商品无关），该表已由 V66 迁移 DROP，
-- OR-016 的前提改成「店铺目录里有加工项」（= 下面的 `processing_items` 种子）——
-- 目录非空即会询问，与商品是否绑过加工项无关。

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

-- 旧写法在此把刺绣工艺「关联到 B 端常用商品」（product_processing_items）——
-- 已随 #4371 解耦删除：加工项目录是店铺级，无需（也无法）挂到商品上。

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
  v_pi     INTEGER;
  v_cust   INTEGER;
  v_emp    INTEGER;
BEGIN
  SELECT count(*) INTO v_prod   FROM products          WHERE id = 'prod_eval_2699' AND deleted = 0;
  SELECT count(*) INTO v_colors FROM product_colors    WHERE product_id = 'prod_eval_2699';
  SELECT count(*) INTO v_pi     FROM processing_items  WHERE id = 'pi_eval_embroidery' AND deleted = 0;
  SELECT count(*) INTO v_cust   FROM customer_profiles WHERE id = 'cust_eval_zhangsan';
  SELECT count(*) INTO v_emp    FROM agent_employees   WHERE id = 'emp_eval_wangwu' AND deleted = 0;
  -- 加工项关联计数（v_assoc）随 #4371 解耦删除：product_processing_items 已被 V66 DROP，
  -- OR-016 的前提改为「店铺加工项目录非空」（v_pi 即该前提的读数）。
  RAISE NOTICE 'B 端评测 fixture 核对: 2699商品=% 颜色=% 刺绣工艺=% 客户张三=% 员工王五=%',
    v_prod, v_colors, v_pi, v_cust, v_emp;
  IF v_prod < 1 OR v_colors < 1 OR v_pi < 1 THEN
    RAISE EXCEPTION 'B 端 fixture 注入失败：2699 商品/颜色/加工项目录 缺失（prod=% colors=% pi=%）',
      v_prod, v_colors, v_pi;
  END IF;
  IF v_cust < 1 OR v_emp < 1 THEN
    RAISE EXCEPTION 'B 端 fixture 注入失败：客户张三=% 员工王五=%', v_cust, v_emp;
  END IF;
END $$;

-- ============================================================================
-- Phase 2（#3511）：B 端历史订单 —— AS-003（退货挂单）/ PG-013（加工单生成）
-- ============================================================================
-- 为什么需要：B 端首跑（run 34804430769）这三条失败的原因是**干净库没有可挂单/可加工的订单**：
--   · AS-003 原输入硬编码订单号「20260910619250007」（云测试环境存量数据）→ 干净库必然查不到
--     ⇒ 本 PR 同时把该用例**自包含化**（输入改为「查一下最近的订单」，见 aftersales.yml）
--   · PG-013 输入「最近有没有已确认、需要加工的订单？」→ 需要 status=confirmed 且明细带
--     processing_info 的订单存在，否则 agent 无从生成加工单（行为合理）
-- 命名/金额与 C 端 seed（xiaobu_eval_seed.sql）同风格，便于互证。
INSERT INTO orders
  (id, tenant_id, order_no, user_id, customer_name, customer_phone, customer_address,
   total_amount, status, payment_status, stock_deducted, follow_status, remark,
   created_at, updated_at, deleted)
VALUES
  ('b1c2d3e4-f5a6-4b7c-8d9e-000000000001', 1, 'EVAL-MB-ORD-0001', NULL, '张三', '13800138000',
   '浙江省杭州市西湖区文三路 1 号 1 幢 101 室', 528.00, 'completed', 'paid', TRUE,
   'completed', 'B 端评测 fixture：已完成订单（AS-003 退货挂单用）',
   TIMESTAMPTZ '2026-09-01 10:00:00+08', TIMESTAMPTZ '2026-09-05 10:00:00+08', 0),
  ('b1c2d3e4-f5a6-4b7c-8d9e-000000000002', 1, 'EVAL-MB-ORD-0002', NULL, '张三', '13800138000',
   '浙江省杭州市西湖区文三路 1 号 1 幢 101 室', 528.00, 'confirmed', 'paid', TRUE,
   'completed', 'B 端评测 fixture：已确认含加工项订单（PG-013 加工单生成用）',
   TIMESTAMPTZ '2026-09-10 10:00:00+08', TIMESTAMPTZ '2026-09-10 10:00:00+08', 0),
  -- #3658（issue #3658）：PG-013/015/016 竞态修复 —— 三条用例此前**共用** EVAL-MB-ORD-0002，
  -- 并发跑时只有一个能生成加工单成功（PG-015 实测赢、PG-013/016 吃「订单已生产中」假红）。
  -- 现各自独立订单：0002=PG-013、0003=PG-015（查）、0004=PG-016（状态流转）。
  -- 客户刻意用**不同手机号**（李四/王五），避免污染 AS-003/AS-007 的「张三 13800138000 最近订单」定位。
  ('b1c2d3e4-f5a6-4b7c-8d9e-000000000003', 1, 'EVAL-MB-ORD-0003', NULL, '李四', '13900139000',
   '浙江省杭州市拱墅区莫干山路 2 号 2 幢 202 室', 540.00, 'confirmed', 'paid', TRUE,
   'completed', 'B 端评测 fixture：已确认含加工项订单（PG-015 加工单查询用）',
   TIMESTAMPTZ '2026-09-11 10:00:00+08', TIMESTAMPTZ '2026-09-11 10:00:00+08', 0),
  ('b1c2d3e4-f5a6-4b7c-8d9e-000000000004', 1, 'EVAL-MB-ORD-0004', NULL, '王五', '13700137000',
   '浙江省杭州市滨江区江南大道 3 号 3 幢 303 室', 524.00, 'confirmed', 'paid', TRUE,
   'completed', 'B 端评测 fixture：已确认含加工项订单（PG-016 加工单状态流转用）',
   TIMESTAMPTZ '2026-09-12 10:00:00+08', TIMESTAMPTZ '2026-09-12 10:00:00+08', 0)
ON CONFLICT (id) DO NOTHING;

-- 订单明细：第二笔带 processing_info（PG-013「需要加工的订单」的判定依据）；
-- 加工项与 pi_eval_punch（纳米圈打孔 ¥8/米）一致，quantity=3 米 → subtotal=24。
-- 0003/0004 的 processing_info 分别用种子里真实存在的 pi_eval_hem（韩式波浪折边 ¥12/米，
-- quantity=3 → 36）与 pi_eval_iron（高温定型 ¥10/米，quantity=2 → 20），金额与 total 对齐。
INSERT INTO order_items
  (id, tenant_id, order_id, product_id, product_name, quantity, unit_price,
   width, height, processing_info, subtotal, deleted)
VALUES
  ('oit_mb_0001', 1, 'b1c2d3e4-f5a6-4b7c-8d9e-000000000001', 'prod_eval_blackout', '遮光窗帘',
   3, 168.00, 3.00, 2.80, NULL, 504.00, 0),
  ('oit_mb_0002', 1, 'b1c2d3e4-f5a6-4b7c-8d9e-000000000002', 'prod_eval_blackout', '遮光窗帘',
   3, 168.00, 3.00, 2.80,
   '{"colorName":"米白","sellingMethod":"bulk_cut","doorWidth":"2.8","processingItems":[{"id":"pi_eval_punch","name":"纳米圈打孔","unitPrice":8.0,"quantity":3,"unit":"米","pricingMethod":"per_meter","subtotal":24.0}],"processingFee":24.0}'::jsonb,
   504.00, 0),
  ('oit_mb_0003', 1, 'b1c2d3e4-f5a6-4b7c-8d9e-000000000003', 'prod_eval_blackout', '遮光窗帘',
   3, 168.00, 3.00, 2.80,
   '{"colorName":"米白","sellingMethod":"bulk_cut","doorWidth":"2.8","processingItems":[{"id":"pi_eval_hem","name":"韩式波浪折边","unitPrice":12.0,"quantity":3,"unit":"米","pricingMethod":"per_meter","subtotal":36.0}],"processingFee":36.0}'::jsonb,
   504.00, 0),
  ('oit_mb_0004', 1, 'b1c2d3e4-f5a6-4b7c-8d9e-000000000004', 'prod_eval_blackout', '遮光窗帘',
   3, 168.00, 3.00, 2.80,
   '{"colorName":"米白","sellingMethod":"bulk_cut","doorWidth":"2.8","processingItems":[{"id":"pi_eval_iron","name":"高温定型","unitPrice":10.0,"quantity":2,"unit":"米","pricingMethod":"per_meter","subtotal":20.0}],"processingFee":20.0}'::jsonb,
   504.00, 0)
ON CONFLICT (id) DO NOTHING;

-- 数据核对（Phase 2）
DO $$
DECLARE
  v_done   INTEGER;
  v_conf   INTEGER;
  v_conf3  INTEGER;
  v_conf4  INTEGER;
  v_proc   INTEGER;
  v_proc3  INTEGER;
  v_proc4  INTEGER;
BEGIN
  SELECT count(*) INTO v_done FROM orders
   WHERE tenant_id = 1 AND order_no = 'EVAL-MB-ORD-0001' AND deleted = 0;
  SELECT count(*) INTO v_conf FROM orders
   WHERE tenant_id = 1 AND order_no = 'EVAL-MB-ORD-0002' AND status = 'confirmed' AND deleted = 0;
  SELECT count(*) INTO v_conf3 FROM orders
   WHERE tenant_id = 1 AND order_no = 'EVAL-MB-ORD-0003' AND status = 'confirmed' AND deleted = 0;
  SELECT count(*) INTO v_conf4 FROM orders
   WHERE tenant_id = 1 AND order_no = 'EVAL-MB-ORD-0004' AND status = 'confirmed' AND deleted = 0;
  SELECT count(*) INTO v_proc FROM order_items
   WHERE order_id = 'b1c2d3e4-f5a6-4b7c-8d9e-000000000002'
     AND processing_info IS NOT NULL AND deleted = 0;
  SELECT count(*) INTO v_proc3 FROM order_items
   WHERE order_id = 'b1c2d3e4-f5a6-4b7c-8d9e-000000000003'
     AND processing_info IS NOT NULL AND deleted = 0;
  SELECT count(*) INTO v_proc4 FROM order_items
   WHERE order_id = 'b1c2d3e4-f5a6-4b7c-8d9e-000000000004'
     AND processing_info IS NOT NULL AND deleted = 0;
  RAISE NOTICE 'B 端 Phase 2 核对: 已完成订单=% 已确认订单(0002/0003/0004)=%/ %/ % 含加工项明细(0002/0003/0004)=%/ %/%',
    v_done, v_conf, v_conf3, v_conf4, v_proc, v_proc3, v_proc4;
  IF v_done < 1 OR v_conf < 1 OR v_proc < 1
     OR v_conf3 < 1 OR v_proc3 < 1 OR v_conf4 < 1 OR v_proc4 < 1 THEN
    RAISE EXCEPTION 'B 端 Phase 2 注入失败：已完成=% 已确认=% 含加工项=%（0003: %/% 0004: %/%）',
      v_done, v_conf, v_proc, v_conf3, v_proc3, v_conf4, v_proc4;
  END IF;
END $$;

-- ============================================================================
-- Phase 3（#3519）：B 端未处理售后工单 —— AS-004（关闭第一张未处理工单）
-- ============================================================================
-- 为什么需要：独立栈首跑 AS-004 实测 `after_sales_manage(action=list)` →
--   `After-sales list: page=1, size=10, total=0` → agent 如实回「没有工单」→ 用例判红。
--   **行为正确，缺的是数据**：干净库 after_sales_tickets 为空（C 端 xiaobu_eval_seed.sql
--   也不含工单），「第一张未处理工单」无从指代。与 Phase 2 的 OR-016/AS-003 同源归因。
--
-- 为什么是 orders 里新插一笔订单（而不是复用 Phase 2 的 EVAL-MB-ORD-0001）：
--   AfterSalesTicketService.createTicket 有「同订单同类型活跃工单」防重护栏
--   （order_id 上存在 pending/processing 的 return 工单即拒建），而 AS-003 会
--   对「最近订单」挂退货工单。若复用 0001，AS-003 先跑时可能正好选中
--   0001 收货单 → 撞上本 fixture 的 pending return 工单 → 假失败。
--   故用独立订单 EVAL-MB-ORD-0005（同客户张三）承载本次工单，与 Phase 2 互不干扰（#4259 改用唯一 id/order_no，缘由见本段末「#4259 修正说明」）。
-- 同理 created_at 必须**早于** Phase 2 两单：订单列表按 created_at DESC 排序
--   （OrderService:214，order_query list 默认取第 1 页），AS-003 的「最近的订单」会命中
--   最新一笔 —— 若本 fixture 订单成了最新，AS-003 又会跑到挂单撞防重护栏。故钉在 09-01。
--
-- 幂等：ON CONFLICT (id) DO NOTHING；ticket_timeline 以 (ticket_id, action) 去重。
-- 说明：不做 status 翻转（不把已关闭工单改回 pending）—— 测试不修改生产语义的数据，
--   存量被消耗（AS-004 关闭本工单后重跑）交由用例侧 pre_clean 的
--   aftersales_ticket_prepare 补建（local_runner.py 已实现）。
INSERT INTO orders
  (id, tenant_id, order_no, user_id, customer_name, customer_phone, customer_address,
   total_amount, status, payment_status, stock_deducted, follow_status, remark,
   created_at, updated_at, deleted)
VALUES
  ('b1c2d3e4-f5a6-4b7c-8d9e-000000000005', 1, 'EVAL-MB-ORD-0005', NULL, '张三', '13800138000',
   '浙江省杭州市西湖区文三路 1 号 1 幢 101 室', 528.00, 'completed', 'paid', TRUE,
   'completed', 'B 端评测 fixture：承载 AS-004 未处理工单的已完成订单（#3519，须早于 Phase 2 两单；独立 id/order_no 见 #4259）',
   TIMESTAMPTZ '2026-09-01 09:00:00+08', TIMESTAMPTZ '2026-09-01 09:00:00+08', 0)
ON CONFLICT (id) DO NOTHING;

-- 未处理（pending）退货工单：AS-004 第 2 轮「把第一张未处理的工单关闭」的指代对象。
-- 列核对（docs/sql/schema.sql:604~630 + V8/V25 迁移）：显式给出 id/tenant_id/ticket_no/
--   order_id/customer_id/ticket_type/status/source/priority/description/images/
--   refund_amount/evidence_images/created_at/updated_at/deleted。
--   · ticket_type 是**唯一 NOT NULL 且无默认值**的业务列（id/tenant_id 同理必给；其余
--     列皆有 DEFAULT 或可空），故必须显式给（'return' ∈ 列注释枚举 return/exchange/
--     repair/complaint）；
--   · images/evidence_images 有 DEFAULT '[]'，显式给 '[]'::jsonb 与之同型（JSONB），
--     避免空值字段被前端/工具当 null 处理；
--   · refund_amount=528.00（= 订单总额）让用例输入「客户要退货」与工单语义自洽；
--     ⚠️ 副作用提示：该单若被置为 resolved（而非本用例的 closed），
--     linkRefundToOrderAndFinance 会把 528 累加进订单退款额并登记退款流水 ——
--     只影响评测栈 seed 数据，勿在验收栈误走 resolved 分支。
--   · 不给 handler_id（可空，但给错值会撞 agent_employees 外键）、不给 close_reason/
--     internal_notes（建单时本无备注，避免与真值文档语义冲突）；
--   · deleted=0 与 MyBatis @TableLogic 一致（默认查询过滤 deleted=0）。
INSERT INTO after_sales_tickets
  (id, tenant_id, ticket_no, order_id, customer_id, ticket_type, status, source, priority,
   description, images, refund_amount, evidence_images, created_at, updated_at, deleted)
VALUES
  ('tkt_eval_as_9001', 1, 'AS-20260914-9001', 'b1c2d3e4-f5a6-4b7c-8d9e-000000000005',
   'cust_eval_zhangsan', 'return', 'pending', 'customer', 'normal',
   'B 端评测 fixture：遮光窗帘尺寸不符申请退货，待处理（AS-004 关闭未处理工单用例，issue #3519）',
   '[]'::jsonb, 528.00, '[]'::jsonb,
   TIMESTAMPTZ '2026-09-14 09:30:00+08', TIMESTAMPTZ '2026-09-14 09:30:00+08', 0)
ON CONFLICT (id) DO NOTHING;

-- 建单时间线（可选，非 AS-004 断言依赖）：schema.sql:633 的 ticket_timeline 只有
--   id/tenant_id/ticket_id/action/actor_type 非空（V8 给 actor_type 补了 DEFAULT 'system'，
--   但这里显式给出，避免 V8 未应用的库上落空值）。
-- 为什么仍然插：售后详情的 statusHistory 由 ticket_timeline 渲染（AS-002 断言
--   「statusHistory 首条 status=pending」），工单没有任何时间线时该链路只剩空历史；
--   本行让新工单在详情页呈现一致。幂等键 (ticket_id, action) 在库中无唯一约束，故用
--   WHERE NOT EXISTS 去重（重复执行不会累积重复时间线）。
INSERT INTO ticket_timeline
  (id, tenant_id, ticket_id, action, actor_type, content, created_at, updated_at)
SELECT 'ttl_eval_as_9001_created', 1, t.id, 'created', 'customer',
       jsonb_build_object('status', 'pending', 'source', 'eval_fixture',
                          'remark', 'B 端评测 fixture 建单（#3519）'),
       TIMESTAMPTZ '2026-09-14 09:30:00+08', TIMESTAMPTZ '2026-09-14 09:30:00+08'
FROM after_sales_tickets t
WHERE t.id = 'tkt_eval_as_9001'
  AND NOT EXISTS (
    SELECT 1 FROM ticket_timeline x
    WHERE x.ticket_id = t.id AND x.action = 'created'
  );

-- 数据核对（Phase 3）
DO $$
DECLARE
  v_ord      INTEGER;
  v_pending  INTEGER;
  v_timeline INTEGER;
BEGIN
  -- 承载订单：**必须三合一**（issue #4259）—— ① 按 order_no 找得到；② 它正是工单挂的那张；
  --   ③ 它的客户 = 工单的客户。旧口径只核 ①，而本段原先与 Phase 2 撞 id 时 ① 仍然 = 1
  --   （数到的是 Phase 2 的李四单）⇒ 「静默少插一行」对这条核对**结构性不可见**。
  SELECT count(*) INTO v_ord FROM orders o
   WHERE o.tenant_id = 1 AND o.order_no = 'EVAL-MB-ORD-0005' AND o.deleted = 0
     AND o.id = (SELECT t.order_id FROM after_sales_tickets t
                  WHERE t.tenant_id = 1 AND t.ticket_no = 'AS-20260914-9001'
                    AND t.deleted = 0)
     AND o.customer_phone = (SELECT c.phone FROM customer_profiles c
                              WHERE c.id = (SELECT t.customer_id FROM after_sales_tickets t
                                             WHERE t.tenant_id = 1
                                               AND t.ticket_no = 'AS-20260914-9001'
                                               AND t.deleted = 0));
  -- 判据沿用工具真实查询口径（status='pending' + deleted=0；多租户过滤由
  -- TenantLineInnerInterceptor 按下发身份注入，此处按 tenant_id=1 核对）
  SELECT count(*) INTO v_pending FROM after_sales_tickets
   WHERE tenant_id = 1 AND ticket_no = 'AS-20260914-9001'
     AND status = 'pending' AND deleted = 0;
  SELECT count(*) INTO v_timeline FROM ticket_timeline
   WHERE tenant_id = 1 AND ticket_id = 'tkt_eval_as_9001' AND action = 'created';
  RAISE NOTICE 'B 端 Phase 3 核对: 承载订单(存在∧是工单挂的∧客户同族)=% 未处理工单=% 建单时间线=%',
    v_ord, v_pending, v_timeline;
  IF v_ord < 1 OR v_pending < 1 THEN
    RAISE EXCEPTION 'B 端 Phase 3 注入失败：AS-004 需要的 pending 工单或其承载订单不成立
（承载订单=% 工单=%）', v_ord, v_pending;
  END IF;
END $$;

-- #4259 修正说明（本段原先的缺陷，留档防复发）：
--   · 旧形态：本段复用 Phase 2 的 id `…-000000000003` 与 order_no `EVAL-MB-ORD-0003`
--     （注释却写「同客户张三」）⇒ `ON CONFLICT (id) DO NOTHING` 按 **id** 去重、**先到者胜**：
--     真正生效的是 Phase 2 那行（李四 / 13900139000），本段整行被**静默丢弃**
--     （不报错、不警告）⇒ 注释描述的是一个**从未被插入的状态**，而库里也真的少插了一行。
--   · 现形态：唯一 id `…-000000000005` + order_no `EVAL-MB-ORD-0005`，客户 = 张三 /
--     13800138000（与工单的 `customer_id = cust_eval_zhangsan` 同族）。
--   · 判据（静态）：tests/unit_ci_workflows/test_declaration_truth_guards.py
--     （逐条核「每个 EVAL-MB-ORD-* 的声明行真的会生效」+「注释客户 = 实际生效行」+ 工单同族）；
--     判据（运行期）：上方 Phase 3 DO 块的「承载订单三合一」计数 —— 回注该缺陷时它会
--     RAISE EXCEPTION（实测 `psql -v ON_ERROR_STOP=1` exit=3，种子步骤 fail-fast）。

-- ============================================================================
-- 遗留 TODO（#3496 / #3519 剩余失败）：
--   · AS-004 工单 seed —— ✅ 已完成（本文件 Phase 3 段，issue #3519）。
--     ⚠️ 数据到位 ≠ 用例必过，另有 2 个**非种子**缺口需单独处理（本次已核实，勿误判为
--        数据缺失）：① 状态机护栏 `AfterSalesTicketService.STATUS_TRANSITIONS`
--        （schema.sql 同源）pending → 仅 processing/rejected，**不许直跳 closed** ——
--        而 AS-004 第 2 轮输入正是「把第一张未处理的工单关闭」；若 agent 走
--        update_status(pending→closed)，admin-api 会回「不允许从 [待处理] 变更为 [已关闭]」。
--        需产品确认：是放宽流转（pending→closed）还是在用例/引导层改（先转处理中再关闭）。
--        ② 字段名跨层不一致：`after_sales_manage._update_status` 下发 `reason`，
--        而 admin-api `AfterSalesStatusUpdateRequest` 只接 `remark` → 即使流转成功，
--        AS-004 断言的 `closeReason` 也不会落库（closedAt 会）。
--   · HR-003 真实失败形态是 `employee_manage!权限不足` —— 属**独立栈评测身份的角色权限
--     配置缺口**（非种子，见 #3511 评论的机制定位：tool 需 allowed_roles/employee:list，
--     默认岗位由 Flyway V29/V32 种入 → 需在栈侧授予评测身份含该权限的岗位；
--     **不得放宽工具护栏**）
--   · PR-016（applicable_category_id 未传）待重放判别：真行为缺口 → 修引导；等价变体 → 校准断言
-- ============================================================================
