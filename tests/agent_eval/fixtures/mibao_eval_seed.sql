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
-- 仅用于评测栈，**不并入** backend/admin-api/src/main/resources/db/init/schema.sql（生产 bootstrap 不应含演示数据）。
-- ============================================================================

-- ── 1. 商品：2699 系列雪尼尔窗帘面料（OR-016 点名）──
-- 名称必须含「2699系列雪尼尔窗帘面料」（用例输入原文）；价格 23.80 取生产同款量级。
-- has_processing 列已随 #4371 解耦删除（V66 迁移 DROP COLUMN）：加工项是店铺级目录，
-- 「该商品是否绑了加工项」不再有语义 ⇒ OR-016 的询问前提改为「店铺加工项目录非空」
-- （见下方 processing_items 种子），不再依赖商品侧的信号位。
-- V111（用户裁定 2026-09-21）：售卖方式 `selling_methods` 与 `roll_length_m`（1 卷 = 多少米）
-- 都是**商品货号级基础参数**（不再是 SKU 组合维度）⇒ 必须在 products 行上给值。
INSERT INTO products
  (id, tenant_id, name, category_id, base_price, description, images, detail_images,
   stock, stock_warning_threshold, status, unit, pricing_type, sku_code,
   stock_deduction_mode, sales_count, sales_amount, recommended,
   selling_methods, roll_length_m)
VALUES
  ('prod_eval_2699', 1, '2699系列雪尼尔窗帘面料', 'cat_eval_curtain', 23.80,
   '雪尼尔面料，手感厚实，适合窗帘定制（B 端评测 fixture）',
   '[]'::jsonb, '[]'::jsonb, 1000, 10, 'on_sale', '米', 'per_meter', 'EVAL-2699-28',
   'on_order', 0, 0, FALSE, '["bulk_cut", "full_roll"]'::jsonb, 60.00)
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

-- V111：`product_skus.selling_method` 列已删除（售卖方式上移为 products.selling_methods），
-- 唯一键 = (product_id, color_id, door_width) ⇒ 本 INSERT 不得再写该列。
INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT 1, pc.product_id, pc.id, pc.color_name, '2.8', p.base_price, 500,
       p.sku_code || '-' || pc.color_name
FROM product_colors pc
JOIN products p ON p.id = pc.product_id
WHERE pc.product_id = 'prod_eval_2699'
  AND NOT EXISTS (
    SELECT 1 FROM product_skus s
    WHERE s.product_id = pc.product_id AND s.color_id = pc.id
      AND s.door_width = '2.8'
  );

-- ── 商品 ↔ 加工项关联：**已随 #4371 解耦删除** ──
-- 旧写法往 `product_processing_items` 写「prod_eval_2699 ↔ pi_eval_punch/hem/iron」，
-- 作为 OR-016「商品绑定加工项 ⇒ 必须主动询问加工项」的**前提**。
-- 解耦后加工项是**店铺级目录**（与商品无关），该表已由 V66 迁移 DROP，
-- OR-016 的前提改成「店铺目录里有加工项」（= 下面的 `processing_items` 种子）——
-- 目录非空即会询问，与商品是否绑过加工项无关。

-- ── 2. 加工项 `pi_eval_embroidery`（刺绣工艺，per_area）**已按用户裁定真删** ──
-- 用户裁定（2026-09-19，二次裁定「**真删**」）：该行**删除**（不是注释掉）⇒ 评测栈的加工项
--   目录**只保留 ERP 附件那 16 项**（全 `per_meter`）。
-- ⚠️ **覆盖损失（如实登记，不许粉饰）**：**`per_area` 计价路径的评测覆盖随本夹具删除而移除**
--   （原接地对象 = PP-009 `calculate_price` 的 `totalPrice=240.00`、OR-028 的 per_area
--   8.4㎡=252.00、`local_runner` 的 `processingItemConfigs.<项>.finalPrice` 夹具）。
--   这 3 处断言已按 **per_meter** 重算改判（逐处见各 case 的 `merge_log`）。
--   **若要恢复 per_area 覆盖**：需**新增一个显式标注为评测夹具**的 per_area 项 ——
--   本单**不**自行新造（用户要的是删）。
-- 历史（删除前的口径，留档）：`pricing_method` 取值集 per_meter / per_set / fixed / per_area
--   （无 per_piece）；本项曾是「自定义价」与 `calculate_price` 的唯一 per_area 接地对象
--   （`per_area` / 30.00 元/平方米）。

