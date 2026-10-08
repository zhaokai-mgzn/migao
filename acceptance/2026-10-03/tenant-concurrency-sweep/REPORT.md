# 并发 × 跨租户串号 + ai-agent-service(:8001) 租户链路 验证报告（线 ④）

- **日期**：2026-10-03（本机时区 Asia/Shanghai，UTC+8；观测窗口 `11:02`–`11:13` +08）
- **产物目录**：`acceptance/2026-10-03/tenant-concurrency-sweep/`（`REPORT.md` + `harness/` + `out/`）
- **本线是否改 MIGAO 业务代码**：**否**。只新增验证脚本（`harness/*.mjs`），未触碰 `backend/**`、`frontend/**`、
  `.github/cases/**`、`CHANGELOG.md`；未跑 `verify-all.sh gate/quick/full`（本包为读数验证，非代码改动包）。
- **是否派发真实 LLM 评测**：**否**（#4262）。**本包产生的 LLM 调用次数 = 0**：全部判据走非 LLM 面
  （admin-api 管理面 + `:8001` 内部工具直调/健康/配置面）；唯一"疑似 LLM"的路径
  （`PUT /api/admin/briefing/config` 的 **开启**分支会触发简报生成）**全程传 `enabled=false`**，
  实测前后 `briefing/config` 读数均为 `{enabled:false}`（见 `out/probe-async*.json`）。
- **上游复用**：上一线 `tenant-isolation-sweep`（单线程差分对照）的**未覆盖面第 4/6 项**正是本单，
  其 `harness/registry.mjs` 的端点/`pick` 提取器写法与登录工装已按相同口径复用。

---

## 1. 结论（先说结论，证据在后）

**并发下的租户上下文（ThreadLocal `TenantContext`）在本次观测中未发现串号；`:8001` 的租户链路逐跳一致。**

- admin-api `:8080`：**14 条判据全 pass**（0 fail / 0 skip），覆盖 barrier 对齐真交错（160 请求）、
  超线程池并发（320 请求 > `server.tomcat.threads.max=200`）、切换疲劳（120 次交替）、
  异常路径后紧接他租户请求（5 类）、并发跨租户按 id 读（32 对 + 32 正对照）。
  逐响应比对的**对象 id 总数 4106**（P1）+ 32×2（P5），**无一属对方租户**。
- `ai-agent-service :8001`：**5 条判据全 pass**。租户由**服务端从 JWT claim 绑定**（C 端面）或
  **由调用方 `body.tenant_id` 指定**（内部面）；`X-Tenant-Id` 头在 `:8001` **完全不被消费**（伪造无效）。
- 线程复用**确已发生**（机器读数：388 个 Tomcat 线程中 **180 个**先后服务过 >1 个租户，例如
  `http-nio-8080-exec-15 → 21/20/1`）—— 故"没串号"不是"没复用"的结果。
- **P0/P1 = 0**。发现 **1 条设计边界（需知悉，非缺陷）** + **1 条环境观察（不可归因）** + **3 条未覆盖面**。

---

## 2. 环境与构建点（被测对象自证）

| 项 | 读数 | 采集方式 |
|---|---|---|
| admin-api 构建点 | **`1233b8a42`**（`/Users/guangzhen.zk/migao-wt/main-live`：`1233b8a426036d77d93b928bfe5ce5b644686bf1 2026-10-03 09:58:07 +0800 fix(production): #6126 …`） | `git -C /Users/guangzhen.zk/migao-wt/main-live rev-parse --short HEAD` |
| admin-api 进程 cwd | `/Users/guangzhen.zk/migao-wt/main-live/backend/admin-api`（pid 33126，`/opt/homebrew/.../java`） | `lsof -a -p 33126 -d cwd` |
| admin-api 日志 | `/Users/guangzhen.zk/ai native/migao/acceptance/2026-10-03/out/main-live-1233b8a42-api.log`（`com.migao.admin.mapper: DEBUG` ⇒ 逐条 SQL + 线程名可读） | `lsof -p 33126` |
| 健康 | `GET :8080/actuator/health` → 200（上游线已核 `db: UP`） | `curl` |
| ai-agent-service 构建点 | **cwd = `/Users/guangzhen.zk/ai native/migao/backend/ai-agent-service`**（pid 65007，`uvicorn app.main:app --host 0.0.0.0 --port 8001`）⇒ **被测代码 = 仓内工作树当前文件**（本包报告引用的 `:8001` 代码行号即该工作树） | `lsof -a -p 65007 -d cwd` + `ps` |
| ai-agent 健康 | `GET :8001/health` → 200 `{"status":"healthy","service":"ai-agent-service","version":"1.0.0"}`；`GET /ready` → 200 `{"status":"ready",…}` | `curl` |
| ai-agent 日志 | `/Users/.../backend/ai-agent-service/logs/ai_agent_2026-10-03.log`（含每请求 `status/duration` 行） | `lsof -p 65007` |
| 库 | 云 dev RDS（凭据取自 `backend/admin-api/.env` 的 `RDS_*`），只读 psql | `harness/lib.mjs::psql()` |
| 租户 | `tenants`：`1 词元通达` / `20 米高POC演示布艺` / `21 POC彩排5605` | 直连 DB |
| 含 `tenant_id` 表 | **79** 张 | `information_schema.columns` |
| `:8001` 路由 | openapi 29 条（`/api/chat/**` 15、`/api/internal/**` 11、`/health`、`/ready`…） | `GET :8001/openapi.json` |

> ⚠️ **构建点口径**：仓内工作树（`/Users/guangzhen.zk/ai native/migao`）**不是** admin-api 的被测对象；
> 一切 admin-api 读数归属 `1233b8a42`。`:8001` 相反 —— 它**就是**跑在工作树上的代码。
> 本报告同时给两个真值，禁止互相顶替。

