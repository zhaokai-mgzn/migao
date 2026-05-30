# 认证服务设计与部署

> 版本：v8.0（2 服务架构 + 公众号 OAuth + 客服员工工作台 + 自建 RAG + CRM）  
> 日期：2026-04-12  
> 变更：认证合并到 admin-api；ai-chat + ai-admin 合并为 ai-agent；百炼知识库迁移至 DashVector 自建 RAG

---

## 1. 认证服务架构

### 1.1 服务职责

认证功能已合并到 admin-api（Java Spring Boot 3），统一部署到单个 SAE 应用：

```
admin-api/ (Java Spring Boot 3)
├── 认证模块
│   ├── 微信小程序登录（C 端）
│   ├── 微信公众号 OAuth 扫码登录（C 端，测试用）
│   ├── 客服员工登录（小程序 + PC H5）
│   ├── 企业账号密码登录（管理端）
│   ├── JWT Token 生成与验证
│   └── 用户身份管理
├── 管理后台业务模块
│   ├── 商品/订单/租户管理
│   └── 租户 AI 配置管理
└── AI 网关模块
    └── 调用 ai-agent-service（HTTP/gRPC）
```

### 1.2 目录结构

```
admin-api/src/main/java/com/ai_customer_service/
├── auth/
│   ├── controller/
│   │   ├── MiniLoginController.java        # 微信小程序登录
│   │   ├── H5OAuthController.java          # 公众号 OAuth
│   │   ├── AgentAuthController.java        # 客服员工登录
│   │   ├── AccountLoginController.java     # 账号密码登录
│   │   └── AuthInternalController.java     # 内部 Token 验证
│   ├── service/
│   │   ├── AuthenticationService.java      # 统一认证服务
│   │   ├── WeChatMiniService.java          # code2Session + 防重放
│   │   ├── WeChatH5Service.java            # 公众号 OAuth
│   │   ├── AgentEmployeeService.java       # 客服员工管理
│   │   └── JwtService.java                 # RS256 JWT 签发/验证
│   ├── client/WeChatApiClient.java         # 微信 HTTP 客户端
│   ├── config/                             # 微信AppID/Secret、JWT密钥配置
│   └── model/                              # 请求/响应 DTO
├── admin/                                  # 管理后台业务
├── common/
│   ├── config/ (Redis, DB, CORS)
│   ├── middleware/ (TenantIsolation, JwtAuth, ReplayProtection)
│   └── security/ (RateLimiter, InternalAuthVerifier)
└── AiCustomerServiceApplication.java
```

### 1.3 API 接口

```
# 公开接口（不需要认证）
POST /api/auth/mini/login              # 小程序登录 { code, tenant_id }
GET  /api/auth/h5/authorize            # 公众号 OAuth 跳转
GET  /api/auth/h5/callback             # OAuth 回调
POST /api/auth/account/login           # 账号密码登录
POST /api/auth/account/refresh         # 刷新 Token
POST /api/auth/agent/login             # 员工扫码登录

# 需认证接口
POST /api/auth/account/logout          # 登出（吊销 JWT）
GET  /api/auth/me                      # 获取用户信息
PUT  /api/auth/me                      # 更新用户信息
POST /api/auth/agent/invite            # 管理员邀请员工
PUT  /api/agent/status                 # 设置在线/离线
GET  /api/agent/sessions               # 获取会话列表

# 内部接口（仅 VPC 内网）
POST /api/auth/internal/verify         # Token 验证（HMAC 认证）
```

> 多端共用同一套 JWT 和业务服务。详见 [多租户多端架构](../architecture/multi-tenant-multi-platform.md)。

---

## 2. 认证机制详解

### 2.1 JWT 规范（RS256 非对称签名）

| 字段 | 说明 |
|------|------|
| 算法 | RS256（私钥签发/公钥验证） |
| iss | `admin-api` |
| aud | `youke` |
| sub | user_id |
| Claims | `tenant_id`, `identity_type`, `role` |
| jti | UUID（用于吊销） |
| 时钟偏差 | 允许 30s |

**密钥管理**：
- 私钥仅 admin-api 持有（`/app/keys/private.pem`）
- 公钥分发给 ai-agent-service 做本地验证

