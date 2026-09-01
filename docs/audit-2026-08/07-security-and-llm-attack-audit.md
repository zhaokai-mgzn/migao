# MIGAO 安全漏洞 / 权限漏洞 / LLM 恶意攻击风险审计报告（07）

> 审计日期：2026-08-30 ｜ 审计方式：**只读**（未修改任何业务代码）
> 方法：4 个并行深度代码审计子代理（admin-api 认证鉴权租户隔离 / admin-api 通用 API 安全 / ai-agent-service LLM 攻击面 / 前端+基础设施 CI）+ 主线程逐条复核高危证据（含与 08-29 加固提交 e0b27e10、gitleaks 门禁、PII 脱敏等现状对照，剔除过期结论）。
> 前置审计：[06-open-source-production-gap-analysis.md](06-open-source-production-gap-analysis.md)（战略级差距）——本文档是**代码级漏洞审计**，与 06 互补。

## 0. 执行摘要

**总体评级：高风险（当前不宜直接对外商业化上线）**

存在 2 条可在公网直接利用的**全平台账户接管链**（SMS 万能码默认生效 + 商户员工可自提 super_admin），且 LLM 侧存在「间接提示注入 → 无确认执行写操作」的真实可利用面。同时需肯定：租户隔离主链路、JWT RS256、SQL 注入防线、服务间鉴权等基础设计扎实，且 08-29→08-30 已快速落地一批加固（nginx 屏蔽敏感端点、端口绑 loopback、资源限制、gitleaks 门禁、日志 PII 脱敏、workflow 最小权限）。

| 维度 | 评级 | P0 | P1 | P2 |
|---|---|---|---|---|
| admin-api 认证/鉴权/租户隔离 | 高危 | 3 | 7 | 8 |
| admin-api 通用 API/数据安全 | 高危 | 2 | 5 | 12 |
| ai-agent-service LLM 攻击面 | 中高危 | 2 | 10 | 6 |
| 前端 + 基础设施/CI | 中 | 0 | 9 | 14 |
| **合并去重后** | **高风险** | **3** | **~18** | **~20** |

---

## 1. P0 —— 高危可利用（合并去重后 3 条）

### P0-1 SMS 万能验证码默认值 123456 生效 + 短信从未真正发送 → 任意手机号登录（含平台超管）

- **位置**：`backend/admin-api/src/main/resources/application.yml:140`、`service/SmsService.java:41,111-115,137-142`、`service/AuthService.java:131-161`；联动 `ai-agent-service/app/tools/order_create.py:30,176-180`（`SMS_BYPASS_CODE` 同款后门）
- **证据**：
  ```yaml
  # application.yml:140 —— yml 层默认值把 Java 侧空默认覆盖为 123456（fail-open）
  bypass-code: ${SMS_BYPASS_CODE:123456}
  ```
  ```java
  // SmsService.java:139 —— 万能码直接放行
  if (bypassCode != null && !bypassCode.isEmpty() && bypassCode.equals(code)) return true;
  // SmsService.java:111-115 —— 真实短信 API 调用被注释，验证码仅进 Redis 并打到 WARN 日志
  log.warn("[测试模式] 短信发送已 bypass，请使用万能验证码 {} 完成校验。phone={}, generatedCode={}", ...);
  ```
- **攻击场景**：生产服务器 `.env.admin-api` 只要未显式写 `SMS_BYPASS_CODE=`（空），**任意手机号 + 123456 直接登录**。`AuthService.loginBySms` 按 phone 命中 `platform_admins` 即签发 `super_admin` JWT（tenantId=-1 跳过全部租户过滤）→ **全平台数据沦陷**。企业入驻 `/api/auth/register` 同样走该验证码。即便禁用万能码，短信也从未真正下发（验证码收不到），等于登录功能本身未闭环——当前这是唯一登录方式。
- **补充子项**：验证码 `verifyCode` 无失败次数限制（可爆破 6 位码）；验证码生成用 `ThreadLocalRandom`（非加密安全）；Java 侧多处以明文日志记录 phone 与生成的验证码。
- **修复**：① 默认值改 `${SMS_BYPASS_CODE:}`（fail-closed），部署脚本加启动断言（非 DEBUG 且 bypass 非空 → 拒绝启动）；② 接入真实短信（技术债 #2616）；③ verify 增加 Redis 失败计数锁定；④ 移除验证码日志。