-- ── 2. 加工项：**只保留 3 条目录评测夹具**（ERP 目录 16 项一律由 V83 提供）──
-- 背景（issue #4571/#4572）：用户提问「加工项的测试数据为嘛还未重建完」⇒ 真库实测发现
--   **重名冲突**：ERP 加工项目录**已由 V83 迁移**为每个活跃租户种过 16 项（含 tenant 1）
--   ⇒ 评测种子**不得再插一遍** —— 真库实测「种子插 16 行」会让每个名字**两行**
--   （`打孔` = `pi_eval_punch` ¥8 与 `pi-v83-1-01` ¥0）⇒
--     ① `processing_item_query(打孔)` 返 2 条、金额断言不确定；
--     ② `processing_item_count_for_keyword: 打孔, expect: 1`（PP-008 前置）**运行期必红**。
--
-- 裁定口径（2026-09-19）：
--   · **ERP 目录 16 项一律由 V83 提供**（产品口径不动：目录无价，R10）；
--     其余 13 项（`韩定+S钩`/`穿杆`/`平幔`/`花边`/`扣环`/`接高`/`拼接`/`双眼皮`/`缎带`/
--     `换货`/`超高`/`超宽`/`倒幅`）**不在本文件重复插入**。
--   · 评测种子**只保留 3 条目录夹具**（`打孔` ¥8/米 · `韩折` ¥12/米 · `定型` ¥10/米，
--     id 仍是 `pi_eval_punch`/`pi_eval_hem`/`pi_eval_iron`）—— 评测夹具的职责是给 eval 断言
--     提供**金额接地**（订单总额 / 加工费 / `calculate_price`），产品侧「目录无价」不适用于夹具；
--     **id 保留** ⇒ 引用面最小（金额断言逐值不变：OR-014 的 528 = 168×3 + 8×3 等）。
--   · 插入**之前**先删掉 V83 为这 3 个名字种的行 ⇒ **同名只有一行**。
--     ⚠️ **两种执行顺序都安全**（双保险，不是只靠 DELETE）：
--       ① 先注种子后跑 V83 ⇒ V83 的 `NOT EXISTS (tenant_id, name)` 业务键去重会**跳过**这 3 项；
--       ② 先跑 V83 后注种子 ⇒ 本 DELETE 把 V83 那 3 行删掉再插带价行。
--     V83 没跑过时 DELETE 影响 0 行（安全）；`processing_items` **没有任何外键引用它**
--     （已核 `backend/admin-api/src/main/resources/db/init/schema.sql` 的 `REFERENCES processing_items` = 0 命中）。
--   · `刺绣工艺`（`pi_eval_embroidery`，per_area）**已按用户裁定真删** —— 它原是 PR-020 /
--     PP-009 / OR-028 的 per_area 接地对象，那 3 处已按 **per_meter** 重算改判；
--     **per_area 计价路径的评测覆盖随之移除**（逐处登记在各 case 的 `merge_log`）。
--
-- 守卫 = `tests/unit_ci_workflows/test_eval_seed_catalog.py`：判「种子**不**插入 V83 已种的
--   名字」+「3 条目录夹具在」+「`DELETE … pi-v83-%` 那行在且在 INSERT 之前」+「真库无重名」。
-- 幂等：`ON CONFLICT (id) DO NOTHING`（与本节既有写法一致）。
DELETE FROM processing_items
 WHERE tenant_id = 1 AND name IN ('打孔', '韩折', '定型') AND id LIKE 'pi-v83-%';
-- #4882（用户裁定）：加工项目录**不再有** `pricing_method` / `unit_price`（V101 已删列）⇒
--   本夹具的 INSERT **不得**再写这两列（写了真库直接 `column does not exist`）。
--   保留下来的 3 条（打孔 / 韩折 / 定型）职责改为：给按名字定位的用例提供**目录接地对象**
--   （`unit='米'` / `status='active'` / `craft_hint`），**不再是金额接地** —— 加工项已无价，
--   金额接地真值源是「加工费组合」（R10）。

INSERT INTO processing_items
  (id, tenant_id, name, category_id, unit,
   min_quantity, max_quantity, description, craft_hint, options, ai_recommended, status, deleted)
VALUES
  ('pi_eval_punch', 1, '打孔', 'pcat_eval_curtain', '米',
   1, 999, '顶部打孔（#4572 由「纳米圈打孔」改名到 ERP 逐字名；价格保留，同名 V83 行已删）', '打孔', '[]'::jsonb, TRUE, 'active', 0),
  ('pi_eval_hem', 1, '韩折', 'pcat_eval_curtain', '米',
   1, 999, '韩式褶皱（#4572 由「韩式波浪折边」改名到 ERP 逐字名；价格保留，同名 V83 行已删）', '韩褶', '[]'::jsonb, TRUE, 'active', 0),
  ('pi_eval_iron', 1, '定型', 'pcat_eval_curtain', '米',
   1, 999, '高温定型加工（#4572 由「高温定型」改名到 ERP 逐字名；价格保留，同名 V83 行已删）', NULL, '[]'::jsonb, TRUE, 'active', 0)
ON CONFLICT (id) DO NOTHING;

-- ── 目录去冲突自检（**真库口径**，fail-fast；判据 a/b）──
-- 真库实测（#4572）：重复插 V83 已种的名字会让每个名字**两行** ⇒
-- `processing_item_count_for_keyword: 打孔, expect: 1`（PP-008 前置）**运行期必红**。
-- 本块把「无重名」+「3 项各恰好 1 行且带价」钉成**运行期**断言 —— 静态守卫看不见 SQL 执行结果
-- （#4514 同族：静态全绿而真库必红）。
DO $$
DECLARE
  v_dup INTEGER;
  v_n   INTEGER;
