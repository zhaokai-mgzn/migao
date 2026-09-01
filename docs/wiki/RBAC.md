# RBAC 权限体系

> 2026-08 已实现「员工管理权限全链路」：门禁 → 细粒度接口鉴权 → 前端菜单/按钮/路由 → 米宝工具，见下文「全链路现状」。

## 角色（实际生效）

| 角色 | 编码 | 权限来源 |
|------|------|---------|
| 企业管理员 | admin | 恒为全部权限 `["*"]`（`RoleService.getUserPermissions`） |
| 平台管理员 | super_admin | 全部权限（在 `platform_admins` 表，走 `PermissionInterceptor` 直通） |
| 运营经理 | operator | 内置角色：无 role_permissions 时回退硬编码权限集（看板/订单/商品/客户/财务/员工列表/系统设置等） |
| 商品管理员 | product_manager | 内置角色：回退硬编码权限集（看板/商品/加工项） |
| 知识编辑 | knowledge_editor | 内置角色：回退硬编码权限集（看板） |
| 自定义角色 | 角色管理创建 | **角色管理页勾选的权限码落库到 `role_permissions`**（V16），分配给员工后精确生效 |

> 权限来源优先级：角色 `role_permissions` 关联（角色管理勾选）> 内置角色硬编码映射 > 员工个人权限码（`users.permissions`）。
> 员工在「员工管理 → 账号权限」勾选的权限码始终合并进最终权限集。

## 权限模型

```
roles ──< role_permissions >── permissions   （角色授权：角色管理页勾选，V16 落库）
users ──< user_roles >── roles               （用户-角色分配）
users.permissions (JSON 权限码)               （员工管理页直接勾选）
```

- 「角色管理」页创建/编辑角色时勾选权限 → `role_permissions` 全量替换落库；角色详情/列表回填 `permissions` 用于回显
- 内置角色（admin/operator/product_manager/knowledge_editor）未配置 role_permissions 时沿用硬编码映射，配置后以 role_permissions 为准（admin 恒为 `["*"]`）

## JWT Claims

```json
{
  "sub": "user_id",
  "tenant_id": 1,
  "roles": ["operator"],
  "permissions": ["employee:list", "dashboard:view", "..."],
  "exp": 1704153600
}
```

- RS256 非对称签名 (admin-api 持私钥, ai-agent-service 持公钥)
- `permissions` claim 由 `JwtAuthenticationFilter` 解析，米宝 Tool 细粒度鉴权同源（`ToolContext.permissions`）

## 全链路现状（员工管理权限）

```
管理员勾选权限(员工管理/账号权限)
  → users.permissions 落库
  → 员工登录 (短信/JWT)
  → /api/auth/me 返回 permissions+menus → 前端侧边栏按权限过滤
  → 前端路由守卫(403 页) + 按钮级权限(employee:create 才可见新增/编辑/删除/禁用)
  → 后端 SecurityConfig 门禁(/api/admin/** 仅商户员工角色, customer/agent 拒绝)
  → @RequirePermission + PermissionInterceptor 按权限码 403
  → 米宝: ToolContext.permissions → employee_manage 按 employee:list/employee:create 放行
```

## 强制点（已启用）

| 层 | 机制 |
|----|------|
| 门禁 | `SecurityConfig.adminApiAuthorizationManager`：`/api/admin/**` 允许平台管理员/内部服务/商户员工角色；小程序/B2C 用户（customer/agent）一律 403 |
| Controller | `@RequirePermission("模块:操作")` + `PermissionInterceptor` AOP 切面（方法级 + 类级），平台管理员(super_admin)/内部服务(service) 直通 |
| Service | MyBatis 拦截器自动注入 `WHERE tenant_id = ?` |
| AI Tool | `required_permissions` + 工具内按 action 二次校验（如 `employee_manage`：查询需 employee:list，写操作需 employee:create） |
| 前端 | `lib/permission.ts usePermission()`：菜单过滤 + `(dashboard)/layout.tsx` 路由守卫 + 员工页按钮级权限 |

## 菜单过滤

前端侧边栏根据 `permissions` 动态渲染（`Sidebar.tsx`），`admin`/`super_admin`/`*` 显示全部菜单；
`/api/auth/me` 的 `buildMenusByPermissions` 与侧边栏口径一致。

## 登录方式

| 端 | 接口 | 认证方式 |
|----|------|---------|
| 小程序 | `/api/auth/mini/login` | wx.login() → code → JWT（角色 customer，禁止访问 /api/admin/**） |
| 管理后台 | `/api/auth/admin/login` | 短信验证码 → JWT（密码登录已禁用 #375） |
| 公众号H5 | `/api/auth/h5/authorize` | OAuth 2.0 → code → JWT |
| 服务间 | `X-Service-Token` | ServiceTokenFilter → ROLE_SERVICE 直通 |

---
详见: [部署](Deployment.md) · [API 参考](../api/api-reference.md)