### P0-2 商户员工可 mass assignment 自提 super_admin → 垂直越权全平台接管

- **位置**：`controller/AdminUserController.java:103-118,160-187`、`service/UserService.java:243-252,286-290`、`security/PermissionInterceptor.java:86-89`、`config/MybatisPlusConfig.java:29-33,73`
- **证据**：
  ```java
  // AdminUserController.java:106 —— role 直接取请求体，无白名单
  String role = (String) body.get("role");
  // UserService.java:248 —— 原样落库
  .role(role != null ? role : "operator")
  // updateUser 同理可改任意同租户用户 role（UserService.java:286-289）
  ```
- **提权链（逐环验证）**：`POST /api/admin/users {"role":"super_admin"}`（或 `PUT /{id}` 改自己）→ 短信登录 → `getUserRoles` 返回该字符串 → JWT `roles=["super_admin"]` → `MybatisPlusConfig` 跳过租户过滤 → `SecurityConfig:213` 放行 `/api/admin/**` → `PermissionInterceptor.hasBypassRole` 跳过全部 `@RequirePermission` → `RegistrationController` 超管审批接口放行。
- **影响**：全平台数据读写；`tenants/tenant_applications/platform_admins` 为忽略租户过滤的表 → 可读全平台入驻申请（联系人/手机号/营业执照 URL）与平台管理员手机号、审批入驻。
- **修复**：服务端角色/权限白名单（仅允许租户 roles 表存在的 code，禁止 `super_admin`/`admin`/`service`/`customer`/`agent` 由商户侧赋值，禁止授予 `"*"`）；校验操作者权限 ≥ 目标角色；超管判定改为 DB 角色关联而非 `User.role` 字符串。

### P0-3 内部服务令牌（SERVICE_TOKEN）默认值硬编码于仓库，可猜测

- **位置**：`deploy/docker-compose.yml:59,78`（`${DEV_SERVICE_TOKEN:-dev-service-token-secret}`）；`security/ServiceTokenFilter.java:63-84`（服务令牌 + 客户端自报 `X-Tenant-Id` 即认证为 service 角色）
- **影响**：按 dev compose 部署且未设 `DEV_SERVICE_TOKEN` 时，攻击者 `X-Service-Token: dev-service-token-secret` + 任意 `X-Tenant-Id` → service 角色直通全部权限 → 任意租户数据读写。**注**：生产 SWAS compose（`deploy/swas/docker-compose.yml`）已改为 `env_file` 注入、无硬编码默认值（已核），故本条对生产需服务器侧确认 token 强度；dev/模板环境为真实风险。
- **修复**：删除硬编码默认值（fail-closed）；强随机 secret 由编排平台注入；服务间调用 mTLS/短期签名；`X-Tenant-Id` 与调用方身份绑定。

---

## 2. P1 —— 中危（合并去重后 ~18 条）

### 认证/授权/租户隔离

