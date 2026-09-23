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
-- 仅用于评测栈，**不并入** backend/admin-api/src/main/resources/db/init/schema.sql（生产 bootstrap 不应含演示数据）。
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


-- ── 3. 商品（PR-003 名称查询 / PR-001 关键词搜索 / OR-017 指名商品下单）──
-- ⚠️ 商品名必须覆盖用例**点名**的商品：OR-017 的输入是「我想买夏日清风窗帘…」，
--    库里没有这个商品 → `product_search` 搜不到 → agent 无从下单 → 该用例恒 0 分。
--    实测 CI：OR-017 `tools=[customer_address_query ×3]`、0 建单 —— 看着像 agent 不会
--    下单，实为库里没这个东西。**数据层缺口，不是能力缺陷。**
-- `recommended`：只让「遮光窗帘」进推荐位，避免 CH-010「推荐几款热销窗帘」的
--    「第一款」在多个推荐商品间变得不确定；夏日清风靠**名称**命中，不靠推荐位。
-- V111（用户裁定 2026-09-21）：售卖方式 `selling_methods` 与 `roll_length_m`（1 卷 = 多少米）
-- 都是**商品货号级基础参数**（不再是 SKU 组合维度）⇒ 必须在 products 行上给值。
INSERT INTO products
  (id, tenant_id, name, category_id, base_price, description, images, detail_images,
   stock, stock_warning_threshold, status, unit, pricing_type, sku_code,
   stock_deduction_mode, sales_count, sales_amount, recommended,
   selling_methods, roll_length_m)
VALUES
  ('prod_eval_blackout', 1, '遮光窗帘', 'cat_eval_curtain', 168.00,
   '高遮光面料，适合卧室与客厅，遮光率 95%，支持散剪与加工定制',
   '[]'::jsonb, '[]'::jsonb, 1000, 10, 'on_sale', '米', 'per_meter', 'EVAL-BLK-28',
   'on_order', 0, 0, TRUE, '["bulk_cut", "full_roll"]'::jsonb, 60.00),
  ('prod_eval_dark_green', 1, '北欧风窗帘', 'cat_eval_curtain', 128.00,
   '北欧简约风格，棉麻质感，适合客厅与书房',
   '[]'::jsonb, '[]'::jsonb, 800, 10, 'on_sale', '米', 'per_meter', 'EVAL-NRD-28',
   'on_order', 0, 0, FALSE, '["bulk_cut", "full_roll"]'::jsonb, 60.00),
  ('prod_eval_summer', 1, '夏日清风窗帘', 'cat_eval_curtain', 158.00,
   '轻薄透气夏日清风系列，支持散剪 2.8 米门幅与打孔/折边加工',
   '[]'::jsonb, '[]'::jsonb, 600, 10, 'on_sale', '米', 'per_meter', 'EVAL-SMB-28',
   'on_order', 0, 0, FALSE, '["bulk_cut", "full_roll"]'::jsonb, 60.00)
ON CONFLICT (id) DO NOTHING;

-- ── 4. 颜色 / SKU（选品规格收集所需：colorId + doorWidth —— V108 起 SKU 组合**只有** 颜色 × 门幅）──
INSERT INTO product_colors (tenant_id, product_id, color_name, main_color_hex, sort_order)
SELECT v.tenant_id, v.product_id, v.color_name, v.hex, v.ord
FROM (VALUES
  (1, 'prod_eval_blackout', '米白', '#F5F0E6', 1),
  (1, 'prod_eval_blackout', '浅灰', '#C8C8C8', 2),
  (1, 'prod_eval_dark_green', '雾霾蓝', '#8FA3B0', 1),
  -- 「白色」给到每个商品：CH-010 顾客说「第一款，白色…」，而"第一款"由商品搜索
  -- 排序决定（可能落在任一商品上）。若某商品没有白色 → 流程卡在颜色上死循环
  -- （实测 run 34624202564：agent 选中北欧风窗帘，顾客要白色，来回追问）。
  (1, 'prod_eval_dark_green', '白色', '#FFFFFF', 2),
  (1, 'prod_eval_summer', '米白色', '#F7F3E8', 1)
) AS v(tenant_id, product_id, color_name, hex, ord)
WHERE NOT EXISTS (
  SELECT 1 FROM product_colors pc
  WHERE pc.product_id = v.product_id AND pc.color_name = v.color_name
);