**Token 传递方式**：
- 管理后台：HttpOnly Cookie（`access_token`，Secure, SameSite=Lax）
- 小程序端：Authorization Header（`Bearer <token>`）

### 2.2 微信小程序登录

**安全要求**：code 防重放（每个 code 只能使用一次）

流程：
1. 小程序 `wx.login()` 获取 code
2. POST `/api/auth/mini/login` { code, tenant_id }
3. 后端验证 code 未使用 → 调用微信 code2Session → 标记 code 已使用（Redis, 5min TTL）
4. 查找/创建用户 → 生成 JWT → 返回 token

### 2.3 微信公众号 OAuth（测试用）

流程：
1. GET `/api/auth/h5/authorize` → 302 跳转微信授权页
2. 用户授权 → 微信回调 `/api/auth/h5/callback?code=xxx&state=xxx`
3. 后端用 code 换 access_token + openid → 获取 userinfo
4. 查找/创建用户（通过 unionid 跨平台关联）→ Set-Cookie → 302 跳转 H5 页

### 2.4 客服员工登录

流程：
1. 管理员调用 POST `/api/auth/agent/invite` 生成邀请码
2. 员工扫描邀请二维码 → 打开工作台小程序
3. 小程序 `wx.login()` 获取 code
4. POST `/api/auth/agent/login` { invite_code, wechat_mini_code, tenant_id }
5. 验证邀请码 → 绑定 openid → 签发 JWT（role=agent）

### 2.5 企业账号密码登录

流程：
1. POST `/api/auth/account/login` { phone, password, tenant_code }
2. 查找租户 → 验证密码（BCrypt）→ 生成 JWT
3. Set-Cookie（HttpOnly）→ 返回 user 信息

### 2.6 用户身份统一管理

通过 `unionid` 实现跨平台用户识别：
1. 优先通过 unionid 查找（跨平台同一用户）
2. 其次通过 identity_type + external_id 查找
3. 都不存在则创建新用户

---

## 3. 安全加固

### 3.1 CORS 配置

> 原则：仅允许已知前端域名，禁止 `*` 通配符。

```java
@Configuration
public class CorsConfig {
    @Value("${cors.allowed-origins}")
    private String[] allowedOrigins;
    
    @Bean
    public CorsFilter corsFilter() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOriginPatterns(Arrays.asList(allowedOrigins));
        config.setAllowCredentials(true);
        config.setAllowedMethods(Arrays.asList("GET", "POST", "PUT", "DELETE"));
        config.setAllowedHeaders(Arrays.asList(
            "Content-Type", "Authorization", 
            "X-Request-Timestamp", "X-Request-Nonce"));
        config.setMaxAge(600L);
        // ...
    }
}
```

### 3.2 防重放攻击

> `X-Request-Timestamp` 和 `X-Request-Nonce` 对认证接口为**必填**。

规则：
- 仅对 `/api/auth/` 路径启用（豁免 `/api/auth/internal/`）
- 时间戳有效窗口：5 分钟
- nonce 缓存 5 分钟（Redis），相同 nonce 视为重放

错误码：
| 错误 | 说明 |
|------|------|
| MISSING_TIMESTAMP | 缺少时间戳 |
| INVALID_TIMESTAMP | 格式错误 |
| REQUEST_EXPIRED | 超过5分钟 |
| MISSING_NONCE | 缺少 nonce |
| REPLAY_DETECTED | 重复请求 |

### 3.3 租户隔离

> **核心安全规则**：`tenant_id` 始终从 JWT 中获取，禁止通过请求头或参数覆盖。

实现：
- `TenantIsolationFilter`（Order=1，JWT认证后执行）
- 从 Authorization Header 或 Cookie 提取 JWT
- 验证后注入 userId/tenantId/role 到 request attribute
- 所有数据库查询强制携带 tenant_id

公开路径白名单：`/health`, `/api/auth/mini/login`, `/api/auth/account/login`, `/api/auth/account/refresh`

### 3.4 内部服务认证（HMAC）

> 用途：ai-agent-service 调用 admin-api 的 `/api/auth/internal/verify`

签名算法：HMAC-SHA256(`timestamp:body`, shared_secret)  
时间窗口：30 秒  
请求头：`X-Internal-Timestamp` + `X-Internal-Signature`

### 3.5 限流

