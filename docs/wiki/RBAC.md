# RBAC 权限体系

> 2026-08 已实现「员工管理权限全链路」：门禁 → 细粒度接口鉴权 → 前端菜单/按钮/路由 → 米宝工具，见下文「全链路现状」。
> 2026-09（#2969）「角色权限」改名「**岗位权限**」：岗位=角色体系（roles 表即岗位），role_permissions 即岗位默认权限；创建员工选岗位自动带出默认权限，保存勾选=员工最终权限（快照式）。

## 岗位（实际生效）

| 岗位 | 编码 | 权限来源 |
|------|------|---------|
| 管理员 | admin | 恒为全部权限 `["*"]`（`RoleService.getUserPermissions`） |
| 平台管理员 | super_admin | 全部权限（在 `platform_admins` 表，走 `PermissionInterceptor` 直通） |
| 客服 | customer_service | 岗位默认权限：role_permissions 预置 —— 实际权限码 `dashboard:view`, `order:list`, `order:detail`, `customer:view`, `agent:session`, `processing:view`, `inbound:view`, **`after_sales:view`**（售后**读**码，issue #5246 新增 —— 客服经米宝查售后不再 403）, **`knowledge:view`**（知识卡片读码，issue #5246 新增）, **`agent:session:manage`**（会话转接/结束写码，issue #5246 第二批）。**仍无** `order:refund`（退款写面）与 `order:update`（改单写面） |
| 运营 | operator | 岗位默认权限：role_permissions 预置 —— `dashboard:view`, `order:list`, `order:detail`, `order:refund`, `product:list`, `product:create`, `product:category`, `processing:manage`, `processing:view`, `processing:update`, `inbound:view`, `inbound:create`, `customer:view`, `finance:view`, `agent:session`, `employee:list`, **`after_sales:view`**, **`knowledge:view`**, **`order:update`**, **`order:create`**, **`customer:create`**, **`finance:create`**, **`agent:session:manage`**（后七个码 issue #5246 新增） |
| 销售 | sales | 岗位默认权限：role_permissions 预置 —— `dashboard:view`, `product:list`, `order:list`, `order:detail`, `customer:view`, `processing:view` |
| 财务 | finance | 岗位默认权限：role_permissions 预置 —— `dashboard:view`, `order:list`, `order:detail`, `finance:view`, `processing:view`, `inbound:view`, **`finance:create`**（登记收支写码，issue #5246 第二批） |
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
  （当前 `PERMISSION_DENIED`），否则授权失败会进自修复重试的参数改写重放；
  ③ **权限码是「商户员工」概念（issue #5246）**：C 端（`customer`/`agent`）JWT 里没有 `permissions`
  claim ⇒ 对 C 端而言细粒度层**不可判**。⇒ 声明了权限码的**双端工具**（同时被小布 skill 绑定：
  `product_search` / `product_detail` / `processing_item_query` / `order_create` / `knowledge_search` /
  `production_progress_query`）必须在类上显式写 `c_end_reachable = True`，C 端才按**角色层**放行
  （= 与加码前逐字一致，C 端零回归）；**未声明**该标记的工具对 C 端一律拒绝（既有 C 端硬闸）。
  取值不得手写：`tests/unit_ci_workflows/test_agent_permission_parity.py` 按 skill 绑定机械核对。
  另一条边界：C 端经 `X-User-Id=customer/agent` 调 admin-api 时 `ServiceTokenFilter` 回退成
  `service` 权威、`PermissionInterceptor.hasBypassRole` 直通 ⇒ **admin-api 侧对 C 端没有权限码校验**，
  C 端的隔离靠业务层的 `X-User-Id` 过滤（`/api/customer/**`、`/api/admin/agent/**` 各自过滤）。

## 全链路现状（员工管理权限）

