-- ============================================================
-- 米高 POC 演示数据 seed 脚本
--
-- 用途：为 POC 演示准备真实感演示数据（窗帘商品 + SKU 矩阵 + 加工项 + 客户 + 订单）
-- 用法：psql "$DATABASE_URL" -v tenant_id=1 -f demo-seed.sql
-- 幂等：所有 INSERT 用 WHERE NOT EXISTS 守卫，可重复执行
-- ⚠️ 参数化只有 psql 变量一种范式（issue #5502）：psql **不在 dollar-quoted 体内**做
--    `:变量` 替换 ⇒ 别把 `:tenant_id` 写进 `DO $$ … $$` / 函数体里（服务端直接收到
--    `:tenant_id` ⇒ `syntax error at or near ":"`）。要把变量带进块里，就把它拼进块**外层**
--    的语句（见第 3 节的 SKU 段：`INSERT … SELECT … FROM product_colors c WHERE …`）。
--    判据：tests/unit_ci_workflows/test_psql_vars_outside_dollar_quotes.py（注入即红）。
-- 数据来源：knowledge_base/products/product_catalog.md + docs/curtain-fabric-quote-rules.md
-- ============================================================

-- ──────────────────────────────────────────────
-- 1. 商品分类
-- ──────────────────────────────────────────────
INSERT INTO categories (id, tenant_id, name, sort_order, status)
SELECT 'cat-curtain', :tenant_id, '遮光窗帘', 1, 'active'
WHERE NOT EXISTS (SELECT 1 FROM categories WHERE id = 'cat-curtain' AND tenant_id = :tenant_id);

INSERT INTO categories (id, tenant_id, name, sort_order, status)
SELECT 'cat-sheer', :tenant_id, '纱帘', 2, 'active'
WHERE NOT EXISTS (SELECT 1 FROM categories WHERE id = 'cat-sheer' AND tenant_id = :tenant_id);

INSERT INTO categories (id, tenant_id, name, sort_order, status)
SELECT 'cat-fabric', :tenant_id, '雪尼尔/绒布', 3, 'active'
WHERE NOT EXISTS (SELECT 1 FROM categories WHERE id = 'cat-fabric' AND tenant_id = :tenant_id);

-- ──────────────────────────────────────────────
-- 2. 商品（3 个窗帘商品）
-- ──────────────────────────────────────────────
INSERT INTO products (id, tenant_id, name, category_id, base_price, description, unit, pricing_type, sku_code, status)
SELECT 'p-zg-001', :tenant_id, '星空全遮光窗帘', 'cat-curtain', 98.00,
       '高精密涤纶三层织造，遮光率99%以上，物理遮光无甲醛，双面同色，垂感优良',
       '米', 'per_meter', 'MG-ZG-001', 'on_sale'
WHERE NOT EXISTS (SELECT 1 FROM products WHERE id = 'p-zg-001' AND tenant_id = :tenant_id);

INSERT INTO products (id, tenant_id, name, category_id, base_price, description, unit, pricing_type, sku_code, status)
SELECT 'p-zg-002', :tenant_id, '云朵半遮光窗帘', 'cat-curtain', 68.00,
       '涤纶高密度编织，遮光率75%-85%，莫兰迪色系，柔软细腻，适合客厅书房',
       '米', 'per_meter', 'MG-ZG-002', 'on_sale'
WHERE NOT EXISTS (SELECT 1 FROM products WHERE id = 'p-zg-002' AND tenant_id = :tenant_id);

INSERT INTO products (id, tenant_id, name, category_id, base_price, description, unit, pricing_type, sku_code, status)
SELECT 'p-sl-001', :tenant_id, '雾霭柔光纱帘', 'cat-sheer', 35.00,
       '涤纶雪纺纱，透光不透人，2.8米超宽幅减少拼接，轻盈飘逸',
       '米', 'per_meter', 'MG-SL-001', 'on_sale'
WHERE NOT EXISTS (SELECT 1 FROM products WHERE id = 'p-sl-001' AND tenant_id = :tenant_id);