| # | 漏洞 | 位置 | 要点 |
|---|---|---|---|
| P1-1 | **小程序登录租户自报 + WeChat Mock openid 可预测** | `AuthService.java:256-267`；`WechatService.java:51-55,116-124` | 公开端点 `/api/auth/mini/login` 的 `tenantId` 直接来自请求体，未找到即在**任意指定租户自动创建 customer 并签发 JWT**；appid/secret 未配置时 Mock 模式 openid=`mock_openid_`+sha256(code) 前16位，可枚举伪造 → 任意微信用户可进驻任意租户、Mock 下可伪造任意 openid。修复：tenant 归属由服务端从 code2Session 推导；微信配置缺失禁用该端点 |
| P1-2 | **同手机号跨租户登录歧义** | `UserMapper.java:20-22`；`AuthService.java:187-192` | `selectByPhoneIgnoreTenant` 按 `ORDER BY updated_at DESC LIMIT 1` 静默选一条 → 用户可能登录进错误租户获得他人身份。修复：登录要求显式租户标识/冲突选租户 |
| P1-3 | **C 端会话发消息无归属校验（IDOR）** | `CustomerAgentSessionController.java:50-59`；`AgentSessionService.java:357-396` | `sendMessage` 只校验租户不校验 `senderId==session.customerId` → 租户内客户间消息注入/伪造。修复：强制会话归属校验 |
| P1-4 | **无权限注解的水平越权面** | `AdminRoleController.java:118-123`（删除角色）、`SettingsController.java:174-261`（读写 AI 配置）、`UploadController.java:33-129`（上传/删除文件） | 最低权限员工（非 customer/agent 即放行 `/api/admin/**`）即可删角色、篡改租户 AI 配置、上传/删除文件。修复：补 `@RequirePermission` |
| P1-5 | **Refresh Token 明文回传响应体、7 天有效、无设备绑定** | `AuthService.java:414-503` | 前端被迫存 localStorage（与 P1-F1 叠加放大）。修复：改 HttpOnly cookie、缩短有效期、绑定设备指纹 |

### 数据/API 安全

| # | 漏洞 | 位置 | 要点 |
|---|---|---|---|
| P1-6 | **知识库搜索 OR 优先级绕过租户过滤（跨租户读）** | `KnowledgeController.java:170-178` | `eq(tenantId).eq(isActive).like(title).or().like(content)` → SQL 等价 `(tenant_id=? AND is_active=? AND title LIKE ?) OR (content LIKE ?)` → content 关键词命中**所有租户**文档，接口返回全文。已查 V1-V18 迁移无 RLS 兜底。修复：`.or()` 包进 `wrapper.and(w->...)`；全仓排查同类 `eq(...).or()` 链 |
| P1-7 | **本地文件存储路径穿越 + 删除任意文件** | `LocalFileStorageService.java:69,96-110`；`UploadController.java:36,74-79` | `Paths.get("uploads", directory/relativePath)` 未校验 `..`；`directory=../..` 任意目录写、`{"url":"../../application.yml"}` 可删 uploads 外任意文件（任意员工无权限门槛）。修复：路径规范化 + `startsWith(UPLOAD_DIR)` 校验 + 权限注解 |
| P1-8 | **上传文件匿名可读、无租户隔离** | `SecurityConfig.java:140`（`/api/files/static/**` permitAll）、`WebConfig.java:25-26` | 入驻营业执照等敏感文件 URL 泄露即可匿名访问；跨租户无隔离。修复：鉴权访问/签名 URL、敏感目录单独授权 |
| P1-9 | **上传无 magic number 校验，Content-Type 客户端可控** | `LocalFileStorageService.java:126-154`；`OssService.java:83,163-192` | 仅校验扩展名；`.jpg` + `text/html` 内容的存储型 XSS 面。修复：魔数校验 + 服务端推断 Content-Type |
| P1-10 | **订单/售后退款并发双花** | `OrderService.java:856-866`；`AfterSalesTicketService.java:403-413` | 读 refundAmount → 计算 → `updateById` 覆盖写非原子，并发请求可累计退款超实收。修复：原子 `UPDATE ... WHERE refund_amount + :applied <= actual_amount` |
| P1-11 | **验证码校验无失败次数限制** | `SmsService.java:136-161` | 60 秒防刷只限「发送」不限「校验」，6 位码 5 分钟窗口可爆破。修复：verify 加失败计数锁定（与 P0-1 一并修） |
| P1-12 | **静态共享 SERVICE_TOKEN + 任意 tenant_id（内部接口跨租户读）** | `ai-agent app/api/internal.py:82-97`；`utils/auth.py:51-121` | `/internal/tools/execute` 凭单一共享 token，token 泄露即可对任意租户执行只读工具（order/customer/employee/finance 查询）。修复：mTLS/租户签名 token + 审计日志 + 频控 |