### 2.1 主体（登录读数逐字）

| 记号 | 手机号 | 租户 | 角色 | 登录返回体读数 |
|---|---|---|---|---|
| **A** | 13870217889 | 20 米高POC演示布艺 | admin | `tenantId:20 role:admin user.id=9068a79a939c9be846a605dc78dc30b6` |
| **B** | 13797101248 | 21 POC彩排5605 | admin | `tenantId:21 role:admin user.id=2047a4f6803b8bc14b11c77d8c20b4cd` |
| **C** | 13800138000 | 1 词元通达 | admin | 登录链路上游线已核（本线只用其数据面做对照） |

统一万能码：`POST :8080/api/auth/sms/login {"phone":"…","code":"123456"}` → `{"success":true,…accessToken}`。

### 2.2 云 dev 租户的 `:8001` 运行态（影响判据解读，必须登记）

`/Users/guangzhen.zk/ai native/migao/backend/ai-agent-service/.env` 里 **`DEBUG=true`**，且 `.env`
（含 `SERVICE_TOKEN`，len=65，与 admin-api `.env` 的 `SERVICE_TOKEN_SECRET` **逐字节相同**：`same: true`）
**就在工作树内**。运行态后果（实测）：

- 带 `X-Debug-Role: customer` 的**无 token** 请求被放行为 `tenant_id=1`（`app/utils/auth.py` 的 DEBUG 分支）：
  实测 `GET :8001/api/chat/orders/mine` → 200，返回租户 1 的 12 单（与 DB 逐 id 一致）。
- 代码注释已声明该分支为开发便利、生产 `DEBUG=false` 永不进入（`app/utils/auth.py:236-262` 附近）。
- **⇒ 本机 dev 环境不能用来证明"生产无此旁路"**；本报告只把"生产不可达"记为**代码级声明**，不作为实测结论。

---

## 3. 线程边界表（交付物之一；代码级只读读数）

被测被测对象：`1233b8a42`（admin-api）。`TenantContext` = `ThreadLocal<Long>`（`config/TenantContext.java:9`）。

### 3.1 设置点 / 清理点 / 读取点

| 类别 | 位置（仓库相对 `backend/admin-api/src/main/java/com/migao/admin/`） | 语义 |
|---|---|---|
| **设置** | `security/JwtAuthenticationFilter.java:112` | JWT claim `tenantId`（`null`/`-1` 不设；缺 `tenantId` 直接拒绝认证，fail-closed） |
| **设置** | `security/ServiceTokenFilter.java:104` | `X-Tenant-Id`（**仅**在「合法 service token ∧ `SecurityContext` 为空」时消费） |
| **设置** | `service/AuthService.java:196,449,524,739` | 登录/入驻链路显式 set（无 JWT 的请求） |
| **设置+还原** | `controller/WorkerAuthController.java:60-71,92-101`、`worker/WorkerSessionService.java:318-331`、`service/DailyBriefingService.java:345-353,1424-1442`、`service/RegistrationService.java:414-440`、`service/AutoBatchDueScanService.java:110-166` | 保存 `previous` → `set` → `finally` 还原/清理（**这 5 处是"显式作用域"，不与请求线程生命周期绑定**） |
| **清理** | `security/JwtAuthenticationFilter.java:165-168` | `doFilterInternal` 的 `finally` → `TenantContext.clear()`（**无条件**） |
| **清理** | `security/JwtAuthenticationFilter.java:171-178` | `doFilterNestedErrorDispatch` 的 `finally` → `clear()`（Servlet **ERROR 派发**同线程复用） |
| **清理** | `security/ServiceTokenFilter.java:174-181` | `filterChain` 之后 `finally` → `clear()`（仅当本过滤器设置过 `tenantContextSet`） |
| **清理** | `security/WorkerSessionFilter.java:76,85,129` | 工人会话路径 clear |
| **读取** | `config/MybatisPlusConfig.java:69-87` | `getTenantId()`：`==null` ⇒ 主体是 `super_admin` 则**跳过过滤**，否则**抛异常** `Tenant context not initialized - possible unauthenticated access`（**守门人会是红的**）；`==-1` ⇒ 跳过过滤 |

### 3.2 线程边界

| 边界 | 上下文是否传播 | 读数/依据 |
|---|---|---|
| **Tomcat 请求线程池**（`server.tomcat.threads.max=200`、`accept-count=100`） | **否**；每请求 `finally clear()` ⇒ 复用安全 | 实测线程复用 **180/388** 个线程服务多租户（`out/redproof-threadreuse.json`）；P1/P2/P3/P5/P6 未见串号 |
| **Servlet ERROR 派发** | 同一请求线程（已补 `clear()`） | `JwtAuthenticationFilter.java:171-178`（P4 的 404/422/401 均走正常 dispatch） |
| **`@Async SessionDistillListener.onSessionEnded`**（`listener/SessionDistillListener.java:27`） | **不传播**（`@EnableAsync` 无 `AsyncConfigurer`/`TaskDecorator`；Spring Boot 默认 `ApplicationTaskExecutor`） | 回调内 `distillSession(event.tenantId(), …)` **显式传参**，不依赖 `TenantContext`；**触发条件 = 人工客服会话结束（事务 AFTER_COMMIT）⇒ 本轮未行使**（见 §7 未覆盖面-1） |
| **`@Async AuditLogService.recordLogAsync`**（`service/AuditLogService.java:72`） | **不传播** | 主动行使（`PUT /api/admin/briefing/config` → `BriefingController.java:118`）；见 §4.3 判据 A1/A2 |
| SSE / 流式（admin-api） | **不存在** | `grep SseEmitter\|text/event-stream\|StreamingResponseBody\|DeferredResult\|WebAsyncTask\|CompletableFuture` 在 `admin-api/src/main/java` 命中 **0** 处 |
| SSE / 流式（`:8001`） | 存在（`app/api/chat.py` 的 4 处 `StreamingResponse(media_type="text/event-stream")`） | **必走 LLM ⇒ 本轮不判**（见 §7 未覆盖面-3） |