```
管理员创建/编辑员工(员工管理弹窗)
  → 选岗位(岗位下拉) → 自动带出岗位默认权限树(role_permissions codes)
  → 可手动增删 → 保存: users.permissions 快照 + 岗位名/角色关联
  → 员工登录 (短信/JWT)
  → /api/auth/me 返回 permissions+menus → 前端侧边栏按权限过滤
  → 前端路由守卫(403 页) + 按钮级权限(employee:create 才可见新增/编辑/删除/禁用)
  → 后端 SecurityConfig 门禁(/api/admin/** 仅商户员工角色, customer/agent/worker 拒绝)
  → @RequirePermission + PermissionInterceptor 按权限码 403
  → 米宝: ToolContext.permissions → employee_manage 按 employee:list/employee:create 放行
```

## 强制点（已启用）

| 层 | 机制 |
|----|------|
| 门禁 | `SecurityConfig.adminApiAuthorizationManager`：`/api/admin/**` 允许平台管理员/内部服务/商户员工角色；**拒绝集合** `ADMIN_API_REJECTED_ROLES` = 小程序/B2C 用户（customer/agent）+ **工人端身份（worker，issue #4727 按 #4716 设计 C11 预留）** 一律 403 |
| Controller | `@RequirePermission("模块:操作")` + `PermissionInterceptor` AOP 切面（方法级 + 类级）；平台管理员(super_admin) 直通。内部服务(service) **不再无条件直通**：service token 请求带 `X-User-Id` 且该用户解析为**同租户商户员工**（role ∉ {customer, agent}）时，改以该员工的真实角色进入 `PermissionInterceptor` 做细粒度强控（#4105，`ServiceTokenFilter`）；无 `X-User-Id` / C 端顾客 / 非本租户 / 查库异常时**保持原直通语义**（零回归）。403 响应保留所需权限码并附可执行 suggestion（`GlobalExceptionHandler` + `SecurityConfig.accessDeniedHandler` 同构） |
| Service | MyBatis 拦截器自动注入 `WHERE tenant_id = ?` |
| AI Tool | `required_permissions`（与 admin-api 权限目录**同源**）+ 工具内按 action 二次校验（如 `employee_manage`：查询需 employee:list，写操作需 employee:create）。**#4106 铺开 + #5246 收口**：`app/tools/*.py` 里每个 B 端可达工具都声明了码（纯本地工具走显式白名单），且与端点生效码/菜单节点码/岗位矩阵**四方对账** —— 判据 = `tests/unit_ci_workflows/test_agent_permission_parity.py`（九条，各带注入式红证） |
| 前端 | `lib/permission.ts usePermission()`：菜单过滤 + `(dashboard)/layout.tsx` 路由守卫 + 员工页按钮级权限 |

## `/api/admin/**` 放行策略现状（issue #4727 实测，2026-09-20）

`SecurityConfig.securityFilterChain()` 把 `/api/admin/**` 交给 `adminApiAuthorizationManager`（**唯一门禁**），
其余路径落到 `.anyRequest().authenticated()`。逐分支：

| 分支 | 身份 | 判定 | 依据 |
|---|---|---|---|
| ① 放行 | `admin` / `super_admin` / `service` | 直接进入 | `adminApiAuthorizationManager`（平台管理员与内部服务拥有全部权限） |
| ② 拒绝 | `customer` / `agent` / **`worker`**（常量 `ADMIN_API_REJECTED_ROLES`） | **403** | 垂直越权防护（#4105）；`worker` 由 issue #4727 按 #4716 设计 C11 预留 |
| ③ 放行进入 | 其余**一切**角色（**含零权限的自定义岗位**） | 进入，**能否访问由 `@RequirePermission` 决定** | 商户员工（岗位码是开放集合，无法用白名单穷举） |
| ④ 未认证 | 无 token / 匿名 | **401** | `authenticationEntryPoint` |

