# RBAC 权限体系

> 2026-08 已实现「员工管理权限全链路」：门禁 → 细粒度接口鉴权 → 前端菜单/按钮/路由 → 米宝工具，见下文「全链路现状」。
> 2026-09（#2969）「角色权限」改名「**岗位权限**」：岗位=角色体系（roles 表即岗位），role_permissions 即岗位默认权限；创建员工选岗位自动带出默认权限，保存勾选=员工最终权限（快照式）。

## 岗位（实际生效）

| 岗位 | 编码 | 权限来源 |
|------|------|---------|
| 管理员 | admin | 恒为全部权限 `["*"]`（`RoleService.getUserPermissions`） |
| 平台管理员 | super_admin | 全部权限（在 `platform_admins` 表，走 `PermissionInterceptor` 直通） |
| 客服 | customer_service | 岗位默认权限：role_permissions 预置（看板/订单查看/客户/会话） |
| 运营 | operator | 岗位默认权限：role_permissions 预置（看板/订单/商品/加工/客户/财务/会话/员工列表） |
| 销售 | sales | 岗位默认权限：role_permissions 预置（看板/商品/订单查看/客户） |
| 财务 | finance | 岗位默认权限：role_permissions 预置（看板/订单查看/财务） |
| 自定义岗位 | 岗位权限页创建 | **岗位权限页勾选的权限码落库到 `role_permissions`**（V16），作为该岗位默认权限 |

> 新租户注册初始化五岗种子（管理员/客服/运营/销售/财务）+ role_permissions 预置（V29 为存量租户补齐）。
> **快照式权限语义（#2969）**：员工权限 = 员工管理页保存的勾选（users.permissions 快照），与岗位脱钩 ——
> 后续修改岗位默认权限不影响已建员工；改岗位仅作为下次创建/编辑员工时的默认模板。
> 兼容存量：无 users.permissions 快照（历史员工 / ai-agent 直接创建）时回退角色权限合并逻辑（role_permissions 优先，内置角色回退硬编码）。

## 权限模型

```
roles ──< role_permissions >── permissions   （岗位默认权限：岗位权限页勾选，V16 落库）
users.permissions (JSON 权限码)               （员工权限快照：员工管理页保存勾选，最终生效）
```

- 「岗位权限」页（原「角色权限」页，URL /roles 不变）创建/编辑岗位时勾选权限 → `role_permissions` 全量替换落库；岗位详情/列表回填 `permissions` 用于回显
- 创建/编辑员工：岗位下拉选择（岗位列表 = roles 表），选中自动预填该岗位默认权限树 → 可手动增删 → 保存为快照；编辑时切换岗位则权限树重置为新岗位默认
- admin 恒为 `["*"]`

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
管理员创建/编辑员工(员工管理弹窗)
  → 选岗位(岗位下拉) → 自动带出岗位默认权限树(role_permissions codes)
  → 可手动增删 → 保存: users.permissions 快照 + 岗位名/角色关联
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

前端侧边栏（#2969 重构七大组：工作台 / 智能客服(含知识库) / 商品管理 / 订单管理 / 客户管理(含财务对账) / 组织管理(员工+岗位权限+企业信息) / 通知中心）根据 `permissions` 动态渲染（`Sidebar.tsx`），
`admin`/`super_admin`/`*` 显示全部菜单；
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