-- ──────────────────────────────────────────────
-- 3. 颜色 + SKU 矩阵（颜色 × 门幅；售卖方式已在 V111 上移为商品级，不再是 SKU 维度）
-- ──────────────────────────────────────────────
-- 星空全遮光：象牙白/浅灰/藏蓝
INSERT INTO product_colors (tenant_id, product_id, color_name, main_color_hex, sort_order)
SELECT :tenant_id, 'p-zg-001', '象牙白', '#F5F0E8', 1
WHERE NOT EXISTS (SELECT 1 FROM product_colors WHERE tenant_id = :tenant_id AND product_id = 'p-zg-001' AND color_name = '象牙白');

INSERT INTO product_colors (tenant_id, product_id, color_name, main_color_hex, sort_order)
SELECT :tenant_id, 'p-zg-001', '浅灰', '#C8C8C8', 2
WHERE NOT EXISTS (SELECT 1 FROM product_colors WHERE tenant_id = :tenant_id AND product_id = 'p-zg-001' AND color_name = '浅灰');

INSERT INTO product_colors (tenant_id, product_id, color_name, main_color_hex, sort_order)
SELECT :tenant_id, 'p-zg-001', '藏蓝', '#2B3A67', 3
WHERE NOT EXISTS (SELECT 1 FROM product_colors WHERE tenant_id = :tenant_id AND product_id = 'p-zg-001' AND color_name = '藏蓝');

-- 云朵半遮光：奶白/雾蓝/豆沙粉
INSERT INTO product_colors (tenant_id, product_id, color_name, main_color_hex, sort_order)
SELECT :tenant_id, 'p-zg-002', '奶白', '#F8F4EE', 1
WHERE NOT EXISTS (SELECT 1 FROM product_colors WHERE tenant_id = :tenant_id AND product_id = 'p-zg-002' AND color_name = '奶白');

INSERT INTO product_colors (tenant_id, product_id, color_name, main_color_hex, sort_order)
SELECT :tenant_id, 'p-zg-002', '雾蓝', '#9BB0C1', 2
WHERE NOT EXISTS (SELECT 1 FROM product_colors WHERE tenant_id = :tenant_id AND product_id = 'p-zg-002' AND color_name = '雾蓝');

INSERT INTO product_colors (tenant_id, product_id, color_name, main_color_hex, sort_order)
SELECT :tenant_id, 'p-zg-002', '豆沙粉', '#D8A7A0', 3
WHERE NOT EXISTS (SELECT 1 FROM product_colors WHERE tenant_id = :tenant_id AND product_id = 'p-zg-002' AND color_name = '豆沙粉');

-- 雾霭柔光纱：白色/米白
INSERT INTO product_colors (tenant_id, product_id, color_name, main_color_hex, sort_order)
SELECT :tenant_id, 'p-sl-001', '白色', '#FFFFFF', 1
WHERE NOT EXISTS (SELECT 1 FROM product_colors WHERE tenant_id = :tenant_id AND product_id = 'p-sl-001' AND color_name = '白色');

INSERT INTO product_colors (tenant_id, product_id, color_name, main_color_hex, sort_order)
SELECT :tenant_id, 'p-sl-001', '米白', '#F5EFE0', 2
WHERE NOT EXISTS (SELECT 1 FROM product_colors WHERE tenant_id = :tenant_id AND product_id = 'p-sl-001' AND color_name = '米白');

-- SKU 矩阵（issue #7583 缺陷 2）：**每个颜色至少一行**，主销两档门幅（2.8 / 3.2）；
-- 星空白/云朵 3 色 × 2 门幅，雾霭柔光纱（2.8 超宽幅）2 色 × 1 门幅。
-- 为什么**逐行显式**（不写成 JOIN product_colors 的生成式）：判据要能**逐行静态读**
--   `tests/unit_ci_workflows/test_seed_data_quality.py`（每个 color 有 SKU / 单价 ∈ SKU 价集 /
--   门幅 canonical 都是**值**层面的判断，生成式只能靠 SQL 求值，离线判不了 ⇒ 判不了就成了假绿）。
-- 色号用**相关子查询**取（`FROM product_colors c`），不是 `DO` 块里的 `SELECT … INTO`：
--   后者要把 `:tenant_id` 带进 dollar-quoted 体内，而 psql 在体内不做替换（issue #5502）。
-- ⚠️ `door_width` 落 **canonical 裸数值**（与 `SkuMatrix.tsx` 的 `normalizeDoorWidth`、
--    eval 种子 `'2.8'` 同口径）；带单位的 `2.8米` 只允许出现在**显示层**。