### 前端/基础设施

| # | 漏洞 | 位置 | 要点 |
|---|---|---|---|
| P1-F1 | **JWT 双渠道存储：localStorage + 非 HttpOnly 跨子域 Cookie** | `frontend/admin-web/src/store/auth.ts:11-26,257-268`；`.env.production:13` | 后端已正确签发 HttpOnly+Secure cookie，前端又用 JS 将 accessToken+refreshToken 写入 localStorage 与**非 HttpOnly、Domain=.migaozn.com** 的 cookie → 任一子域（含 C 端 H5）XSS 即可偷后台 JWT（7 天 refreshToken）。修复：删除前端写 cookie 与 localStorage 持久化，仅用后端 HttpOnly cookie，登录态由 `/api/auth/me` 判定 |
| P1-F2 | **ACR 密码明文落盘 + 进云控制台命令历史** | `deploy/scripts/swas-deploy-ci.sh:64-68`；`deploy-ai-agent-service.yml:40-42` | 密码拼进 RunCommand `--command-content`（阿里云审计可见）并写 `/opt/migao-deploy/.env.registry`（默认 umask 644）。修复：临时 token/`--password-stdin`/600 + 用完即删 |
| P1-F3 | **生产端口绑定（部分已修复）** | `deploy/swas/docker-compose.yml` | 已核：8-30 起三服务端口已绑 `127.0.0.1`（nginx 80/443 对外）——**已缓解**；请复核 SWAS 安全组仅放行 80/443 |
| P1-F4 | **API schema/actuator 公网可达（部分已修复）** | `SecurityConfig.java:132-138`；`application.yml:167-175`；nginx | 已核：nginx 已屏蔽 `/actuator|/v3/api-docs|/swagger-ui` 与 FastAPI `/docs|/redoc|/openapi.json`（e0b27e10）——**已缓解**；残留：actuator `show-details: always` 建议关、非 prod profile 仍暴露 springdoc |

### LLM 侧 P1（详见 §4 专题）

P1-L1 间接注入数据原样进 prompt（DB/工具结果/记忆/vision，无信任分级）
P1-L2 DEBUG 模式无 token 注入 tenant-1 admin 且跳过 JWT 验签（`auth.py:139-163,256-267`；`.env.example` 已默认 false，需生产强制校验）
P1-L3 order_create SMS 校验不绑定登录用户、无重试限制、单价不核验、万能码后门
P1-L4 LLM 滥用/DoS：预算仅告警不阻断（`cost_tracker.py:127-144`）、无 per-tenant 配额、会话级限速内存态可绕过
P1-L5 多模态注入：任意 https 图片 URL + 图内嵌文字指令经 vision 以 SystemMessage 身份回注主模型
P1-L6 输出安全：异常 `str(e)`/traceback 回显前端、tool_result 原始 error 透传、模型输出未净化（markdown/外链）
P1-L7 商户可控企业名注入 C 端小布 system prompt（`chat.py:114-159` → `base_skill.py:841-849`）
P1-L8 employee_manage 破坏性动作仅需 `employee:create`，无独立删除/重置权限码
P1-L9 记忆提取可被诱导植入持久化注入（当前 `format_for_prompt` 未接线，潜伏）

---

## 3. P2 —— 低危加固（节选 ~20 条）