BEGIN
  SELECT count(*) INTO v_dup FROM (
    SELECT name FROM processing_items
     WHERE tenant_id = 1 AND deleted = 0
     GROUP BY name HAVING count(*) > 1) d;
  IF v_dup > 0 THEN
    RAISE EXCEPTION '目录去冲突失败：tenant 1 有 % 个重名加工项（V83 与评测夹具同名未去重）', v_dup;
  END IF;
  SELECT count(*) INTO v_n FROM processing_items
   WHERE tenant_id = 1 AND deleted = 0
     AND ((id = 'pi_eval_punch' AND name = '打孔' AND unit = '米')
       OR (id = 'pi_eval_hem'   AND name = '韩折' AND unit = '米')
       OR (id = 'pi_eval_iron'  AND name = '定型' AND unit = '米'));
  IF v_n <> 3 THEN
    RAISE EXCEPTION '目录评测夹具不成立：应恰好 3 条（打孔 / 韩折 / 定型，均 unit=米），实为 %', v_n;
  END IF;
  RAISE NOTICE '加工项目录去冲突核对: tenant1 重名=0 目录夹具=3/3';
END $$;


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

-- ── 3b. 客户：王五（CU-005「模糊名 → 澄清 → 搜到真人 → 拿 customer_id」的点名对象）──
-- 为什么补（#5030 的 case-trust burn-down 缴费用）：CU-005 原写「就是王建国」，而评测栈是
-- **全新库 + 固定 seed**（`.github/workflows/post-deploy-eval.yml`）⇒ 考场里根本没有这个客户，
-- 用例的期望链（客户列表搜到人 → 查其订单 → 发货）**物理不可满足**。王五 是本种子里**已有**的
-- 员工/订单客户名（`emp_eval_wangwu` / `EVAL-MB-ORD-0004`）⇒ 补一条客户档案即让该链路可达。
INSERT INTO customer_profiles
  (id, tenant_id, wechat_nickname, phone, vip_level, customer_status, source_channel,
   r_score, f_score, m_score, rfm_total_score, total_orders, total_consumption)
VALUES
  ('cust_eval_wangwu', 1, '王五', '13700137000', 'normal', 'active', 'wechat_mini',
   0, 0, 0, 0, 0, 0.00)
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
  v_cust_w INTEGER;
BEGIN
  SELECT count(*) INTO v_prod   FROM products          WHERE id = 'prod_eval_2699' AND deleted = 0;
  SELECT count(*) INTO v_colors FROM product_colors    WHERE product_id = 'prod_eval_2699';
  -- 读数改为**ERP 加工项目录**（issue #4572：编造夹具 `pi_eval_embroidery` 已按用户裁定删除
  -- ⇒ 不能再拿它当「目录非空」的读数）。前提口径不变：目录非空即会询问加工项（#4371 解耦后
  -- 加工项是店铺级目录，与商品是否绑过无关）。
  -- 目录 = **16 项**（#4572 裁定后：**V83 提供全部 16 项**，其中 `打孔`/`韩折`/`定型`
  -- 三行被本种子的**目录夹具**替换 —— 故整表仍是 16 行）。
  SELECT count(*) INTO v_pi     FROM processing_items  WHERE tenant_id = 1 AND deleted = 0;
  SELECT count(*) INTO v_cust   FROM customer_profiles WHERE id = 'cust_eval_zhangsan';
  SELECT count(*) INTO v_emp    FROM agent_employees   WHERE id = 'emp_eval_wangwu' AND deleted = 0;
  -- CU-005 的点名对象之一（#5030 缴费用）：客户档案「王五」。
  -- ⚠️ 另一个点名对象（其**无加工项**的可发货订单 `EVAL-MB-ORD-0006`）**不在本块核对**：
  --   该订单由 **Phase 3** 才 INSERT，而本块在 Phase 1 ⇒ 「自检早于被检查对象」会让
  --   `psql -v ON_ERROR_STOP=1` 在本块当场中止（issue #5501 的真库实测形态，rc=3）。
  --   ⇒ 该读数已随它的 INSERT 挪到 Phase 3 的自检块（判据见文件末尾「#5501 修正说明」）。
  SELECT count(*) INTO v_cust_w FROM customer_profiles WHERE id = 'cust_eval_wangwu';
  -- 加工项关联计数（v_assoc）随 #4371 解耦删除：product_processing_items 已被 V66 DROP，
  -- OR-016 的前提改为「店铺加工项目录非空」（v_pi 即该前提的读数）。
  RAISE NOTICE 'B 端评测 fixture 核对: 2699商品=% 颜色=% 加工项目录=% 客户张三=% 员工王五=% 客户王五=%',
    v_prod, v_colors, v_pi, v_cust, v_emp, v_cust_w;
  IF v_prod < 1 OR v_colors < 1 OR v_pi < 16 THEN   -- 16 = ERP 目录项数（见上）
    RAISE EXCEPTION 'B 端 fixture 注入失败：2699 商品/颜色/加工项目录 缺失（prod=% colors=% pi=%）',
      v_prod, v_colors, v_pi;
  END IF;
  IF v_cust < 1 OR v_emp < 1 OR v_cust_w < 1 THEN
    RAISE EXCEPTION 'B 端 fixture 注入失败：客户张三=% 员工王五=% 客户王五=%',
      v_cust, v_emp, v_cust_w;
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
   total_amount, status, follow_status, remark,
   created_at, updated_at, deleted)
