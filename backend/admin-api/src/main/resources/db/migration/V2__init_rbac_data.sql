-- ============================================
-- RBAC 权限系统初始化数据
-- 包含默认权限、角色、管理员用户
-- ============================================

-- --------------------------------------------
-- 1. 默认权限数据
-- --------------------------------------------
INSERT INTO permissions (id, tenant_id, name, code, resource_type, resource_id, action, description, status, deleted, created_at, updated_at) VALUES
('perm_dashboard_view', 'DEFAULT', '查看数据看板', 'dashboard:view', 'page', 'dashboard', 'view', '查看数据看板页面', 'active', 0, NOW(), NOW()),
('perm_order_list', 'DEFAULT', '订单列表', 'order:list', 'page', 'order', 'list', '查看订单列表', 'active', 0, NOW(), NOW()),
('perm_order_detail', 'DEFAULT', '订单详情', 'order:detail', 'page', 'order', 'detail', '查看订单详情', 'active', 0, NOW(), NOW()),
('perm_order_refund', 'DEFAULT', '退换货', 'order:refund', 'page', 'order', 'refund', '退换货操作', 'active', 0, NOW(), NOW()),
('perm_product_manage', 'DEFAULT', '商品管理', 'product:manage', 'module', 'product', 'manage', '管理商品和分类', 'active', 0, NOW(), NOW()),
('perm_product_list', 'DEFAULT', '商品列表', 'product:list', 'page', 'product', 'list', '查看商品列表', 'active', 0, NOW(), NOW()),
('perm_product_create', 'DEFAULT', '新增商品', 'product:create', 'page', 'product', 'create', '新增商品', 'active', 0, NOW(), NOW()),
('perm_product_category', 'DEFAULT', '商品分类管理', 'product:category', 'page', 'product', 'category', '管理商品分类', 'active', 0, NOW(), NOW()),
('perm_processing_manage', 'DEFAULT', '加工项管理', 'processing:manage', 'module', 'processing', 'manage', '管理加工项和分类', 'active', 0, NOW(), NOW()),
('perm_knowledge_manage', 'DEFAULT', '知识库管理', 'knowledge:manage', 'module', 'knowledge', 'manage', '管理知识库文档', 'active', 0, NOW(), NOW()),
('perm_agent_session', 'DEFAULT', '会话监控', 'agent:session', 'page', 'agent', 'session', '监控客服会话', 'active', 0, NOW(), NOW()),
('perm_agent_quickreply', 'DEFAULT', '快捷回复', 'agent:quickreply', 'page', 'agent', 'quickreply', '管理快捷回复', 'active', 0, NOW(), NOW()),
('perm_employee_list', 'DEFAULT', '员工列表', 'employee:list', 'page', 'employee', 'list', '查看员工列表', 'active', 0, NOW(), NOW()),
('perm_employee_create', 'DEFAULT', '新增员工', 'employee:create', 'page', 'employee', 'create', '新增员工', 'active', 0, NOW(), NOW()),
('perm_system_manage', 'DEFAULT', '系统管理', 'system:manage', 'module', 'system', 'manage', '系统设置', 'active', 0, NOW(), NOW());

-- --------------------------------------------
-- 2. 默认角色数据
-- --------------------------------------------
INSERT INTO roles (id, tenant_id, name, code, description, status, deleted, created_at, updated_at) VALUES
('role_admin', 'DEFAULT', '管理员', 'admin', '拥有大部分管理权限', 'active', 0, NOW(), NOW()),
('role_operator', 'DEFAULT', '运营人员', 'operator', '管理商品和知识库', 'active', 0, NOW(), NOW()),
('role_product_manager', 'DEFAULT', '商品管理员', 'product_manager', '管理商品和加工项', 'active', 0, NOW(), NOW()),
('role_knowledge_editor', 'DEFAULT', '知识库编辑', 'knowledge_editor', '管理知识库', 'active', 0, NOW(), NOW());

-- --------------------------------------------
-- 3. 用户角色关联数据（为管理员用户分配管理员角色）
-- 注意：需要先创建用户，然后关联角色
-- --------------------------------------------

-- 假设管理员用户的ID为 'user_admin_001'（需要在用户创建后执行）
-- INSERT INTO user_roles (id, tenant_id, user_id, role_id, deleted, created_at) VALUES
-- ('ur_admin_001', 'DEFAULT', 'user_admin_001', 'role_admin', 0, NOW());

-- --------------------------------------------
-- 4. 默认管理员用户（仅非生产环境）
--    手机号: 13800138000  密码: admin123
--    生产环境通过 FLYWAY_SKIP_SEED_USERS=true 跳过
--    ⚠️ 安全提示: 此 INSERT 仅用于 dev/staging 环境
-- --------------------------------------------
-- 插入默认管理员用户（所有环境幂等，ON CONFLICT 保证不重复）
INSERT INTO users (id, tenant_id, phone, password_hash, nickname, avatar, role, session_ttl, status, deleted, created_at, updated_at) VALUES
('user_admin_001', 'DEFAULT', '13800138000', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iAt6Z5EO', '系统管理员', NULL, 'admin', 7200, 'active', 0, NOW(), NOW())
ON CONFLICT (id) DO NOTHING;

-- 为管理员用户关联管理员角色
INSERT INTO user_roles (id, tenant_id, user_id, role_id, deleted, created_at) VALUES
('ur_admin_001', 'DEFAULT', 'user_admin_001', 'role_admin', 0, NOW())
ON CONFLICT DO NOTHING;

-- --------------------------------------------
-- 5. 测试用户数据（可选）
-- --------------------------------------------

-- 运营人员账号（手机号: 13900139000，短信验证码: 123456）
-- INSERT INTO users (id, tenant_id, phone, password_hash, nickname, avatar, role, session_ttl, status, deleted, created_at, updated_at) VALUES
-- ('user_operator_001', 'DEFAULT', '13900139000', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iAt6Z5EO', '运营人员', NULL, 'operator', 7200, 'active', 0, NOW(), NOW());

-- INSERT INTO user_roles (id, tenant_id, user_id, role_id, deleted, created_at) VALUES
-- ('ur_operator_001', 'DEFAULT', 'user_operator_001', 'role_operator', 0, NOW());

-- --------------------------------------------
-- 6. 权限说明
-- --------------------------------------------
-- 权限格式: 模块:操作
--   - dashboard:view    - 查看数据看板
--   - product:manage    - 商品管理（包含增删改查）
--   - processing:manage - 加工项管理
--   - knowledge:manage  - 知识库管理
--   - system:manage     - 系统管理
--
-- 角色权限映射:
--   - admin:            dashboard:view, product:manage, processing:manage, knowledge:manage, system:manage
--   - operator:         dashboard:view, product:manage, knowledge:manage
--   - product_manager:  dashboard:view, product:manage, processing:manage
--   - knowledge_editor: dashboard:view, knowledge:manage
--
-- 菜单权限映射:
--   - dashboard:view    → 数据看板
--   - product:manage    → 商品管理
--   - processing:manage → 加工项管理
--   - knowledge:manage  → 知识库管理
--   - system:manage     → 系统设置
-- --------------------------------------------
