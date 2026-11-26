-- 产品品牌内置值随产品更名：观星台 → 生意管家（issue #9121）
--
-- 背景：`frontend/admin-web/src/components/products/ProductAttributes.tsx` 的「品牌」下拉
-- 内置了平台自有品牌值 `观星台`。产品更名后，新的写入用 `生意管家`；存量行若不回填，
-- 商家在商品详情里会继续看到旧品牌名。
--
-- 口径（用户 2026-11-24 逐字「把PC端和小程序端和官网的『观星台』『词元观星台』都更名为
-- 『生意管家』」）：只改**精确等于** `观星台` 的品牌值，其余自定义品牌一字不动。
--
-- 幂等：带旧值谓词 ⇒ 重复执行不会产生第二次变化。
-- 回滚：UPDATE product_attributes SET attr_value = '观星台'
--       WHERE attr_key = 'brand' AND attr_value = '生意管家';
--       （回滚会把用户后来主动改成的「生意管家」一并改回旧名；如已发生，按业务需要人工核。）
UPDATE product_attributes
SET attr_value = '生意管家'
WHERE attr_key = 'brand'
  AND attr_value = '观星台';