VALUES
  ('b1c2d3e4-f5a6-4b7c-8d9e-000000000001', 1, 'EVAL-MB-ORD-0001', NULL, '张三', '13800138000',
   '浙江省杭州市西湖区文三路 1 号 1 幢 101 室', 528.00, 'completed', 'completed', 'B 端评测 fixture：已完成订单（AS-003 退货挂单用）',
   TIMESTAMPTZ '2026-09-01 10:00:00+08', TIMESTAMPTZ '2026-09-05 10:00:00+08', 0),
  ('b1c2d3e4-f5a6-4b7c-8d9e-000000000002', 1, 'EVAL-MB-ORD-0002', NULL, '张三', '13800138000',
   '浙江省杭州市西湖区文三路 1 号 1 幢 101 室', 528.00, 'confirmed', 'completed', 'B 端评测 fixture：已确认含加工项订单（PG-013 加工单生成用）',
   TIMESTAMPTZ '2026-09-10 10:00:00+08', TIMESTAMPTZ '2026-09-10 10:00:00+08', 0),
  -- #3658（issue #3658）：PG-013/015/016 竞态修复 —— 三条用例此前**共用** EVAL-MB-ORD-0002，
  -- 并发跑时只有一个能生成加工单成功（PG-015 实测赢、PG-013/016 吃「订单已生产中」假红）。
  -- 现各自独立订单：0002=PG-013、0003=PG-015（查）、0004=PG-016（状态流转）。
  -- 客户刻意用**不同手机号**（李四/王五），避免污染 AS-003/AS-007 的「张三 13800138000 最近订单」定位。
  ('b1c2d3e4-f5a6-4b7c-8d9e-000000000003', 1, 'EVAL-MB-ORD-0003', NULL, '李四', '13900139000',
   '浙江省杭州市拱墅区莫干山路 2 号 2 幢 202 室', 540.00, 'confirmed', 'completed', 'B 端评测 fixture：已确认含加工项订单（PG-015 加工单查询用）',
   TIMESTAMPTZ '2026-09-11 10:00:00+08', TIMESTAMPTZ '2026-09-11 10:00:00+08', 0),
  ('b1c2d3e4-f5a6-4b7c-8d9e-000000000004', 1, 'EVAL-MB-ORD-0004', NULL, '王五', '13700137000',
   '浙江省杭州市滨江区江南大道 3 号 3 幢 303 室', 524.00, 'confirmed', 'completed', 'B 端评测 fixture：已确认含加工项订单（PG-016 加工单状态流转用）',
   TIMESTAMPTZ '2026-09-12 10:00:00+08', TIMESTAMPTZ '2026-09-12 10:00:00+08', 0)
ON CONFLICT (id) DO NOTHING;

-- 订单明细：第二笔带 processing_info（PG-013「需要加工的订单」的判定依据）；
-- 加工项与 pi_eval_punch（打孔 ¥8/米）一致，quantity=3 米 → subtotal=24。
-- 0003/0004 的 processing_info 分别用种子里真实存在的 pi_eval_hem（韩折 ¥12/米，
-- quantity=3 → 36）与 pi_eval_iron（定型 ¥10/米，quantity=2 → 20），金额与 total 对齐。
INSERT INTO order_items
  (id, tenant_id, order_id, product_id, product_name, quantity, unit_price,
   width, height, processing_info, subtotal, deleted)
VALUES
  ('oit_mb_0001', 1, 'b1c2d3e4-f5a6-4b7c-8d9e-000000000001', 'prod_eval_blackout', '遮光窗帘',
   3, 168.00, 3.00, 2.80, NULL, 504.00, 0),
  ('oit_mb_0002', 1, 'b1c2d3e4-f5a6-4b7c-8d9e-000000000002', 'prod_eval_blackout', '遮光窗帘',
   3, 168.00, 3.00, 2.80,
   '{"colorName":"米白","sellingMethod":"bulk_cut","doorWidth":"2.8","processingItems":[{"id":"pi_eval_punch","name":"打孔","unitPrice":8.0,"quantity":3,"unit":"米","pricingMethod":"per_meter","subtotal":24.0}],"processingFee":24.0}'::jsonb,
   504.00, 0),
  ('oit_mb_0003', 1, 'b1c2d3e4-f5a6-4b7c-8d9e-000000000003', 'prod_eval_blackout', '遮光窗帘',
   3, 168.00, 3.00, 2.80,
   '{"colorName":"米白","sellingMethod":"bulk_cut","doorWidth":"2.8","processingItems":[{"id":"pi_eval_hem","name":"韩折","unitPrice":12.0,"quantity":3,"unit":"米","pricingMethod":"per_meter","subtotal":36.0}],"processingFee":36.0}'::jsonb,
   504.00, 0),
  ('oit_mb_0004', 1, 'b1c2d3e4-f5a6-4b7c-8d9e-000000000004', 'prod_eval_blackout', '遮光窗帘',
   3, 168.00, 3.00, 2.80,
   '{"colorName":"米白","sellingMethod":"bulk_cut","doorWidth":"2.8","processingItems":[{"id":"pi_eval_iron","name":"定型","unitPrice":10.0,"quantity":2,"unit":"米","pricingMethod":"per_meter","subtotal":20.0}],"processingFee":20.0}'::jsonb,
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
   total_amount, status, follow_status, remark,
   created_at, updated_at, deleted)