| # | 项 | 位置 | 说明 |
|---|---|---|---|
| P2-1 | JWT 未校验 aud/iss | `JwtTokenProvider.java:285-299` | ai-agent 侧已验 aud=migao；admin-api 签发/解析侧补验 |
| P2-2 | 异常 message 回显 | `GlobalExceptionHandler.java:124-139` | IllegalArgumentException/IllegalStateException 的 `e.getMessage()` 原样返回，可能泄 SQL/路径 |
| P2-3 | 重置密码默认=手机号后 6 位且明文回显 | `UserService.java:322-332`、`AdminUserController.java:224-227` | 密码登录当前禁用（#375），未来启用即高危弱口令 |
| P2-4 | X-Forwarded-For 可伪造绕过 IP 限频 | `RegistrationController.java:116-125` | 已核 nginx 已改为 `X-Forwarded-For $remote_addr` 覆盖（#2661）——**已缓解**；应用层勿再信任首段 |
| P2-5 | actuator health `show-details: always` | `application.yml:167-175` | prod 关 details/metrics |
| P2-6 | mapper SQL DEBUG 日志 | `application.yml:152` | prod 覆盖为 INFO，防 SQL 参数（手机号）落日志 |
| P2-7 | Java 侧日志 PII 明文 | `AuthService.java:132,147,170,190,196`、`SmsService.java:114-115,140`、`CustomerService.java:186,282` 等 | Python 侧已脱敏（fae43a7f），Java 侧仍打全量 phone；`SmsService` 直接打印生成的验证码 |
| P2-8 | 刷新令牌黑名单为 Redis 内存态 | `AuthService.java:710-720` | 重启即失效；建议 DB 持久化吊销 + 轮换 |
| P2-9 | 批量接口无数量上限 | `ProductController.java:142-180`、`DashboardController.java:294,321` | batch productIds/limit 无上限 |
| P2-10 | 上传先读后判（内存 DoS） | `ai-agent app/api/upload.py:99-113`、`asr.py:206-209` | 按 Content-Length 预检 |
| P2-11 | CORS `*` 配置面 | `SecurityConfig.java:52-93` | 默认白名单固定域名 ✓；禁止部署时配 `*` |
| P2-12 | admin-web 镜像 root 运行、无 .dockerignore | `frontend/admin-web/Dockerfile` | 对比后端两服务已非 root+HEALTHCHECK；改多阶段 + `USER node` + .dockerignore |
| P2-13 | Actions 全部浮点 tag 未 SHA pin | 16 个 workflow | 供应链风险，dependabot 已配 github-actions 生态 |
| P2-14 | 无镜像/依赖漏洞扫描；npm audit continue-on-error | `pr-check.yml:103-106` | 补 trivy/pip-audit，audit 改 fail-closed |
| P2-15 | gitleaks 仅 PR 事件 | `pr-check.yml:384-398` | 补 push/main 触发器 + 历史全量扫描 |
| P2-16 | 登录开放重定向 | `src/app/login/page.tsx:56-57` | callbackUrl 仅允许站内相对路径 |
| P2-17 | `next.config.mjs` Host 白名单无效 | `next.config.mjs:14-23` | Next 14.2.35 无 `trustHost/hosts` 键，用 `experimental.trustHostHeader` |
| P2-18 | AI 图片外链直载无域名白名单 | `MessageList.tsx:383-390`、`lib/utils.ts:30-45`、mini-app `MessageBubble.tsx:190-198` | 后端有 `_validate_image_url`/IMAGE_URL_REWRITE，前端未联动；补 CDN 白名单 |
| P2-19 | nginx 无安全响应头/ssl_ciphers | `deploy/swas/nginx.conf` | 补 HSTS/CSP/X-Frame-Options/ssl_ciphers |
| P2-20 | 登出残留/无服务端撤销 | `store/auth.ts:243-254`、mini-app `auth.ts:106-112` | 清键 + 服务端黑名单 |
| P2-21 | 私有 key 随 classpath 打进镜像 | `Dockerfile`（resources 打包）、`application.yml:91` | 私钥文件存在工作区（git 已忽略，未入库），构建镜像时进制品；生产强制 `JWT_PRIVATE_KEY` 注入 |
| P2-22 | 对抗评测仅追踪不阻塞 | `agent-eval-adversarial.yml:36-48` | DF-006 注入/DF-007 越权失败仅建 Issue，建议升 nightly 阈值 |

---

## 4. LLM 被恶意攻击风险专题（核心关切）

### 4.1 直接提示注入

