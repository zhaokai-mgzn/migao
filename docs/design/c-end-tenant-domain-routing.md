# C 端租户域名路由（<tenantId>.app.migaozn.com）设计方案

> 状态：实施中 · 关联 Issue：#3011 · 阶段：①后端解析+登录关联+客户建档（本 PR）②前端移除写死 tenantId（后续）③nginx 配置上线（部署侧）

## 背景与问题

现状 C 端小布小程序登录租户判定依赖**客户端传参**：

- 前端写死 `DEFAULT_TENANT_ID = 1`（`frontend/mini-app/src/utils/constants.ts:19`），登录时 body 传 `tenantId`
- 后端 `POST /api/auth/mini/login {code, tenantId}` 信任该值（仅校验租户存在且 active）
- 后果：① 多租户多小程序场景下租户归属不可信、易串；② C 端微信用户只建 `users` 账号，**不落 CRM 客户档案**（`CustomerService.createFromSession` 生产零调用），客户列表看不到消费者

## 未来形态（客户颁发约定）

每客户颁发独立 C 端入口域名：`<tenantId>.app.migaozn.com`，**租户 id 直接绑定在域名上**。
C 端 API/入口请求该域名时，服务端可从请求 Host / 网关头解析出租户，实现「进谁的小程序就归谁的租户」。

## 方案

### 1. 解析层：`TenantDomainResolver`（admin-api 新增，纯工具类）

从 `HttpServletRequest` 解析租户 id，优先级：

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | `X-Tenant-Id` 请求头 | nginx 按子域名注入：`server_name ~^(?<tenant>\d+)\.app\.migaozn\.com$` → `proxy_set_header X-Tenant-Id $tenant`（**覆盖**客户端同名头，防伪造） |
| 2 | `Host` 头正则 | `^(\d+)\.app\.migaozn\.com$` 兜底（本地直连/无 nginx 场景可验证） |
| — | 都不匹配 | `Optional.empty()` |

### 2. 登录租户判定（`AuthController.miniProgramLogin`）

```
effectiveTenantId = resolver.resolve(request)            // 域名解析（权威）
                   ?? requestBody.tenantId                // 兼容期兜底（log.warn，后续移除）
                   ?? 抛 400「无法识别租户」
```

- `MiniLoginRequest.tenantId` 由 `@NotNull` 放宽为可空（服务端解析为主）
- `AuthService.miniProgramLogin` 签名不变（继续收 tenantId），控制器负责解析策略，职责单一可测

### 3. 登录自动落 CRM 客户档案（`AuthService` 注入 `CustomerService`）

`miniProgramLogin` 找到/创建用户后统一调用幂等建档：

```java
customerService.createFromSession(tenantId, openid, user.getNickname(), "wechat_mini");
```

- 已有 openid → 刷新 `last_active_at`；新 openid → 新建 `customer_profiles`（vip_level=normal, customer_status=active）
- 客户列表（CRM）从此能看到 C 端消费者，与员工管理彻底分离（上一 PR #3007 已把 customer 挡在员工列表外）

### 4. 安全基线

- `X-Tenant-Id` 只能在网关层被覆盖写入，客户端同名头无效（nginx `proxy_set_header` 语义）
- 解析出的租户仍走既有校验：不存在/非 active → 拒绝建号（审计 07 P1-1 继续生效）
- 解析失败且 body 无 tenantId → 显式 400，**不静默落到默认租户**

## 影响面

| 模块 | 改动 |
|---|---|
| admin-api | 新增 `TenantDomainResolver` + `TenantDomainResolverTest`；`AuthController.miniProgramLogin` 解析策略；`MiniLoginRequest` 放宽；`AuthService` 注入 CustomerService 并建档；相关单测/集成测试 |
| ai-agent-service | 无（C 端会话租户来自 JWT） |
| admin-web | 无 |
| mini-app（第二阶段） | 移除 `DEFAULT_TENANT_ID` 传参，登录不再带 tenantId |
| nginx / 部署（第二阶段） | 子域名 server_name 与 `X-Tenant-Id` 注入（部署文档） |

## 测试计划

1. `TenantDomainResolverTest`：X 头优先 / Host 子域解析 / 非法格式 / 均无 → empty
2. `AuthIntegrationTest`：`X-Tenant-Id: 5` + body tenantId=1 → 传给 service 的为 5（域名权威）；无头仅 body → 用 body；均无 → 400
3. `AuthServiceTest`：mini 登录建号/已有用户均调用 `createFromSession`（mock 断言参数 openid/nickname/channel）
4. 行为用例：`CU-xxx`（C 端微信用户进入企业域名小程序 → 自动关联租户 + 建档），Java 单测验证，不进入 agent-eval 冒烟

## 分阶段落地

- **阶段一（本 PR）**：①②③后端实现 + 测试 + case
- **阶段二**：mini-app 移除 `DEFAULT_TENANT_ID`；nginx 子域名配置与部署文档
- **阶段三（可选）**：`tenant_apps`（appid→租户）双检接线；`tenantId.app.migaozn.com` 通配证书/自动签发

## 相关

- 上一 PR #3007：员工管理列表排除 role=customer（数据与展示分离，本方案补客户建档闭环）
- 审计 07：租户自动建号封堵（P1-1 租户存在性校验，本方案在其上加域名级租户来源）