-- 星空全遮光（p-zg-001，¥98.00/米）：象牙白 / 浅灰 / 藏蓝 × 2.8 / 3.2
INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-zg-001', c.id, '象牙白', '2.8', 98.00, 500, 'MG-ZG-001-象牙白-2.8'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-zg-001' AND c.color_name = '象牙白'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-zg-001' AND s.color_id = c.id AND s.door_width = '2.8');

INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-zg-001', c.id, '象牙白', '3.2', 98.00, 400, 'MG-ZG-001-象牙白-3.2'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-zg-001' AND c.color_name = '象牙白'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-zg-001' AND s.color_id = c.id AND s.door_width = '3.2');

INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-zg-001', c.id, '浅灰', '2.8', 98.00, 500, 'MG-ZG-001-浅灰-2.8'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-zg-001' AND c.color_name = '浅灰'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-zg-001' AND s.color_id = c.id AND s.door_width = '2.8');

INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-zg-001', c.id, '浅灰', '3.2', 98.00, 400, 'MG-ZG-001-浅灰-3.2'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-zg-001' AND c.color_name = '浅灰'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-zg-001' AND s.color_id = c.id AND s.door_width = '3.2');

INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-zg-001', c.id, '藏蓝', '2.8', 98.00, 300, 'MG-ZG-001-藏蓝-2.8'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-zg-001' AND c.color_name = '藏蓝'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-zg-001' AND s.color_id = c.id AND s.door_width = '2.8');

INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-zg-001', c.id, '藏蓝', '3.2', 98.00, 260, 'MG-ZG-001-藏蓝-3.2'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-zg-001' AND c.color_name = '藏蓝'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-zg-001' AND s.color_id = c.id AND s.door_width = '3.2');

-- 云朵半遮光（p-zg-002，¥68.00/米）：奶白 / 雾蓝 / 豆沙粉 × 2.8 / 3.2
INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-zg-002', c.id, '奶白', '2.8', 68.00, 600, 'MG-ZG-002-奶白-2.8'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-zg-002' AND c.color_name = '奶白'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-zg-002' AND s.color_id = c.id AND s.door_width = '2.8');

INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-zg-002', c.id, '奶白', '3.2', 68.00, 480, 'MG-ZG-002-奶白-3.2'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-zg-002' AND c.color_name = '奶白'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-zg-002' AND s.color_id = c.id AND s.door_width = '3.2');

INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-zg-002', c.id, '雾蓝', '2.8', 68.00, 600, 'MG-ZG-002-雾蓝-2.8'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-zg-002' AND c.color_name = '雾蓝'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-zg-002' AND s.color_id = c.id AND s.door_width = '2.8');

INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-zg-002', c.id, '雾蓝', '3.2', 68.00, 480, 'MG-ZG-002-雾蓝-3.2'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-zg-002' AND c.color_name = '雾蓝'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-zg-002' AND s.color_id = c.id AND s.door_width = '3.2');

INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-zg-002', c.id, '豆沙粉', '2.8', 68.00, 320, 'MG-ZG-002-豆沙粉-2.8'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-zg-002' AND c.color_name = '豆沙粉'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-zg-002' AND s.color_id = c.id AND s.door_width = '2.8');

INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-zg-002', c.id, '豆沙粉', '3.2', 68.00, 260, 'MG-ZG-002-豆沙粉-3.2'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-zg-002' AND c.color_name = '豆沙粉'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-zg-002' AND s.color_id = c.id AND s.door_width = '3.2');

-- 雾霭柔光纱（p-sl-001，¥35.00/米）：白色 / 米白 × 2.8（超宽幅，2.8 单档）
INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-sl-001', c.id, '白色', '2.8', 35.00, 800, 'MG-SL-001-白色-2.8'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-sl-001' AND c.color_name = '白色'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-sl-001' AND s.color_id = c.id AND s.door_width = '2.8');