- 防线以 prompt 文本为主（`principles.md:24-32` 安全铁律：拒绝角色切换/输出 system prompt），**无真实指令层级**：`general_agent.py:33` 声称的 `<user_query>` 标签包裹从未实现（`base_skill.py:908-913` 组装消息时不包裹）。
- **确认守卫代码层只覆盖 destructive 工具**（`base_skill.py:545-562`）：`if not destructive: return False` → **非 destructive 写工具（finance 记账/通知/会话分配/库存调整/商品更新等 10 个）在注入驱动下无任何代码级确认**，仅靠 prompt 文本约束 → **P0-L1**。
- 系统提示词模板不含 API key/内部 URL/service token（已全量 grep 验证 ✓）；但工具 schema 经 bind_tools 天然暴露。

### 4.2 间接提示注入（数据投毒 → 注入驱动写操作）——**本系统最大 LLM 风险面**

- **成立且面广**：商品名/工单描述/客户名/企业名/vision 分析结果均**未脱敏、以 SystemMessage/ToolMessage 身份**回注主模型（`base_skill.py:957-970,875-884,1105`；`context_manager.py:104-119`）：
  - 恶意商户可创建商品/分类名称为注入文本（`product_manage.py:49-56` 原样入库）→ 本租户所有员工会话被污染；
  - C 端顾客可在售后工单原因/转人工描述写入注入文本（`aftersale_create.py:220-229`）→ 商户客服查询工单时触发；
  - 企业名（`chat.py:1041-1054` → `base_skill.py:841-849`）注入 C 端小布 system prompt 首段（仅清洗换行/截断，无指令语义过滤）→ **P1-L7**；
  - 图片内嵌文字经 vision 识别后以 `SystemMessage` 身份注入（`base_skill.py:970`）→ **P1-L5**（任意 https 图片 URL 可引用，`chat.py:336-341`）。
- **完整攻击链**：数据投毒（商品名/工单/图片）→ 间接注入 → 驱动 `finance_api.create_transaction` / `notification_manage.create` / `session_manage.end` / `product_update` 等**无确认写工具** → 本租户内未授权数据变更（权限仍受 JWT 限制，跨租户受限）。

### 4.3 工具权限强制（已验证总体良好）

- `registry.execute_tool` 与每个工具 `execute` 内双重 `check_permission`（角色 + `required_permissions`）✓；角色来自 RS256+aud 校验的 JWT，用户消息无法伪造 ✓；C 端小布工具面最小化（无 admin 工具绑定）✓；多数工具对 admin-api 响应做 tenant 回验 ✓。
- **两个破口**：
  1. **`__PAGE__` 分页协议直调绕过确认守卫（P0-L2）**：`chat.py:704-717` 白名单注释声称「仅 list 操作」，但含 `product_manage`/`customer_manage`/`employee_manage` 等**写/破坏性工具且无 action 限制**，`chat.py:800` 将用户 params 直接透传 `execute_tool`（该路径无 `_requires_confirmation`）→ 持有效 JWT 的员工可发 `__PAGE__|customer_manage|{"action":"delete",...}` 绕过 LLM 与确认卡片直接删客户/商品/员工。`product_manage` 甚至根本没有 list action（`VALID_ACTIONS={create,update,toggle_status}`）。
  2. `employee_manage` 破坏性动作仅需 `employee:create` 权限码（P1-L8）。

### 4.4 租户/数据隔离（已验证总体良好）

- tenant_id 全链路源自 JWT → ToolContext → `X-Tenant-Id`，工具**不接收** tenant_id 参数 ✓；session/user memory 按 tenant+user 查询 ✓；**唯一跨租户面是内部接口共享 token + 任意 tenant_id（P1-12）**。

### 4.5 LLM 滥用/DoS/成本

- `cost_tracker.check_budget` 超月预算**仅告警不阻断**（`cost_tracker.py:127-144`），无 per-tenant/per-user 配额 → 任一登录用户循环新建会话 + 长文本（`max_length=10000`）可持续消耗 token 直至预算超支，服务照常运行 → **P1-L4**。
- 限速按 session 内存态计（`base_skill.py:742-761`），新建会话即绕过；多实例失效。
- ASR 共享 36,000 秒免费额度无 per-user 限制（`asr.py:193-259`）。