> **为什么这张表是本单的核心交付物**：判据只能在"边界存在"的地方有意义。
> 本仓的 `TenantContext` 生命周期**绑定在请求线程**上（filter `finally`），
> 唯一出网口的异步面（2 个 `@Async`）**不传播上下文**却**显式传参**；
> 加上 `TenantLineInnerInterceptor` 在 `tenantId==null` 时**抛异常而非放行**（fail-closed 守门人），
> 这三条一起构成"并发不串号"的结构性解释 —— 不只是"这次没测出来"。

---

## 4. 判据矩阵（期望来源 / 并发度 / 实测 / 结论）

**汇总读数（机器可复算）**：主跑 **`pass=19  fail=0  skip=0`**
（`probe` 4 + `probe2` 3 + `probe-agent` 5 + `probe-async` 2 + `probe-redproof` 5）；
**红证翻转跑** `pass=0  fail=14`（4+3+5+2，同一个 `--flip` 开关，见 §6.1）。

### 4.1 admin-api 并发 × 跨租户（判据组 P）

| ID | 判据 | 期望来源 | 并发度 | 实测 | 结论 |
|---|---|---|---|---|---|
| **P1** | A/B token **交错**打同类端点（列表 + 按 id 读），**每个响应体里的对象 id 必须全属发起方租户** | **直连 DB** 的 `select id from <table> where tenant_id=?`（A/B/1 全集，交集 ∅） | 114 请求（并发上限 60；预热 120 请求把池填满）；墙钟 1835ms，**首个响应 74ms 时仍有 113/114 在飞** | 核对 **4106** 个 id，越租户 **0**，非 200 **0** | ✅ pass |
| **P2** | A/B **严格同时起跑**（同一 microtask gate）的列表响应租户归属 | 同上（订单表 359 vs 1） | 160 请求（80 轮 × 2，barrier 对齐）；墙钟 2494ms，首个响应 271ms 时 **159 个仍在飞** | 跨租户/异常 **0** | ✅ pass |
| **P3** | 同一连接会话**连续交替 A→B→A→B ≥60 次**后仍不串号 | 同上 | 120 次交替 | 异常 **0** | ✅ pass |
| **P4** | **异常路径**（非法 id / 3 MB body / 403 无 token / 401 篡改 token / 并发删不存在行）后**紧接另一租户**请求，不得继承前一请求的租户上下文 | 后一请求必须 200 且只含 B(21) 的 id | 5 类异常各 1 次触发 + 紧接 1 次他租户请求 | 触发读数 `404 / 422 / 404 / 401 / 401`；紧接请求 **5/5 → 200 且外来 id 0** | ✅ pass |
| **P5** | 并发下按 id 读的**跨租户拒绝** + **同租户正对照** | 正对照 A→A 必须 200（FAIL-CLOSED：不 200 记 skip）；越租户 A→B 的 id 必须 403/404 | 64 请求成对（32 越租户 + 32 正对照）+ 8 个 skip 位（4 资源 × 2 方向） | 正对照 **32/32 → 200**；越租户 **32/32 被拒**（404），越权成功 **0** | ✅ pass |
| **P6** | 并发 **320**（> `tomcat max-threads 200`）下的租户归属与可用性 | 同 P1 | 320 请求 | 墙钟 5138ms、p95 4917ms；异常/跨租户 **0** | ✅ pass |
| **P7** | **C 端订单链**（`:8001`→admin-api）经 24 个他租户并发请求后**立即**打，仍只返回本租户本用户订单 | **非空夹具**：直连 DB `tenant_id=1 and user_id='debug_customer_1'` = **12 单**；响应 id 必须 ⊆ 该集合 | 3 轮（每轮 24 并发 + 立即 1 次）+ 1 次伪造头 + 1 次 200 并发压满后 | 3 轮均 **12/12/12**；叠加 `X-Tenant-Id:20` → 12（头被忽略）；压满后 → 12；越租户 id **0** | ✅ pass |

**P1 逐字证据**（`out/probe-main.json` → `P1-并发交错.evidence`，`out/probe-concurrency.json`）：

```
并发 114 请求（请求并发上限 60，预热后观测；墙钟 1835ms，首个响应 74ms 时仍有 113 个请求在飞 ⇒ 真交错），
逐响应核对 4106 个对象 id（直连 DB 归属）→ 越租户响应 0 个、非 200 0 个
```

**P4 逐字证据**（`out/probe-exception.json`）：

```
X1-非法id     trigger=404(NOT_FOUND "请求的资源不存在: /api/admin/orders/not-a-uuid-@@@") → 紧接 B 请求 200 foreign=[]
X2-超大body   trigger=422(VALIDATION_ERROR "参数校验失败")                              → 紧接 B 请求 200 foreign=[]
X3-删除中读   trigger=404(NOT_FOUND "商品不存在")                                      → 紧接 B 请求 200 foreign=[]
X4-无token    trigger=401(UNAUTHORIZED)                                               → 紧接 B 请求 200 foreign=[]
X5-篡改token  trigger=401(UNAUTHORIZED)                                               → 紧接 B 请求 200 foreign=[]
```

**P7 夹具一致性（正对照，防"空集假绿"）**：`:8001` 返回的 12 个订单 id 与 DB 的 12 个 id
**逐 id 比对一致**（`out/probe2-cend.json` 的 `dbIds1` vs `attempts`）；若夹具不成立（DB 计数为 0），
该判据会因 `got1.length !== dbCount` 直接报红。