- `/api/auth/**` 里在 `permitAll()` 名单内的（`admin/login`、`mini/login`、`bmini/login`、`h5/authorize`、`h5/callback`、`refresh`、`sms/**`、`register`）**完全公开**；
  其余 `/api/auth/**`（`me`/`logout`/`mini/bind-phone`）只需**任意已认证身份**（含 C 端）—— 它们是自助端点，**不得**加权限码。
- `/api/customer/**`（C 端人工会话）与 `/api/super-admin/**`（`checkSuperAdminPermission()` 显式校验 `super_admin`）**都不走本门禁**。
- ⚠️ **分支 ③ 的含义：没有 `@RequirePermission` 的端点 = 对所有商户员工开放**（含零权限岗位）——
  这就是 issue #4727 的审计对象。
- ⚠️ **未把 `worker` 加进 `ServiceTokenFilter.C_END_ROLES`**（有意不做）：那里的语义是「C 端角色」，
  加进去会让持 `X-User-Id=工人` 的内部服务调用**回退成 `service` 身份**⇒ 反而**旁路**掉细粒度校验（更宽）。
  现状下 worker 经 service token 也会被解析成真实角色 `worker` ⇒ 落在上面的分支 ② 被 403。

## 权限注解面审计（issue #4727，2026-09-20 实测）

审计口径：扫描 `backend/admin-api/src/main/java/com/migao/admin/controller/**`（**含 `agent/` 子目录**）全部端点，
按「方法级注解优先、其次类级」解析每个端点的**生效权限码**。