### 4.6 其他

- **RAG 注入面当前不存在**：`[RAG 禁用]` 属实（`app/rag` 不存在、knowledge 工具未注册、internal sync 恒返回 RAG_DISABLED）——间接注入经 RAG 文档的路径关闭；残留 `/internal/knowledge/sync` 接口建议同步禁用。
- 记忆提取器可被诱导存注入文本（`extractor.py:103-107`），`format_for_prompt` 全仓无调用点（当前不注入），一旦接线即成**跨会话持久化注入**（P1-L9，潜伏高）。
- 思考内容剥离（`<think>`）做得正确（`chat.py:553,618`）✓。

**LLM 攻击面总体结论**：对「本租户内越权/未确认写操作」与「注入驱动的写操作」防御不足（P0-L1/P0-L2/P1-L1 需优先修复）；对「跨租户直接越权」防御良好。

---

## 5. 权限漏洞专题（认证/授权/隔离链）

| 层 | 结论 |
|---|---|
| 门禁 | `/api/admin/**` 仅拒 customer/agent，**任意其他角色（含零权限自定义角色）可进入**，细粒度靠 `@RequirePermission`——但 UploadController/AdminRoleController.deleteRole/SettingsController.aiConfig 等**无注解**（P1-4） |
| 角色来源 | `User.role` 字符串直接进 JWT，**无白名单**（P0-2）；同手机号跨租户歧义（P1-2） |
| 租户 | MyBatis-Plus 拦截器全局注入 + JWT claim 取租户 + 缺租户 fail-closed ✓；被 P0-2 伪造 super_admin 击穿（忽略表 tenants/platform_admins/tenant_applications 无过滤）；`KnowledgeController.test-search` OR 拼接绕过（P1-6）；DB 层无 RLS 兜底（文档 S4 失实已修 008 部分表，其余仍无） |
| 会话 | JWT HttpOnly+Secure+SameSite=strict ✓；**前端自毁为 localStorage+非 HttpOnly cookie**（P1-F1）；refresh token 明文回传（P1-5） |
| 服务间 | SERVICE_TOKEN 恒时比较 + fail-closed ✓；默认值硬编码（P0-3）+ 租户自报（P1-12） |

---

## 6. 安全亮点（已逐条验证，防误报）

1. **SQL 注入面干净**：全仓无 `${}` 拼接，mapper 全 `#{}` 参数化，排序字段白名单。
2. **JWT 算法混淆不可利用**：RS256 固定 fail-fast（`JwtTokenProvider.java:82-96`），jjwt 0.12 拒 alg=none/HS256。
3. **租户拦截器主链路正确**：TenantContext 请求级 finally 清理无线程池串号；JWT 缺 tenantId fail-closed。
4. **服务间鉴权双向**：`verify_service_token` 恒时比较 + 未配置 503 fail-closed；admin-api→ai-agent 带 token；ai-agent 校验 JWT aud=migao。
5. **destructive 工具确认守卫对 Agent 图路径有效**（`base_skill.py` `_is_explicit_confirmation` 防注入诱导），写操作审计日志结构化，`<think>` 剥离。
6. **上传扩展名白名单 + 大小限制**；OSS 永久/临时双 bucket ACL 区分。
7. **密码 hash 响应脱敏**；GlobalExceptionHandler 兜底异常不回显堆栈；订单状态流转原子化条件 UPDATE。
8. 前端 chat 渲染 react-markdown v10 默认剔除 `javascript:`/`data:` 协议与原始 HTML（**当前无直接 XSS**，但缺显式 sanitize 兜底）。
9. mini-app 无硬编码密钥、无 XSS 面（全 `<Text>` 转义）、token 不进 URL。
10. 治理文件（SECURITY.md/CONTRIBUTING/CODEOWNERS/dependabot/FUNDING）、gitleaks PR 门禁、block-env-files 门禁已落地。

---

## 7. 08-29 审计（06）后已修复/缓解对照