-- color_name 必须一并写入：ProductSku 实体声明了该列，admin-api 拉 SKU 列表时 SELECT 它
-- （schema.sql/V41 已补列；不写则返回 null，前端色号显示为空）。
-- V111：`product_skus.selling_method` 列已删除（售卖方式上移为 products.selling_methods），
-- 唯一键 = (product_id, color_id, door_width) ⇒ 本 INSERT 不得再写该列。
INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT 1, pc.product_id, pc.id, pc.color_name, '2.8', p.base_price, 500,
       p.sku_code || '-' || pc.color_name
FROM product_colors pc
JOIN products p ON p.id = pc.product_id
WHERE pc.product_id IN ('prod_eval_blackout', 'prod_eval_dark_green', 'prod_eval_summer')
  AND NOT EXISTS (
    SELECT 1 FROM product_skus s
    WHERE s.product_id = pc.product_id AND s.color_id = pc.id
      AND s.door_width = '2.8'
  );

-- ── 4b. 第二门幅 SKU（issue #5039：CH-043「候选门幅集」的接地对象）──
-- 为什么必须补这一行（**前提核实结论，照实登记**）：issue #5039 的场景写的是
--   「该商品 SKU 有 2.8 / 3.2 两门幅」，而本夹具此前**每个商品只有 `2.8` 一种门幅**
--   （按 `door_width` 检索实测只有 `'2.8'`）⇒ 模型即使正确执行「把 SKU 门幅去重后传
--   `fabric_widths`」，去重结果恒为 `[2.8]`（长度 1）⇒ 「含 2.8 与 3.2」的断言**恒红**
--   （按 `migao-acceptance`：恒红与恒绿同属**空断言**，什么都没测）。
--   #5016 的工具 description / `customer_quote.md` 举的例子正是 `[2.8, 3.2]`
--   （原文「同一商品常同时有 2.8 / 3.2 两种门幅」）⇒ 夹具按真实商品形态补上 3.2。
-- 为什么只补 `prod_eval_summer`（夏日清风窗帘）的**米白色 / 散剪**：
--   · 点名该商品的下单用例只有 OR-017（输入自带「米白色，3 米，**门幅 2.8 米**散剪」）
--     与 OR-018（输入自带「米白色 3 米」，**不**断言 doorWidth）⇒ 新增一种门幅不改变
--     两者的解析结果；断言 doorWidth 的 OR-008/OR-009 打的是「遮光窗帘」且输入自带 2.8，不受影响。
--   · 价格取 `p.base_price`（与既有 2.8 SKU **同价** 158.00）⇒ 订单金额断言逐值不变。
-- 幂等：`NOT EXISTS` 判据含 `door_width`（与上一块同一形态，可重复执行）。
INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT 1, pc.product_id, pc.id, pc.color_name, '3.2', p.base_price, 500,
       p.sku_code || '-' || pc.color_name || '-3.2'
FROM product_colors pc
JOIN products p ON p.id = pc.product_id
WHERE pc.product_id = 'prod_eval_summer'
  AND NOT EXISTS (
    SELECT 1 FROM product_skus s
    WHERE s.product_id = pc.product_id AND s.color_id = pc.id
      AND s.door_width = '3.2'
  );

-- ── 5. 商品 ↔ 加工项关联：**已随 #4371 解耦删除** ──
-- 旧写法往 `product_processing_items` 把「遮光窗帘/北欧风窗帘/夏日清风窗帘」各自挂上
-- 加工项（作为下单加工项环节 `processing_items` 的来源）。解耦后加工项是**店铺级目录**
-- （第 2 节 `processing_items` 种子即全部可选项），该表已由 V66 迁移 DROP ——
-- 下单/建品的加工项一律从目录整体取，不再经商品过滤。

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
-- 仅用于评测栈，不并入 backend/admin-api/src/main/resources/db/init/schema.sql（生产 bootstrap 不应含演示数据）。
-- ============================================================================