### 4.2 ai-agent-service `:8001` 租户链路（判据组 G）

| ID | 判据 | 期望来源 | 实测 | 结论 |
|---|---|---|---|---|
| **G1** | 无 / 伪造 / 空 `X-Service-Token` 打 `:8001` 内部面必须 401 | `app/utils/auth.py:105-166` 的 fail-closed 实现 | 无=`401` 伪造=`401` 空=`401` | ✅ pass |
| **G2** | `/internal/tools/execute` 的租户归属：`body.tenant_id` 决定查哪个租户；`X-Tenant-Id` 头**不生效** | **直连 DB** 的 `products.tenant_id` 全集（20=35 件 / 21=1 件 / 1=93 件，**三向不相交**） | `tenant_id=20 → 35 件(越租户 0)`；`=21 → 1 件(0)`；`=1 → 93 件(0)`；`tenant_id=20 + 头 X-Tenant-Id:21 → 35 件(0)` | ✅ pass |
| **G3** | C 端只读端点按 token/调试身份的租户过滤 | **非空夹具**：DB `products where tenant_id=1 and recommended` = `["701dec2d2d994da111167c859c7cbf26"]`（20/21 各 0 件） | `X-Debug-Role: customer` → 返回该 1 件，与 DB **逐 id 一致**；叠加伪造头 → 仍该 1 件（头被忽略）；含 20/21 商品 **0** | ✅ pass |
| **G4** | C 端 JWT：真 token 可用、坏/缺 token 一律 401（不回落租户 1） | 真 token 由 `:8080` 签发（RS256，同一 `JWT_PUBLIC_KEY`） | 真 A=`200`、真 B=`200`、乱码=`401`、无 token=`401`、伪造无 `tenantId`=`401` | ✅ pass |
| **G5** | `:8001` 并发下工具直调的租户归属 | 同 G2 | 60 并发 A/B 交错，墙钟 2108ms，首个响应 175ms 时 59 个在飞；越租户 **0** | ✅ pass |

**判定链（代码级 + 实测，落图见下）**：

```
C 端： 客户端 --JWT--> :8001 get_current_user(app/utils/auth.py) --user.tenant_id-->
       http_client._get_headers(tenant_id=user.tenant_id) → X-Tenant-Id + X-Service-Token
       --> :8080 ServiceTokenFilter(消费 X-Tenant-Id) → TenantContext → MyBatis 租户插件
       ★ 租户 = 服务端从 JWT 绑定；请求方无法用头/参数改写（G3/G4 实测）

内部面：调用方 --X-Service-Token--> :8001 /api/internal/**（verify_service_token）
       body.tenant_id → ToolContext.tenant_id → 工具 → 同上转给 :8080
       ★ :8001 内部面**不校验调用方与租户的绑定**：谁持有合法 service token，就能指定任意租户（G2）
```

### 4.3 异步面（判据组 A）

| ID | 判据 | 期望来源 | 实测（12 次并发 `PUT /api/admin/briefing/config`） | 结论 |
|---|---|---|---|---|
| **A1** | `@Async` 审计落库：请求 200 后表里**必须有行**（不得静默丢行） | 12 次 200 ⇒ 期望审计行 ≥1（调用点 `BriefingController.java:118` 每次必调） | `audit_logs(action=update, resource_type=briefing_config)` 增量 **A=6 / B=6 = 12**，与 12 次请求 1:1 | ✅ pass |
| **A2** | `@Async` 并发下审计行的 `tenant_id` 与调用租户一致（不串号） | 行的 `resource_id`（= `String.valueOf(tenantId)`，同一调用点写入）与 `tenant_id` **列**必须一致且 ∈{20,21} | 近 10 分钟窗口 **0 条错租户** | ✅ pass |

**为什么这条能红**：`MybatisPlusConfig.getTenantId()` 在 `TenantContext==null` 时**抛异常**（不是放行）；
若异步线程真的丢了上下文，A1 会从"表里有行"翻红成"丢行"。实测 12/12 落库
⇒ 说明该写入路径的 `@Async` 线程并未走到需要 `TenantContext` 的 SQL（或由 INSERT 显式列承载租户，
`AuditLog.builder().tenantId(tenantId)`），**A1/A2 双向可判**（§6.1 翻转后两条都红）。

---

## 5. 发现清单

> 级别定义：P0=可越权读/写他租户数据且**已实测发生**；P1=同上且可规模化；P2=需产品裁定/硬化；P3=低。
> **本线 P0/P1 = 0。**

### F-1（P2 · 设计边界，需知悉不需修）`:8001` 内部面「持有 service token 即可指定任意租户」

- **判据（一句话）**：*`:8001` 的 `/api/internal/**` 只校验 `X-Service-Token`，不校验调用方与 `body.tenant_id` 的绑定
  ⇒ 令牌持有者可用一个请求读取/触发任意租户的数据或工具；风险等价于令牌本身的泄露面。*
- **最小复现**（零 LLM，逐字）：
  ```
  POST http://localhost:8001/api/internal/tools/execute
  X-Service-Token: <合法内部令牌>
  {"tool_name":"product_search","params":{"keyword":"","size":100,"page":1},"tenant_id":21,"user_id":"probe-user"}
  → 200 {"success":true,"data":{"products":[{"id":"caa4b914ff80bb3fdac746929a421560","name":"彩排窗帘9434",…}],…}}
  同一请求换 tenant_id=1 → 200，返回租户 1 的 93 件商品（DB 核对无越租户）
  ```
- **影响面**：`/api/internal/**` 11 条（`tools/execute`、`knowledge/distill`、`vision/recognize`、
  `briefing/generate`、`production/*`、`registration/review`…）。**写操作已被单独拦**：
  `/internal/tools/execute` 对 `read_only == False` 的工具返回 **403 `WRITE_TOOL_FORBIDDEN`**
  （`app/api/internal.py:240-252`）—— 这条降低了破坏面，是本边界的安全垫。
