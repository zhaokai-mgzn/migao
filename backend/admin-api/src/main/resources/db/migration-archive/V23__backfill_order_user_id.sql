-- V20260902: 存量订单按 customer_phone 回填 user_id
-- 背景：orders.user_id 是新增字段，历史订单为空。
-- 回填策略：以 customer_phone 精确匹配 users.phone（同租户内），
-- 能唯一匹配到 C 端用户则绑定；无法匹配的保持 NULL（视为"游客/商户代录订单"，
-- C 端"我的订单"查询不可见——语义正确，因为无法证明归属）。
--
-- 注意：同租户内同手机号可能命中多个 users 记录（如员工账号与顾客账号同号），
-- 此时只回填能唯一匹配的（COUNT = 1），避免误绑。
UPDATE orders o
SET user_id = (
    SELECT u.id
    FROM users u
    WHERE u.deleted = 0
      AND u.tenant_id = o.tenant_id
      AND u.phone = o.customer_phone
    LIMIT 1
)
WHERE o.user_id IS NULL
  AND o.customer_phone IS NOT NULL
  AND (
      SELECT COUNT(*)
      FROM users u
      WHERE u.deleted = 0
        AND u.tenant_id = o.tenant_id
        AND u.phone = o.customer_phone
  ) = 1;