Redis 计数器实现：
- 登录接口：每分钟 5 次/IP
- 超限返回 429（RATE_LIMITED）

### 3.6 Token 吊销

- 登出时将 jti 加入 Redis 黑名单（TTL = Token 剩余有效期）
- 验证时检查黑名单
- 清除 Cookie（path=/api, domain=.migaozn.com, HttpOnly, Secure, maxAge=0）

---

## 4. 登录流程图

### 微信小程序（C 端）

```
小程序端                    admin-api                    微信服务器
  │ 1. wx.login()             │                              │
  │ POST /api/auth/mini/login │                              │
  │ { code, tenant_id }       │                              │
  │ ──────────────────────────>│ 2. code2Session              │
  │                            │ ────────────────────────────>│
  │                            │    openid + session_key      │
  │                            │ <────────────────────────────│
  │ 4. { token, user }        │ 3. 创建/更新用户 + JWT       │
  │ <──────────────────────────│                              │
  │ 5. wx.setStorageSync      │                              │
```

### 管理后台浏览器

```
浏览器                      admin-api                    数据库
  │ POST /account/login       │                              │
  │ { phone, password,        │ 验证密码                     │
  │   tenant_code }           │ ────────────────────────────>│
  │ ──────────────────────────>│ 生成 RS256 JWT              │
  │ Set-Cookie: access_token  │ <────────────────────────────│
  │ <──────────────────────────│                              │
  │ 后续请求自动带 Cookie     │                              │
```

---

## 5. 部署配置要点

> 详细的 SAE 环境变量、Terraform 配置等参见 [deployment-aliyun.md](./deployment-aliyun.md)

### 5.1 API Gateway 路由关键规则

| 优先级 | 路径 | 后端 | 认证 | 说明 |
|--------|------|------|------|------|
| 高 | /api/auth/mini/login | admin-api | 否 | 小程序登录 |
| 高 | /api/auth/h5/* | admin-api | 否 | OAuth |
| 高 | /api/auth/account/login | admin-api | 否 | 账号登录 |
| 高 | /api/auth/account/refresh | admin-api | 否 | 刷新 |
| 中 | /api/chat/* | ai-agent-service | 是 | AI对话 |
| 中 | /api/admin/ai/* | ai-agent-service | 是 | AI管理助手 |
| 低 | /api/admin/* | admin-api | 是 | Java管理后端(兜底) |

> 注意：`/api/admin/ai/*` 必须在 `/api/admin/*` 之前配置。

### 5.2 Cookie 配置

| 属性 | 值 | 说明 |
|------|----|------|
| name | access_token | |
| domain | .migaozn.com | 跨子域共享 |
| path | /api | 仅 API 请求携带 |
| HttpOnly | true | 防 XSS |
| Secure | true | 仅 HTTPS |
| SameSite | Lax | 防 CSRF |

### 5.3 关键安全配置清单

- [ ] RS256 密钥对已生成并挂载
- [ ] JWT 公钥已分发到 ai-agent-service
- [ ] CORS 仅允许已知域名（禁止 `*`）
- [ ] INTERNAL_SERVICE_SECRET 已配置到所有服务
- [ ] Redis 启用密码认证
- [ ] RDS 白名单仅允许 VPC 内 IP
- [ ] 限流规则配置并测试
- [ ] code 防重放机制测试通过
- [ ] Token 吊销功能测试通过
- [ ] 租户隔离测试通过

---

## 6. 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| 小程序登录失败 | code2Session 错误 | 检查 AppID/AppSecret |
| code 已被使用 | 重复提交 | 确保每次 wx.login() 用新 code |
| JWT 验证失败 | 公私钥不匹配 | 检查密钥对挂载 |
| Token 过期快 | session_ttl 配置错误 | 调整用户表或环境变量 |
| 跨域错误 | CORS 配置 | 检查 CORS_ALLOWED_ORIGINS |
| 内部调用 403 | HMAC 签名不匹配 | 检查 INTERNAL_SERVICE_SECRET |
| Cookie 未携带 | SameSite/Domain 配置 | 检查 COOKIE_DOMAIN 和 secure |
| 登录被限流 | 短时间多次尝试 | 等待窗口过期或调整规则 |
| admin-api 启动失败 | 密钥文件未找到 | 检查 JWT_PRIVATE_KEY_PATH |