INSERT INTO product_skus (tenant_id, product_id, color_id, color_name, door_width, price, stock, sku_code)
SELECT :tenant_id, 'p-sl-001', c.id, '米白', '2.8', 35.00, 700, 'MG-SL-001-米白-2.8'
FROM product_colors c
WHERE c.tenant_id = :tenant_id AND c.product_id = 'p-sl-001' AND c.color_name = '米白'
  AND NOT EXISTS (SELECT 1 FROM product_skus s WHERE s.tenant_id = :tenant_id AND s.product_id = 'p-sl-001' AND s.color_id = c.id AND s.door_width = '2.8');

-- ──────────────────────────────────────────────
-- 4. 加工项（6 个布艺核心加工项）
-- ──────────────────────────────────────────────
INSERT INTO processing_categories (id, tenant_id, name, sort_order, status)
SELECT 'pc-cut', :tenant_id, '裁剪基础', 1, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_categories WHERE id = 'pc-cut' AND tenant_id = :tenant_id);

INSERT INTO processing_categories (id, tenant_id, name, sort_order, status)
SELECT 'pc-fold', :tenant_id, '褶皱工艺', 2, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_categories WHERE id = 'pc-fold' AND tenant_id = :tenant_id);

INSERT INTO processing_items (id, tenant_id, name, category_id, unit, description, processing_days, ai_recommended, status)
SELECT 'pi-lock', :tenant_id, '锁边', 'pc-cut', '米', '布料锁边处理，防止毛边散线', 1, TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_items WHERE id = 'pi-lock' AND tenant_id = :tenant_id);

INSERT INTO processing_items (id, tenant_id, name, category_id, unit, description, processing_days, ai_recommended, status)
SELECT 'pi-punch', :tenant_id, '打孔（罗马圈）', 'pc-fold', '米', '打孔加工，适配罗马杆，每米约6个孔', 1, TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_items WHERE id = 'pi-punch' AND tenant_id = :tenant_id);

INSERT INTO processing_items (id, tenant_id, name, category_id, unit, description, processing_days, ai_recommended, status)
SELECT 'pi-korean', :tenant_id, '韩式褶（S钩）', 'pc-fold', '米', '韩式固定褶，褶皱均匀饱满', 1, TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_items WHERE id = 'pi-korean' AND tenant_id = :tenant_id);

INSERT INTO processing_items (id, tenant_id, name, category_id, unit, description, processing_days, ai_recommended, status)
SELECT 'pi-hook', :tenant_id, '四爪钩（挂钩）', 'pc-fold', '米', '四爪钩式，含布带和钩子', 1, TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_items WHERE id = 'pi-hook' AND tenant_id = :tenant_id);

INSERT INTO processing_items (id, tenant_id, name, category_id, unit, description, processing_days, ai_recommended, status)
SELECT 'pi-hem', :tenant_id, '折边（脚位）', 'pc-cut', '米', '下摆折边处理，8cm脚位+止口', 1, TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_items WHERE id = 'pi-hem' AND tenant_id = :tenant_id);

INSERT INTO processing_items (id, tenant_id, name, category_id, unit, description, processing_days, ai_recommended, status)
SELECT 'pi-trim', :tenant_id, '帘头加工', 'pc-fold', '米', '帘头造型加工（花边另计）', 2, TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_items WHERE id = 'pi-trim' AND tenant_id = :tenant_id);

-- 注：按个计价的 pi-punch-pc / pi-hook-pc 已随 issue #3005 回滚移除——
-- 行业加工费按米计价、辅料（罗马圈/四爪钩等）含在按米加工费中（打孔按米 8 元即含圈含工），
-- 加工项无 per_piece 计价与「每米数量」密度；订单数量 = 面料米数（per_meter）/ 1（per_set/fixed/per_area）。

-- ──────────────────────────────────────────────
-- 5. 客户（3 个 RFM 客户）
-- ──────────────────────────────────────────────
INSERT INTO customer_profiles (id, tenant_id, wechat_nickname, phone, gender, region_city, vip_level, customer_status, source_channel, r_score, f_score, m_score, rfm_total_score, total_orders, total_consumption, lifecycle_stage, registered_at)
SELECT 'cu-001', :tenant_id, '林女士', '13800138001', 'female', '杭州市', 'vip2', 'active', 'wechat_mini', 5, 4, 4, 13, 6, 12800.00, 'mature', NOW() - INTERVAL '180 days'
WHERE NOT EXISTS (SELECT 1 FROM customer_profiles WHERE id = 'cu-001' AND tenant_id = :tenant_id);