- **token 是否会流到 C 端**：**否**（见 §5.1 的 grep 取证）。
- **同源读数（admin-api 侧）**：`X-Tenant-Id` 头在 `:8080` 同样"合法 service token 即任意租户"：
  实测 `GET :8080/api/admin/products?page=1&size=2` + `X-Service-Token` + `X-Tenant-Id: 21` → **200**，
  返回的正是租户 21 的唯一商品 `caa4b914…`（`out/probe-agent.json` G 段与本节复现）。
- **建议**：把"调用方 ↔ 租户"绑定写进令牌或请求签名（如令牌内嵌 tenant 白名单），
  或至少在内部面加"仅允许本租户"的参数校验；若判定"内部网可信 + 令牌不出网"即为设计边界 ⇒
  **建议在 `docs/` 或代码注释里显式登记**（当前注释只说明"必须显式传 X-Tenant-Id"，未声明"可传任意值"）。

### F-2（P3 · 环境观察，不可归因）`:8001` C 端订单面在高负载窗口曾返回「空集」而非真实 12 单

- **现象**：并行包同时跑压测的窗口内（约 `11:07:54` +08），
  `GET :8001/api/chat/orders/mine?size=20` + `X-Debug-Role: customer`
  在一次"24 个他租户请求并发 + 立即打"的组合下返回 **200 `{"success":true,"data":{"items":[],"total":0}}`**，
  紧随的下一次同样请求返回 **12 单**（与 DB 一致）。
- **归因读数（按强度阶梯，只到"存在性"）**：
  - admin-api 日志在同窗口**确认**该请求到了业务层且租户正确：
    `[http-nio-8080-exec-187] [Agent] 查询我的订单: userId=debug_customer_1, page=1, size=20, status=null, tenantId=1`
    ⇒ **不是串号**（`tenantId=1` 是正确租户）；`:8001` 侧同窗口所有 `orders/mine` 均 `status=200 duration≈130ms`，
    错误日志无新条目。
  - 受控复现失败：单独重跑 3 轮（24 并发 + 立即打）→ **12/12/12**；200 并发压满连接后 → **12**；
    连续 10 次单发 → 全 12。**⇒ 不可归因**（缺一次"当时为什么 total=0"的服务端读数；
    最可能是**云端 DB 连接获取/超时**类瞬时问题，但**我没有该次请求的 SQL 返回读数**，不写猜测为结论）。
- **判据（一句话）**：*同一条只读请求在同一窗口一次返回空集、下一次返回全量，而服务端日志显示租户与用户
  标识都正确 ⇒ 属"读数不稳定"，**不构成租户隔离缺陷**；需要复现时请同时抓 `:8001` 的 `admin-api call failed`
  与 admin-api 的 SQL 返回计数。*
- **不影响本线结论**：P7 的三轮受控读数全 12，且 F-2 不涉及任何跨租户数据。

### F-3（P3 · 环境数据卫生，复用上游发现）租户 20 的表数据不足以支撑"按手机号"的 C 端订单链

- `orders` 表 `tenant_id=20` 的 393 行 **`user_id` 全为 NULL**，而 `users` 表租户 20 的 17 个手机号与
  订单的 `customer_phone` **零交集**（`select u.id,u.phone,count(o.id) … join on phone` → `[]`）
  ⇒ `AgentOrderController.getMyOrders` 的手机兜底分支在租户 20 **不可达**（不影响安全，只影响可测性）。
- **判据**：*以「手机号 → 用户 → 订单」为入口的 C 端链路在租户 20 无法构造非空夹具 ⇒
  本线改用「租户 1 的 `debug_customer_1`（12 单）」做非空夹具（见 §4.1 P7）。*

### 5.1 token 泄漏面取证（`:8001` service token 是否会流到前端）

| 检查 | 命令（在 `backend/` 与 `frontend/` 各跑一次） | 读数 |
|---|---|---|
| 前端是否出现 service token 头 | `grep -rl "X-Service-Token" frontend --include=*.ts --include=*.tsx --include=*.js --include=*.jsx --include=*.json --include=*.vue \| grep -v node_modules \| wc -l` | **0** |
| 前端是否出现 `SERVICE_TOKEN` / `serviceToken` 标识 | 同上（模式 `SERVICE_TOKEN\|serviceToken`） | **0** |
| `:8001` 侧引用点 | `grep -rn "settings.SERVICE_TOKEN" app/` | 仅 `app/utils/http_client.py:95`（**出向**头，打 admin-api）与 `app/api/upload.py:209`（**出向**头） |
| `:8001` `.env` 位置 | `ls backend/ai-agent-service/.env` | 存在（**工作树内**，dev 环境；`.gitignore` 覆盖，见 §2.2） |

⇒ **未发现 service token 出现在任何前端代码/构建物里**（P0 级"令牌流到 C 端"**未出现**）。
⚠️ **未覆盖面**：未扫 `frontend/**/dist`、`node_modules`、H5 发布产物（见 §7-2）。

---

## 6. 红证（逐字）

### 6.1 红证①：判据反转注入（`--flip`）—— 同一个判据开关，把"必须属本租户"反转成"允许对方租户"

