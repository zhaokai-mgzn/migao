-- ============================================================
-- 米高 POC 演示数据 seed 脚本
--
-- 用途：为 POC 演示准备真实感演示数据（窗帘商品 + SKU 矩阵 + 加工项 + 客户 + 订单）
-- 用法：psql "$DATABASE_URL" -v tenant_id=1 -f demo-seed.sql
-- 幂等：所有 INSERT 用 WHERE NOT EXISTS 守卫，可重复执行
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
INSERT INTO products (id, tenant_id, name, category_id, base_price, description, unit, pricing_type, sku_code, has_processing, status)
SELECT 'p-zg-001', :tenant_id, '星空全遮光窗帘', 'cat-curtain', 98.00,
       '高精密涤纶三层织造，遮光率99%以上，物理遮光无甲醛，双面同色，垂感优良',
       '米', 'per_meter', 'MG-ZG-001', TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM products WHERE id = 'p-zg-001' AND tenant_id = :tenant_id);

INSERT INTO products (id, tenant_id, name, category_id, base_price, description, unit, pricing_type, sku_code, has_processing, status)
SELECT 'p-zg-002', :tenant_id, '云朵半遮光窗帘', 'cat-curtain', 68.00,
       '涤纶高密度编织，遮光率75%-85%，莫兰迪色系，柔软细腻，适合客厅书房',
       '米', 'per_meter', 'MG-ZG-002', TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM products WHERE id = 'p-zg-002' AND tenant_id = :tenant_id);

INSERT INTO products (id, tenant_id, name, category_id, base_price, description, unit, pricing_type, sku_code, has_processing, status)
SELECT 'p-sl-001', :tenant_id, '雾霭柔光纱帘', 'cat-sheer', 35.00,
       '涤纶雪纺纱，透光不透人，2.8米超宽幅减少拼接，轻盈飘逸',
       '米', 'per_meter', 'MG-SL-001', FALSE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM products WHERE id = 'p-sl-001' AND tenant_id = :tenant_id);

-- ──────────────────────────────────────────────
-- 3. 颜色 + SKU 矩阵（颜色×售卖方式×门幅）
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

-- SKU：星空全遮光（象牙白 × 散剪/整卷 × 2.8米/1.4米）
DO $$
DECLARE cid BIGINT;
BEGIN
  SELECT id INTO cid FROM product_colors WHERE tenant_id = :tenant_id AND product_id = 'p-zg-001' AND color_name = '象牙白';
  IF cid IS NOT NULL THEN
    INSERT INTO product_skus (tenant_id, product_id, color_id, selling_method, door_width, price, stock, sku_code)
    SELECT :tenant_id, 'p-zg-001', cid, 'bulk_cut', '2.8米', 98.00, 500, 'ZG001-象牙白-散剪-2.8'
    WHERE NOT EXISTS (SELECT 1 FROM product_skus WHERE tenant_id = :tenant_id AND product_id = 'p-zg-001' AND color_id = cid AND selling_method = 'bulk_cut' AND door_width = '2.8米');
    INSERT INTO product_skus (tenant_id, product_id, color_id, selling_method, door_width, price, stock, sku_code)
    SELECT :tenant_id, 'p-zg-001', cid, 'full_roll', '2.8米', 88.00, 100, 'ZG001-象牙白-整卷-2.8'
    WHERE NOT EXISTS (SELECT 1 FROM product_skus WHERE tenant_id = :tenant_id AND product_id = 'p-zg-001' AND color_id = cid AND selling_method = 'full_roll' AND door_width = '2.8米');
  END IF;
END $$;

-- SKU：雾霭柔光纱（白色 × 散剪 × 2.8米）
DO $$
DECLARE cid BIGINT;
BEGIN
  SELECT id INTO cid FROM product_colors WHERE tenant_id = :tenant_id AND product_id = 'p-sl-001' AND color_name = '白色';
  IF cid IS NOT NULL THEN
    INSERT INTO product_skus (tenant_id, product_id, color_id, selling_method, door_width, price, stock, sku_code)
    SELECT :tenant_id, 'p-sl-001', cid, 'bulk_cut', '2.8米', 35.00, 800, 'SL001-白色-散剪-2.8'
    WHERE NOT EXISTS (SELECT 1 FROM product_skus WHERE tenant_id = :tenant_id AND product_id = 'p-sl-001' AND color_id = cid AND selling_method = 'bulk_cut' AND door_width = '2.8米');
  END IF;
END $$;

-- ──────────────────────────────────────────────
-- 4. 加工项（6 个布艺核心加工项）
-- ──────────────────────────────────────────────
INSERT INTO processing_categories (id, tenant_id, name, sort_order, status)
SELECT 'pc-cut', :tenant_id, '裁剪基础', 1, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_categories WHERE id = 'pc-cut' AND tenant_id = :tenant_id);

INSERT INTO processing_categories (id, tenant_id, name, sort_order, status)
SELECT 'pc-fold', :tenant_id, '褶皱工艺', 2, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_categories WHERE id = 'pc-fold' AND tenant_id = :tenant_id);

INSERT INTO processing_items (id, tenant_id, name, category_id, pricing_method, unit_price, unit, description, processing_days, ai_recommended, status)
SELECT 'pi-lock', :tenant_id, '锁边', 'pc-cut', 'per_meter', 5.00, '元', '布料锁边处理，防止毛边散线', 1, TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_items WHERE id = 'pi-lock' AND tenant_id = :tenant_id);