INSERT INTO customer_profiles (id, tenant_id, wechat_nickname, phone, gender, region_city, vip_level, customer_status, source_channel, r_score, f_score, m_score, rfm_total_score, total_orders, total_consumption, lifecycle_stage, registered_at)
SELECT 'cu-002', :tenant_id, '王先生', '13900139002', 'male', '杭州市', 'normal', 'active', 'wechat_mini', 3, 3, 2, 8, 2, 3600.00, 'growing', NOW() - INTERVAL '60 days'
WHERE NOT EXISTS (SELECT 1 FROM customer_profiles WHERE id = 'cu-002' AND tenant_id = :tenant_id);

INSERT INTO customer_profiles (id, tenant_id, wechat_nickname, phone, gender, region_city, vip_level, customer_status, source_channel, r_score, f_score, m_score, rfm_total_score, total_orders, total_consumption, lifecycle_stage, registered_at)
SELECT 'cu-003', :tenant_id, '陈阿姨', '13700137003', 'female', '宁波市', 'vip1', 'active', 'wechat_mini', 2, 5, 3, 10, 5, 8500.00, 'mature', NOW() - INTERVAL '240 days'
WHERE NOT EXISTS (SELECT 1 FROM customer_profiles WHERE id = 'cu-003' AND tenant_id = :tenant_id);

-- ──────────────────────────────────────────────
-- 6. 订单（4 个不同状态 + 金额链闭合，issue #7583 缺陷 3）
--    口径（判据 = tests/unit_ci_workflows/test_seed_data_quality.py）：
--      ① `orders.total_amount` == Σ 该单 `order_items.subtotal`（逐单闭合，演示对账/报表才不会穿帮）；
--      ② 每单**至少一条明细**（旧形态 o-003 / o-004 有单无明细）；
--      ③ 明细 `unit_price` ∈ 该商品的 SKU 价集（p-zg-001 = 98.00 / p-zg-002 = 68.00 / p-sl-001 = 35.00）；
--      ④ `quantity × unit_price` == `subtotal`；`actual_amount`（已收）≤ `total_amount`。
--    ⇒ 改动任一金额时必须同步改另一半，否则判据当场红。
-- ──────────────────────────────────────────────
INSERT INTO orders (id, tenant_id, order_no, customer_name, customer_phone, customer_address, total_amount, actual_amount, status, follow_status, remark, created_at)
SELECT 'o-001', :tenant_id, 'YK20260801001', '林女士', '13800138001', '杭州市西湖区文三路100号', 1234.80, 1234.80, 'completed', 'completed', '星空全遮光窗帘 2 套（象牙白 + 藏蓝），打孔加工', NOW() - INTERVAL '20 days'
WHERE NOT EXISTS (SELECT 1 FROM orders WHERE id = 'o-001' AND tenant_id = :tenant_id);

INSERT INTO orders (id, tenant_id, order_no, customer_name, customer_phone, customer_address, total_amount, actual_amount, status, follow_status, remark, created_at)
SELECT 'o-002', :tenant_id, 'YK20260820002', '王先生', '13900139002', '杭州市滨江区江南大道200号', 3560.00, 3000.00, 'producing', 'following', '云朵半遮光窗帘 3 套 + 雾霭柔光纱帘，韩式褶加工，对花（已付定金 3000，尾款 560 赊账）', NOW() - INTERVAL '3 days'
WHERE NOT EXISTS (SELECT 1 FROM orders WHERE id = 'o-002' AND tenant_id = :tenant_id);

INSERT INTO orders (id, tenant_id, order_no, customer_name, customer_phone, customer_address, total_amount, actual_amount, status, follow_status, remark, created_at)
SELECT 'o-003', :tenant_id, 'YK20260828003', '陈阿姨', '13700137003', '宁波市鄞州区', 889.00, 0.00, 'confirmed', 'pending', '雾霭柔光纱帘 1 套（未付款，赊账待收）', NOW() - INTERVAL '1 day'
WHERE NOT EXISTS (SELECT 1 FROM orders WHERE id = 'o-003' AND tenant_id = :tenant_id);

