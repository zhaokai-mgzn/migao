-- #4865 验收剧本的**可辨识**临时实体（全部以 acc-fix4865- 前缀；跑完由 run.sh 复查 0 残留）
-- 租户 1（米高智能 / migao）由 docs/sql/schema.sql 播种。
--
-- 账号：role=admin ⇒ RoleService.getUserPermissions 返回 ["*"]（租户管理员全权限）
--       ⇒ 走**真实登录端点** POST /api/auth/sms/login 拿 token（不手搓 JWT）。
INSERT INTO users (id, tenant_id, phone, nickname, role, status, deleted)
VALUES ('acc-fix4865-user', 1, '13900004865', 'acc-fix4865 验收账号', 'admin', 'active', 0);

-- 订单 + 3 个部位行（布/纱/帘头）：curtain_type/craft 走 V63 列 ⇒ 路线可派生（布帘×韩褶 / 帘头×平幔）；
-- processing_info.craftLineId 三条相同 ⇒ **一樘窗**（1 套 ⇒ 3 个部位码，与 #4865 实测形态同构）。
INSERT INTO orders (id, tenant_id, order_no, status, total_amount)
VALUES ('acc-fix4865-order', 1, 'acc-fix4865-ORD', 'confirmed', 100);

INSERT INTO order_items (id, tenant_id, order_id, product_name, quantity, curtain_type, craft,
                         processing_info)
VALUES
  ('acc-fix4865-i1', 1, 'acc-fix4865-order', '布帘', 3.20, '布帘', '韩褶',
   '{"craftLineId":"acc-fix4865-cl-A","processingItems":[{"name":"韩褶","pricingMethod":"per_meter"}]}'::jsonb),
  ('acc-fix4865-i2', 1, 'acc-fix4865-order', '纱帘', 3.20, '纱帘', '韩褶',
   '{"craftLineId":"acc-fix4865-cl-A","processingItems":[{"name":"韩褶","pricingMethod":"per_meter"}]}'::jsonb),
  ('acc-fix4865-i3', 1, 'acc-fix4865-order', '帘头', 1.00, '帘头', '平幔',
   '{"craftLineId":"acc-fix4865-cl-A","processingItems":[{"name":"平幔","pricingMethod":"per_set"}]}'::jsonb);