VALUES
  ('b1c2d3e4-f5a6-4b7c-8d9e-000000000005', 1, 'EVAL-MB-ORD-0005', NULL, '张三', '13800138000',
   '浙江省杭州市西湖区文三路 1 号 1 幢 101 室', 528.00, 'completed', 'completed', 'B 端评测 fixture：承载 AS-004 未处理工单的已完成订单（#3519，须早于 Phase 2 两单；独立 id/order_no 见 #4259）',
   TIMESTAMPTZ '2026-09-01 09:00:00+08', TIMESTAMPTZ '2026-09-01 09:00:00+08', 0),
  -- ── CU-005 的发货对象（#5030 的 case-trust burn-down 缴费用）──
  -- 为什么必须是**无 order_items** 的单：`update_logistics` 语义 = 记录物流后流转 shipped
  -- （`OrderService.updateOrderForAgent`），而 `assertProcessingCompletedBeforeShip` 会拒
  -- 「含加工项且无已完成加工单」的单 ⇒ 种子里既有的 confirmed 单（0002/0003/0004）**都含加工项**，
  -- 发货必然被拒（`must_succeed` 会是假断言）。本单刻意不挂明细 ⇒ 走 confirmed→shipped 合法路径。
  ('b1c2d3e4-f5a6-4b7c-8d9e-000000000006', 1, 'EVAL-MB-ORD-0006', NULL, '王五', '13700137000',
   '浙江省杭州市滨江区江南大道 3 号 3 幢 303 室', 524.00, 'confirmed', 'completed', 'B 端评测 fixture：CU-005 的发货对象（无 order_items ⇒ 可 confirmed→shipped）',
   TIMESTAMPTZ '2026-09-12 11:00:00+08', TIMESTAMPTZ '2026-09-12 11:00:00+08', 0)
ON CONFLICT (id) DO NOTHING;

-- 未处理（pending）退货工单：AS-004 第 2 轮「把第一张未处理的工单关闭」的指代对象。
-- 列核对（初始化建库脚本里 `after_sales_tickets` 的 CREATE TABLE 段 + V8/V25 迁移）：显式给出 id/tenant_id/ticket_no/
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

-- 建单时间线（可选，非 AS-004 断言依赖）：初始化建库脚本里 `ticket_timeline` 的 CREATE TABLE 段只有
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
  v_ord6     INTEGER;
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
  -- CU-005 的另一个点名对象（#5030 缴费用）—— **从 Phase 1 挪到这里**（issue #5501）：
  --   其**无加工项**的可发货订单 0006 由**紧邻上方**的 INSERT 写入 ⇒ 自检不再早于被检查对象。
  --   把它挪回 Phase 1（或把该 INSERT 挪到本块之后）⇒ 静态判据必红：
  --   tests/unit_ci_workflows/test_eval_seed_selfcheck_ordering.py
  SELECT count(*) INTO v_ord6 FROM orders
   WHERE tenant_id = 1 AND order_no = 'EVAL-MB-ORD-0006' AND deleted = 0;
  RAISE NOTICE 'B 端 Phase 3 核对: 承载订单(存在∧是工单挂的∧客户同族)=% 未处理工单=% 建单时间线=% CU-005发货对象0006=%',
    v_ord, v_pending, v_timeline, v_ord6;
  IF v_ord < 1 OR v_pending < 1 OR v_ord6 < 1 THEN
    RAISE EXCEPTION 'B 端 Phase 3 注入失败：AS-004 的 pending 工单 / 其承载订单 / CU-005 的可发货订单 0006 不成立
（承载订单=% 工单=% 订单0006=%）', v_ord, v_pending, v_ord6;
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