INSERT INTO processing_items (id, tenant_id, name, category_id, pricing_method, unit_price, unit, description, processing_days, ai_recommended, status)
SELECT 'pi-punch', :tenant_id, '打孔（罗马圈）', 'pc-fold', 'per_meter', 8.00, '元', '打孔加工，适配罗马杆，每米约6个孔', 1, TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_items WHERE id = 'pi-punch' AND tenant_id = :tenant_id);

INSERT INTO processing_items (id, tenant_id, name, category_id, pricing_method, unit_price, unit, description, processing_days, ai_recommended, status)
SELECT 'pi-korean', :tenant_id, '韩式褶（S钩）', 'pc-fold', 'per_meter', 10.00, '元', '韩式固定褶，褶皱均匀饱满', 1, TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_items WHERE id = 'pi-korean' AND tenant_id = :tenant_id);

INSERT INTO processing_items (id, tenant_id, name, category_id, pricing_method, unit_price, unit, description, processing_days, ai_recommended, status)
SELECT 'pi-hook', :tenant_id, '四爪钩（挂钩）', 'pc-fold', 'per_meter', 5.00, '元', '四爪钩式，含布带和钩子', 1, TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_items WHERE id = 'pi-hook' AND tenant_id = :tenant_id);

INSERT INTO processing_items (id, tenant_id, name, category_id, pricing_method, unit_price, unit, description, processing_days, ai_recommended, status)
SELECT 'pi-hem', :tenant_id, '折边（脚位）', 'pc-cut', 'per_meter', 10.00, '元', '下摆折边处理，8cm脚位+止口', 1, TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_items WHERE id = 'pi-hem' AND tenant_id = :tenant_id);

INSERT INTO processing_items (id, tenant_id, name, category_id, pricing_method, unit_price, unit, description, processing_days, ai_recommended, status)
SELECT 'pi-trim', :tenant_id, '帘头加工', 'pc-fold', 'per_meter', 50.00, '元', '帘头造型加工（花边另计）', 2, TRUE, 'active'
WHERE NOT EXISTS (SELECT 1 FROM processing_items WHERE id = 'pi-trim' AND tenant_id = :tenant_id);

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
-- 6. 订单（4 个不同状态）
-- ──────────────────────────────────────────────
INSERT INTO orders (id, tenant_id, order_no, customer_name, customer_phone, customer_address, total_amount, status, payment_status, follow_status, remark, created_at)
SELECT 'o-001', :tenant_id, 'YK20260801001', '林女士', '13800138001', '杭州市西湖区文三路100号', 1280.50, 'completed', 'paid', 'completed', '星空全遮光窗帘 2 套，打孔加工', NOW() - INTERVAL '20 days'
WHERE NOT EXISTS (SELECT 1 FROM orders WHERE id = 'o-001' AND tenant_id = :tenant_id);

INSERT INTO orders (id, tenant_id, order_no, customer_name, customer_phone, customer_address, total_amount, status, payment_status, follow_status, remark, created_at)
SELECT 'o-002', :tenant_id, 'YK20260820002', '王先生', '13900139002', '杭州市滨江区江南大道200号', 3560.00, 'producing', 'paid', 'following', '雪尼尔窗帘 3 套，韩式褶加工，对花', NOW() - INTERVAL '3 days'
WHERE NOT EXISTS (SELECT 1 FROM orders WHERE id = 'o-002' AND tenant_id = :tenant_id);

INSERT INTO orders (id, tenant_id, order_no, customer_name, customer_phone, customer_address, total_amount, status, payment_status, follow_status, remark, created_at)
SELECT 'o-003', :tenant_id, 'YK20260828003', '陈阿姨', '13700137003', '宁波市鄞州区', 890.00, 'confirmed', 'unpaid', 'pending', '雾霭柔光纱帘 1 套', NOW() - INTERVAL '1 day'
WHERE NOT EXISTS (SELECT 1 FROM orders WHERE id = 'o-003' AND tenant_id = :tenant_id);

INSERT INTO orders (id, tenant_id, order_no, customer_name, customer_phone, customer_address, total_amount, status, payment_status, follow_status, remark, created_at)
SELECT 'o-004', :tenant_id, 'YK20260829004', '林女士', '13800138001', '杭州市西湖区文三路100号', 2200.00, 'pending', 'unpaid', 'pending', '云朵半遮光窗帘 1 套，待确认尺寸', NOW()
WHERE NOT EXISTS (SELECT 1 FROM orders WHERE id = 'o-004' AND tenant_id = :tenant_id);

-- 订单明细（o-001）
INSERT INTO order_items (id, tenant_id, order_id, product_id, product_name, quantity, unit_price, width, height, subtotal, created_at)
SELECT 'oi-001', :tenant_id, 'o-001', 'p-zg-001', '星空全遮光窗帘', 6.6, 98.00, 3.0, 2.5, 646.80, NOW() - INTERVAL '20 days'
WHERE NOT EXISTS (SELECT 1 FROM order_items WHERE id = 'oi-001' AND tenant_id = :tenant_id);

-- 订单明细（o-002）
INSERT INTO order_items (id, tenant_id, order_id, product_id, product_name, quantity, unit_price, width, height, subtotal, created_at)
SELECT 'oi-002', :tenant_id, 'o-002', 'p-zg-001', '星空全遮光窗帘', 9.0, 128.00, 3.0, 2.7, 1152.00, NOW() - INTERVAL '3 days'
WHERE NOT EXISTS (SELECT 1 FROM order_items WHERE id = 'oi-002' AND tenant_id = :tenant_id);

-- ──────────────────────────────────────────────
-- 完成
-- ──────────────────────────────────────────────
SELECT 'POC 演示数据 seed 完成' AS status;
