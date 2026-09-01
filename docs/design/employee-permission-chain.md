# 员工管理权限全链路 + 企业基础信息设置（2026-08-28 交付说明）

> 本文说明两条链路当前如何工作、如何验证，以及「企业基础信息」各设置项的用途与体现位置。

---

## 一、员工管理权限全链路（已打通）

### 1.1 链路全景

```
管理员在「员工管理 → 新增/编辑员工 → 账号权限」勾选权限码（菜单树）
  → users.permissions (JSON) 落库（admin 角色恒为 "*"）
管理员在「角色管理 → 新增/编辑角色」勾选权限
  → role_permissions 落库（V16），角色列表/详情回显勾选
员工用手机号 + 短信验证码登录
  → /api/auth/me 返回 permissions（角色 role_permissions ∪ 员工个人权限码）+ 按权限生成的 menus
  → 前端侧边栏按权限过滤菜单（Sidebar.tsx usePermission）
  → 前端路由守卫：无权限访问页面 → 403 提示页（layout.tsx ROUTE_PERMISSION_MAP）
  → 前端按钮级权限：仅 employee:create 才显示 新增/编辑/删除/禁用（employees/page.tsx）
  → 后端门禁：/api/admin/** 仅商户员工角色可进（SecurityConfig.adminApiAuthorizationManager）
  → 后端细粒度：@RequirePermission + PermissionInterceptor 按权限码 403
  → 米宝：JWT permissions → ToolContext.permissions → employee_manage 按 employee:list / employee:create 放行
```

### 1.2 关键口径

| 权限码 | 含义 | 前端 | 后端接口 | 米宝工具 |
|--------|------|------|---------|---------|
| `employee:list` | 查看员工列表/详情 | 员工管理菜单、页面可访问 | GET /api/admin/users, GET /{id} | employee_manage list/detail |
| `employee:create` | 新增/编辑/删除/禁用/重置密码 | 新增/编辑/删除/状态按钮 | POST /users, PUT /{id}, DELETE, reset-password, status | employee_manage 其余 action |
| `system:manage` | 企业基础信息/角色管理 | 企业基础信息菜单 | /api/admin/settings*, /api/admin/roles* | settings_manage |

- **角色来源**：`RoleService.getUserPermissions(userId)` = 角色权限（`role_permissions` 优先，内置角色回退硬编码）∪ 员工个人权限码；admin 恒为 `["*"]`。
- **角色授权**：`role_permissions(role_id, permission_id)` 表承载角色管理页勾选的权限（V16 迁移），`assignPermissions` 全量替换，角色列表/详情回填 `permissions` 回显。
- **门禁**：`/api/admin/**` 允许平台管理员(admin/super_admin)/内部服务(service)/商户员工角色；
  `customer`/`agent`（小程序/B2C 用户）一律 403（垂直越权防护不回归）。
- **平台管理员/内部服务**：`PermissionInterceptor` 对 super_admin / service 直通（不查租户权限表）。

### 1.3 验证方式

```bash
# 单元/集成（已全绿）
cd backend/admin-api && ./mvnw test -Dtest='SecurityConfigTest,PermissionInterceptorTest,AdminUserControllerTest'
cd backend/ai-agent-service && .venv/bin/python -m pytest tests/test_tools_employee_manage.py -q
cd frontend/admin-web && npx vitest run tests/unit/pages/employees.test.tsx tests/unit/lib/auth-guard.test.tsx

# 真实 API 全链路（本地服务 + 云 dev 库，已通过）
# 步骤：管理员登录 → 创建 custom_staff 员工(仅 dashboard:view+employee:list) → 员工登录
# → 菜单仅 [dashboard, employees] → GET /users 200 / POST /users 403 / PUT status 403 / GET /orders 403
```

---

## 二、企业基础信息设置：用途与体现

### 2.1 三个 Tab

| Tab | 内容 | 落库位置 | 用途 |
|-----|------|---------|------|
| 基本设置 | 公司名称 / Logo / 系统通知开关 / 通知邮箱 | `tenants.name` / `tenants.logo` / `tenants.notification_enabled` / `tenants.notification_email` | 品牌展示 + 通知配置 |
| 修改密码 | 原密码 + 新密码 | `users.password_hash` | 账号安全（自服务） |
| 登录日志 | 登录时间/IP/设备/用户 | `audit_logs`（action=login） | 登录审计 |

### 2.2 各项设置「如何使用和体现」

| 设置项 | 在哪里体现 / 被谁使用 |
|--------|----------------------|
| **公司名称** (companyName) | ① 后台侧边栏企业名（`/api/auth/me → user.tenantName`）；② 米宝 System Prompt 企业身份（`【企业信息】你当前服务的企业是「xxx」`，替代硬编码“词元通达”） |
| **Logo** | 后台侧边栏企业名旁的图片（`user.tenantLogo`）。**未设置/已移除/URL 加载失败时均回退米高默认 Logo**（侧边栏与设置页预览一致，不出现空白/破图）；设置页提供「上传 Logo」「移除 Logo」入口，移除后保存即落库为 NULL。**上传校验**：格式（JPG/PNG/WebP）+ 大小（≤5MB，前后端双端）+ 分辨率（≥128×128，前端读取自然尺寸，过低阻止上传并提示） |
| **系统通知开关 / 通知邮箱** | 持久化保存（刷新不丢）；当前为站内通知开关的配置项，后续通知触达（短信/邮件）接入时读取该配置 |
| **修改密码** | 修改当前登录账号密码（后端 PUT /api/admin/settings/password 校验原密码） |
| **登录日志** | 展示本租户 action=login 的审计日志（IP/设备/时间），支持分页 |

> ⚠️ 2026-08-28 修复：此前 Logo/通知设置仅存前端 state（刷新即丢，后端忽略字段），
> 现已迁移 `V15__add_branding_to_tenants.sql` 落库；并修复 MyBatis-Plus `updateById`
> 跳过 null 导致「无法清空 Logo/邮箱」的问题（改用 UpdateWrapper 显式 set）。

### 2.3 数据流

```
GET/PUT /api/admin/settings ⇄ tenants 表
GET  /api/auth/me        → user.tenantName / user.tenantLogo（前端品牌）
ai-agent-service         → _get_tenant_name(tenant_id)（Redis 缓存 → tenants.name）→ System Prompt
GET  /api/admin/settings/login-logs → audit_logs（action=login）
PUT  /api/admin/settings/password   → users.password_hash
```

---

## 三、本次改动的安全边界

- `customer`/`agent` 角色仍被门禁 403（垂直越权防护测试 `SecurityConfigTest` 保留）。
- 权限码由服务端 `PermissionInterceptor` 强制（前端隐藏仅是体验优化，后端仍 403）。
- 米宝写操作（employee_manage create/delete/reset/toggle）除权限外仍走 confirm 卡片确认。
- 超管(super_admin)/内部服务(service) 直通，不受租户权限表约束（多租户隔离在 Service 层由
  MyBatis 租户拦截器保证）。
