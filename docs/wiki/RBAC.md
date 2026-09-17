# RBAC 权限体系

> 2026-08 已实现「员工管理权限全链路」：门禁 → 细粒度接口鉴权 → 前端菜单/按钮/路由 → 米宝工具，见下文「全链路现状」。
> 2026-09（#2969）「角色权限」改名「**岗位权限**」：岗位=角色体系（roles 表即岗位），role_permissions 即岗位默认权限；创建员工选岗位自动带出默认权限，保存勾选=员工最终权限（快照式）。

## 岗位（实际生效）

| 岗位 | 编码 | 权限来源 |
|------|------|---------|
| 管理员 | admin | 恒为全部权限 `["*"]`（`RoleService.getUserPermissions`） |
| 平台管理员 | super_admin | 全部权限（在 `platform_admins` 表，走 `PermissionInterceptor` 直通） |
| 客服 | customer_service | 岗位默认权限：role_permissions 预置 —— 实际权限码 `dashboard:view`, `order:list`, `order:detail`, `customer:view`, `agent:session`, `processing:view`（**无** `order:refund`；见下方「权限码矩阵与已知缺口」） |
| 运营 | operator | 岗位默认权限：role_permissions 预置 —— `dashboard:view`, `order:list`, `order:detail`, `order:refund`, `product:list`, `product:create`, `product:category`, `processing:manage`, `processing:view`, `processing:update`, `customer:view`, `finance:view`, `agent:session`, `employee:list` |
| 销售 | sales | 岗位默认权限：role_permissions 预置 —— `dashboard:view`, `product:list`, `order:list`, `order:detail`, `customer:view`, `processing:view` |
| 财务 | finance | 岗位默认权限：role_permissions 预置 —— `dashboard:view`, `order:list`, `order:detail`, `finance:view`, `processing:view` |
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
- `permissions` claim 由 `JwtAuthenticationFilter` 解析，并透传到米宝工具的 `ToolContext.permissions`（同一份权限码，不另立口径）。
  生效边界（#4106 铺开后为**全部 B 端工具**；此前只有 `employee_manage` 声明 `required_permissions`）：
  工具声明 `required_permissions` 时按权限码放行，`allowed_roles` 只做粗筛与路由；越权的最终关口是 admin-api 的 `@RequirePermission` 403（见下方「强制点」与「权限码矩阵与已知缺口」）。

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
| Controller | `@RequirePermission("模块:操作")` + `PermissionInterceptor` AOP 切面（方法级 + 类级）；平台管理员(super_admin) 直通。内部服务(service) **不再无条件直通**：service token 请求带 `X-User-Id` 且该用户解析为**同租户商户员工**（role ∉ {customer, agent}）时，改以该员工的真实角色进入 `PermissionInterceptor` 做细粒度强控（#4105，`ServiceTokenFilter`）；无 `X-User-Id` / C 端顾客 / 非本租户 / 查库异常时**保持原直通语义**（零回归）。403 响应保留所需权限码并附可执行 suggestion（`GlobalExceptionHandler` + `SecurityConfig.accessDeniedHandler` 同构） |
| Service | MyBatis 拦截器自动注入 `WHERE tenant_id = ?` |
| AI Tool | `required_permissions`（与 admin-api 权限目录**同源**）+ 工具内按 action 二次校验（如 `employee_manage`：查询需 employee:list，写操作需 employee:create）。覆盖范围随 #4106 铺开：此前仅 `employee_manage` 声明，其余工具只有 `allowed_roles` 角色粗筛 |
| 前端 | `lib/permission.ts usePermission()`：菜单过滤 + `(dashboard)/layout.tsx` 路由守卫 + 员工页按钮级权限 |

## 权限码矩阵与已知缺口

**客服（customer_service）没有 `order:refund`，而售后只读端点也要求该码**（#4104 登记）：
`AfterSalesController` 与 `agent/AgentAfterSalesController` 是**类级** `@RequirePermission("order:refund")`，
连只读端点一并覆盖 ⇒ 客服在 admin-web 打开售后页长期 403，米宝侧只是把这个 403 藏在工具失败里
（agent 路径"看不见"不等于不存在）。**该矩阵缺口的修复本轮刻意不做**（用户裁定，超出 #4103 范围）；
写越权用例时请避开售后这一格 —— 用角色**从来就没有**的权限码（如 `employee:create` / `system:manage`）
才能得到无歧义的"拒绝"语义。

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
| 服务间 | `X-Service-Token` | ServiceTokenFilter → ROLE_SERVICE；**带 `X-User-Id` 且该用户为同租户商户员工时不再直通**，按该员工真实角色走 `PermissionInterceptor` 细粒度强控（#4105）；其余情形（无 X-User-Id / C 端顾客 / 非本租户 / 查库异常）维持直通 |

---
详见: [部署](Deployment.md) · [API 参考](../api/api-reference.md)