> **issue #5246 落地状态（2026-09-23）** —— 上表逐条结论已落地，**没有一条留在沉默里**：
> · **该补的补了**：第 1/2/3 行（`AdminPermissionController` / `NotificationRule` / `NotificationTemplate`）
>   已是 `system:manage`；第 5 行 `POST /api/admin/notifications` 补 `system:manage`，
>   **同批**给 ai-agent 的 `notification_manage` 声明同一码（单边改动会砍掉运营经米宝发通知的能力）。
> · **该放行的登记为「有意放行」**：第 4/6/7/8/9/10/11 行 + 部分覆盖表的读面，逐条登记在守卫
>   `tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `UNANNOTATED_ENDPOINTS`（每条含理由）；
>   判据 8 会因「新增了未登记的无码端点」或「登记项已陈旧」而变红 ⇒ 沉默放行不再可能。
> · **读写拆分（同批）**：`AfterSalesController` / `agent/AgentAfterSalesController` 的类级
>   `order:refund` 拆成方法级 —— 读（GET 列表/详情、`/agent/after-sales/mine`）→ **新码 `after_sales:view`**，
>   写（建单/改状态）→ 保留 `order:refund`；`KnowledgeCard` / `KnowledgeCandidate` / `KnowledgeTemplate`
>   的类级 `knowledge:manage` 同样拆分（读 → **新码 `knowledge:view`**，写 → 保留）；
>   `AgentProductController` 的商品/库存/SKU 写端点从 `product:list` 拆到 `product:create`。
> · **可见性变化（两处节点）**：『知识库』节点码 `knowledge:manage` → `knowledge:view`
>   ⇒ 客服 / 运营现在能看到该菜单项；『售后工单』节点码 `order:refund` → `after_sales:view`
>   ⇒ **客服**新看到该菜单项（运营原本就有）。其余节点码一个未动。
>
> **issue #5246 第二批（同日，用户裁定「本轮一并收口」）：拆出真写码，写动作不再挂在读码上**
> —— 新增 `order:update` / `order:create` / `customer:create` / `finance:create` /
> `agent:session:manage` 五个**写**码（目录两处、岗位矩阵、V124 迁移、端点注解同批落地）：
> · `OrderController` 的 `PUT /{id}/status|payment|cancel|remark|follow-status|logistics` 与
>   `DELETE /{id}` → `order:update`；`POST /` → `order:create`（`PUT /{id}/refund` 仍是 `order:refund`）；
> · `AgentOrderController`：`POST /` → `order:create`、`PATCH /{id}` → `order:update`
>   （退款 action 的 `requirePermission("order:refund")` 复检保留）；
> · `CustomerController` 的写面（改/删客户与标签）→ `customer:create`；
> · `FinanceController` 的 `POST /transactions` → `finance:create`；
> · `AgentSessionController` 的 `assign/end/messages` → `agent:session:manage`。
> **有意收窄（能力增量表见 PR）**：`customer_service` / `sales` / `finance` 此前**因写动作挂在
> 读码上**而能改单、删客户、登记收支；现在不能（各自只保留读面）。**没有给任何岗位新增权限**：
> 新写码只授给原本就用这些写面工作的岗位（operator，及 finance / customer_service 各自那一个）。

**完全没有 `@RequirePermission` 的 controller：11 个** = 顶层 10 个 + `agent/` 子目录 1 个。
（issue #4727 正文与 #4716 设计附录 A7 写的「10 个」只扫了顶层 `controller/*.java`、未含子目录 —— 口径差异，非事实冲突。）

| # | controller | 端点 | 现状 | 结论 | 依据 |
|---|---|---|---|---|---|
| 1 | `AdminPermissionController` | `GET /api/admin/permissions` | 无注解 | ✅ **补 `system:manage`** | 权限目录：唯一前端调用方「岗位权限」页已要求 `system:manage`；唯一 ai-agent 调用方 `role_manage` 工具的 `required_permissions` 本就是 `["system:manage"]` ⇒ **零回归**。且该端点带**写副作用**（`ensureFullPermissionCatalog` 懒补种） |
| 2 | `NotificationRuleController` | `GET/POST/PUT/DELETE /api/admin/notification-rules` | 无注解 | ✅ **补类级 `system:manage`** | 租户级通知配置（含写面），与「租户设置」同族；前端与 ai-agent **零调用**（仅单测命中）⇒ 零回归 |
| 3 | `NotificationTemplateController` | `GET/POST/PUT/DELETE /api/admin/notification-templates` | 无注解 | ✅ **补类级 `system:manage`** | 同上 |
| 4 | `NotificationController` | `GET /notifications`、`GET /unread-count`、`PUT /{id}/read`、`PUT /read-all`、`DELETE /{id}` | 无注解 | ⬜ **该放行** | **自助**端点：收件人一律取 `SecurityContext` 的当前 `userId`（不接受 body 注入）⇒ 无跨用户读写；通知中心**无前端路由守卫**（全员可见）⇒ 加码会砍掉所有岗位的通知铃铛 |
| 5 | `NotificationController` | `POST /api/admin/notifications` | 无注解 | ⚠️ **本轮不改（登记为分叉）** | 语义上是「管理员手动发送」的**租户级写面**（收件人由 body 指定），但 ai-agent 的 `notification_manage`（`allowed_roles=["admin","agent","tenant_admin","operator"]`、**未声明** `required_permissions`）与 `human_handoff`（C 端）都在调它 ⇒ 单方面补 `system:manage` 会**砍掉 operator 经米宝发通知**的既有能力。正解 = 注解 **与** ai-agent 侧 `required_permissions` **同 PR** 落地（#4727 禁改 ai-agent） |
| 6 | `MenuController` | `GET /api/admin/menus` | 无注解 | ⬜ **该放行** | 内容是**静态常量**（`MENU_TREE` 硬编码权限码目录，不读任何租户/业务数据），且每个已认证员工本来就能从 `/api/auth/me` 拿到 `permissions`/`menus`；唯一调用方「员工管理」页（守卫 `employee:list`）的勾选树依赖它 |
| 7 | `UserController` | `GET /api/admin/user/info` | 无注解 | ⬜ **该放行** | **自助**首屏：只返回**自己**的角色/权限/菜单，是侧边栏与前端路由守卫的数据源；任何权限码都会让无该码的员工登录后白屏 |
| 8 | `AuthController` | 10 个 `/api/auth/**` 端点 | 无注解 | ⬜ **该放行** | 公开登录/OAuth/refresh（`permitAll`）+ 自助 `me`/`logout`/`mini/bind-phone`（C 端能力，**加码 = 线上故障**） |
| 9 | `SmsController` | `POST /api/auth/sms/send` | 无注解 | ⬜ **该放行** | 公开端点（`/api/auth/sms/**` 在 `permitAll` 名单），登录前置 |
| 10 | `RegistrationController` | `POST /api/auth/register`；`GET/PUT /api/super-admin/registrations/**` | 无注解 | ⬜ **该放行** | 注册面公开；超管面**不在 `/api/admin/**`**，已由 `checkSuperAdminPermission()` 显式校验 `super_admin`（`@RequirePermission` 对 `super_admin` 是直通，加了也无效） |
| 11 | `agent/AgentAuditLogController` | `POST /api/admin/agent/audit-logs` | 无注解 | ⬜ **该放行** | 内部服务**取证上报**面：ai-agent 每次写工具调用都带 `X-User-Id` 上报；加码会让**受限岗位员工**的写操作审计被 403 ⇒ **取证缺口**（`audit_logs` 是取证材料，宁可放行不可丢） |

**部分覆盖（有注解但只覆盖一部分端点）—— 逐条结论**：

| controller | 未覆盖端点 | 结论 | 依据 |
|---|---|---|---|
| `AdminRoleController` | `GET /roles`、`GET /roles/all`、`GET /roles/{id}` | ⬜ **该放行**（读面） | `/roles/all` 是「员工管理」页**岗位下拉**的数据源（`employeeApi.loadPositions()`），持 `employee:create` 的员工必须能读；写面（POST/PUT/DELETE）已是 `system:manage` |
| `SettingsController` | `PUT /api/admin/settings/password` | ⬜ **该放行** | 自助改密：只改**当前认证用户**自己的密码 |
| `agent/AgentPaymentController` | `GET /api/admin/agent/payment-qrcodes` | ⬜ **该放行** | 米宝收款码读面（会话内展示给客户），与类级 `order:list` 同族的读口径 |

> **残余风险（照实登记，本轮不修）**：分支 ③ + 上表第 6/7 行意味着**零权限的商户员工**仍能读
> `/api/admin/menus`（静态目录）与自己的 `/api/admin/user/info`。二者都不含跨用户/租户数据，
> 且与 `/api/auth/me` 已返回的信息同源 ⇒ 判定为**可接受**；不为此加码（加码会砍掉自助首屏与员工页勾选树）。

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

> ✅ **该缺口已于 issue #5246 关闭**：售后接口不再用类级 `order:refund` 覆盖只读端点 ——
> 读面改为 `after_sales:view` 并授给客服/运营，写面保留 `order:refund` ⇒
> 客服驱动米宝**查**售后不再 403；客服仍**不能**退款/建工单（无 `order:refund`）—— 这是有意的读写分权。

## 写越权用例时的取值纪律（#4104 登记）

> ✅ **#4104 登记的这一格已随 issue #5246 关闭**：`AfterSalesController` /
> `agent/AgentAfterSalesController` 的类级 `order:refund` 已拆成方法级（读 → `after_sales:view`，
> 写 → `order:refund`），客服岗位默认权限已含读码 ⇒ 「客服查售后」现在**应该成功**。
> 评测用例可以正常使用这一格，但**必须写清是读还是写**：
> · 「客服查售后**成功**」= 正向对照（持 `after_sales:view`）；
> · 「客服**退款/建工单被拒**」= 负向（无 `order:refund`）。

⇒ 写"越权被拒"类用例的取值纪律不变：优先用角色**从来就没有**的权限码（如 `employee:create` /
`system:manage`）得到无歧义的"拒绝"语义，并配一条**正向对照**（持该码时同一诉求应成功），
否则无法区分"正确拒绝"与"整条链路坏了"。


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