```
$ node probe.mjs --flip --n=60 --conc=40
❌ [P1-并发交错] … 逐响应核对 2025 个对象 id（直连 DB 归属）→ 越租户响应 0 个、非 200 0 个 ⇒ 出现对方租户数据
❌ [P3-切换疲劳] … 交替 120 次（A↔B），异常响应 0 个
❌ [P4-异常路径] … 继承前一租户上下文 0 次
❌ [P5-并发跨租户读] … 正对照 A→A 32/32 个 200；越租户 A→B 的 id 32 个：被拒 32、越权成功 0
=== probe 读数：pass=0 fail=4 skip=0 total=4

$ node probe2.mjs --flip
❌ [P2-barrier对齐] … 跨租户/异常响应 0 个
❌ [P6-超线程池并发] … 异常/跨租户 0 个
❌ [P7-C端订单链残留] … 3 轮 → 12/12/12 单；叠加 X-Tenant-Id:20 → 12；200 并发压满后 → 12；越租户 id 0
=== probe2 读数（flip=true）：pass=0 fail=3 skip=0 total=3

$ node probe-agent.mjs --flip
❌ [G1-服务令牌闸] 🔴 未全拒 401/401/401
❌ [G2-工具直调租户归属] 🔴 body.tenant_id=20 → 35 件(越租户 0)；=21 → 1 件(0)；=1 → 93 件(0)…
❌ [G3-C端端点租户过滤] 🔴 …（头被忽略）；含租户 20/21 商品 0 件
❌ [G4-C端JWT认证] 🔴 坏 token 未被拒：乱码=401 无=401 伪造=401
❌ [G5-并发租户归属] 🔴 … 越租户响应 0 个
=== probe-agent 读数（flip=true）：pass=0 fail=5 skip=0 total=5

$ node probe-async.mjs --flip
❌ [A1-异步审计不丢行] 🔴 12 次 PUT 全 12/12 → 200；增量 A=6 B=6（合计 12） ⇒ 异步落库静默丢行
❌ [A2-异步审计不串号] 🔴 0 条错租户：[]
=== probe-async 读数（flip=true）：pass=0 fail=2 skip=0 total=2
```

- **读数**：**14 条判据全部翻红**（4+3+5+2），`pass=0`。
- **反向自证（不是"一律红"）**：同一批脚本在 `flip=false` 下 **19 条全绿**（§4）。
  ⇒ 断言是**跟着读数走**的，既不恒真也不恒假（双向可判）。
- **注意**：翻转后 `pass=0` 是**预期**（判据期望被反转，而现实没变）——
  若翻转后仍有 `pass`，才说明那条判据是空断言；本次**没有**这种条目。

### 6.2 红证②：正对照（串行单租户必须全绿；`A→A` 按 id 读必须 200）

```
$ node probe-redproof.mjs
✅ [RP1-正对照] 单线程单租户串行列表请求必须全部 200 且无他租户 id — 36 个串行请求，失败 0 个
✅ [RP4-期望独立性] 期望集合取自直连 DB 且两侧不相交（交集 ∅ ⇒ 越租户可判别）— A=35 B=1 交集=0
```

P5 内部的按 id 读正对照：`正对照 A→A 32/32 个 200`（attacker 侧无行的 4 个资源记 skip，**不记 pass**）。
⇒ 同一端点在不同主体/对象下产生 **200 / 401 / 404** 三种读数，不存在"全局 404"式假绿。

### 6.3 红证③：注入式（判据级 + 检测器级 + 线程复用级）

```
✅ [RP2-检测器注入] 判据能检出合成越租户响应 — 合成体含 1 个非 20 的 id ⇒ 判据报红
✅ [RP3-线程复用证据] 388 个线程中 180 个先后服务过多租户；
     样例：http-nio-8080-exec-7→20/1 | exec-56→20/1/21 | exec-15→21/20/1
✅ [RP5-判据级注入] 比对器对「干净体」绿、对「掺入他租户 id」红（双向可判）—
     干净体越租户数=0（期望 0）；掺入体越租户数=1（期望 >0）
```

- **RP2/RP5 的期望来源与被测系统当下的读面**：注入体里的"外来 id"取自**直连 DB**
  （`orders` 里确实属租户 21 的 id），不是从 API 响应里抄的。
- **RP3 的意义**：把"线程复用确实发生"变成**被测服务自身日志**的机器读数
  （`[http-nio-8080-exec-N]` + `tenantId=`），而不是推断 —— 这样"没串号"才是可归因的正面结论。

### 6.4 红证④（自加）：零残留读数不是空断言

见 §8.1：残留比对覆盖 **79 表 × 3 租户 = 237 格**（含行数 + `md5(string_agg(id))` 指纹），
**2 格变化**且**逐条归因到本线自身的可解释写入**（`audit_logs` 12 行，由 §4.3 的探针创建）。
⇒ "无未归因残留"这个读数**能红**（任何未解释的变化都会出现在 diff 里）。

---

## 7. 假绿自查（重点回答任务点名的两个坑）

