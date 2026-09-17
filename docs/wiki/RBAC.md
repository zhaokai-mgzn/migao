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
  两点补充口径（#4147）：① `allowed_roles = ["*"]` 表示**角色层不适用**（任何已认证身份），
  只允许纯本地校验类工具声明（当前唯一 `validate_input`）—— 商户角色码是**开放集合**
  （「岗位权限」页可创建任意岗位码），任何手写清单都会把持码员工判成「权限不足」；
  ② 工具层 `check_permission` 的拒绝必须带 `error_code ∈ NON_RETRYABLE_ERROR_CODES`
  （当前 `PERMISSION_DENIED`），否则授权失败会进自修复重试的参数改写重放。

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

## 服务间调用的授权边界（ai-agent → admin-api，issue #4105）

ai-agent 调用 admin-api **始终**带 `X-Service-Token` + `X-Tenant-Id` + `X-User-Id`。
`ServiceTokenFilter` 按 `X-User-Id` 分两种身份，**这是安全边界，不得回退**：

| `X-User-Id` | 认证身份 | 细粒度鉴权 |
|---|---|---|
| 命中**本租户商户员工**（行存在且未软删、`status=active`、租户一致、角色 ∉ {customer, agent}） | 该员工的**真实角色**（不再挂 `service`） | **生效** —— `@RequirePermission` + `roleService.getUserPermissions(realUserId)` |
| 其余（无 `X-User-Id` / C 端 customer·agent / 跨租户 / 查不到用户） | 内部服务 `service`（今日行为） | 直通（无细粒度校验） |

- 商户员工判定口径与 `UserMapper.selectActiveEmployeesByPhoneIgnoreTenant`（SQL `role NOT IN ('customer','agent')`）、
  `AuthService.validateBminiEmployee`、`UserService` 员工管理「排除 C 端消费者」**同源**，不另造第二套。
- 查库异常时回退 `service` 身份**并记 ERROR**：调用方已持有可信 `SERVICE_TOKEN`（可信内部服务，非不可信第三方），
  失败回退不构成提权；留痕用于区分「查失败」与「查不到」。
- ⚠️ 判定必须在 `TenantContext` 就绪**之后**执行（`users` 表不在 `MybatisPlusConfig.IGNORE_TENANT_TABLES` 内，
  `TenantLineHandler` 在租户上下文为空时会抛错）——顺序写反会被上面的 fallback 吞成**静默失效**：
  F2 全绿的单测/E2E 都 mock 了 Mapper，看不出来。守卫：
  `ServiceTokenFilterTest.merchantStaffLookup_runsAfterTenantContextIsSet` 断言「查库那一刻的 TenantContext」。
- 403 响应体（两条入口同一口径，`PermissionDeniedResponse`）：`error.code=PERMISSION_DENIED`、
  `error.message` 含缺失权限码、`error.details[0]={field:"requiredPermission"}`，并带
  **LLM 可执行 `suggestion`**（说明这是角色/权限限制、不是参数问题、不要重试同一工具、请管理员在「岗位权限」中授权）。

> ⚠️ 内置岗位默认权限存在缺口（如 `customer_service` 默认权限不含 `order:refund`，而售后接口类级要求它）：
> 此前被服务间旁路掩盖，F2 生效后客服驱动米宝处理售后会被 403。属**岗位权限矩阵**问题，见 #4104 后续修复；
> `operator` 已有 `order:refund`，运营驱动的 B 端链路不受影响。

## 写越权用例时的取值纪律（#4104 登记）

岗位权限矩阵的存量缺口（如 `customer_service` 默认权限不含 `order:refund`，而 `AfterSalesController` /
`agent/AgentAfterSalesController` 是**类级** `@RequirePermission("order:refund")`，连只读端点一并覆盖，
详见上方缺口说明与 #4104）修复本轮刻意不做（用户裁定，超出 #4103 范围）。

⇒ 编写"越权被拒"类评测用例时请**避开售后这一格**：它同时受"岗位矩阵缺口"影响，拒绝语义有歧义。
用角色**从来就没有**的权限码（如 `employee:create` / `system:manage`）才能得到无歧义的"拒绝"语义，
并且必须配一条**正向对照**用例（持该码时同一诉求应成功），否则无法区分"正确拒绝"与"整条链路坏了”。


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
| 服务间 | `X-Service-Token` | ServiceTokenFilter：`X-User-Id` 命中本租户商户员工 → 挂真实角色走细粒度鉴权；否则 ROLE_SERVICE 直通（见「服务间调用的授权边界」） |


---
详见: [部署](Deployment.md) · [API 参考](../api/api-reference.md)