-- 6.1 C 端顾客（与 auth.py DEBUG customer 身份 user_id 严格一致）
INSERT INTO users (id, tenant_id, phone, nickname, role, status, deleted)
VALUES ('debug_customer_1', 1, '13800138000', '评测顾客', 'customer', 'active', 0)
ON CONFLICT (id) DO NOTHING;

-- 6.1b 新客（**无任何历史订单**，issue #3391）：C 端「无历史收货信息 → 主动收集」路径。
--      debug_customer_1 有历史订单 → customer_address_query 恒 has_address=true，
--      该路径在评测里原本**不可达**（而验收 C-A1 暴露的问题正出在这里）。
--      评测通过请求头 X-Debug-User: debug_customer_new 切到本身份
--      （app/utils/auth.py 的 DEBUG-only + debug_ 前缀白名单）。
INSERT INTO users (id, tenant_id, phone, nickname, role, status, deleted)
VALUES ('debug_customer_new', 1, '13900139000', '评测新客', 'customer', 'active', 0)
ON CONFLICT (id) DO NOTHING;

-- 6.1c B 端管理员账号（**转人工通知投递路径可达性**，issue #3553 / CH-008 覆盖缺口）
--      ⚠️ 不要当脏数据删掉：删除会让 CH-008 的「通知真的送达」重新变成**永不可达**。
--      为什么必须有：`POST /api/admin/notifications` **按收件人落库、无广播语义**，
--      `human_handoff._notify_admins` 靠 `GET /api/admin/users?status=active`（默认排除
--      role=customer，优先 role='admin'）解析收件人。C 端评测栈此前**只有 role='customer'
--      账号** → 解析不到收件人 → 工具走
--      `success=True` + `error="admin_notification_skipped_no_recipient"` +
--      `data.adminNotified=false` 的降级分支 → 「管理员真的收到转人工通知」在评测里
--      **任何栈都不可达**（CH-008 只能断言「工具调用成功」= 只有一半覆盖）。
--      本账号（role='admin'，与 NotificationService.triggerForTenantAdmins 口径一致）
--      让真实投递分支可被机器判定：CH-008 的 `output_verify: adminNotified=true`。
--      数据隔离影响：本账号**没有任何订单**（C 端订单隔离按 user_id 判定），
--      也不进 `agent_employees` 员工列表（B 端 employee_manage 按该模型查询）→
--      不影响 CH-011（跨用户订单拒绝）/ DF-020（冒充管理员）等 C 端隔离用例。
INSERT INTO users (id, tenant_id, phone, nickname, role, status, deleted)
VALUES ('debug_admin_eval', 1, '13600136000', '评测管理员', 'admin', 'active', 0)
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
  ('a1b2c3d4-e5f6-4a7b-8c9d-000000000001', 1, 'EVAL-ORD-0001', 'debug_customer_1', '张三', '13800138000',
   '浙江省杭州市西湖区文三路 1 号 1 幢 101 室', 504.00, 'completed', 'paid', TRUE,
   'completed', 'C 端评测 fixture：已完成订单（地址预填 / 售后建单用）',
   TIMESTAMPTZ '2026-08-01 10:00:00+08', TIMESTAMPTZ '2026-08-05 10:00:00+08', 0),
  ('a1b2c3d4-e5f6-4a7b-8c9d-000000000002', 1, 'EVAL-ORD-0002', 'debug_customer_1', '张三', '13800138000',
   '浙江省杭州市西湖区文三路 1 号 1 幢 101 室', 384.00, 'shipped', 'paid', TRUE,
   'completed', 'C 端评测 fixture：已发货订单（物流查询 / 最近一笔用）',
   TIMESTAMPTZ '2026-09-01 10:00:00+08', TIMESTAMPTZ '2026-09-09 18:00:00+08', 0)
ON CONFLICT (id) DO NOTHING;

-- 6.3 订单明细（列表/详情展示、售后关联商品）
INSERT INTO order_items
  (id, tenant_id, order_id, product_id, product_name, quantity, unit_price,
   width, height, subtotal, deleted)