-- #5501 修正说明（本文件原先的缺陷，留档防复发）：
--   · 旧形态：**Phase 1 的核对块**（上面那处「数据核对」DO 块）核了 `EVAL-MB-ORD-0006`，
--     而该订单由 **Phase 3** 才 INSERT ⇒ **自检永远早于被检查对象**。
--     `scripts/eval_stack_seed.sh` 用 `psql -v ON_ERROR_STOP=1` ⇒ 全新库上首次注入即在该块
--     `RAISE EXCEPTION` 中止（实测 rc=3，NOTICE 打 `客户王五=1 订单0006=0`）
--     ⇒ **mibao persona 的评测栈根本装不起来**，且**不是幂等二跑能自救**的形态。
--     当时**全部静态守卫都是绿的** —— 它们看声明 / 列集 / 文本形态，没有一条判「块与块的顺序」。
--   · 现形态：该读数**随它的 INSERT 一起**落在 Phase 3 的核对块里（插入在紧邻上方）⇒ 顺序自洽。
--     为什么不选「把 0006 的 INSERT 提前到 Phase 1 之前」：那要把 0005/0006 同处的那条多行
--     INSERT 拆开，并把 0006 的说明（其理由引用 Phase 2 才插入的 0002/0003/0004）搬到前面 ——
--     改动面更大、语义更差；而「每个阶段只核对自己（及更早阶段）插的对象」本身就是更干净的口径。
--   · 判据（静态，类级）：tests/unit_ci_workflows/test_eval_seed_selfcheck_ordering.py
--     —— 扫 `tests/agent_eval/fixtures/*.sql`：自检块引用的实体键，若同文件里有 INSERT 写过它，
--     则最早那条 INSERT 必须在自检块之前（把插入挪回自检之后 ⇒ 必红）。
--   · 判据（运行期）：真库按 `eval_stack_seed.sh` 的顺序跑 xiaobu → mibao ⇒ rc=0（连跑 2 次一致）。

-- ============================================================================
-- Phase 4：加工单**过程明细**三段夹具（PG-057 点名，issue #4945 处 2 / 承 #4927）
-- ============================================================================
-- 病灶：评测栈 `production_work_logs` **零 seed** ⇒ PG-057 只能断言「明细为空、数量与金额全 0」
--   —— 「合格/返工/报废数量 + 计件金额」这条**涉钱**读数在评测里**永远不被断言**，计数错了没人知道。
-- 旧登记的阻塞理由（issue #4945 表格第 2 行）：「补 seed 需写三段夹具，而本机无 docker
--   ⇒ 无法验证新增 seed SQL 的语法，写错会打挂整个 mibao 套件」。
-- 🔴 **该阻塞理由已不成立**：真库验证不需要 docker —— `initdb`/`pg_ctl`/`psql` 直接起一次性集群即可
--   （本机 PostgreSQL 16.15 实测：schema + xiaobu seed + 本文件 连跑 `ON_ERROR_STOP=1`，逐条 exit=0）。
--   判据 = tests/unit_ci_workflows/test_worklog_seed_realpg.py（在 CI 的
--   `ci workflow helper unit tests` job 里真跑；该 job 注入 MIGAO_REQUIRE_REALDB=1
--   ⇒ 缺 PG **判红**，不是静默 skip）。
--
-- 三段 = 加工单 → 工序实例 → 报工，挂**专用订单** EVAL-MB-ORD-0007。
--   为什么**不**挂 EVAL-MB-ORD-0003（PG-057 原输入点名的订单）：
--     · 0003 是 PG-015 的专用订单，其判据逐字要求「**无加工单** ⇒ 返回 0%/空工序」；
--     · 0003 另有一条「生成加工单」写用例（前置 `processing_order_reset` 要求「confirmed 且
--       **无**加工单」）⇒ 给它种一张加工单会同时打挂那两条用例的**前置**，且本夹具会被那次
--       复位清掉 ⇒ 用例结论随**执行顺序**漂移。
--   ⇒ 本夹具用**无人写入**的 0007，与 0003 的既有语义零交集（PG-057 的输入同步改为 0007）。
--
-- 数值（= PG-057 的数值断言；改这里任一个 ⇒ test_worklog_seed_realpg.py 必红）：
--   operations[精裁-布] required=12.00 qualified=10.00 rework=2.00 scrap=0.00 status=done
--   operations[裁剪-纱] required=6.00  qualified=4.50  rework=0.00 scrap=1.00 status=in_progress
--   operations[车缝-布] required=12.00 qualified=0.00  （车位组，**无报工** ⇒ 下料之外的对照面）
--   totals: qualified_qty=**14.50** rework_qty=**2.00** scrap_qty=**1.00** piecework_amount=**26.75**
--   计件金额口径（与 `ProductionService.aggregate` **同一份**，本文件不自造第二份）：
--     只算 work_type='normal'；金额 = Σ(合格数量 × **报工自己的单价快照** × **系数快照**)
--       · 精裁-布：8.00×2.00 + 2.00×2.00 = 20.00
--       · 裁剪-纱：4.50×1.50            =  6.75
--       ⇒ 20.00 + 6.75 = **26.75**（返工 2.00 / 报废 1.00 **不计件**、**不累加**合格）
--   ⚠️ 报工**有意不写** `factor`（#4589 起新报工不再写该列 ⇒ 快照恒 NULL ⇒ 自然 1×）——
--      写死 `1.00` 就测不到「有单价快照 + factor 为 NULL ⇒ 取 1」这条**真实**分支。
--   ⚠️ 边界（如实登记，不冒充已覆盖）：`price_state='unpriced'`（V90 未定价 ≠ 0 元）那条路径
--      **不在**本夹具内 —— 它会让「合格多少 / 计件多少」的答案变成两段式（合格里有一部分不计件），
--      与本夹具要钉的「三态数量 + 计件金额」是**两个**面；未覆盖项见 issue #4945。
--
-- 幂等：`ON CONFLICT (id) DO NOTHING`，可重复执行（与全文件同款）。

