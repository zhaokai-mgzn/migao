-- ============================================================
-- 004_tenant_applications.sql - 企业入驻申请表 + 超管角色初始化
-- 版本: v1.0
-- 日期: 2026-05-02
-- 说明: 创建企业入驻申请表（平台级，无 tenant_id）
--       初始化超管角色和权限
-- ============================================================

-- ============================================================
-- 1. 企业入驻申请表 (tenant_applications)
-- 平台级表，不属于任何租户
-- ============================================================
CREATE TABLE IF NOT EXISTS tenant_applications (
    id BIGSERIAL PRIMARY KEY,
    company_name VARCHAR(200) NOT NULL,
    contact_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20) NOT NULL,
    business_license_url VARCHAR(500),
    industry VARCHAR(100),
    address TEXT,
    description TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending/approved/rejected
    reject_reason TEXT,
    reviewed_by VARCHAR(64) REFERENCES users(id),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tenant_applications_phone ON tenant_applications(phone);
CREATE INDEX idx_tenant_applications_status ON tenant_applications(status);

-- ============================================================
-- 2. 超管角色和权限初始化
-- 超管是平台级别的，tenant_id 使用默认租户(1)
-- ============================================================

-- 创建超管角色
INSERT INTO roles (id, tenant_id, name, code, description, status) VALUES
    ('role_super_admin', 1, '超级管理员', 'super_admin', '平台超级管理员，拥有所有权限（含审批入驻）', 'active'),
    ('role_tenant_admin', 1, '企业管理员', 'tenant_admin', '企业入驻后的默认管理员角色', 'active')
ON CONFLICT DO NOTHING;

-- 创建超管相关权限
INSERT INTO permissions (id, tenant_id, name, code, resource_type, action, description, status) VALUES
    ('perm_registration_manage', 1, '入驻审批管理', 'registration:manage', 'registration', 'manage', '审批企业入驻申请', 'active'),
    ('perm_tenant_manage', 1, '租户管理', 'tenant:manage', 'tenant', 'manage', '管理所有租户', 'active'),
    ('perm_dashboard_view', 1, '仪表板查看', 'dashboard:view', 'dashboard', 'view', '查看数据概览', 'active'),
    ('perm_product_manage', 1, '商品管理', 'product:manage', 'product', 'manage', '管理商品', 'active'),
    ('perm_processing_manage', 1, '加工管理', 'processing:manage', 'processing', 'manage', '管理加工项', 'active'),
    ('perm_knowledge_manage', 1, '知识库管理', 'knowledge:manage', 'knowledge', 'manage', '管理知识库', 'active'),
    ('perm_system_manage', 1, '系统管理', 'system:manage', 'system', 'manage', '管理系统设置', 'active')
ON CONFLICT DO NOTHING;

-- 超管角色关联权限（角色-权限暂无独立关联表，角色通过 code 匹配权限）

-- ============================================================
-- 3. 默认超级管理员用户初始化
-- 平台级账号，tenant_id 使用默认租户(1)
-- 登录用户名: superadmin  默认密码: Admin@2024 （BCrypt 加密）
-- 请在生产环境部署后立即修改密码！
-- ============================================================
INSERT INTO users (id, tenant_id, phone, password_hash, nickname, role, status) VALUES
    ('user_superadmin', 1, 'superadmin', '$2a$10$S1F2r6kKqL61LP8mWy21xOqea7qyfTH8/NGkAMPrUqHvm0BTSZ5F.', '超级管理员', 'super_admin', 'active')
ON CONFLICT DO NOTHING;

-- 超管用户关联超管角色
INSERT INTO user_roles (id, tenant_id, user_id, role_id) VALUES
    ('ur_superadmin', 1, 'user_superadmin', 'role_super_admin')
ON CONFLICT DO NOTHING;