| 问题（任务点名） | 自查结论 | 依据 |
|---|---|---|
| **"是不是并发根本没交错上？"** | **不是**。三条独立读数：① barrier 门控让 A/B 在**同一 microtask** 起跑，首个响应到达时 **159/160** 个请求仍在飞；② 并发 320 **超过** `tomcat threads.max=200`，p95 4917ms（**排队**发生了）；③ 被测服务自身日志证明**线程复用**：180/388 个线程服务过 >1 个租户 | §4.1 P1/P2/P6、§6.3 RP3 |
| **"期望是否取自被测系统自身读面？"** | **不是**。全部"应属哪个租户"的期望来自**直连 DB** 的 `select id from <table> where tenant_id=?`（A/B/1 三向**交集 ∅**，RP4 机器核对），并落盘 `out/*-idfyixture*.json`；响应只用来**被比对**，不用来定义期望 | §6.2 RP4、`harness/resources.mjs::dbIds` |
| 是不是所有请求都 404/401（判据无判别力）？ | **不是**：同一端点在不同主体/对象下产生 200 / 401 / 404 三种读数；串行正对照 36/36 → 200；`A→A` 按 id 读 32/32 → 200 | §6.2 |
| 跨租户读的 404 会不会是"路由/校验先拒"伪装？ | **部分已排除**：P5 用**同租户自己的 id** 做正对照（200），说明该端点/该方法确实可达；P4 的 422（超大 body）与 404 分别来自不同层，且**不改变**隔离结论 | §4.1 P4/P5 |
| 空集断言？ | **已逐条查**：凡依赖数据的判据都配了**非空夹具**或 FAIL-CLOSED skip：P7（DB 12 单）、G2（35/1/93 件）、G3（租户 1 的 1 件 recommended）、A1（期望 ≥1 行）；attacker 侧无行的 4 个资源在 P5 记 **skip 而非 pass**；弃用的早期版本（`data.items` 取空导致三项"0 件即通过"）已被发现并改写 —— **第一版 G2/G3 就是空的，见下** | `out/probe2-crossread.json::skippedNoRows`、`out/probe-agent.json` |
| **假绿复盘（诚实登记）**：第一版 `probe-agent.mjs` 用 `data.items` 取 `:8001` 工具返回，而工具返回在 `data.products` ⇒ 三项判据在"0 件"上通过（**空断言**）。已按 `out/agent-service-boundary.json` 的 `tenant20_count:0` 反查发现并改写为 `data.products ?? data.items ?? []` + 非空前置，重跑后才得到 35/1/93 的真读数 | 同上 |
| "先读代码定位"是不是只做了 grep？ | **不是**：`TenantContext` 的 8 个设置点 / 4 个清理点 / 1 个读取点逐处读正文（§3.1），并确认**无 `AsyncConfigurer`/`TaskDecorator`**、**无 SSE/流式**（`@EnableAsync` 在 `AdminApiApplication.java:15`） | §3、`out/thread-boundary.json` |
| 我改的期望会不会"跟着实现走"？ | `X-Tenant-Id` 头在 `:8001` **不被消费**这条期望，来源是**代码读**（`:8001` 无该头的消费点）+ **实测**（G2 伪造头后件数不变），不是从响应反推 | §4.2 G2 |

---

## 8. 零残留（机器读数）

### 8.1 读数

| 项 | 读数 | 文件 |
|---|---|---|
| 残留比对范围 | **79 张含 `tenant_id` 表 × 3 租户 = 237 格**（行数 + `md5(string_agg(id order by id))` 指纹） | `out/residue-diff.json` |
| before | `2026-10-03 11:10:57 +08` | `out/residue-before.json` |
| after | `2026-10-03 11:16:01 +08`（**修 P1 计数读数并重跑后重取**；两次窗口的 diff 结论逐字相同） | `out/residue-after.json` |
| 变化 | **2 格**：`audit_logs#20` 12→18、`audit_logs#21` 12→18（指纹均变） | `out/residue-diff.json` |
| 归因 | **本线自身的可解释写入**：§4.3 的探针打了 12 次 `PUT /api/admin/briefing/config`（A 6 次 / B 6 次），每次由 `BriefingController.java:118` 同步调 `recordLogAsync` ⇒ 12 行；`resource_type='briefing_config'`、`action='update'`，`tenant_id` 与调用方一致（A2 已核） | `out/probe-async-counts.json` |
| 前缀标记扫描（`并发验收` / `probe-`，覆盖 79 张表的 text/varchar/jsonb 列） | 命中 `client_request_keys` **2 行** —— **非本线**：本线**没有任何**写 `client_request_keys` 的请求（本线写面仅 `briefing/config`）；该表 2 行属并行包（幂等/重放探针） | `out/residue-marker.json` |
| **本线自建对象的残留** | **0** | 同上 |

**"探针存活残留 = 0" 的机器判据**：本线**不创建任何业务对象**（读面探针 + 一次 conf 写），
故"自建对象计数"恒为 0（不是没测，是**没有**）；等价判据 = **未归因变化格数 = 0**（237 格中 2 格变化，
100% 归因到本线自己的 `audit_logs` 写入）。

### 8.2 附带清理

- 早期一次 `curl -X POST /api/admin/orders` 探针（超大 body）曾因相对路径在工作树里产生
  `backend/admin-api/orders/`、`backend/ai-agent-service/orders/` 两个**空目录** ⇒ 已 `rm -rf` 删除（实测不存在）。
- `git status --porcelain` 在本包工作区只显示 `?? acceptance/2026-10-03/`（本包产物）与
  `?? acceptance/2026-10-02/tenant20-full-sweep/`（**他包产物**）⇒ **未改任何仓库业务代码**。

---

## 9. 未覆盖面（诚实登记，不得读成"通过"）

1. **`@Async SessionDistillListener` 路径未行使**：需要"人工客服会话结束"（事务 AFTER_COMMIT）才能触发，
   而该事件的业务入口本轮不可安全构造（会写业务数据、且与并行包写面冲突）。
   ⇒ 该 `@Async` 边界**只有代码级读数**（§3.2），**没有**实测读数。
   （补测方式：在隔离栈建一个会话 → 结束它 → 断言 `knowledge_candidates` 行的 `tenant_id` 与结束方一致。）
2. **前端发布产物未扫**：§5.1 的 grep 只覆盖 `frontend/**` 源码（`.ts/.tsx/.js/.jsx/.json/.vue`，排除 `node_modules`）；
   未扫 `dist/`、H5 发布产物、`node_modules` 内的第三方包。⇒ "service token 不出现在前端"这条**限定于源码面**。
3. **`:8001` 的 SSE/流式面未判**：`app/api/chat.py` 有 4 处 `StreamingResponse(text/event-stream)`，
   它们**必走真实 LLM**（#4262 不得为验证刷额度）⇒ **"需 LLM 才能判、本轮不判"**。
   同样未判的还有 `/api/chat/send`（LLM 主链路）与 `/chat/transcribe`（ASR 外部依赖）。