| 06 编号 | 项 | 状态（08-30 复核） |
|---|---|---|
| S2 | DEBUG=true 无 token 直通租户 1 | **已修**：`.env.example` 默认 `DEBUG=false`；仍建议生产强制校验（P1-L2） |
| S3 | 历史 JWT 私钥泄漏 | **已修**：密钥已轮换（md5 不同），当前私钥 gitignore 未入库 |
| S5 | 日志 PII 明文 | **部分修**：Python 侧递归脱敏（fae43a7f）；Java 侧仍明文（P2-7） |
| C1 | 无 secret 扫描/SAST | **部分修**：gitleaks PR 门禁已加；trivy/SAST/actions SHA pin 仍缺（P2-13/14/15） |
| C2 | admin-web 镜像 root | **未修**（P2-12） |
| O1/O3/O4 | 回滚/资源限制/零停机 | **部分修**：8-30 已加 mem_limit/cpus/healthcheck；镜像 tag 仍 `latest` 滚动 |
| S1 | SMS 万能码 123456 | **未修（P0-1）**：默认值仍是 123456，属决策 D2 技术债，但作为唯一登录方式风险升级为 P0 |
| S4 | RLS 声明失实 | **部分修**：008 部分表补 RLS；文档与其余表仍无 |
| D1 | RAG 下线 | **已执行**：`[RAG 禁用]` 属实 |
| 2.5-C1 | 敏感端点公网 | **已修**：nginx 屏蔽 actuator/api-docs/swagger/docs + 端口绑 loopback + XFF 覆盖（e0b27e10，#2661/#2662） |

---

## 8. 修复路线图（按依赖与风险排序）

1. **本周（P0，阻断性）**：
   - P0-1：SMS 万能码 fail-closed（改空默认 + 启动断言 + 真短信接入 #2616 + verify 限流）
   - P0-2：员工管理角色/权限白名单 + 服务端授权上限校验
   - P0-3：删除硬编码 service token 默认值；服务器侧核验 `SERVICE_TOKEN`/`SMS_BYPASS_CODE` 实际值
2. **第 2 周（P1 高价值）**：
   - P1-F1：前端 token 存储整改（删 localStorage/JS cookie，仅 HttpOnly cookie）
   - P0-L1/L2 + P1-L1：确认守卫推广到全部写工具；`__PAGE__` 白名单按 (tool, action) 收紧；外部数据不可信标记
   - P1-6：`eq(...).or()` 跨租户修复（全仓排查）
   - P1-7/8/9：文件存储路径规范化 + 权限注解 + 魔数校验 + 静态文件鉴权
   - P1-10：退款原子 UPDATE
3. **第 3-4 周（P1/P2 批量）**：P1-1 mini 登录租户服务端解析、P1-2 手机号登录歧义、P1-3 会话归属、P1-5 refresh 入 cookie、P1-F2 ACR 凭据、P2-12 admin-web 镜像、P2-13/14/15 CI 供应链、P2-7 Java 日志脱敏、P2-21 私钥注入
4. **持续**：LLM 预算硬阻断 + per-tenant 配额（P1-L4）、对抗用例升 nightly 阈值（P2-22）、安全组/ACR/RDS 服务器侧核验

---

## 9. 审计限制与待核验项（静态审计无法覆盖）

- 服务器侧 `.env.admin-api` / `.env.ai-agent` 实际值：`SMS_BYPASS_CODE` 是否显式置空、`SERVICE_TOKEN`/`AI_AGENT_SERVICE_TOKEN` 强度、`DEBUG` 是否 false、`JWT_PRIVATE_KEY` 是否覆盖默认
- SWAS 安全组/防火墙入方向是否仅 80/443；ACR 仓库是否私有
- RDS 备份策略 / Tair 持久化；云监控告警
- 生产镜像中是否含 `resources/rsa/private.pem`（若构建环境工作区含该文件）
- 微信小程序真实 appid/secret 是否已配置（决定 P1-1 Mock 面是否在生产生效）
