-- 角色-权限关联表（角色授权真实落库）
-- 此前角色页勾选的权限在 createRole/updateRole 中被忽略（assignPermissions 占位实现），
-- 自定义角色因此拿不到任何权限（角色权限为代码硬编码 + 员工个人权限码）。
-- 本表启用后：角色管理勾选的权限码持久化，getUserPermissions 按 role_permissions 合并。
CREATE TABLE IF NOT EXISTS role_permissions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id BIGINT NOT NULL,
    role_id VARCHAR(64) NOT NULL,
    permission_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    deleted INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_role_permissions_role ON role_permissions(role_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_role_permissions ON role_permissions(role_id, permission_id);