4. **C 端 JWT 面的"非空 payload"只用调试身份拿到**：云 dev 的 `:8001` 有 `DEBUG=true` + `X-Debug-Role` 旁路
   （§2.2），我用它构造了非空夹具（G3/P7）。**用真实 RS256 C 端 token 构造非空 payload 的路径本轮不可达**
   （`customer_profiles` 与 `orders` 之间无 `user_id` 关联、`users` 与订单手机号零交集，见 F-3；
   而伪造 token 需要与被测进程一致的私钥，见下）。
   ⇒ **两个方向的读数都有**（真 admin token：可用但空；调试身份：非空且与 DB 一致），结论成立；
   但"真实 C 端用户 token 的端到端"**未测**。
5. **未测的 `:8080` 面**（沿用上游未覆盖面，本线未扩）：`batch/*`、`import/export`、`upload/*`、
   `/api/worker/**`（22 条）、`/api/super-admin/**`、幂等/重放（`client_request_keys`）。
6. **未做**：不改被测代码的"注入式线程残留"实验（要改 filter 才能构造），
   本线用 **RP2/RP5 判据级注入 + RP3 线程复用实测**替代（见 §6.3），**不等价于**源码级变异注入。

---

## 10. 双 AI 交叉验证（待办，本包未做）

本包为**单 AI（DeepSeek）**执行，**未**做 `migao-acceptance` §1.5 的复核裁判（GLM-5.3-Flash）交叉验证。
⇒ 本报告的结论强度**止于**"主验收 AI 自证 + 红证 + 正对照"，**不得**被引用为"已双裁通过"。
建议集成侧把 `out/*.json` 与本报告交给复核 AI 做一次**不看本报告结论**的独立抽样。

---

## 11. 建议

1. **（P2 · 登记优先）** 把 F-1 的"内部面 service token ⇒ 任意租户"写成**显式设计边界**
   （注释/文档），并评估是否需要"调用方 ↔ 租户"绑定；若判定可接受，**保留 `read_only` 限制**这条安全垫。
2. **（P3 · 可测性）** 云 dev 补一份真实的「用户 ↔ 客户 ↔ 订单」关联（或给 `orders.user_id` 回填），
   否则所有依赖 C 端用户身份的链路验证（含 AI 评测）都只能靠 `DEBUG=true` 旁路 ⇒ 生产口径永远验不到。
3. **（P3 · 环境）** `backend/ai-agent-service/.env` 的 `DEBUG=true` 出现在工作树里，
   是"dev 旁路可被误当生产行为"的根源；建议把 dev 专属开关移出仓库工作树（或加显式启动期告警）。
4. **（方法学沉淀）** 本线的三条做法建议固化：
   ① **非空夹具前置**（凡"越租户=空集"类判据，先证明响应非空，否则记 skip）；
   ② **`--flip` 判据反转**必须让**全部**判据翻红（有 `pass` 残留即空断言）；
   ③ **线程复用必须自证**（从被测服务日志数同一线程的多租户计数），否则"没串号"无法归因。
5. **（补测）** 若要闭合 §9-1，建议在**隔离栈**做"结束会话 → 断言提炼候选行租户"的确定性用例（零 LLM 可用 stub）。

---

## 12. 产物清单

| 文件 | 内容 |
|---|---|
| `harness/lib.mjs` | HTTP/登录/psql/Recorder（`api()` 带超时与 NETERR 兜底）+ `SERVICE_TOKEN` 读取 |
| `harness/resources.mjs` | 18 资源注册表（列表/按 id 读/DB 表）+ `dbIds()`；主体 A/B/C 定义 |
| `harness/probe.mjs` | P1/P3/P4/P5 + `--flip` 红证（含预热、交错可核性读数） |
| `harness/probe2.mjs` | P2（barrier 对齐）/P6（超线程池）/P7（C 端订单链残留）+ `--flip` |
| `harness/probe-agent.mjs` | G1~G5（`:8001` 租户链路，全非 LLM）+ `--flip` |
| `harness/probe-async.mjs` | A1/A2（`@Async` 审计）+ 落盘**线程边界表** `out/thread-boundary.json` + `--flip` |
| `harness/probe-redproof.mjs` | RP1 正对照 / RP2 检测器注入 / RP3 线程复用证据 / RP4 期望独立性 / RP5 判据级注入 |
| `harness/residue.mjs` | `snap-before` / `snap-after` / `diff` / `marker`（79 表 × 3 租户 + 前缀标记扫描） |
| `out/probe2-cend-repeat.json` / `-narrow.json` / `-trace.json` | F-2 的三次受控复现尝试（重复性 / 窄化场景 / 带时间戳的日志关联） |
| `out/*.json` / `out/*.txt` | 全部**逐字**读数（含 `probe-*-flip*.json` 红证、`redproof-*.json`、`residue-*.json`、`probe-async-log-slice.txt`） |
| `out/run.log` | 带 UTC 时间戳的执行流水 |

**复算方式**（任一条都可零 LLM 重跑）：

```bash
cd acceptance/2026-10-03/tenant-concurrency-sweep/harness
node probe.mjs --n=120 --conc=60      # P1/P3/P4/P5
node probe2.mjs                       # P2/P6/P7
node probe-agent.mjs                  # G1~G5（:8001）
node probe-async.mjs                  # A1/A2（会写 12 行 audit_logs，action=update/briefing_config）
node probe-redproof.mjs               # 红证/正对照（只读 + 日志读数）
node residue.mjs snap-before && node residue.mjs marker && node residue.mjs snap-after
node probe.mjs --flip --n=60 --conc=40 && node probe2.mjs --flip && node probe-agent.mjs --flip && node probe-async.mjs --flip
```
