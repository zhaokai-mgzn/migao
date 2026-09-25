-- V128 — 员工登录标识 + 首登强制改密（issue #5485）
--
-- 背景：登录重构为「企业管理员 = 手机号 + 短信」「员工 = 用户名@企业编码 + 密码」。
--   · `users.username`：员工登录用户名。**存量行保持 NULL**（issue #5485 明确裁定：不自动迁移、
--     不自动生成用户名；管理员逐个补设前无法登录是预期行为）；
--   · 唯一性是**租户内**的（部分唯一索引，NULL 不参与）⇒ 不同企业可以有同名员工，
--     而跨企业串号由「登录时先由 tenantCode 解析出 tenant_id、查询必须带 tenant_id」挡住；
--   · `users.must_change_password`：管理员设的初始密码必须首登改掉（默认 FALSE ⇒ 存量行不受影响）。
--
-- 幂等：可在「对象已存在」的库上重复执行（建库脚本已建出终态后，本目录仍会照常跑一遍）。

ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(64);
ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS uk_users_tenant_username
    ON users (tenant_id, username)
    WHERE username IS NOT NULL AND deleted = 0;