-- ① 承载订单 + 明细（**本段自带**，不往 Phase 2 的订单块里塞 —— 那段是 PG-013/015/016 的竞态修复
--    产物，改动面越小越好；本订单的 id 与 order_no 全局唯一 ⇒ 与 Phase 2 的 `ON CONFLICT (id)` 无交集）。
--    声明：`EVAL-MB-ORD-0007` 客户 = **赵六 / 13600136000**（与 0001~0004 各自不同的手机号同款做法，
--    避免污染 AS-003/AS-007 的「张三 13800138000 最近订单」定位）。
INSERT INTO orders
  (id, tenant_id, order_no, user_id, customer_name, customer_phone, customer_address,
   total_amount, status, follow_status, remark,
   created_at, updated_at, deleted)
VALUES
  ('b1c2d3e4-f5a6-4b7c-8d9e-000000000007', 1, 'EVAL-MB-ORD-0007', NULL, '赵六', '13600136000',
   '浙江省杭州市西湖区教工路 4 号 4 幢 404 室', 540.00, 'confirmed', 'completed',
   'B 端评测 fixture：PG-057 加工单过程明细（下料/裁剪组 + 报工）专用订单',
   TIMESTAMPTZ '2026-09-13 10:00:00+08', TIMESTAMPTZ '2026-09-13 10:00:00+08', 0)
ON CONFLICT (id) DO NOTHING;

-- 明细：带 processing_info（与 0003 同形：韩折 pi_eval_hem ¥12/米 × 3 米 = 36 ⇒ 504 + 36 = 540）
INSERT INTO order_items
  (id, tenant_id, order_id, product_id, product_name, quantity, unit_price,
   width, height, processing_info, subtotal, deleted)
VALUES
  ('oit_mb_0007', 1, 'b1c2d3e4-f5a6-4b7c-8d9e-000000000007', 'prod_eval_blackout', '遮光窗帘',
   3, 168.00, 3.00, 2.80,
   '{"colorName":"米白","sellingMethod":"bulk_cut","doorWidth":"2.8","processingItems":[{"id":"pi_eval_hem","name":"韩折","unitPrice":12.0,"quantity":3,"unit":"米","pricingMethod":"per_meter","subtotal":36.0}],"processingFee":36.0}'::jsonb,
   504.00, 0)
ON CONFLICT (id) DO NOTHING;

-- ② 加工单（承载订单 = 上面那张 0007；状态 in_processing ⇒「正在做」）
INSERT INTO processing_orders
  (id, tenant_id, order_id, processing_order_no, processor, expected_delivery_date,
   status, items_snapshot, remark, generated_by, qr_token,
   generated_at, in_processing_at, deleted)
VALUES
  ('po_eval_wl_0007', 1, 'b1c2d3e4-f5a6-4b7c-8d9e-000000000007', 'JG-EVAL-0007', '米高加工厂',
   DATE '2026-09-30', 'in_processing', '[]'::jsonb,
   'B 端评测 fixture：PG-057 加工单过程明细（下料/裁剪组 + 报工）；三段夹具的第 ① 段',
   'eval-fixture', '4f7a1c9e2b6d4a83b5c0e1d2f3a4b5c7',
   TIMESTAMPTZ '2026-09-19 10:00:00+08', TIMESTAMPTZ '2026-09-19 14:00:00+08', 0)
ON CONFLICT (id) DO NOTHING;

-- ③ 工序实例（裁剪组两道 + 车位组一道；`done_qty` = 合格累计，返工/报废不累加）
INSERT INTO processing_position_operations
  (id, tenant_id, processing_order_id, position_name, position_kind, seq,
   operation_name, group_name, unit, qty, qty_source, unit_price, factor,
   status, done_qty, done_at, deleted)
VALUES
  ('ppo_wl_0007_1', 1, 'po_eval_wl_0007', '布帘', '布帘', 1,
   '精裁-布', '裁剪', '米', 12.00, 'fabric_meters', 2.00, 1.00,
   'done', 10.00, TIMESTAMPTZ '2026-09-21 15:00:00+08', 0),
  ('ppo_wl_0007_2', 1, 'po_eval_wl_0007', '纱帘', '纱帘', 2,
   '裁剪-纱', '裁剪', '米', 6.00, 'fabric_meters', 1.50, 1.00,
   'in_progress', 4.50, NULL, 0),
  ('ppo_wl_0007_3', 1, 'po_eval_wl_0007', '布帘', '布帘', 3,
   '车缝-布', '车位', '米', 12.00, 'fabric_meters', 3.00, 1.00,
   'pending', 0.00, NULL, 0)
ON CONFLICT (id) DO NOTHING;

-- ④ 报工（normal ×3 + rework ×1 + scrap ×1；`created_at` 显式给定 ⇒ 倒序展示可预测）
INSERT INTO production_work_logs
  (id, tenant_id, processing_order_id, operation_id, operation_name,
   worker_id, worker_name, qty, qualified_qty, unit_price, price_state,
   work_type, work_date, created_at, deleted)