VALUES
  ('oit_eval_0001', 1, 'a1b2c3d4-e5f6-4a7b-8c9d-000000000001', 'prod_eval_blackout', '遮光窗帘', 3, 168.00,
   3.00, 2.80, 504.00, 0),
  ('oit_eval_0002', 1, 'a1b2c3d4-e5f6-4a7b-8c9d-000000000002', 'prod_eval_dark_green', '北欧风窗帘', 3, 128.00,
   3.00, 2.80, 384.00, 0)
ON CONFLICT (id) DO NOTHING;

-- 6.4 物流轨迹（已发货订单的物流查询用例数据源）
INSERT INTO order_logistics
  (id, tenant_id, order_id, logistics_company, tracking_no, status, tracking_info, shipped_at)
SELECT 'olg_eval_0002', 1, 'a1b2c3d4-e5f6-4a7b-8c9d-000000000002', '顺丰速运', 'SF1234567890123', 'in_transit',
       '[{"time":"2026-09-10 09:00","desc":"快件已从杭州中转场发出"}]'::jsonb,
       TIMESTAMPTZ '2026-09-09 18:00:00+08'
WHERE NOT EXISTS (
  SELECT 1 FROM order_logistics WHERE order_id = 'a1b2c3d4-e5f6-4a7b-8c9d-000000000002'
);

-- ── 数据核对（CI 日志可见，避免"注入了但没生效"静默）──
DO $$
DECLARE
  v_orders INTEGER;
  v_items  INTEGER;
  v_new_orders INTEGER;
  v_admins INTEGER;
BEGIN
  SELECT count(*) INTO v_orders FROM orders
   WHERE tenant_id = 1 AND user_id = 'debug_customer_1' AND deleted = 0;
  SELECT count(*) INTO v_items FROM order_items WHERE tenant_id = 1 AND deleted = 0;
  -- 新客（OR-022 多身份用例）必须**没有**任何订单：有订单就会走 has_address=true 分支，
  -- 用例"看起来覆盖了新客路径、其实没覆盖"（假绿）。故这里是**断言**，不只是打印。
  SELECT count(*) INTO v_new_orders FROM orders
   WHERE tenant_id = 1 AND user_id = 'debug_customer_new' AND deleted = 0;
  -- 6.1c 的 B 端管理员必须在：缺失时 CH-008「通知真的送达」会静默降级为
  -- admin_notification_skipped_no_recipient（success=True 但 adminNotified=false）→
  -- output_verify 断言会红，但根因是**种子缺失**而非能力缺陷。这里先 fail-closed。
  SELECT count(*) INTO v_admins FROM users
   WHERE tenant_id = 1 AND role = 'admin' AND status = 'active' AND deleted = 0;
  RAISE NOTICE 'C 端评测 fixture 核对: debug_customer_1 订单=% 明细=% 新客订单=% B端管理员=%',
    v_orders, v_items, v_new_orders, v_admins;
  IF v_orders < 2 THEN
    RAISE EXCEPTION 'C 端 fixture 注入失败：debug_customer_1 订单数=% (<2)', v_orders;
  END IF;
  IF v_new_orders > 0 THEN
    RAISE EXCEPTION '新客 fixture 被污染：debug_customer_new 订单数=%（必须为 0，否则 OR-022 假绿）',
      v_new_orders;
  END IF;
  IF v_admins < 1 THEN
    RAISE EXCEPTION 'C 端 fixture 缺少 B 端管理员账号（role=admin, status=active）：% —— '
      'CH-008 转人工通知投递分支将不可达（adminNotified 恒 false）', v_admins;
  END IF;
END $$;

-- ⚠️ 本块**必须留在文件末尾**（不能紧跟上面那段 INSERT）：`test_schema_integrity.py` 的
-- `test_orders_self_check_uses_same_customer_id` 取的是本文件**第一个** `DO $$` 块
-- （= 下面的订单自检块）。把它插到前面会让那条守卫核到错的块（本单实测踩过）。
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