INSERT INTO orders (id, tenant_id, order_no, customer_name, customer_phone, customer_address, total_amount, actual_amount, status, follow_status, remark, created_at)
SELECT 'o-004', :tenant_id, 'YK20260829004', '林女士', '13800138001', '杭州市西湖区文三路100号', 2040.00, 0.00, 'pending', 'pending', '云朵半遮光窗帘 1 套，待确认尺寸（未付款）', NOW()
WHERE NOT EXISTS (SELECT 1 FROM orders WHERE id = 'o-004' AND tenant_id = :tenant_id);

-- 订单明细：o-001（星空全遮光 × 2 套 = 646.80 + 588.00 = 1234.80）
INSERT INTO order_items (id, tenant_id, order_id, product_id, product_name, quantity, unit_price, width, height, subtotal, created_at)
SELECT 'oi-001', :tenant_id, 'o-001', 'p-zg-001', '星空全遮光窗帘', 6.6, 98.00, 3.0, 2.5, 646.80, NOW() - INTERVAL '20 days'
WHERE NOT EXISTS (SELECT 1 FROM order_items WHERE id = 'oi-001' AND tenant_id = :tenant_id);

INSERT INTO order_items (id, tenant_id, order_id, product_id, product_name, quantity, unit_price, width, height, subtotal, created_at)
SELECT 'oi-003', :tenant_id, 'o-001', 'p-zg-001', '星空全遮光窗帘', 6.0, 98.00, 3.2, 2.6, 588.00, NOW() - INTERVAL '20 days'
WHERE NOT EXISTS (SELECT 1 FROM order_items WHERE id = 'oi-003' AND tenant_id = :tenant_id);

-- 订单明细：o-002（云朵半遮光 40 米 × 68.00 + 雾霭柔光纱 24 米 × 35.00 = 3560.00）
INSERT INTO order_items (id, tenant_id, order_id, product_id, product_name, quantity, unit_price, width, height, subtotal, created_at)
SELECT 'oi-002', :tenant_id, 'o-002', 'p-zg-002', '云朵半遮光窗帘', 40.0, 68.00, 2.8, 2.7, 2720.00, NOW() - INTERVAL '3 days'
WHERE NOT EXISTS (SELECT 1 FROM order_items WHERE id = 'oi-002' AND tenant_id = :tenant_id);

INSERT INTO order_items (id, tenant_id, order_id, product_id, product_name, quantity, unit_price, width, height, subtotal, created_at)
SELECT 'oi-004', :tenant_id, 'o-002', 'p-sl-001', '雾霭柔光纱帘', 24.0, 35.00, 2.8, 2.7, 840.00, NOW() - INTERVAL '3 days'
WHERE NOT EXISTS (SELECT 1 FROM order_items WHERE id = 'oi-004' AND tenant_id = :tenant_id);

-- 订单明细：o-003（雾霭柔光纱 25.4 米 × 35.00 = 889.00）
INSERT INTO order_items (id, tenant_id, order_id, product_id, product_name, quantity, unit_price, width, height, subtotal, created_at)
SELECT 'oi-005', :tenant_id, 'o-003', 'p-sl-001', '雾霭柔光纱帘', 25.4, 35.00, 3.0, 2.6, 889.00, NOW() - INTERVAL '1 day'
WHERE NOT EXISTS (SELECT 1 FROM order_items WHERE id = 'oi-005' AND tenant_id = :tenant_id);

-- 订单明细：o-004（云朵半遮光 30 米 × 68.00 = 2040.00）
INSERT INTO order_items (id, tenant_id, order_id, product_id, product_name, quantity, unit_price, width, height, subtotal, created_at)
SELECT 'oi-006', :tenant_id, 'o-004', 'p-zg-002', '云朵半遮光窗帘', 30.0, 68.00, 3.0, 2.6, 2040.00, NOW()
WHERE NOT EXISTS (SELECT 1 FROM order_items WHERE id = 'oi-006' AND tenant_id = :tenant_id);

-- ──────────────────────────────────────────────
-- 完成
-- ──────────────────────────────────────────────
SELECT 'POC 演示数据 seed 完成' AS status;