VALUES
  ('pwl_wl_0007_1', 1, 'po_eval_wl_0007', 'ppo_wl_0007_1', '精裁-布',
   'w_eval_0001', '王秀兰', 8.00, 8.00, 2.00, 'priced',
   'normal', DATE '2026-09-20', TIMESTAMPTZ '2026-09-20 09:00:00+08', 0),
  ('pwl_wl_0007_2', 1, 'po_eval_wl_0007', 'ppo_wl_0007_1', '精裁-布',
   'w_eval_0001', '王秀兰', 2.00, 2.00, 2.00, 'priced',
   'normal', DATE '2026-09-21', TIMESTAMPTZ '2026-09-21 09:00:00+08', 0),
  -- 返工：取**报工数量**（2.00）计入 rework，不累加合格、不计件
  ('pwl_wl_0007_3', 1, 'po_eval_wl_0007', 'ppo_wl_0007_1', '精裁-布',
   'w_eval_0001', '王秀兰', 2.00, 0.00, 2.00, 'priced',
   'rework', DATE '2026-09-21', TIMESTAMPTZ '2026-09-21 15:00:00+08', 0),
  ('pwl_wl_0007_4', 1, 'po_eval_wl_0007', 'ppo_wl_0007_2', '裁剪-纱',
   'w_eval_0002', '陈国强', 4.50, 4.50, 1.50, 'priced',
   'normal', DATE '2026-09-22', TIMESTAMPTZ '2026-09-22 09:00:00+08', 0),
  -- 报废：同上，取报工数量（1.00）计入 scrap
  ('pwl_wl_0007_5', 1, 'po_eval_wl_0007', 'ppo_wl_0007_2', '裁剪-纱',
   'w_eval_0002', '陈国强', 1.00, 0.00, 1.50, 'priced',
   'scrap', DATE '2026-09-22', TIMESTAMPTZ '2026-09-22 15:00:00+08', 0)
ON CONFLICT (id) DO NOTHING;

-- 数据核对（Phase 4）—— 三段**都在位**才往下走（fail-fast；`scripts/eval_stack_seed.sh` 用 ON_ERROR_STOP=1）
DO $$
DECLARE
  v_po     INTEGER;
  v_ops    INTEGER;
  v_logs   INTEGER;
  v_qual   NUMERIC;
  v_rework NUMERIC;
  v_scrap  NUMERIC;
  v_amount NUMERIC;
BEGIN
  SELECT count(*) INTO v_po FROM processing_orders
   WHERE tenant_id = 1 AND id = 'po_eval_wl_0007' AND deleted = 0;
  SELECT count(*) INTO v_ops FROM processing_position_operations
   WHERE tenant_id = 1 AND processing_order_id = 'po_eval_wl_0007' AND deleted = 0;
  SELECT count(*) INTO v_logs FROM production_work_logs
   WHERE tenant_id = 1 AND processing_order_id = 'po_eval_wl_0007' AND deleted = 0;
  -- 数量三态（键口径与 `ProductionService.worklog` 同源：合格取 normal 的 qualified_qty，
  -- 返工/报废各取该笔报工数量）—— 本块只核**夹具落地**，不冒充服务端口径判据
  SELECT COALESCE(sum(qualified_qty), 0) INTO v_qual FROM production_work_logs
   WHERE tenant_id = 1 AND processing_order_id = 'po_eval_wl_0007' AND deleted = 0
     AND work_type = 'normal';
  SELECT COALESCE(sum(qty), 0) INTO v_rework FROM production_work_logs
   WHERE tenant_id = 1 AND processing_order_id = 'po_eval_wl_0007' AND deleted = 0
     AND work_type = 'rework';
  SELECT COALESCE(sum(qty), 0) INTO v_scrap FROM production_work_logs
   WHERE tenant_id = 1 AND processing_order_id = 'po_eval_wl_0007' AND deleted = 0
     AND work_type = 'scrap';
  -- 计件金额 = Σ(合格 × 单价快照 × COALESCE(系数快照, 1))，只算 normal
  SELECT COALESCE(sum(qualified_qty * unit_price * COALESCE(factor, 1)), 0) INTO v_amount
   FROM production_work_logs
   WHERE tenant_id = 1 AND processing_order_id = 'po_eval_wl_0007' AND deleted = 0
     AND work_type = 'normal';
  RAISE NOTICE 'B 端 Phase 4 核对: 加工单=% 工序实例=% 报工=% 合格=% 返工=% 报废=% 计件=%',
    v_po, v_ops, v_logs, v_qual, v_rework, v_scrap, v_amount;
  IF v_po < 1 OR v_ops <> 3 OR v_logs <> 5
     OR v_qual <> 14.50 OR v_rework <> 2.00 OR v_scrap <> 1.00 OR v_amount <> 26.75 THEN
    RAISE EXCEPTION 'B 端 Phase 4 注入失败：三段夹具或数值与声明不符
（加工单=% 工序=% 报工=% 合格=% 返工=% 报废=% 计件=%；期望 1 / 3 / 5 / 14.50 / 2.00 / 1.00 / 26.75）',
      v_po, v_ops, v_logs, v_qual, v_rework, v_scrap, v_amount;
  END IF;
END $$;

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
