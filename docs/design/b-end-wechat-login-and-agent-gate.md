# 小程序端管理员微信登录 + 米宝唤出授权门 —— 设计真值源（定向回退 #5485 · 小程序侧）

> **状态**：**设计单**（docs-only，**不改生产代码、不碰 ai-agent、不动 CHANGELOG**）。issue **#5642**。
> **基线**：`origin/main @ 78c67effc`。所有「现状」结论均为在该基线上的**实测**，复算命令见附录 A。
>
> ## 用户裁定（**逐字，本文不得自行改判**）
>
> | # | 日期 | 逐字 | 落法 |
> |---|---|---|---|
> | 裁定⓪ | 2026-09-26 | 「功能5，支持管理员通过微信授权登录，这点需要和普通员工区分开来，管理员可以在 H5 上唤出 migao Agent 进行对话，其他员工需要授权才能唤出 migao Agent」 | 本单的**功能面**（登录 + 唤出授权门，两端） |
> | 裁定① | 2026-09-26 | 微信端登录方式 = **微信授权拿手机号 → 用手机号自动登录**（小程序端） | §2 登录链路 |
> | 裁定② | 2026-09-26 | 浏览器 / H5 端**仍然需要账号密码**（微信授权在 H5 不生效） | §4.4；`AuthService.buildWechatH5AuthorizeUrl` 的 501 占位**保持不动** |
> | 裁定③ | 2026-09-26 | 「管理员」判定**按权限码**，**不新增 role、不做 `is_owner`** | §3 |
> | 裁定④ | 2026-09-26 | 管理员权限码集合 = **`dashboard:view` + `employee:create` + `agent:chat`**，作为**单一真值**同时驱动小程序端与 H5 端的米宝唤出门 | §3（⚠️ 其中一个码**在本仓不存在** ⇒ §3.2 处置：**必须新增**，无「复用既有码」选项） |
> | 裁定⑤ | 2026-09-26 | 租户消歧方式 = **手机号全局匹配；命中多个企业时，让用户选企业**（不是「先填企业编码」，也不是「每企业独立小程序」） | §4（🔴 本单的**核心难点**，安全论证见 §5） |
>
> **本单只出设计**：先定口径，再落码。**本文不含任何实现改动**。
>
> ## 🔴 本文修正了一个**上游错误前提**（逐字登记，不静默改掉）
>
> 派单时给出的前提是「`agent:chat` 是**既有**权限码，只需在『复用』与『新增』之间选」。**实测证伪**：`git grep -n "agent:chat" origin/main` ⇒ **0 命中**（全仓）。更关键的是 —— **「谁能唤出米宝」这件事今天根本没有任何权限码在管**（`backend/ai-agent-service/app/api/chat.py` 的 `/api/chat/send` 无端点级码；小程序 `pages/chat` 无 UI 门）⇒ **「复用既有码」这个选项在本单的语境里不存在**。
>
> ⇒ **本文的结论是「必须新增 `agent:chat` + 显式回填策略」**（§3.2），而**不是**「把 `agent:chat` 读作某个语义相近的既有码」。同时**改正了另一处**：`employee:create` 的种子**不在 `db/**`**（只在 Java 种子里）⇒ 「从 `db/**` 抽权限码全集」这个抽取面**会漏掉一整批码**（§3.1 末）。
>
> ### 🔴 写作过程中的三处**自我修正**（实测推翻本文原稿的判断，逐条登记不藏）
>
> | # | 原稿判断 | 实测推翻 | 位置 |
> |---|---|---|---|
> | 1 | 「跨租户查库**违反 I1 的字面**」 | ❌ **证伪**：`AuthService.smsLogin` **就在**跨租户查库，且**未被 #5485 退役** —— 它被登记进豁免台账 + 写了补偿控制 + 有类级元守卫。⇒ **I1 管的是「签发」不是「查询」** | §5.2.1 |
> | 2 | 「本单的全局匹配 = 把 #5485 点名退役的形态原地复活，需新造受约束查询」 | ❌ **证伪**：`smsLogin` **已经**实现「跨租户手机号 + 仅管理员 + 多租户 fail-closed」，且**已有台账与元守卫**。⇒ 本单应是「**复用既有护栏 + 只补差量**」，**不新增**第二个跨租户查询（新增反而多一条台账条目，而台账**只许缩短**） | §4.4.1 / §4.4.2 |
> | 3 | 「§4.3 必须五合一（连『有几家』都不能说）」+「只回『命中多家』不列名 ⇒ 仍是枚举位 ⇒ 不成立」 | ❌ **证伪**：既有 `smsLogin` **就**单独回「该手机号关联多个租户账号…」⇒ 「说有几家」是**已被接受的既有口径**。⇒ 该形态**成立**（= 路 X），原稿那一格判断错误 | §4.3 / §5.6 |
>
> **另外**：本文原稿曾把「`agent:chat` 读作 `agent:session`」列为推荐（选项 A）—— **已被实测证伪**（§3.2.1：`agent:session` 承载人工接待工位，复用会把两个授权意图焊死；且「谁能唤出米宝」今天无码在管 ⇒ 复用不是降本而是语义错误）。
>
> **配套真值源 / 既有设计**：
> [multi-tenant-wechat.md](multi-tenant-wechat.md)（多租户微信接入）·
> [tenant-miniapp-launch-and-payment.md](tenant-miniapp-launch-and-payment.md)（多租户小程序发布）·
> [employee-permission-chain.md](employee-permission-chain.md)（员工权限链）·
> `docs/wiki/RBAC.md`（权限体系真值源）·
> [worker-h5-scan-and-report.md](worker-h5-scan-and-report.md)（写作体例参照）

---

## 0. 一句话

小程序端给**企业管理员**一条免密路径（微信授权拿手机号 → 在**跨租户**范围内按手机号查账号 → 命中多个企业时由**用户自己选** → 签发与 #5485 **同一套** JWT），**浏览器仍走账号密码**；同时把「谁能唤出米宝」从「人人可唤」改成**按权限码**：管理员（持该组权限码）默认可唤，其他员工**需被管理员授权**才可唤，未授权时给「需要管理员授权」+ 可行动引导（**两端同样生效**）。

**与 issue 正文的一处实质性偏差（必须显式登记，不藏）**：#5642 正文的「范围 · 1 🔴 租户怎么确定」与「关键设计裁定」两处写的是「在**已确定租户内**匹配」「匹配**只在已确定的租户内**做」，而**用户裁定⑤**（2026-09-26，晚于正文草案）明确改为「**手机号全局匹配 + 多企业让用户选**」。**本文以裁定⑤为准**（裁定优先于 issue 草案），并按本单任务要求**正面论证它成不成立** → 结论见 **§5.6**：**在「不校验手机号持有者」的前提下，裁定⑤ 不成立**；给出**两条可成立的处置**并推荐其一。

---

## 1. 现状（`origin/main @ 78c67effc` 实测）

| 件 | 现状 | 复核锚点（**符号 / 文本，不含行号**） |
|---|---|---|
| 小程序员工登录 | ✅ 「用户名@企业编码 + 密码」→ `POST /api/auth/employee/login` | `frontend/bmini-app/src/utils/auth.ts` 的 `employeeLogin(identifier, password)` |
| 员工登录页 | ✅ 无 `getPhoneNumber` 按钮；空输入本地拦，其余交后端 | `frontend/bmini-app/src/pages/auth/login/index.tsx` 的 `handleLogin` |
| **废弃端点的实际形态** | ⚠️ **端点仍在、仍在 `permitAll`、仍收 `phoneCode`，但一定抛 401** —— **不是 404，也不是可用** | `backend/admin-api/src/main/java/com/migao/admin/controller/AuthController.java` 的 `bminiLogin`（`@PostMapping("/bmini/login")`，签名仍收 `BminiLoginRequest`，日志仍打 `hasPhoneCode`）；`backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java` 的 `bminiLogin`（`@Deprecated // #5485`，**恒抛** `BusinessException.authFailed("小程序手机号登录已禁用，请使用员工登录入口（用户名@企业编码 + 密码）")`）；`backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java` 的 `permitAll` 列表含 `"/api/auth/bmini/login"` |
| 🔴 **微信侧能力（本单的重要正面发现）** | ✅ **B 端渠道的微信调用已实现、已接线**：`bminiCode2Session` 与 `bminiGetPhoneNumber` 都在 | `backend/admin-api/src/main/java/com/migao/admin/service/WechatService.java` 的 `bminiCode2Session(code)` / `bminiGetPhoneNumber(code)`（共用私有 `code2Session(appId, appSecret, code, label)` / `getPhoneNumber(...)`；未配置 appid 且 `WECHAT_MOCK_ENABLED=true` 时走 Mock，见其 `log.warn("【Mock 模式】微信 AppID/Secret 未配置（{}渠道）…")`） |
| 🔴 **跨租户按手机号查账号的方法（仍在！）** | ⚠️ **`UserMapper.selectActiveUsersByPhoneIgnoreTenant(phone)` 在主线上仍然存在** | `backend/admin-api/src/main/java/com/migao/admin/mapper/UserMapper.java`；#5485 退役说明逐字点名它（「原 `UserMapper.selectActiveEmployeesByPhoneIgnoreTenant`…按手机号**跨租户**匹配员工，正是本次要消灭的『账号定位不落在企业内』形态」）⇒ **本单复用需显式论证**，见 §4.4 |
| 微信授权链退役守卫 | ✅ 元守卫在（3 条判据） | `frontend/bmini-app/tests/bmini-login-retired.test.ts`，注释头 `# case_ids: AU-001, BM-002` |
| 微信 H5 网页授权 | ❌ **501 占位**（`NOT_IMPLEMENTED`） | `backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java` 的 `buildWechatH5AuthorizeUrl` / `handleWechatH5Callback` |
| 小程序 appid / secret 配置位 | ⚠️ **配置位在，但默认值是空串** | `backend/admin-api/src/main/resources/application.yml` 的 `wechat.bmini.appid: ${WECHAT_BMINI_APPID:}` / `secret: ${WECHAT_BMINI_SECRET:}` |
| 米宝唤出控制（小程序） | ❌ **人人可唤**（`pages/chat` 无任何权限门） | `frontend/bmini-app/src/pages/chat/index/index.tsx`；`git grep -n "permission" frontend/bmini-app/src/pages/chat/ frontend/bmini-app/src/store/` **⇒ 0 命中** |
| 米宝唤出控制（H5） | ❌ 同上（无门） | 同源：`frontend/bmini-app` 一端双编译（§6） |
| RBAC 结构 | ✅ `permissions` 目录 + `roles` + `role_permissions` + `users.permissions` 快照 | `backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java` 的 `defaultPermissions` / `attachDefaultPermissions`；`RoleService.getUserPermissions` |
| `role='admin'` | ✅ **确实存在**，且**恒为通配** `["*"]` | `RegistrationService`（注册首账号 `.code("admin")` + `role="admin"`）；`RoleService.getPermissionCodesForRole` 的 `case "admin" -> List.of("*")`；`PermissionInterceptor.requirePermission` 的 `userPermissions.contains("*")` 分支 |
| `super_admin` / `service` | ✅ 旁路角色，**全部权限** | `PermissionInterceptor.hasBypassRole` |
| 登录失败计数 | ✅ 已在（#5531），**员工侧 + 工人侧两处调用** | `backend/admin-api/src/main/java/com/migao/admin/security/LoginFailureGuard.java`（`MAX_FAILS = 5` / `WINDOW = 5min` / `KEY_PREFIX = "login:fail:"`）；调用点 `AuthService`（`keyOf("employee", tenantCode, username)`）与 `WorkerSessionService`（`keyOf("worker", tenantId, workerNo)`） |
| 审计留痕载体 | ✅ 通用审计日志服务已在 | `backend/admin-api/src/main/java/com/migao/admin/service/AuditLogService.java` 的 `recordLog` / `recordLogAsync`；实体 `backend/admin-api/src/main/java/com/migao/admin/entity/AuditLog.java`（字段 `tenantId` / `userId` / `action` / `resourceType` / `resourceId` / `actionDetails` / `ipAddress` / `userAgent` / `createdAt`） |
| 权限面机械守卫 | ✅ **已有且很厚**（11 条判据 + 注入式红证） | `tests/unit_ci_workflows/test_agent_permission_parity.py`，注释头 `# case_ids: MC-012` |
| B 端双编译能力 | ✅ Taro 4.2.1，weapp + h5 平台插件均在 | `frontend/bmini-app/package.json`：`build:weapp` / `build:h5` 脚本、依赖含 `@tarojs/plugin-platform-weapp@4.2.1` 与 `@tarojs/plugin-platform-h5@4.2.1` |

### 1.1 🔴 五条「issue 正文与实测不符」的读数（**必须先看**）

**读数 ①：`agent:chat` 在本仓不存在 —— 它不是「既有码」，是「尚不存在的码」。**
```
git grep -n "agent:chat" origin/main          ⇒ 0 命中（全仓、全文件类型）
```
实测 `agent` 命名空间下**只有两个码**（见 `RegistrationService.defaultPermissions` 的 `{"会话监控", "agent:session", ...}` 与 `{"会话操作", "agent:session:manage", ...}`）：

| 码 | 中文名 | 说明（逐字取自 `defaultPermissions`） |
|---|---|---|
| `agent:session` | 会话监控 | 「**米宝对话**/会话监控/在线接待」（`AgentSessionController` **类级**读码） |
| `agent:session:manage` | 会话操作 | 「转接/结束会话/发消息」（写码） |

⇒ 用户裁定④里的 `agent:chat` **既不在权限目录里、也无法被任何账号持有**（包括 `role='admin'` —— `["*"]` 是通配**判定**，不是持有了一个叫 `agent:chat` 的码；目录里没有这一行）。**按裁定④逐字落码 ⇒ 管理员集合恒为空 ⇒ 没有一个人是管理员 ⇒ 登录链路与唤出门全部不可达。**
⇒ 🔴 **正确处置不是「静默替换成语义相近的既有码」，而是「新增这个码 + 显式回填策略」** —— 理由见 **§3.2**（关键：**「谁能唤出米宝」今天根本没有码在管**，故**不存在「复用既有码」这个选项**）。

**读数 ②：`WECHAT_BMINI_APPID` / `WECHAT_BMINI_SECRET` 全仓只有空占位。**
`application.yml` 是 `${WECHAT_BMINI_APPID:}`（冒号后为空 ⇒ 默认空串）。且 `.github/cases/processing.yml` 已把这一事实写进判据（issue #4726 的边界登记，逐字）：「bmini 凭据缺失（`WECHAT_BMINI_APPID`/`WECHAT_BMINI_SECRET` 全仓只有空占位），且 `WechatService` 无 `getUnlimited`/`wxacode` 能力」。
⇒ 真实微信调用不可用（**但 Mock 可用** —— 见读数 ③）⇒ 登记为**阻塞项 B1**（§11）。

**读数 ③（正面发现）：微信 B 端渠道的调用能力**已经**实现并接线**，本单**不是零起点**。
`backend/admin-api/src/main/java/com/migao/admin/service/WechatService.java` 已有 `bminiCode2Session(code)` 与 `bminiGetPhoneNumber(code)`（共用私有 `code2Session(appId, appSecret, code, label)` / `getPhoneNumber(...)`）；未配置 appid 且 `WECHAT_MOCK_ENABLED=true` 时**走 Mock**（其日志逐字：「【Mock 模式】微信 AppID/Secret 未配置（{}渠道），使用 Mock 模式处理 code2Session」）。
⇒ **本单的增量只在「服务端按手机号查账号 + 管理员判定 + 签发」，不在「调微信」**。⇒ 同时意味着**Mock 模式下可端到端联调**（缓解 B1 对开发期的阻塞；真机验收仍需真凭据）。

**读数 ④（🔴 与本单核心冲突）：跨租户按手机号查账号的方法在主线上仍然存在。**
`backend/admin-api/src/main/java/com/migao/admin/mapper/UserMapper.java` 的 **`selectActiveUsersByPhoneIgnoreTenant(phone)`** 未被删除。而 #5485 的退役说明**逐字点名它**（`AuthService.bminiLogin` 的 Javadoc）：

> 「员工登录统一为「用户名@企业编码 + 密码」（`POST /api/auth/employee/login`）；微信手机号匹配员工的那条路径（原 `UserMapper.selectActiveEmployeesByPhoneIgnoreTenant`）随之退场 —— 它按手机号**跨租户**匹配员工，正是本次要消灭的「**账号定位不落在企业内**」形态。」

⇒ 本单的「手机号全局匹配」在**代码面上等于复用这个被点名的方法**。**必须显式论证**（§4.4），否则就是把 #5485 明令退役的东西原地复活。

**读数 ⑤：新登录端点必须同时进 `SecurityConfig` 的 `permitAll` 列表，否则会 401 在最外层。**
`SecurityConfig` 的 `permitAll` 逐条列了认证入口（含 `"/api/auth/employee/login"`、`"/api/auth/bmini/login"`）。⇒ 新增的 `/api/auth/bmini/wechat-login` **不在**该列表里 ⇒ 请求会在 Spring Security 层被拦（**不是**业务 401），表现为「端点写了但永远 401」——**典型的「绿了但没跑」**。⇒ 登记为**落码必做项**（§11 T1），并须有判据（§9.2 N9）。

**读数 ⑥（先例，对 §3.2 至关重要）：`agent:quickreply` 曾被整体移除。**
`.github/cases/ui.yml` 逐字：「`agent:quickreply` 权限码**从后端权限目录与岗位默认权限移除**；后端 `/api/admin/quick-replies` 接口与 `quick_reply_manage` 工具随功能下线」。而 `backend/admin-api/src/main/resources/db/migration-archive/V29__backfill_default_positions.sql` 里**仍有**它的回填痕迹（归档不可改）。
⇒ **两条教训（写进 §3.2 的回填策略）**：① 本仓**有**「权限码新增/移除」的完整先例与迁移范式；② **新增一个码不是一行 INSERT** —— 它同时牵动「目录 / 岗位矩阵 / 回填迁移 / 前端菜单 / 工具声明」五处（`tests/unit_ci_workflows/test_agent_permission_parity.py` 的判据 9/10 正是钉这个的）。

### 1.2 「H5 端的米宝入口」指哪一个（**易混，先定名**）

`frontend/bmini-app` 是**一端双编译**（`build:weapp` / `build:h5`，平台插件均已装，§6.1）。因此「两端同样生效」在工程上**不是两份实现**，而是**同一份门在两种编译产物里生效**。

⚠️ 但仓里**另有**一棵 `agent-workspace` 菜单树（`frontend/admin-web/src/config/menu.ts` 的「在线接待」节点，码 `agent:session`，指向 `/agent-workspace/human-sessions`），它是**人工接待工位**，与「商家员工唤出米宝对话」**不是同一个入口**。本单的「H5 端同样生效」指**后者**。完整边界见 §6.3。

---

## 2. 「管理员」判定：按权限码（裁定③）与 `role='admin'` 的对齐

### 2.1 实测：`role='admin'` 的语义是**通配**，不是「持有一组码」

三条独立证据（同一份实现，四处分支）：

| 位置 | 证据 |
|---|---|
| `RoleService.getPermissionCodesForRoleEntity` | `if ("admin".equals(role.getCode())) return List.of("*");` |
| `RoleService.getPermissionCodesForRole` | `case "admin" -> List.of("*");` |
| `RoleService.getUserPermissions`（两条快照/角色分支） | `if ("admin".equals(user.getRole())) return List.of("*");` · `if ("admin".equals(role.getCode())) return List.of("*");` |
| `PermissionInterceptor.requirePermission` | `boolean hasPermission = userPermissions.contains("*") \|\| userPermissions.contains(requiredPermission);` |
| `RoleService.hasPermission` | `return permissions.contains("*") \|\| permissions.contains(permission);` |

⇒ **`role='admin'` ⇒ 权限集 = `{"*"}` ⇒ 对任意权限码判定均为「有」。** 注册首个账号走 `RegistrationService`（建 `code="admin"` 角色 + `role="admin"`），且该角色在 `attachDefaultPermissions(tenantId, adminRole, permissionByCode.keySet(), ...)` 里被**显式预置全部权限码**（注释逐字：「管理员岗位也预置全部权限码（岗位权限页回显「全部权限」…）」）。

### 2.2 「持三个码」与「`role='admin'`」的关系（**逐条回答任务要求**）

**问题 A：`role='admin'` 的账号是否必然持这三个码？**
**是**（对 `dashboard:view` 与 `employee:create` 必然；对 `agent:chat` 因该码不存在而无从谈起 ⇒ 见 §3.2）。理由：`'*'` 通配 ⇒ 任意码判定为真；且 `role_permissions` 里也**逐码实授**了全部目录码（两重保证，任一单独成立即可）。

**问题 B：若不等价呢？—— 实测**不等价**，而且是**超集方向**。**
按 §1.1 的岗位矩阵复算「哪些内置岗位持有 `dashboard:view` ∧ `employee:create` ∧ `agent:session`」：

| 岗位 | `dashboard:view` | `employee:create` | `agent:session` | 三码全持？ |
|---|---|---|---|---|
| `admin` | ✅ | ✅ | ✅（经 `*` 且实授） | **✅** |
| `customer_service` 客服 | ✅ | ❌ | ✅ | ❌ |
| `operator` 运营 | ✅ | ✅ | ❌（只有 `agent:session:manage`） | ❌ |
| `sales` 销售 | ✅ | ❌ | ❌ | ❌ |
| `finance` 财务 | ✅ | ❌ | ❌ | ❌ |

⇒ **在内置岗位种子下，三码集合与 `role='admin'` 恰好等价（集合相等）**。但这是**种子的事实**，不是**逻辑的必然** —— 因为：
- 「岗位权限」页可创建**任意自定义岗位**（`RoleService` 的 `roleCode` 是开放集合，`docs/wiki/RBAC.md` 逐字：「商户角色码是**开放集合**（「岗位权限」页可创建任意岗位码）」）；
- 员工权限是**快照式**（`users.permissions`），员工管理页可**手工增删勾选**，与岗位脱钩。

⇒ **存在两条「不是 admin 却拿到三码」的合法路径**：① 商家给某自定义岗位勾了这三码；② 商家给某个员工手工勾了这三码。

**问题 C：那「不是 admin 的人拿到了米宝唤出权」算**预期内**还是**越权**？**
**判定 = 预期内（不是越权）**，理由是**授权语义的一致性**，不是「三个码看起来很关键」：
- 本仓的授权真值是**权限码**，不是角色码。`docs/wiki/RBAC.md` 的 JWT `claims.permissions` 与 `ToolContext.permissions` **同一份权限码、不另立口径**；`@RequirePermission` 也**只认码**。若本单改成「按 `role='admin'` 判」，就会引入**第二套身份口径**，直接违反裁定③与 #4104 的「同一份身份口径」纪律。
- 🔴 **真正的护栏不是「谁持有」，而是「谁能授予」**：`PermissionInterceptor.assertGrantable`（issue #4104，**用户 2026-09-26 裁定**）强制 `授予集 ⊆ 操作者自身生效权限`，且**授予集包含「所授角色隐含的生效码」**（逐字：「只看快照数组会被『授予一个比自己权限更大的角色』绕过」）。⇒ 商家**无法**把三码授给一个自己都不持三码的人。**这就是「谁算管理员」这个问题的上游答案：只有已是管理员的人，才能造出新的管理员。**
- ⇒ 因此「不是 `role='admin'` 的人持三码」= **管理员有意授权的管理员**，与本单语义一致。**预期内。**

### 2.3 选哪个当**单一真值**？（裁定③已定：权限码）

| 口径 | 采用 | 理由 |
|---|---|---|
| **权限码集合** = `{"dashboard:view", "employee:create", "agent:chat"→见 §3.2}` | ✅ **唯一真值** | 用户裁定③逐字；与 JWT claims / `@RequirePermission` / 工具 `required_permissions` **同一份口径** |
| `role='admin'` | ⚠️ **仅作兼容，不作判定** | 它与三码在**内置种子上**恰好等价（§2.2），故兼容层**不影响任何现有账号的判定结果**；但它**不可作真值**（自定义岗位 / 快照可合法产生「非 admin 的管理员」） |
| 新增 `role` 或 `is_owner` | ❌ **不做** | 用户裁定③逐字 |

**兼容层的具体含义（防止被读成「两套真值」）**：服务端**只**实现 `hasAllAdminPermissionCodes(permissions)` 一个函数（判定 `Set.containsAll(ADMIN_PERMISSION_CODES)`，并对 `"*"` 通配**直接判真** ⇒ `role='admin'` 自动落入 ⇒ **无需为 admin 写任何特例分支**）。**没有第二处判定**。

### 2.4 🔴 机械判据：钉住「管理员权限码集合是单一真值」

**反例参照（任务要求，逐字）**：`craft-display` 三份副本无同步守卫（issue #4393）—— 同一份真值被抄成三份，改一处不会红。

**本单的判据形态（三层，落到既有守卫文件，不新造机制）**：

| 层 | 判据 | 红证形态（注入什么 ⇒ 必红） |
|---|---|---|
| **① 单一常量** | 集合在服务端**只有一处字面量**（`AdminGate.ADMIN_PERMISSION_CODES`）；`git grep` 全仓该三码的**字面量相邻出现**次数 == 1（测试自身与本文除外，语料显式排除判据自身，防 B1「判据被自己计数」） | 在第二个文件里再抄一遍三码数组 ⇒ 计数变 2 ⇒ 红 |
| **② 前端零副本** | `frontend/bmini-app/src/**` 与 `frontend/admin-web/src/**` **不得**出现这三码中任意两个的**字面量共现**（前端**只消费服务端下发的 `capabilities.mibaoChat` 布尔位**，不自己判码） | 在前端写 `permissions.includes('agent:session') && ...` ⇒ 红 |
| **③ 码必须真在目录里** | 集合的每个成员 ∈ `RegistrationService.defaultPermissions` 的码集 **∧** ∈ 迁移链落库的目录（与既有判据 9「两处权限目录逐值相等」**同源复用**） | 写一个目录里没有的码（**本单现状就是这个形态**：`agent:chat`）⇒ 红 |

**归属**：①② 新增到既有 `tests/unit_ci_workflows/test_agent_permission_parity.py`（该文件已有 11 条判据 + 注入式红证 + `LOCAL_ONLY_TOOLS` / `READ_WRITE_EXCEPTIONS` / `READ_CODE_ANCHORS` 等**只许缩短**的台账范式，直接沿用）；③ 该文件判据 9 **已经**在钉「两处权限目录逐值相等」，本单只需把三码**接进**它。⇒ **不新造守卫框架**（最少代码阶梯）。

---

## 3. 权限码集合的定案（裁定④的落地）

### 3.1 集合（**终态**）

```
ADMIN_PERMISSION_CODES = { "dashboard:view", "employee:create", "agent:chat" }
                          ↑ 真实（DashboardController 类级码 + admin-web menu.ts）
                                            ↑ 真实（AdminUserController 的 @RequirePermission("employee:create")，10 处）
                                                              ↑ 🔴 本仓**不存在** ⇒ 必须新增（§3.2）
```

🔴 **`agent:chat` 是本单**要新建**的码，不是既有码** —— 这不是「语义替换」，是「补上那个从来没被建出来的码」。完整清单（目录 / 迁移 / 岗位矩阵 / 角色回退 / 前端与工具）见 §3.2.2。
⚠️ **关于 `employee:create` 的种子位置（复核结论，用于纠正一处常见误读）**：它**不在**任何 `db/migration/**` 或 `db/init/schema.sql` 的抽取结果里 —— 它**只在 Java 种子里**（`backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java` 的 `defaultPermissions`，另 `PermissionService` 亦引用）。⇒ **权限目录的抽取面若只看 `db/**`，会漏掉一整批码**（含 `employee:create`）。**判据口径必须以 `RegistrationService.defaultPermissions` 为准**（`V125` 注释逐字：「权限目录的**唯一真值源**仍是 `RegistrationService.defaultPermissions`」）。

### 3.2 🔴 `agent:chat` 的处置：**必须新增，不存在「复用既有码」这个选项**

**事实**（§1.1 读数①）：`agent:chat` 全仓 0 命中。裁定④逐字写的是 `agent:chat`。

#### 3.2.1 为什么「复用既有码」不是一条路（**这里是关键论证**）

**先看「谁能唤出米宝」今天由什么在管** —— 实测：**没有任何权限码在管**。

| 层 | 实际门禁 | 证据 |
|---|---|---|
| **端点层**（`/api/chat/send`） | ❌ **无端点级权限码** | `backend/ai-agent-service/app/api/chat.py`：注释逐字「其余一律视为**商户员工**并保留原角色码（供 `Tool.allowed_roles` / `required_permissions` 判断）」；全文**无**端点级权限码注解 |
| **角色层** | 「其余一律视为商户员工」（按 `users.role`，排除 `customer`/`agent`） | `backend/ai-agent-service/app/api/chat.py`；`backend/admin-api/src/main/java/com/migao/admin/security/ServiceTokenFilter.java` 的 C 端角色注释逐字「与商户员工门禁 `role NOT IN ('customer','agent')` 同口径」 |
| **工具层** | `Tool.allowed_roles` / `Tool.required_permissions`（能调**哪些工具**） | 同上；`docs/wiki/RBAC.md`「工具声明 `required_permissions` 时按权限码放行，`allowed_roles` 只做粗筛与路由」 |
| **小程序端 UI** | ❌ 零门（`pages/chat` 无 permission 检查） | §1（`git grep -n "permission" … pages/chat/ store/` ⇒ 0 命中） |

⇒ 🔴 **结论：「唤出米宝」这件事在端点上今天没有任何码，所以「其他员工需授权才能唤出」必然要引入一个新码 —— 不存在「复用既有码」的选项。** 具体地：

- **`agent:session` 不能复用**：它的目录语义是「会话监控」（**客服坐席**读码，`AgentSessionController` **类级**码），承载的是**人工接待工位**（`frontend/admin-web/src/config/menu.ts` 的「在线接待」节点 → `/agent-workspace/human-sessions`）。把它当「唤出米宝」的判据 ⇒ **任何有坐席读权的人顺带拿到米宝唤出权**，而**坐席页与米宝页的授权意图不同**（一个是「看客服会话」，一个是「用 AI 助手」）⇒ **两件事共用一个码 = 把两个授权意图焊死**，日后想只放开一个就必须再拆码（**先例：`agent:session` 本身就因为「读写同码」被拆出 `agent:session:manage`**，见 `RegistrationService.defaultPermissions` 的注释逐字「转接/结束发消息此前挂在读码 `agent:session` 上 ⇒ **只看会话的人能替客服转接与发言**」）。
- **`dashboard:view` / `employee:create` 更不能当唤出码**：前者是全租户最普及的码（5 个内置岗位**全部**持有 —— §2.2 矩阵）⇒ 等于「人人可唤」，**正好是本单要改掉的现状**；后者是**管理动作**码，与「使用 AI 助手」无关。
- **⇒ 「复用」在本单的语境里不是一个降本手段，而是一个语义错误。**

#### 3.2.2 新增 `agent:chat` 的完整清单（**五处，缺一处就漂移**）

按本仓既有范式（新增码先例：`V124__backfill_read_permissions.sql` / `V125__backfill_write_permissions.sql` / `V129__backfill_domain_read_permissions.sql`；移除码先例：`agent:quickreply` 整体退役，§1.1 读数⑥）：

| # | 面 | 落法 | 依据 / 范式 |
|---|---|---|---|
| **1** | **权限目录**（Java 种子，唯一真值源） | 在 `RegistrationService.defaultPermissions` 的 `String[][]` 里加一行（码 `agent:chat`） | 目录唯一真值源逐字（`V125` 注释）：「权限目录的**唯一真值源**仍是 `RegistrationService.defaultPermissions`（两处目录的码列必须逐值相等，守卫见 `tests/unit_ci_workflows/test_agent_permission_parity.py` 的判据 9）」 |
| **2** | **回填迁移**（存量租户） | **新建**一条（**不**改已发布的 V124/V125/V129 —— 迁移**只增不改**，`MigrationRunner` 按**文件名**判已应用 ⇒ 往旧文件里加语句会**整份被跳过**且部署显示 success）；范式逐条：`BEGIN/COMMIT` 显式事务 + `WHERE NOT EXISTS` / `ON CONFLICT DO NOTHING` 幂等 + 文末 `DO` 块**终态对账**（不满足即 `RAISE EXCEPTION` 回滚，fail-closed）+ 头部写**回滚 SQL**（登记不落码） | `V129__backfill_domain_read_permissions.sql` 的逐条写作范式；`V125` 的「为什么是新文件」三条理由（① 台账按文件名判 ⇒ 静默失效；② 静态守卫账本 fail-closed；③ `.github/danger_scan.py` 把改迁移判 danger，放行需 owner 评论） |
| **3** | **岗位矩阵**（回填给谁） | 🔴 **必须显式裁定，不能默认**（见 §3.2.3） | `attachDefaultPermissions(tenantId, <role>, List.of(...), permissionByCode)` 五个岗位逐个点名 |
| **4** | **角色回退**（硬编码 `switch`） | 若要给某个岗位回退口径，必须**同批**改 `RoleService.getPermissionCodesForRole` 的 `switch`；⚠️ 该 `switch` **只有 admin/operator/product_manager/knowledge_editor 四个 case**（`finance` / `customer_service` **没有**回退 ⇒ 落 `default` ⇒ 空表）—— 这是**既有事实**（`RoleService` 注释逐字登记），本单须按同一口径处理，**不得**只改种子不改回退（否则「老员工（无权限快照）不能唤、新员工能唤」） | `V129` 的既有教训逐字：「回退路径（无 `role_permissions` 记录）若不跟上，『菜单/Agent 面看得见看不见』会按账号有没有权限快照分叉」 |
| **5** | **前端菜单 / 工具声明** | ⚠️ 本单**不新增菜单节点**（唤出门不是菜单项，它是 `pages/chat` 的访问门）；且**工具层不动**（`agent:chat` 管的是「能不能唤出」，**不是**「能调哪些工具」——后者仍由各工具的 `required_permissions` 管）。⇒ 但**必须在 §3.2.4 写清三层关系**，避免遮蔽 | §3.2.4 |

#### 3.2.3 🔴 回填策略（**必须回答「回填给谁」**）

**先把一个陷阱说清**：`V124`/`V125`/`V129` 的回填范式有一条**共同纪律**（`V129` 头部逐字）：

> 「本迁移授出的码**全部是读码**，且只授给「原本已持管理码」的岗位… ⇒ 这些岗位**本来**就能读那些端点的数据、也**本来**就看得见那些菜单 ⇒ 迁移前后的**可见面逐值相同**」

⇒ **回填的合法理由 = 「该岗位在本单之前就已经在做这件事、只是没有一个码来表达它」**，即**迁移前后行为逐值相同**。用这条尺子量 `agent:chat`：

| 候选回填对象 | 本单之前它能不能唤米宝？ | 按「行为逐值相同」尺子 | 建议 |
|---|---|---|---|
| **`admin` 角色** | ✅ 能（人人可唤） | ✅ **合法回填** | **必回填** —— 且它本来就 `["*"]`，回填只是让「新老租户逐值一致」（`V129` 同款理由：「`admin` 恒为 `["*"]`，一并补 `role_permissions` 行以保持『新老租户逐值一致』」） |
| **其他 4 个内置岗位**（客服/运营/销售/财务） | ✅ **都能**（人人可唤） | ⚠️ **尺子说「都合法」，但这会让本单的授权门形同虚设** | 🔴 **不建议回填** —— 本单的产品意图（裁定⓪）就是**收窄**「人人可唤」；若把 5 个岗位全回填，则**改动上线当天零行为变化**，等于没做。⇒ **只回填 `admin`，其余岗位**有意不回填**（= 管理员显式授权的动作），并在迁移头部**逐字登记「这是有意收窄，不是漏授」** |
| **存量「自定义岗位」** | ✅ 能 | ⚠️ 同上 | 不回填（同理由） |

🔴 **这里有一个必须由用户确认的取舍**（登记在 §12 待裁定-0）：
**「只回填 `admin`」意味着上线当天，除管理员外所有员工的米宝入口从「可唤」变成「需授权」** —— 对**客服**（其岗位职责就是天天用米宝查单/查售后）尤其明显。两条路：
- **(i) 严格收窄**：只回填 `admin`。**符合裁定⓪的字面**（「其他员工需要授权才能唤出」），但上线是一次**行为回退面较大的变更**，需配套**告知 + 批量授权工具**（或在员工管理里支持按岗位批量勾选）。
- **(ii) 宽回填 + 后续收窄**：把 `agent:chat` 回填给**原本就持 `agent:session` 的岗位**（= 客服 + 运营），理由是「这两类岗位今天就是米宝的高频使用者」。**但**这与裁定⓪「其他员工需要授权」**张力明显**，且**开了「按现状回填」的口子就再也收不回来**（同 `V129` 的「只收窄不放宽」纪律）。
- **本文推荐 (i) 严格收窄**，并把「上线告知 + 批量授权」列为**落码必做的配套**（否则会变成「功能上线了但客服当天干不了活」的事故）。**理由**：裁定⓪是**用户逐字的产品意图**，而 (ii) 是用迁移把意图改掉 —— 那是**改判**，不该由迁移来做。

#### 3.2.4 🔴 三层门禁的关系（端点码 × 角色码 × 工具码）—— **叠加，不是任一**

| 层 | 判什么 | 载体 | 与其它层的关系 |
|---|---|---|---|
| **L1 唤出门（本单新增）** | **能不能唤出米宝**（进不进得了 `pages/chat` / 发不发得出第一条消息） | **`agent:chat`**（端点级 `@RequirePermission("agent:chat")`，加在「创建米宝会话 / 发消息」的入口端点上） | **独立一层**，与 L3 **不互相替代** |
| **L2 角色层** | **是不是商户员工**（排除 C 端 `customer`/`agent`） | `users.role`（`ServiceTokenFilter` / ai-agent 的「其余一律视为商户员工」） | **前置条件**：非商户员工直接拒（L1 不参与判定）；商户员工**才**进 L1 |
| **L3 工具层** | **能调哪些工具**（查订单/建单/退款…） | 各 `Tool.required_permissions` / `allowed_roles` | **在下游、独立生效**：过了 L1 只代表「能对话」，**不代表能调任何工具** —— 调工具仍逐工具判码 |

**判定式（**只有一份实现，在服务端**）**：
```
可唤出米宝  ⟺  L2（是商户员工） ∧ L1（ 三码全持 ∨ 持 agent:chat ∨ 持 "*" ）
能调某工具  ⟺  可唤出米宝 ∧ L3（持该工具的 required_permissions）
```
- 🔴 **为什么不是「两个门任一即可」**：L1 的括号里**确实是一条 OR**（三项各有明确语义：管理员默认 / 显式授权 / 平台旁路），但 **L1 与 L3 之间是**叠加**（AND）** —— 过了唤出门**绝不**意味着拿到了任何工具权限。把两者写成 OR 就是**越权**（唤出即全工具）。
- ⚠️ **与 R5（旁路身份）的边界**：`super_admin` / `service` 走 `PermissionInterceptor.hasBypassRole` 直通 ⇒ **自动满足 L1**。⇒ L1 **不得**被当作「更安全的门」，真正的数据面保护仍靠 L3 + 租户隔离。

**未授权时用户看到什么（逐条，对应 §8.1）**：
| 情形 | 用户看到 |
|---|---|
| 非商户员工（L2 不过） | 登录阶段就被拒（不涉及本单） |
| 商户员工但 L1 不过 | **入口可见**，点击 ⇒ 明确「**需要管理员授权**」+ 可行动引导（去哪授权、找谁）—— **不是静默隐藏、不是 403 白屏**（§8.1 / §8.5 G2~G4） |
| L1 过但 L3 不过（如缺 `order:refund`） | **正常进米宝**；问到没有权限的事时，由**工具层**按既有口径回「能力未开通 + 开通路径」（既有行为，本单不改） |

### 3.3 「持三码」到「管理员」的判定函数（逐条）

| 输入 | 判定 | 备注 |
|---|---|---|
| `permissions` 含 `"*"` | **真** | `role='admin'` / `super_admin` / `service` 自动落入（**无需特例分支**，§2.3） |
| `permissions ⊇ ADMIN_PERMISSION_CODES`（**全集**，不是任一） | **真** | 裁定④逐字是「+」= 同时具备 |
| 其余 | **假** | 含「缺一个」的情形 |

**⚠️ 与 `service` 令牌的交互（实测风险，必须先处置）**：`PermissionInterceptor.hasBypassRole` 放行 `super_admin` 与 `service`。而 issue #4105 已把 `service` 的语义收窄（逐字：「`service` 令牌在带 `X-User-Id` 且该用户为同租户商户员工时**不再整体放行**，转而按真实角色细粒度强控」）。⇒ **判定函数必须走「有效主体」（`X-User-Id` 命中则为该商户员工，否则才是内部服务）**，不得直接读 JWT 的 `roles`/`permissions` claim 就下结论。这条同样适用于 §5 的登录链路（**登录端点本身不该由 `service` 令牌可达**）。

---

## 4. 登录链路（小程序端）

### 4.1 时序（含 0 / 1 / N 三分支）

```
[小程序]                          [admin-api]                      [微信平台]
   │                                   │                               │
   │ 1. Taro.login() ────────────────► │                               │
   │    ← js_code                        │                               │
   │                                   │                               │
   │ 2. <button open-type="getPhoneNumber"> ──────────────────────────►│
   │    ← { code }（动态令牌，非手机号明文）                              │
   │                                   │                               │
   │ 3. POST /api/auth/bmini/wechat-login { loginCode, phoneCode }      │
   │    ──────────────────────────────►│                               │
   │                                   │ 4. code2Session(loginCode) ──►│
   │                                   │    ← { openid, session_key }   │
   │                                   │ 5. getPhoneNumber(phoneCode) ►│
   │                                   │    ← { phoneNumber }（解密后） │
   │                                   │                               │
   │                                   │ 6. 🔴 LoginFailureGuard 前置闸  │
   │                                   │    keyOf("bmini-wechat", <盲绑键>)│
   │                                   │                               │
   │                                   │ 7. 全局按手机号查候选账号       │
   │                                   │    （跨租户 ⇒ 见 §5 的安全约束） │
   │                                   │                               │
   │   8a. 0 命中 / N 命中 / 非管理员 ⇒ 统一失败（§4.3 对照表）           │
   │   8b. 1 命中且是管理员：                                            │
   │       ← 签发与 #5485 同一套 JWT（RS256，claims 同构）               │
   │       ← （若裁定「绑 openid」⇒ 附带绑定，§12 待裁定-1）              │
   │                                   │                               │
   │ 9. 存 TOKEN / USER / TENANT_ID（复用既有 STORAGE_KEYS）             │
```

**逐条口径**：

| # | 口径 | 依据 / 约束 |
|---|---|---|
| 1 | 新增端点 `POST /api/auth/bmini/wechat-login`，**不得**复活已废弃的 `POST /api/auth/bmini/login` | 后者是元守卫判红的字面量之一（`frontend/bmini-app/tests/bmini-login-retired.test.ts` 的 `hits(/\/api\/auth\/bmini\/login/)`）；**本单改造守卫时也只放行新路径**（§7） |
| 2 | 前端**只**传 `loginCode` + `phoneCode`，**不传 `tenantId`** | 与 #5485 同纪律（`frontend/bmini-app/src/utils/auth.ts` 注释逐字：「租户**只**由标识里的企业编码解析，前端**不解析租户、不传 tenantId**（否则『任意数字即可切租户』）」）⇒ 本单的租户由**服务端查库结果**决定，同样**不由前端传** |
| 3 | 手机号明文**只在服务端内存**中存在；**不得**落日志、**不得**回前端 | 反枚举 + PII |
| 4 | 签发**同一套**凭据：`accessToken` + `user`（形状 ≡ `types` 的 `User`），claims 同构（RS256 / `tenant_id` / `roles` / `permissions`） | 🔴 **不新造会话机制**（issue #5642 边界逐字：「不新造会话 / 权限结构（复用既有 JWT + RBAC）」） |
| 5 | 成功路径**必须** `LoginFailureGuard.clear(key)` | 否则「成功前打错几次」累积到锁定（`LoginFailureGuard.clear` 注释逐字） |
| 6 | 计数键的 scope 用**新值**（如 `bmini-wechat`），**不新增类** | 复用 `LoginFailureGuard.keyOf(scope, ...)`；与既有 `employee` / `worker` 两个 scope 并存 |

### 4.2 🔴 计数键怎么构造（**本单最容易做错的一处**）

`LoginFailureGuard` 的设计约束（逐字引用其 Javadoc）：
> 「**计的是「被尝试的标识」，不是「已匹配到的账号」**：计数键由调用方用**规整后的输入**构造…**与账号是否存在无关** ⇒「本来就不存在的用户名」同样会被计数与锁定 ⇒ 锁定文案**不泄露账号是否存在**…**调用方不得改成「查到用户后才计数」**。」

⇒ 本链路的「被尝试的标识」= **手机号本身**（它是唯一的暴力猜测维度）。因此：
- 键 = `keyOf("bmini-wechat", E164(phoneNumber))` —— **在查库之前**计数；
- 🔴 **不得**用 `openid` 或 `phoneCode` 当键（它们是**一次性**的，换个 code 就能绕过锁定 ⇒ 防爆破失效）；
- ⚠️ **但「用手机号当键」本身把手机号写进了 Redis key** ⇒ 需确认 Redis 的访问面与 TTL（`WINDOW = 5min`）；若判定不可接受，改用 `HMAC-SHA256(serverPepper, E164(phone))` 前 16 字节 —— **仍保持「同号同键」语义**，不削弱防爆破。**推荐后者**（零额外成本，去掉一处 PII 落点）。
- **IP / 设备维度**：本单**不新增**（复用既有单维度口径，避免与 #5531 的两处口径分叉）。残余风险登记在 §5.7 R4。

### 4.3 🔴 0 / 1 / N / 非管理员 —— 四情形响应对照表（**反枚举的核心**）

> ⚠️ **本节已按 §4.4.1 的实测修订过一次**（原稿要求「五合一」全合并，与**既有的 `smsLogin` 实现冲突**）。以下表为准；修订理由见本节末「§4.3 修订说明」。

**总原则（修订后）**：**凡「不能签发凭据」的路径，一律 `401 + AUTH_FAILED`**（同状态码 + 同 `error.code`）。**文案是否逐字相同，分两组**（见下），因为既有实现**已经有意**区分了其中一格 —— 而本单**要么沿用、要么显式改判**，不能默默不一致。

| # | 情形 | HTTP | `error.code` | 文案（**逐字**） | 是否与其它情形合并 | 备注 |
|---|---|---|---|---|---|---|
| S1 | 手机号**未命中任何**租户账号 | `401` | `AUTH_FAILED` | 「手机号授权未通过，请用账号密码登录」 | **A 组**（`smsLogin` 逐字：「该手机号未注册」⇒ 语义同格，文案按本渠道重写） | 与 #5485 的 `BusinessException.authFailed(...)` 同源 |
| S2 | 命中 **1** 个企业，但该手机号**不是管理员**（在册员工 / 管理员以外岗位 / 被停用） | `401` | `AUTH_FAILED` | **逐字同 S1** | **A 组** | 🔴 任务要求的「反枚举」正落在这一格。⚠️ **但 `smsLogin` 在格上「有意不同」**：它逐字回「该账号非管理员，请使用员工登录入口（用户名@企业编码 + 密码）」，并在源码注释里**显式论证**了为什么可以不同（见下） |
| S3 | 命中 **N≥2** 个企业 | `401` | `AUTH_FAILED` | 「该手机号关联多个企业账号，请用账号密码登录」 | 🔴 **单独一格（B 组）—— 与 S1 不同** | ⚠️ **这是本次修订的关键**：`smsLogin` 既有实现**就**单独回「该手机号关联多个租户账号，请通过对应租户入口登录或指定租户后重试」⇒ **它允许泄露「有多个」这一位**。原稿把 S3 并入 S1 是**比既有实现更严**的要求 ⇒ 必须显式选择（§4.4.4 路 X / Y / Z） |
| S4 | 手机号命中 1 个企业且**是**管理员，但该账号被停用 / 租户被停用 | `401` | `AUTH_FAILED` | **逐字同 S1** | **A 组** | fail-closed |
| S5 | 命中 1 个企业且是管理员 ⇒ **成功** | `200` | — | — | — | 唯一非 401 出口 |
| S6 | 达锁定阈值（`isLocked`） | `401` | `AUTH_FAILED` | 「尝试次数过多，请 5 分钟后再试」（`LoginFailureGuard.LOCKED_MESSAGE` **逐字复用**） | 单独一格（**允许**不同） | 依据：键是「被尝试的标识」⇒ 任何标识（含不存在的）都会被同样锁定 ⇒ **不泄露账号是否存在**，同时给真人可行动出口（`LoginFailureGuard` Javadoc 逐字） |
| S7 | Redis 不可用 | `503` | `AUTH_UNAVAILABLE` | 「登录防护不可用（Redis 异常），已按 fail-closed 拒绝」（`LoginFailureGuard.unavailable` **逐字复用**） | 单独一格 | **fail-closed**，不许「异常 ⇒ 放行」；须打 `UNAVAILABLE_KEYWORD` + 计 `UNAVAILABLE_METRIC` |
| S8 | `phoneCode` 无效 / 过期 / 已被消费 | `401` | `AUTH_FAILED` | **逐字同 S1** | **同上** | 防「用 code 有效性当探测位」 |
| S9 | 请求参数缺失 / 形态错 | `400` | `INVALID_ARGUMENT`（沿用既有） | 参数类文案 | 单独（**与手机号的存在性无关**，不构成枚举位） | |

**分组（修订后）**：

| 组 | 成员 | 规则 | 依据 |
|---|---|---|---|
| **A 组（逐字合并）** | S1, S2, S4, S8 | **同 `401` + 同 `AUTH_FAILED` + 同文案** | 「账号/手机号是否存在」不得成为探测位 —— 任务要求的反枚举正落在此 |
| **B 组（单独文案，允许不同）** | S3（多企业命中） | `401` + `AUTH_FAILED`，但文案**明说「关联多个企业」** | 🔴 **沿用既有 `smsLogin` 的口径**（它本就单独回这一格）。**代价**：泄露「该手机号在 ≥2 家注册企业里存在」这一位 ⇒ **必须由用户确认接受**（§4.4.4 路 X 就是接受它但**不列企业名**） |
| **C 组（与存在性无关，允许不同）** | S6 锁定, S7 基础设施, S9 参数 | 各自文案 | `LoginFailureGuard` 的键语义（「被尝试的标识」而非「已存在的账号」）⇒ 对任意手机号一视同仁 ⇒ 不构成枚举位（其 Javadoc 逐字论证） |

#### §4.3 修订说明（**与原稿的差异，逐条登记**）

| # | 原稿 | 修订后 | 为什么改 |
|---|---|---|---|
| 1 | S3 并入 S1（**五合一**） | S3 **单独一格**（B 组） | 既有 `smsLogin` **已经**单独回这一格（逐字「该手机号关联多个租户账号…」）⇒ 原稿是**比现状更严**的新要求，而本单没有理由无端收紧到那个程度；**若真要收紧，那是改判既有实现**，需用户明示 |
| 2 | S2 并入 S1 | **保留** S2 并入 S1（A 组） | ✅ 但**与 `smsLogin` 有意不同** —— 它在 S2 格上回「该账号非管理员，请使用员工登录入口」，并在源码注释里逐字论证：「这里与员工登录的反枚举口径**有意不同**：员工登录失败不区分病因（防探测账号是否存在），而「**你是员工**」这件事在本路径上已由「手机号在这家企业里命中非 admin 账号」确定。」⇒ 🔴 **本单必须二选一**：① 沿用（= 承认「该手机号是某企业的非管理员员工」可被探测）；② 收紧成 A 组（= 改判既有实现）。**登记为 U12** |
| 3 | — | 新增 B 组 / C 组的显式分组 | 原稿只有「合并 / 可区分」两句话，不足以指导实现 |

🔴 **S3 / S2 两个格子上的「沿用 vs 收紧」是本单的反枚举核心决策**，且**二者与裁定⑤强耦合**（列企业名 = 泄露最多；只说「有多个」 = 泄露中间；全合并 = 泄露最少但用户拿不到任何引导）。**完整权衡见 §4.4.4 与 §5.6。**

---

### 4.4 🔴 复用 `UserMapper.selectActiveUsersByPhoneIgnoreTenant` 的论证（**必须显式回答**）

**事实**（§1.1 读数④）：该方法**仍在主线上**（`backend/admin-api/src/main/java/com/migao/admin/mapper/UserMapper.java` 的 `selectActiveUsersByPhoneIgnoreTenant`），而 `AuthService.bminiLogin` 的 Javadoc **逐字点名它退役**，理由逐字：

> 「它按手机号**跨租户**匹配员工，正是本次要消灭的「**账号定位不落在企业内**」形态。」

⇒ **本单的「手机号全局匹配」在代码面上等于复用这个被点名的方法。** —— **但它并没有退役，而且它不是「没有护栏的危险工具」**。实测（本次取证，**这改变了本节的结论**）：

### 4.4.1 🔴 实测：`AuthService.smsLogin` **已经实现了「跨租户手机号 + 仅管理员 + 多租户 fail-closed」**

`backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java` 的 `smsLogin` 逐条（本次实读）：

| 步 | 行为 | 逐字 / 语义 |
|---|---|---|
| 1 | **跨租户**查：`userMapper.selectActiveUsersByPhoneIgnoreTenant(phone)` | 注释逐字：「根据手机号查找租户用户（**跨租户查询**，使用 `@InterceptorIgnore` 绕过多租户拦截器）」 |
| 2 | 空 ⇒ `authFailed` | 文案「该手机号未注册」 |
| 3 | **`users.size() == 1`** ⇒ 直接用；**`size() > 1` 且 `tenantId == null`** ⇒ **拒绝**（**fail-closed**） | 逐字：「`该手机号关联多个租户账号，请通过对应租户入口登录或指定租户后重试`」；注释逐字「同手机号多租户歧义处理（审计 07 P1-2：**禁止静默 LIMIT 1 落错租户**）」 |
| 4 | `size() > 1` 且**传了** `tenantId` ⇒ 在该租户内筛选；筛不到 ⇒ 拒绝 | 逐字「`该手机号在该租户下未注册`」 |
| 5 | **角色门禁（#5485 不变式 I2）**：只对 `platform_admins`（平台超管）与 `roles ∋ 'admin'` 签发；**其余角色 401 + 明确引导** | 逐字：「`该账号非管理员，请使用员工登录入口（用户名@企业编码 + 密码）`」 |
| 6 | 之后设 `TenantContext`、取权限、签发既有 JWT | ✅ **与 #5485 同一套凭据** |

⇒ 🔴 **本单要设计的东西，在短信登录这条路上已经跑着、已经有判据、已经过了评审。** 这不是「我们打算做一件 #5485 禁止的事」，而是「**把一条已存在的、仅管理员的跨租户手机号登录路径，从短信渠道复用到微信渠道**」。

### 4.4.2 它已经被**类级元守卫 + 豁免台账**钉住了（**不需要本单再新造**）

| 件 | 内容 |
|---|---|
| **豁免台账** | `tests/unit_ci_workflows/tenant_ignore_ledger.json`（issue #5485）：`@InterceptorIgnore(tenantLine = "true")` + 查 `users` 且 SQL **无** `tenant_id` 谓词的方法 ⇒ **必须登记**；头部逐字：「**豁免只许缩短**：销账（补上 tenant_id 或删方法）后必须同批删条目，**新增豁免必须先证明补偿控制**」 |
| **台账里已有本方法的条目** | `method` = `selectActiveUsersByPhoneIgnoreTenant`；`reason` 逐字：「短信登录的服务端查找键是**手机号**（登录标识，天然跨租户）：同号可能存在于多个租户，加 tenant_id 谓词会让多租户下的管理员查不到人。」 |
| **补偿控制（逐字，三条）** | ① 命中多个租户且未指定 `tenantId` ⇒ **拒绝登录**（审计 07 P1-2，禁止静默 `LIMIT 1` 落错租户）；② **role 门禁（#5485 不变式 I2）**：只对 `users.role='admin'` 签发，非管理员一律 401 并引导员工登录入口；③ 平台超管路径走 `platform_admins` 表，不经本查询 |
| **判据源（类级元守卫）** | `tests/unit_ci_workflows/test_tenant_scoped_user_queries.py`（注释头 `# case_ids: AU-002, AU-008`）——三条判据：**① 命中集 ⊆ 台账（未登记 ⇒ 红）**；**② 台账条数 == 现取命中条数（只许缩短；销账后不删条目 ⇒ 红；新增豁免 ⇒ 红）**；**③ 台账条目必须仍活着**（对应方法还在源码里，否则是陈旧豁免）。含**注入式自证**（临时加一个无租户谓词的同形方法 ⇒ 必红） |
| **业务真值溯源** | `.github/cases/auth.yml` 的 `AU-002`（「跨租户隔离：同名员工分属 A/B，凭据只解析到自己企业」，`truths_ref: auth.tenant-local-identity`） |

⇒ 🔴 **本单的处置因此变成「复用既有护栏 + 只补差量」，而不是「新造一套跨租户查询机制」**：

| 项 | 结论 |
|---|---|
| **能不能复用 `selectActiveUsersByPhoneIgnoreTenant`？** | ✅ **能，且应当复用** —— 它就是「跨租户手机号查账号」的既有、已登记、已有补偿控制的入口。**本单不新增第二个跨租户查询**（新增反而会**多一条豁免台账条目**，而台账**只许缩短**、新增须先证明补偿控制 ⇒ 那是**无谓的治理成本**） |
| **台账条目要不要改？** | ⚠️ **要**（但只是**扩充 `reason` / `compensating_control` 的文字**，说明它现在**同时**服务短信登录与微信登录两条渠道）。⚠️ **不得**新增条目；⚠️ 若两条渠道的补偿控制**逐条相同**（本次核对：确实是 —— 都是「多租户拒绝 + 仅 admin + 既有 JWT」）⇒ 文字扩充即可，**无需**第二条 |
| **`AuthService.bminiLogin` 里那句「正是本次要消灭的形态」怎么办？** | 🔴 **它是过期的注释/文档**，必须**同批更正**（否则下一个人读它会把本单读成违规）。**建议**：把该 Javadoc 的措辞从「这条路径随之退场」改为「**微信渠道的自动建号/普通员工免密已退场；跨租户手机号查询本身按 I2 口径收窄为仅管理员**」，并**指向**本设计单。⚠️ **注意 `@Deprecated` 与恒抛行为不要一起改**（`/api/auth/bmini/login` 的退役是**另一件事**，本单不动它 —— §7.1） |

### 4.4.3 与 `smsLogin` 的**逐条差异**（本单要设计的**只有**这些）

| 维度 | `smsLogin`（既有） | 本单（微信登录） | 是否可复用 |
|---|---|---|---|
| 身份证明 | 手机号 + **短信验证码**（`SmsService`，含 `MAX_VERIFY_FAILS`） | 手机号（微信快验证组件的 `phoneCode`） | ⚠️ **不同**：微信侧无短信验证码 ⇒ **持有者证明强度不同**（§5.1）。**这是本单唯一真正的安全差量** |
| 跨租户查询 | `selectActiveUsersByPhoneIgnoreTenant` | **同一方法** | ✅ 复用 |
| 多租户歧义 | 拒绝（未指定租户时） | **裁定⑤ 要求「让用户选企业」** | 🔴 **冲突**，见 §4.4.4 |
| 管理员门禁 | `roles ∋ 'admin'`（**按角色码**） | **按权限码**（裁定③） | ⚠️ **口径升级**：本单用权限码，比既有更细（§2） |
| 凭据 | 既有 JWT | **同一套** | ✅ 复用 |
| 限频 | `SmsService` + `LoginFailureGuard`（#5531） | **`LoginFailureGuard`**（同族，新 scope） | ✅ 复用（§5.4） |

🔴 **注意上面第 4 行：`smsLogin` 的管理员门禁走的是 `roles ∋ 'admin'`（角色码），而裁定③要求本单走权限码。** ⇒ **本单比既有实现更严**（权限码集合可被自定义岗位/快照满足，而 `role='admin'` 只有一个值 —— 见 §2.2）。**这不是回退，是收窄/精细化。** 但同时暴露一个**待决问题**：**短信登录要不要同批改成权限码口径？**（否则同一句「管理员」在两条渠道上是两个口径 —— 正是 §2.3 要防的「两套真值」）。**登记为 U11。**

### 4.4.4 🔴 与裁定⑤ 的正面冲突（**本单最重要的一个「不可兼得」**）

`smsLogin` 的既有行为：**多租户命中且未指定租户 ⇒ 拒绝**，逐字文案「该手机号关联多个租户账号，**请通过对应租户入口登录或指定租户后重试**」。
裁定⑤ 的要求：**多企业命中 ⇒ 让用户选企业**。

⇒ 🔴 **二者互斥**：
- 既有实现**不告诉用户有哪几个租户**（只说「有多个」+ 让用户「通过对应租户入口」）；
- 裁定⑤ 要**列出企业让用户选** ⇒ 必然要把**企业名**给到操作者；
- 而**「有没有多个」这个位本身**就已经是 `smsLogin` 现在**允许**泄露的（它明确说「关联多个租户账号」）—— 这与 §4.3 我原先写的「五合一」**不一致**（§4.3 曾把 S3 要求与 S1 合并 ⇒ 与既有实现冲突）。

**⇒ 必须重新裁定 §4.3 的口径（见 §4.3 的修订说明）。** 三条路：
| 路 | 内容 | 与既有实现 | 与裁定⑤ |
|---|---|---|---|
| **X（= 既有 `smsLogin` 口径）** | 多租户 ⇒ 拒绝，文案**只说「有多个」+ 引导用账号密码**（**不列企业名**） | ✅ 逐字一致 | ❌ **未实现裁定⑤的「让用户选」** |
| **Y** | 多租户 ⇒ **先证明手机号持有者**（实时验证组件 / 短信 OTP），证明后**列出企业名让选** | ⚠️ 比既有**更严**（既有不要求持有者证明就直接说「有多个」） | ✅ 实现了裁定⑤ |
| **Z** | 多租户 ⇒ 直接列出企业名（不额外证明） | ⚠️ 比既有**更宽**（既有多说一个位，Z 把名字也给了） | ✅ 字面实现裁定⑤，❌ **信息泄露风险最大** |

⇒ **本文推荐 X → 若非要多企业选择则必须走 Y**（与 §5.6 的路 A / 路 B **完全同构** —— §5.6 的路 A 就是 X，路 B 就是 Y）。**Z 明确不可取。**
⇒ **且注意**：无论选哪条，**`selectActiveUsersByPhoneIgnoreTenant` 都不需要改**（它是候选集查询，三条路都用它）—— **这就是「复用 + 只补差量」的具体含义**。

### 4.5 🔴 落码前置：新端点必须进 `SecurityConfig` 的 `permitAll`

实测 `backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java` 的 `permitAll` **逐条列了**认证入口（含 `"/api/auth/employee/login"`、`"/api/auth/bmini/login"`）。
⇒ 新增的 `/api/auth/bmini/wechat-login` **若不加进该列表**，请求会在 **Spring Security 层**被拦（**不是**业务 401），表现为「端点写了、单测也过、前端永远 401」——

> 🔴 这是本仓多次登记过的「**绿了但没跑**」形态：**本地单测直调 service 层全绿，而真实入口在最外层就被挡掉**。

⇒ **落码必做**：① 加进 `permitAll`；② 落一条判据（§9.2 N9）断言「该路径在 `permitAll` 里」——**否则没人会因此变红**。⚠️ 该判据必须是**静态读 `SecurityConfig`** 或**真实 HTTP 打端点**，**不能**是「直调 service 断言成功」（那是空跑）。

---

## 5. 🔴 裁定⑤ 的安全论证（**手机号全局匹配 + 多企业选择**）

> 本节的结论是：**裁定⑤ 在「微信 `getPhoneNumber` 不证明手机号持有者」这一实测事实下不成立**；本节给出**证据**与**两条可成立的路**。

### 5.1 微信 `getPhoneNumber` 的语义（**核实，非凭印象**）

**来源**：微信官方文档《手机号快速验证组件》
<https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/getPhoneNumber.html>
（同页亦有「手机号实时验证组件」对照：<https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/getRealtimePhoneNumber.html>；
历史版组件：<https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/deprecatedGetPhoneNumber.html>）

**逐字引用（2026-09-26 实取）**：

> 「该能力旨在帮助开发者向用户发起手机号申请，并且**必须经过用户同意后**，开发者才可获得**由平台验证后的手机号**，进而为用户提供相应服务。」

> 「手机号**快速**验证组件，平台会对号码进行验证，但**不保证是实时验证**；手机号**实时**验证组件，在**每次请求时**，平台均会对用户选择的手机号进行**实时验证**。」

> 「该能力使用时，**用户可选择绑定号码，或自主添加号码**。平台会基于中国三大运营商提供的短信等底层能力对号码进行验证，但**不保证是实时验证**；请开发者根据业务场景需要自行判断并选择是否使用，**必要时可考虑增加其他安全验证手段**。」

> 「自2023年8月28日起，手机号快速验证组件将需要付费使用。标准单价为：**每次组件调用成功，收费 0.03 元**。」

**语义解读（逐条，分清「证实了什么」与「没证实什么」）**：

| 断言 | 是否被官方语义支持 | 依据 |
|---|---|---|
| 手机号**真实存在**（三大运营商底层验证） | ✅ | 「基于中国三大运营商提供的短信等底层能力对号码进行验证」 |
| 用户**同意**了本次申请 | ✅ | 「必须经过用户同意后」 |
| 该手机号**此刻由操作者本人持有 / 控制** | ❌ **未被保证** | ① 组件明确「**不保证是实时验证**」；② 明确「用户可选择绑定号码，**或自主添加号码**」；③ 官方主动建议「**必要时可考虑增加其他安全验证手段**」——若该组件已证明持有者，这句建议无意义 |
| 该手机号**当次**由操作者控制 | ⚠️ **条件成立**：改用「手机号**实时**验证组件」时 | 「在每次请求时，平台均会对用户选择的手机号进行**实时验证**」 |

⇒ 🔴 **结论：快 `getPhoneNumber` 不构成「手机号持有者已验证」，它构成「一个真实存在且用户已同意提供的手机号」。**
⇒ 因而：**把「该手机号所属企业列表」展示给操作者，是信息泄露**（操作者可能只是**自主添加**了一个不属于自己的号码）。

**残余不确定度（照实登记，未核实）**：用户在「自主添加号码」流程里是否**必须**通过一次短信验证码（若必须，则「自主添加」也只证明「可收该号短信」⇒ 仍是**持有者证明**，§5.1 的结论要**弱化**为「快验证组件的**返回值**不保证实时，但添加流程可能已含持有者校验」）。**本次未取证**（微信文档未写该流程细节；需真机实测或查阅「手机号快速验证组件常见问题」）。
🔴 **这一条是本单的「关键未知」**：它单独决定 §5.6 走「路 A」还是「路 B」。登记为**未核实项 U1**（§10），并由 §5.6 给出**不依赖 U1** 的兜底。

### 5.2 与 #5485 不变式 I1 / I3 的关系

**#5485 的不变式（本文按 issue #5642 正文的转述引用，并标注来源）**：
- **I1** —— 租户内唯一：账号匹配**只在租户内**做；
- **I3** —— **绝不跨租户兜底**：租户未确定或匹配到多租户 ⇒ **fail-closed**。

> ⚠️ **来源标注**：I1 / I3 的**编号与逐字**来自 **issue #5642 正文**（「#5485 不变式 I1 / I3 逐字保留」「① 租户内唯一 ② 绝不跨租户兜底」）。本文**未**回溯 #5485 的原始正文逐字核对编号 ⇒ **标为「据 #5642 正文转述，待核」**（任务要求：不把推断写成事实）。

**逐一论证**：

#### 5.2.1 🔴 先纠正一个错读：**「跨租户查库」在本仓是**被允许的既有形态**，不是 I1 的禁区**

原稿把 I1 读成「跨租户查库违反 I1 的字面」——**这个读法被实测证伪**（§4.4.1）：

- **`smsLogin` 就在跨租户查库**（`selectActiveUsersByPhoneIgnoreTenant`），而它**没有被 #5485 退役**，反而被**登记进豁免台账**、并**写明了补偿控制**（台账 `_why_exemptions_exist` 逐字：「少数查询**必须**跨租户（**登录标识本身就是租户外的键**）；给它们硬加 tenant_id 会让多租户场景下查不到人。豁免的代价是必须写清「为什么串号不可能发生」」）。
- **类级元守卫 `test_tenant_scoped_user_queries.py` 正是在管这件事**：跨租户查询**允许**，但**必须登记 + 必须写清补偿控制 + 台账只许缩短**。

⇒ 🔴 **I1 的正确读法**：I1 管的是「**凭据解析出的身份落在哪个租户**」，**不是**「服务端能不能按手机号查库」。
- `AU-002` 逐字印证：判据是「**凭据**只解析到自己企业」+「**绝不跨租户兜底**：解析到 A 时**一次都不**用 B 的 `tenantId` 查用户」—— **讲的是签发与查询路径，不是「禁止全局查」**。
- ⇒ **本单的「手机号全局匹配」在 I1 下是合规的**，前提是它**沿用既有的补偿控制**（多租户 fail-closed + 仅管理员签发）而不是自己另起一套。

#### 5.2.2 #5485 的不变式全貌（**本次拿到了 I2 的逐字**）

| 不变式 | 内容 | 来源（**本次实取**） |
|---|---|---|
| **I1** | **租户内唯一**：凭据只解析到自己企业；**绝不跨租户兜底** | `AU-002` 的 `data_checks` 逐字 + `truths_ref: auth.tenant-local-identity`（本文原按 #5642 正文转述，**现已有逐字出处**） |
| **I2** | **短信仅管理员**：短信登录只对 `platform_admins`（`super_admin`）与 `users.role='admin'` 签发；其余角色 401 + 引导员工登录入口 | `AuthService.smsLogin` 注释逐字「角色门禁（issue #5485 **不变式 I2**）」；`SmsLoginRoleGateTest`（注释头「短信登录的**角色门禁**测试（issue #5485 不变式 I2）」）；`.github/templates/auth-sms.yml` 的 `[auth.sms-admin-only]` |
| **I3** | **绝不跨租户兜底**（多租户命中且未指定 ⇒ 拒绝，**禁止静默 `LIMIT 1`**） | 台账 `compensating_control` 逐字「① 命中多个租户且未指定 tenantId ⇒ **拒绝登录**（审计 07 P1-2，**禁止静默 LIMIT 1 落错租户**）」 |

> ⚠️ **编号仍有一处未核**：issue #5642 正文把「① 租户内唯一 ② 绝不跨租户兜底」称作 **I1 / I3**（跳过了 I2），而 I2 实测是「短信仅管理员」—— **与正文的隐含编号不矛盾但未逐字核对** ⇒ 仍标 **U4（待核）**，但**已不再是「全靠转述」**（I1/I2/I3 三条现均有本仓逐字出处）。

**逐一论证（修订后）**：

| 问题 | 结论 | 论证 |
|---|---|---|
| 「**服务端跨租户按手机号查账号**」违反 I1 吗？ | ✅ **不违反**（**已实测证伪原稿的「字面违反」读法**） | §5.2.1：跨租户查库是**被允许且被管着的**既有形态（豁免台账 + 补偿控制 + 类级元守卫）。I1 管的是**签发**，不是**查询** |
| 「**让用户选企业**」违反 I1 / I3 吗？ | ⚠️ **不违反 I1，但违反 I3 的字面** | 「选 = 用户自己挑 ≠ 系统兜底」⇒ 不违反 I1 的意图；**但** I3 的字面是「多租户命中且未指定 ⇒ **拒绝**」，而「让用户选」是**先不拒绝**。⇒ 要自洽**必须补新不变式**（见下） |
| 需要补新不变式吗？ | ✅ **需要**（但**比原稿少一条**） | 见下 |

**建议新增的不变式（修订后两条，作为本单的护栏，写进 RBAC / 登录真值源）**：

- **I4（可见性门槛）**：跨租户「**可见信息**」的强度**不得超过**持有者证明的强度。具体：**未证明持有该手机号** ⇒ 最多只能得到「**该号关联多个企业**」这**一个位**（= 沿用 `smsLogin` 的既有口径，§4.4.4 路 X）；**要列出企业名让用户选** ⇒ **必须**先有当次持有者证明（实时验证组件 / 短信 OTP，§4.4.4 路 Y）。**禁止**在无证明时列出企业名（路 Z）。
- **I5（签发守卫）**：任何一次签发，`tenant_id` 必须等于**服务端查库得到的那一行账号的 `tenant_id`**；**不存在**「前端传入 / 用户选择 / 默认回退」任一来源的 `tenant_id` 进入签发路径。（把 I1 的**意图**机械化：串号在结构上不可表达。）
  > ⚠️ **注意与既有实现的差异**：`smsLogin` **接受**一个 `tenantId` 入参（用于消歧），但它的用法是「**在候选集里筛**，筛不到就拒绝」—— **不是**「按传入的 tenantId 查库」。⇒ I5 的准确表述是「**传入的 `tenantId` 只能用于筛选服务端已查出的候选集，绝不能作为查询键**」。这两者有本质区别（前者不可能串号，后者可以）。
- ~~I6（选择后重鉴权）~~ ⇒ **并入 I4**（「选择前必须证明」已覆盖「选择后重鉴权」的场景；单列会造成两条互相重叠的不变式）。

⇒ **回答任务的问题「选企业 ≠ 跨租户兜底？还是必须补一条新的不变式？」**：**「选企业」在语义上确实 ≠ 跨租户兜底**（兜底 = 系统替用户挑一个；选择 = 用户自己挑），**但因为 I3 的字面是 fail-closed，所以必须补 I4（可见性门槛）+ I5（签发守卫）才能自洽**。**只靠「≠兜底」这个论证不够** —— 那只是语义辩解，不构成一个可红的判据。
🔴 **且本次实测给出了一个更强的结论**：**I1 从来不禁止跨租户查库**（§5.2.1）⇒ 本单在 I1 上**没有**需要新补的东西；真正需要新补的只有「**可见性随证明强度**」这一条（I4）。

### 5.3 反枚举：不得用任意手机号探出「某手机号是不是某企业管理员」

**威胁模型**：
1. 攻击者持有手机号 `P`（或任意猜测的号段）；
2. 攻击者在小程序里走登录链路，令 `phoneCode` 解出 `P`；
3. 若服务端**区分**了「未命中 / 命中但非管理员 / 命中且是管理员」，攻击者即得到 **`P` 的归属与权限画像**（跨**全部**租户！比单租户探测更严重）；
4. 若服务端还会**列出企业名**（裁定⑤字面），攻击者直接得到 **`P` ↔ 企业**映射表 —— 可批量扫描号段建立「某企业有哪些手机号」的库。

**处置**：**§4.3 的五合一（{S1,S2,S3,S4,S8} ⇒ 同 401 + 同 code + 同文案）就是这条要求的落地**。**关键点**：
- 文案**不得**出现「该手机号不是管理员」「该手机号属于多个企业」「请选择企业」这类**区分性**措辞；
- ⚠️ 但 §4.3 的 S6「尝试次数过多」是**允许**不同的 —— 依据是 `LoginFailureGuard` 的键语义（「被尝试的标识」而非「已存在的账号」），它对**任意**手机号一视同仁 ⇒ **不构成枚举位**。这条**已在原实现里被论证过**，本单**沿用不另立**。

**红证（可执行）**：对 `{未命中, 命中非管理员, 命中多企业, 命中且管理员-但已停用}` 四组输入，断言响应 **逐字节相同**（`status` + `error.code` + `error.message`）；任一组不同 ⇒ 红。**且**必须有一条**正证**（命中且管理员 ⇒ 200）防「全部拒绝」蒙过判据。

### 5.4 限频 / 锁定：**复用 `LoginFailureGuard`，不许新造第二套**（逐条）

| 要求 | 落法 | 依据 |
|---|---|---|
| 复用既有类 | `backend/admin-api/src/main/java/com/migao/admin/security/LoginFailureGuard.java`，**不新增**任何限频类 | issue #5642 安全面 3 逐字：「与既有 `LoginFailureGuard`（#5531：员工侧 `MAX_VERIFY_FAILS`、工人侧防爆破）**同一套**，不许新造第二套」 |
| 阈值 / 窗口 | **沿用常量** `MAX_FAILS = 5` / `WINDOW = Duration.ofMinutes(5)`；**不得**在本链路写新的数字 | 避免「同一认证链上两条路防护强度不对称」（`LoginFailureGuard` Javadoc 逐字：「否则弱的那条就是实际入口」） |
| 计数时机 | **查库之前**，键由手机号构造 | §4.2（Javadoc 逐字「调用方不得改成『查到用户后才计数』」） |
| 成功清零 | `clear(key)` | Javadoc 逐字 |
| Redis 故障 | **fail-closed** → `503 AUTH_UNAVAILABLE` + `UNAVAILABLE_KEYWORD` + `UNAVAILABLE_METRIC` | Javadoc 逐字；降级方向已登记在 `tests/unit_ci_workflows/declared_effective_registry.json` 的 `security_degradation` 台账（**改方向 / 去掉读数 ⇒ 判据必红**） |
| 与短信侧对齐 | `SmsService.MAX_VERIFY_FAILS = 5` | `backend/admin-api/src/main/java/com/migao/admin/service/SmsService.java` |

🔴 **需显式登记的缺口**：`LoginFailureGuard` 的键是**单维度**（`scope + parts`）。本链路新增 `bmini-wechat` scope 后，**同一手机号在「员工密码登录」与「微信登录」两条路上的失败计数是分开的** ⇒ 攻击者可在两条路之间**分摊**尝试次数。**本单不改**（改了会动 #5531 的既有口径，风险大于收益），但**必须登记为残余风险 R4**（§5.7）。

### 5.5 授权门的「审计留痕」（反审计盲区）

**结论**：复用 `AuditLogService`，**不新造留痕表**。需要留痕的四个事件：

| 事件 | `action`（建议） | `resourceType` / `resourceId` | `actionDetails` |
|---|---|---|---|
| 授予某员工可唤米宝 | `MIBAO_ACCESS_GRANT` | `user` / 被授权员工 id | 授予的**权限码** + 授权人 + 是否经岗位 |
| 取消该授权 | `MIBAO_ACCESS_REVOKE` | `user` / 同上 | 同上 |
| 管理员**微信免密登录成功** | `LOGIN_WECHAT_ADMIN` | `user` / 本人 id | 租户 + **不含手机号明文** |
| 微信免密登录**失败**（计数达阈） | `LOGIN_WECHAT_ADMIN_LOCKED` | `user` / — | 走既有 `LoginFailureGuard` 的 `log.warn`（**不落手机号**） |

⚠️ **与 `AuditLog` 字段的对齐**：实体有 `toolName` / `ipAddress` / `userAgent` / `createdAt` 等字段 ⇒ 直接可承载。**手机号明文一律不得进 `actionDetails`**（改用 `HMAC` 前 16 字节或后四位掩码）。

### 5.6 🔴 **裁定⑤ 能不能成立？—— 结论 + 两条可成立的路**

**结论（一段话）**：**裁定⑤ 的「全局匹配」部分成立且无需新增机制**（`smsLogin` 已在跑同样的形态，见 §4.4.1）；**「多企业让用户选企业」这部分不成立** —— 除非**先证明手机号持有者**。因为快 `getPhoneNumber` **不证明持有者**（§5.1 官方逐字），而列出企业名 = 把「某手机号属于哪些企业」交给一个**可能只是自主添加了该号码**的操作者 ⇒ **信息泄露**。⇒ **二者不可兼得**，由用户二选一。

🔴 **重要的口径修正（相对原稿）**：原稿说「五合一 ⇒ 连『有几家』都不能说」。**实测发现既有 `smsLogin` 就允许说「有几家」**（逐字「该手机号关联多个租户账号，请通过对应租户入口登录或指定租户后重试」）⇒ **「说有几家」在本仓是已被接受的既有口径**，本单**沿用即可**（§4.4.4 路 X）。**只有「列企业名」才是新增的泄露面。**

**三条路（互斥，由用户选；与 §4.4.4 的 X/Y/Z 逐字对应）**：

**路 X（= 既有 `smsLogin` 口径；**本单推荐**）—— 保留「免密」，放弃「选企业」**
- 服务端**全局查**手机号（= 裁定⑤的「全局匹配」，✅ 成立）；**恰好 1 个企业命中且是管理员** ⇒ 登录成功；**多企业命中** ⇒ **拒绝**，文案**只说「关联多个企业」+ 引导用账号密码登录**（**不列企业名**）。
- **为什么推荐**：① 满足裁定①②（免密登录真的可用）；② **与既有实现逐字同构**（`smsLogin` 就是这么做的）⇒ **零新机制、零新表、零新码、零持有者证明成本**，且**已被 `AU-002` / `SmsLoginRoleGateTest` / 台账覆盖**；③ 与 I3 的 **fail-closed 字面一致**；④ 相对既有的**唯一新增泄露面 = 0**。
- **代价（用户要注意）**：**「多企业命中」的用户拿不到免密** ⇒ **如果他们正是本单的目标用户（多租户管理员），本单对他们无效**。⚠️ **这是本单最大的产品取舍，必须由用户确认**。若「一个手机号管多家企业」在布艺行业是**常见**形态，路 X 就**解决不了真问题** ⇒ 那时只有路 Y。**（未核实：本仓有无「同一手机号跨多租户」的存量数据统计。登记为 U2。）**

**路 Y（保留「选企业」，但**先证明持有者**；成本换安全）**
- 换用**手机号实时验证组件** `getRealtimePhoneNumber`（官方语义逐字：**「在每次请求时，平台均会对用户选择的手机号进行实时验证」**）。**仅当**实时验证通过 ⇒ 才把「命中 N 家企业」与**企业名列表**返回给用户选。
- `tenant_id` **绝不**作为查询键：服务端为本次选择**签发一次性、短 TTL、绑本次验证的**选择令牌（`selectToken`），用户选定后 `POST` 回服务端，服务端**按 `selectToken` 在服务端侧记录的候选集**筛选（**不是**按前端传的 `tenant_id` 查库 —— 这正是 I5 与既有 `smsLogin` 的准确口径，见 §5.2.2）⇒ 再签发真 JWT。
- **为什么它成立**：官方语义保证「**当次**实时验证」⇒ 把「该手机号所属企业列表」展示给**当次的持有者**是**可接受的**。这正是任务要求的那个论证：**「若是持有者已验证 ⇒ 可接受；若否 ⇒ 信息泄露」** —— **路 Y 就是把「若」变成「是」。**
- **代价**：① 每次登录调用**计费**（0.03 元/次成功，官方逐字）；② 实时组件的**可用性 / 额度**需核实（未取证 ⇒ U3）；③ 需新增选择令牌机制（一处 Redis 键 + 一个端点，**仍是「不新造会话机制」** —— 它是**登录中继**，不是会话）；④ **必须**补不变式 **I4**；⑤ 失败路径仍需按 §4.3 的 A/B/C 分组（**只有通过实时验证这一步**才可能展示列表 ⇒ 攻击者必须**先当次持号**才看得见列表 ⇒ 泄露面收敛为「持有者可见自己的归属」，可接受）。

**不成立的路（明确登记，防被误读为可选）**：
- ❌ **路 Z（= 原稿的「路 C」）**：**快** `getPhoneNumber` + 直接列出企业名 —— **信息泄露**（§5.1 官方逐字：不保证实时验证 + 用户可自主添加号码），**且比既有实现更宽**（既有至多说「有多个」）。
- ❌ **原稿的「路 D」不再是「不成立」** —— ⚠️ **本次修订**：原稿把「只回『命中多家』不列名」判为「仍是枚举位 ⇒ 不成立」，但**既有 `smsLogin` 正是这么做的**（且已被接受、已登记补偿控制）⇒ 它就是上面的**路 X**，**成立**。⇒ **原稿那一格的判断被实测推翻，此处更正。**
- ❌ **路 W**：让前端传 `tenantId` **当查询键**（或「先填企业编码」）—— **#5485 已明确否掉**（`frontend/bmini-app/src/utils/auth.ts` 注释逐字：「否则『任意数字即可切租户』」）。⚠️ 注意与路 Y 的区别：路 Y 里前端**也**回传一个选择，但它**只是候选集里的一个索引**，服务端**不用它查库**（§5.2.2 I5）。

### 5.7 残余风险登记（**照实登记，不粉饰**）

| # | 风险 | 现状 | 处置 / 去向 |
|---|---|---|---|
| **R1** | **手机号自主添加是否校验持有者**未取证 ⇒ §5.1 结论的强度不确定 | **未核实（U1）** | **必须**在落码前取证（真机实测「自主添加一个非本人号码」）；结论决定走路 A 还是路 B。**若必须短信验证 ⇒ 快组件已含持有者校验 ⇒ 路 A 的「选企业」可以放宽讨论**（但仍受 §4.3 与 I5 约束） |
| **R2** | 实时验证组件的**可用性与额度**未取证 | **未核实（U3）** | 路 B 的前置；不影响路 A |
| **R3** | 「同号跨多租户」的**存量规模**未知 ⇒ 不知道路 A 会不会掏空本单价值 | **未核实（U2）** | 落码前跑一条只读统计（按手机号 `GROUP BY HAVING COUNT(DISTINCT tenant_id) > 1`），**照实报数** |
| **R4** | `LoginFailureGuard` 的键是**单维度** ⇒ 「员工密码登录」与「微信登录」两条路**分摊尝试次数** | **本单有意不改** | 登记；改进属 #5531 的口径扩展，不在本单 |
| **R5** | `super_admin` / `service` 旁路身份**天然满足**三码判定 ⇒ 若该判定被用于**端点授权**，旁路身份会绕过「微信登录才可唤」的意图 | 判定函数设计成**只用于「能力位」下发**（§3.3 的 `capabilities.mibaoChat`），**不**作为端点 `@RequirePermission` 的替代 | 落码时须复核：**不得**把 `capabilities.mibaoChat` 当作授权（授权仍由 `@RequirePermission` 强控） |
| **R6** | 快验证组件**计费**（0.03 元/次成功） | 路 A 下每次都调 ⇒ 需估算调用量 | 运营项；若要降本可用「绑 openid 换免手机号授权」（§12 待裁定-1）——**两条待裁定在此处耦合** |
| **R7** | 「微信授权链退役守卫」被改造后**判据面变窄** ⇒ 未来可能长回旧形态 | 见 §7 的白名单 + 两侧红证 | 元守卫**只许收窄白名单不许删**；白名单条目**只许缩短**（台账范式） |

---

## 6. 载体与边界

### 6.1 载体：`frontend/bmini-app`（一端双编译）

| 项 | 值 | 证据 |
|---|---|---|
| 框架 | Taro **4.2.1** | `frontend/bmini-app/package.json` |
| 小程序编译 | `npm run build:weapp`（`taro build --type weapp`） | 同上 |
| **H5 编译** | `npm run build:h5`（`taro build --type h5`） | 同上 |
| 平台插件 | `@tarojs/plugin-platform-weapp@4.2.1` **与** `@tarojs/plugin-platform-h5@4.2.1` **均已装** | 同上（`plugin-platform-h5` 在 `devDependencies`） |
| 登录态存储 | `STORAGE_KEYS.TOKEN` / `USER` / `TENANT_ID`（Taro 存储，两端同 API） | `frontend/bmini-app/src/utils/auth.ts` |
| 米宝页 | `frontend/bmini-app/src/pages/chat/index/index.tsx` | 实测无权限门（§1） |

⇒ **裁定②的「H5 仍账号密码」在同一份代码里怎么表达**：H5 编译产物里**不渲染**微信授权按钮（`getPhoneNumber` 是 `open-type` 按钮，H5 无此能力；Taro 端需按 `process.env.TARO_ENV` 分流），**H5 只渲染账号密码表单**。🔴 **必须有一条判据钉住「H5 产物里不存在微信登录路径」**（§7.4 C3）。

### 6.2 `frontend/worker-h5` —— **与本单无关，不要动**（逐字登记）

`frontend/worker-h5` 是**工人端轻入口**（实测为 5 个 `.mjs` + 1 个 `.css`，**无 Taro、无构建链**：`api.mjs` / `app.mjs` / `render.mjs` / `scan-input.mjs` / `styles.css`）。工人**不是**商户员工、**不持**权限码（`docs/wiki/RBAC.md` 逐字：「**权限码是「商户员工」概念**（issue #5246）」）⇒ 米宝唤出授权门**不适用于工人端**。
⇒ **本单不改 `frontend/worker-h5` 任何文件**；工人侧防爆破（`WorkerSessionService` 的 `keyOf("worker", ...)`）也**保持不动**。

### 6.3 `frontend/admin-web` 的 `agent-workspace` —— 边界（**易混，必须写清**）

`frontend/admin-web/src/config/menu.ts` 的「智能客服」组里有「在线接待」节点（`permissionCode: 'agent:session'`），并有一段注释（逐字）：「#3094 米宝·在线对话 菜单入口已移除，智能体对话经右下角 FAB」。

⇒ **区分两个入口**：

| 入口 | 载体 | 本单是否涉及 |
|---|---|---|
| **商家员工「唤出米宝」对话** | `frontend/bmini-app`（weapp + h5 双编译）+ `admin-web` 的**右下角 FAB** | ✅ **本单的授权门对象** |
| 「在线接待」人工会话工位 | `frontend/admin-web` 的 `agent-workspace/human-sessions` | ❌ **不涉及**（它的码也是 `agent:session`，但它是**人工接待工位**，不是「唤出米宝」） |

⚠️ **两处共用 `agent:session` 这个码**（§3.2 选项 A 的副作用）⇒ **必须显式登记**：本单把 `agent:session` 用作**「可唤出米宝」的判据**，意味着**持该码 = 同时可进人工接待工位**。这是**既有事实**（不是本单引入），但本单**扩大了它的语义负载** ⇒ 落码前需确认这符合预期（登记为**待裁定-0 的一部分**）。**若要解耦，就只能走路 B 的「新增码」** —— 这就是 §3.2 选项 B 的真实代价所在。

---

## 7. 与 #5485 的关系：**定向回退** + 元守卫改造

### 7.1 这是**定向回退**，逐条登记「回退了什么、没回退什么」

| 维度 | #5485 的终态 | 本单 | 是否回退 |
|---|---|---|---|
| 匹配范围 | **租户内**（`用户名@企业编码` 里的编码定租户） | **跨租户全局**（手机号） | 🔴 **回退**（唯一一处；护栏见 §5.2 的 I4/I5） |
| 端 | 小程序 + H5 统一账号密码 | **仅小程序**微信免密；**H5 仍账号密码** | ❌ 不回退（H5 侧 **#5485 口径逐字保留**） |
| 适用人群 | 全部员工 | **仅管理员**（其余员工仍账号密码 + 首登强制改密） | ❌ 不回退 |
| 凭据 | 既有 JWT（RS256） | **同一套**（不新造会话机制） | ❌ 不回退 |
| 微信 H5 网页授权 | 501 占位 | **501 占位不动** | ❌ 不回退 |
| openid | 绑定已整条退场 | **待裁定**（§12 待裁定-1） | ⚠️ 可能部分回退 |
| 元守卫 | 「微信授权链一律不得出现」 | **白名单形态**（只放行这一条收窄链） | ⚠️ **收窄**（不是删除） |

### 7.2 🔴 元守卫改造方案（**不许简单删守卫**）

**现状**（`frontend/bmini-app/tests/bmini-login-retired.test.ts` 实测）：三条判据
1. 全包不得引用废弃端点 `/api/auth/bmini/login`；
2. 全包不得残留 `phoneCode`；
3. **仅登录页**（`pages/auth/login/`）不得出现 `getPhoneNumber`。
并有两项**防空跑前置断言**（语料非空 + 含登录页），以及 `stripComments`（**只判代码不判注释** ⇒ 避免被自己的文档喂红）。

**目标形态（白名单，四段）**：

| 段 | 判据 | 射程 | 红证（注入什么 ⇒ 必红） |
|---|---|---|---|
| **W1 白名单** | `getPhoneNumber` **只允许**出现在**唯一**一个登记文件里（`ALLOWED_PHONE_AUTH_SITES`，**单条**，含该文件路径 + 允许的出现次数） | `src/**` | 在第二个文件里加 `getPhoneNumber` ⇒ 计数超限 ⇒ **红** |
| **W2 旧形态仍红** | ① 废弃端点 `/api/auth/bmini/login` 仍**全包零命中**；② `phoneCode` **只允许**在 W1 那个文件里出现；③ **登录页**（`pages/auth/login/`）**仍**不得出现 `getPhoneNumber`（**免密入口不在账号密码页**，而在**独立页**） | 同上 | ① 把旧端点写回 `utils/auth.ts` ⇒ 红；② 在 `userService` 里加 `phoneCode` ⇒ 红；③ 把授权按钮加进 `pages/auth/login/` ⇒ 红 |
| **W3 台账只许缩短** | 白名单条目数**现取**、上限登记为常量；**只许缩短**（与既有 `READ_WRITE_EXCEPTIONS_CEILING` / `READ_CODE_ANCHORS` 台账范式**同源**） | 判据自身 | 条目数 > 上限 ⇒ 红；**删条目后**新形态仍被 W2 拦住 ⇒ 证明判据**不是**靠条目豁免吃饭 |
| **W4 防空跑** | 语料非空 + 含白名单文件 + 含登录页（**沿用既有两项前置断言并扩一项**） | 判据自身 | 改错 `SRC_DIR` ⇒ 红（不是静默通过） |

🔴 **两侧都要有红证（任务逐字要求）**：
- **放行侧**：收窄链（W1 白名单文件里的 `getPhoneNumber` + 新端点路径）⇒ **必须绿**（判据不得把它判红）；
- **仍红侧**：旧的全量微信授权形态（`phoneCode` 散落多处、`/api/auth/bmini/login`、登录页授权按钮）⇒ **必须红**。

**⚠️ 三个易踩坑（写进实现指引）**：
1. **不得只改正则放宽**（如把 `hits` 的 expect 改成 `[]` 之外的东西）—— 那等于删除判据。必须**新增**白名单机制。
2. **判据只判代码不判注释**（`stripComments` 必须保留）：否则本文档/代码注释里提到 `getPhoneNumber` 会**把判据自己喂红**（§2.2 的 B1 / 「文本匹配型判据被自己的文案喂红」，本仓已有教训）。
3. **判据自身不在语料内**（该文件在 `tests/` 下，`SRC_DIR` 指向 `../src`）⇒ 模式字面量不会自我命中（既有设计，**保持**）。

### 7.3 两侧红证的**可执行形态**（汇总，写进单元测试）

| ID | 判据 | 断言 | 能红吗 |
|---|---|---|---|
| C1 | 收窄链**放行** | 白名单文件出现 `getPhoneNumber` ⇒ `ALLOWED` 计数 == 1 且不判红 | 白名单机制写错（误判红）⇒ 红 |
| C2 | 旧端点仍禁 | `hits(/\/api\/auth\/bmini\/login/)` == `[]` | 注入 ⇒ 红 |
| C3 | H5 产物无微信登录 | H5 编译路径判据：微信授权按钮的渲染受 `TARO_ENV === 'weapp'` 守卫（**静态断言**：该分支存在且互斥） | 去掉守卫（让 H5 也渲染授权按钮）⇒ 红 |
| C4 | 授权门两侧同源 | 「可唤」判定**只**读服务端下发的 `capabilities.mibaoChat`；前端**零**权限码字面量（§2.4 判据②） | 前端硬编码三码之一 ⇒ 红 |
| C5 | 账本只许缩短 | `ALLOWED_PHONE_AUTH_SITES` 条数 == 1（常量冻结） | 加第二条 ⇒ 红 |

---

## 8. 米宝唤出授权门（§8 = 任务要求的第 5 章）

### 8.1 口径

| 主体 | 可唤米宝？ | 依据 |
|---|---|---|
| 持 **全部三码**（§3.1） | ✅ **默认可唤** | 裁定④ |
| 持 `"*"`（`admin` / `super_admin` / `service`） | ✅ 默认可唤 | §3.3 判定表（通配 ⇒ 真）。⚠️ R5：旁路身份只进**能力位**，不进端点授权 |
| 其他员工，**被管理员授权** | ✅ 可唤 | 裁定⓪ + issue 范围 3 |
| 其他员工，**未被授权** | ❌ 不可唤 —— 但**必须**给「需要管理员授权」+ **可行动引导** | issue 范围 3 逐字：「**明确提示「需要管理员授权」+ 可行动引导**（不是静默隐藏，也不是 403 白屏）」 |

🔴 **「不是静默隐藏」是本条最容易做错的地方**：直觉做法是「没权限就不渲染入口」= 静默隐藏 ⇒ **违反要求**。正确做法 = **入口可见**，点击（或进入页面）后给出**明确的授权缺失态**：说清「需要管理员授权」+ 给出**去哪授权**（「请联系企业管理员在『员工管理』中为你开通米宝使用权限」）。

### 8.2 「授权」怎么表达（**复用既有权限体系，不新造开关表**）

issue 范围 3 逐字：「授权 = 由管理员在员工管理里给该员工授**某个权限码**，**复用既有权限体系，不新造开关表**」。

⇒ **授权 ≡ 把某个权限码勾给该员工**（员工管理页的现有交互，落 `users.permissions` 快照）。**不新增表、不新增字段。**
⇒ **这个权限码已经由 §3.2 定案**（**就是 `agent:chat`**，新增码）—— 见 **§12 待裁定-2**（**只剩「粒度」一个子问题**）。

### 8.3 端侧下发形态（**单一真值 → 两端**）

服务端在既有 `/api/auth/me` 的响应里**新增一个能力位**：

```
capabilities: { mibaoChat: true | false }
```

- `mibaoChat` = `hasAllAdminPermissionCodes(perms) || perms.contains(MIBAO_CHAT_GRANT_CODE) || perms.contains("*")`
- 🔴 **前端零权限码字面量**（§2.4 判据②）：两端（weapp / h5 编译产物）**都只读这一个布尔位** ⇒ **改一处即两端同步**（issue 验收标准逐字：「管理员权限码集合是**单一真值**：改一处即两端同步」）。
- ⚠️ **与 R5 的边界**：`capabilities.mibaoChat` 是**能力位（UI 显隐与文案）**，**不是**授权。真正拦住数据面的仍是 `@RequirePermission` + `PermissionInterceptor`（既有架构契约，**不砍**）。⇒ 即便前端被绕过，数据面仍受保护（**纵深**，不是替代）。

### 8.4 授权 / 取消授权**要有留痕**（issue 验收标准逐字）

落 §5.5 的四个审计事件（复用 `AuditLogService`，**不新造表**）。
**注**：如果授权 = 勾一个**既有**权限码，那么「留痕」的**天然载体**就是既有的员工编辑审计（若已存在）—— **本单需复核**该路径是否已留痕；若**未**留痕，则**必须补**（登记为落码任务，**不是**可选）。

### 8.5 未授权态的可执行断言（每条能红）

| ID | 断言 | 红证 |
|---|---|---|
| G1 | 持三码 ⇒ 入口渲染 + 可进对话 | 判据写错 ⇒ 红 |
| G2 | 未授权员工 ⇒ **入口可见**（非静默隐藏，断言入口**存在**） | 改成不渲染 ⇒ 红 |
| G3 | 未授权员工点击 ⇒ 文案含「需要管理员授权」（**逐字子串**） | 文案退回泛化「无权限」⇒ 红 |
| G4 | 未授权员工点击 ⇒ **不是** `403` 白屏（断言无 403 页面、抛出可读引导） | 直接 403 ⇒ 红 |
| G5 | **H5 产物**同样满足 G2~G4 | 只在 weapp 分支加门 ⇒ 红 |
| G6 | 授权 / 取消 ⇒ 审计行落库（`action` ∈ 两值 + `userId` + 时间） | 去掉留痕 ⇒ 红 |

---

## 9. 验收标准（**逐条保留 #5642 正文，再补本单新增**）

### 9.1 保留 #5642 正文的 10 条（**逐字口径不改**）

1. 小程序端：管理员微信授权 → 手机号匹配**唯一**管理员 ⇒ 登录成功，**租户归属正确**；
2. 手机号在**多企业**命中 ⇒ **fail-closed**（明确失败 + 引导去浏览器），**绝不猜租户、绝不跨租户兜底**（红证）；
   > ⚠️ **与裁定⑤的冲突已登记**（§5.6）：正文这条与裁定⑤字面矛盾。**本文按裁定⑤给出路 A / 路 B 两条**，任一条都需用户确认后**改写本条**（路 B 下「多企业」不再是 fail-closed）。
3. 手机号在**该企业内非管理员**（或不存在）⇒ 与「手机号不存在」**同一文案、同一状态码**（反枚举，红证）；
4. 浏览器端：**微信授权不生效**，仍必须账号密码（红证：H5 端走微信授权路径 ⇒ 不通过）；
5. `AuthService.buildWechatH5AuthorizeUrl` **仍是 501 占位**（本单不动它，红证：它没被实现）；
6. 元守卫 `bmini-login-retired.test.ts` 改成白名单形态后 —— ① 收窄链**放行**；② 旧的全量微信授权形态**仍然判红**（**两侧都要有红证**）；
7. 米宝唤出：持该组权限码 ⇒ 可唤；未授权员工 ⇒ **明确「需要管理员授权」提示 + 可行动引导**（不是静默隐藏、不是 403 白屏）；
8. 授权 / 取消授权 ⇒ **有留痕**；
9. 管理员权限码集合是**单一真值**：改一处即两端同步（**机械判据**钉住，不许两处硬编码）；
10. 跨租户：租户 A 的管理员登录后看不到租户 B 任何数据。

### 9.2 本单**新增**的判据（论证得出，每条能红）

| # | 判据 | 红证 | 出处 |
|---|---|---|---|
| N1 | **五合一**：`{未命中, 命中非管理员, 命中多企业, 命中但停用, phoneCode 无效}` 的响应 `status` + `error.code` + `error.message` **逐字节相同** | 任一组不同 ⇒ 红 | §4.3 |
| N2 | **正证**：命中唯一管理员 ⇒ `200` + `tenant_id` == 该账号所在租户 | 全拒绝也能过 N1 ⇒ N2 拦住 | §4.3 S5 |
| N3 | **锁定文案逐字复用** `LoginFailureGuard.LOCKED_MESSAGE`；且**不存在**本链路自写的第二种锁定文案 | 自写文案 ⇒ 红 | §5.4 |
| N4 | **计数在查库之前**：断言失败次数达 `MAX_FAILS` 时，**用户表零查询**（`verify(userMapper, never())`）+ 第 `MAX_FAILS` 次仍查（与原单测同形态） | 改成查到用户后才计数 ⇒ 红 | §4.2；既有形态见 `backend/admin-api/src/test/java/com/migao/admin/security/EmployeeLoginLockoutTest.java` |
| N5 | **计数键不含手机号明文**（若采纳 HMAC 方案）：断言 Redis 键形态为 `login:fail:bmini-wechat:<hex>` | 键里出现 11 位数字 ⇒ 红 | §4.2 |
| N6 | **`tenant_id` 无前端来源**：断言签发路径的 `tenant_id` 全部来自查库结果（静态：端点签名**不含** `tenantId` 入参） | 加一个 `tenantId` 入参 ⇒ 红 | §5.2 I5 |
| N7 | **`agent:chat` 不存在的事实被机械钉住**：三码集合的每个成员 ∈ 目录（§2.4 判据③） | 保留 `agent:chat` 字面 ⇒ **红**（这正是当前状态） | §3.2 |
| N8 | **`role='admin'` 判定等价性回归**：对内置 5 岗位 + 一个「自定义岗位持三码」+ 一个「快照持三码」的构造，断言 `hasAllAdminPermissionCodes` 与「是否 admin」**在内置种子上相等**、在自定义/快照上**不等**（登记为**有意**） | 把判定改成读 `role` 字段 ⇒ 自定义/快照两格红 | §2.2 C |
| N9 | 🔴 **新端点在 `SecurityConfig.permitAll` 里**（否则真实入口在最外层就 401，而单测直调 service 全绿） | 从 `permitAll` 删掉该路径 ⇒ 红 | §4.5 |
| N10 | 🔴 **`selectActiveUsersByPhoneIgnoreTenant` 的调用点 ⊆ 登记台账**（只许缩短），且非登录链路零调用 | 在第二个类里调它 ⇒ 红 | §4.4 (b) |
| N12 | 🔴 **复用既有租户护栏而非新造**：不新增 `@InterceptorIgnore(tenantLine="true")` + 查 `users` 无 `tenant_id` 谓词的方法（否则豁免台账会多一条 ⇒ `test_tenant_scoped_user_queries.py` 判据②「台账条数 == 现取命中条数」必红） | 新增第二个跨租户查询方法 ⇒ 红 | §4.4.2 |
| N11 | 🔴 **`agent:chat` 五面齐全**：目录（`RegistrationService.defaultPermissions`）∧ 迁移（终态对账 `DO` 块）∧ 岗位矩阵（**只 `admin`**，且在迁移头部逐字登记「有意收窄」）∧ 角色回退（按四 case 的既有口径）∧ 工具层**不动** | 任一面缺失 / 多回填一个岗位 ⇒ 红 | §3.2.2 / §3.2.3 |

### 9.3 红证的**前提自证**（本仓纪律，防「绿了但没跑」）

每条验收断言必须附：① 断言**改前**的实测红（命令 + 输出尾部）；② 注入式红证（改一个字符 ⇒ 红）；③ 结论**绑定被验证的 sha**（`78c67effc` 或落码时的基线）。

---

## 10. 明确不做（**边界清单，逐条保留 #5642 正文**）

- ❌ **不实现微信 H5 网页授权**（`AuthService.buildWechatH5AuthorizeUrl` / `handleWechatH5Callback` 保持 `501 NOT_IMPLEMENTED`）；
- ❌ **不恢复「跨租户匹配员工」**（#5485 退役的那条链）；
- ❌ **不给普通员工免密路径**（员工仍账号密码 + 首登强制改密）；
- ❌ **不新造会话 / 权限结构**（复用既有 JWT + RBAC）；
- ❌ **不新增 `role`、不做 `is_owner`**（裁定③）；
- ❌ **不新造第二套限频**（复用 `LoginFailureGuard`）；
- ❌ **不新造开关表**（授权 = 勾既有权限码）；
- ❌ **不动 `frontend/worker-h5`**（工人端轻入口，与本单无关）；
- ❌ **不删元守卫**（改白名单形态）；
- ❌ **不动 `CHANGELOG.md`**（docs-only 豁免，AGENTS.md 铁律 7）。

---

## 11. 依赖与阻塞

| # | 项 | 类型 | 影响 | 处置 |
|---|---|---|---|---|
| **B1** | `WECHAT_BMINI_APPID` / `WECHAT_BMINI_SECRET` **全仓只有空占位** | 🔴 **阻塞（环境）** | 无 appid ⇒ 连 `code2Session` 都调不了 ⇒ **微信登录链路无法真机验证** | 需**运维**提供（非个人主体 + 已完成认证的小程序 —— 快验证组件官方逐字：「目前该接口针对**非个人主体**，且完成了**认证**的小程序开放」）|
| **B2** | 快验证组件**计费** 0.03 元/次成功 | ⚠️ 成本 | 登录链路每次调用计费 | 估量；或用「绑 openid」（§12 待裁定-1）降调用 |
| **B3** | 实时验证组件（路 B）**可用性与额度**未取证 | ⚠️ 未知 | 决定路 B 可否走 | 落码前取证（U3） |
| **B4** | 手机号「自主添加」是否校验持有者**未取证** | 🔴 **阻塞（决策）** | **单独决定走路 A 还是路 B** | 真机实测（U1） |
| **B5** | 「同号跨多租户」存量规模未知 | ⚠️ 未知 | 决定路 A 是否掏空本单价值 | 只读统计（U2） |
| **B6** | `agent:chat` 不存在 ⇒ 裁定④**字面**不可落码 | ✅ **已解（本单）** | 结论：**必须新增该码**（§3.2.1 论证「无码在管 ⇒ 不存在复用选项」）⇒ 不再是阻塞项，转为**落码任务**（§3.2.2 五处清单）。**仅剩**「回填给谁」需用户确认（§12 待裁定-0） |
| **B8** | 🔴 **新端点若不加进 `SecurityConfig.permitAll`，真实入口会在最外层 401**（而单测直调 service 全绿） | 🔴 **落码必做（易漏）** | 「绿了但没跑」形态 | 加进 `permitAll` + 落判据 §9.2 N9（§4.5） |
| **B9** | ✅ **不阻塞（已解除）**：`selectActiveUsersByPhoneIgnoreTenant` 仍在，**但它是被台账登记的既有豁免**，且 `smsLogin` 已在跑同一形态 | ✅ **已解** | **复用即可**（§4.4.2）；**不新增**第二个跨租户查询（新增会多一条台账条目，而台账**只许缩短**） | 只补台账文字（说明它**同时**服务两条渠道）+ 更正 `AuthService.bminiLogin` 的过期 Javadoc 措辞（§4.4.2） |
| **B10** | 🔴 **两处口径不一致需裁定**：`smsLogin` 管理员门禁走 **`roles ∋ 'admin'`**（角色码）而本单走 **权限码**；且 `smsLogin` 在 S2 格**有意**单独回文案 | 🔴 **需裁定** | 不统一 = 同一句「管理员」两条渠道两套真值（§2.3 要防的形态） | §12 待裁定-3 |
| **B7** | `agent:session` 同时承载「人工接待工位」 | ⚠️ 语义耦合 | 本单扩大其语义负载（§6.3） | 需用户确认可接受，否则走路 B 新增码 |

---

## 12. 待裁定（**本文不拍板**；各给选项 + 推荐 + 理由）

### 待裁定-0（🔴 **本单因实测发现而新增，且是本单最需要确认的一条**）：`agent:chat` 的**回填范围**

**已定（不需要裁定）**：`agent:chat` **必须新增**（§3.2.1 已论证：**「谁能唤出米宝」今天没有任何码在管 ⇒ 不存在「复用既有码」的选项**）。这条**不是**待裁定项，是实测结论。

**需要裁定的是「回填给谁」**（§3.2.3）：
| 选项 | 内容 | 上线当天的行为 | 评价 |
|---|---|---|---|
| **(i) 严格收窄（本文推荐）** | 迁移**只**把 `agent:chat` 回填给 `admin` 角色；其余岗位（客服/运营/销售/财务/自定义）**有意不回填**，并在迁移头部逐字登记「这是有意收窄，不是漏授」 | 除管理员外**所有员工**的米宝从「可唤」变「需授权」 —— **客服受影响最明显**（其岗位职责就是天天用米宝） | ✅ 符合裁定⓪字面（「其他员工需要授权才能唤出」）；⚠️ **必须配套**：上线告知 + 批量授权（或员工管理支持按岗位批量勾选），否则会成为「功能上线了但客服当天干不了活」的事故 |
| **(ii) 宽回填** | 把 `agent:chat` 回填给**原本就持 `agent:session` 的岗位**（= 客服 + 运营） | 上线当天这两类岗位**零变化**，其余岗位变「需授权」 | ⚠️ 与裁定⓪「其他员工需要授权」**张力明显**；且**开了「按现状回填」的口子就再也收不回来**（同 `V129` 的「只收窄不放宽」纪律）⇒ 本文视其为**改判**，不该由迁移来做 |

- **推荐 (i)**，理由见 §3.2.3。**若选 (ii)，必须由用户明示**（因为它是用迁移改掉裁定⓪的产品意图）。

### 待裁定-0b：`agent:session` 与「人工接待工位」的语义耦合（**附带确认**）
「在线接待」菜单节点（`frontend/admin-web/src/config/menu.ts`）用的是 `agent:session`。本单**不改**它，但**必须确认**：本单新增的 `agent:chat` 与它**是两个独立的码**（这是 §3.2.1 的结论）⇒ 「持 `agent:session`」**不**自动获得米宝唤出权。**确认这一点**即可（若用户希望「客服默认可唤」，正确做法是在 (i)/(ii) 里把 `agent:chat` 回填给客服岗位，**而不是**让两个码互相蕴含）。

### 待裁定-3（🔴 **本单因实测 `smsLogin` 而新增**）：短信登录与本单的**口径统一**

实测发现 `backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java` 的 `smsLogin` **已经在做同一件事**（跨租户手机号 + 仅管理员 + 多租户 fail-closed），但有两处口径与裁定③/本单**不一致**：

| # | 差异 | 现状（`smsLogin`） | 本单（裁定③） | 需要裁定 |
|---|---|---|---|---|
| 1 | **管理员判定口径** | `roles ∋ 'admin'`（**角色码**） | **权限码**（三码全持） | 🔴 **要不要把 `smsLogin` 同批改成权限码口径？** 不改 ⇒ **同一句「管理员」在两条渠道上是两套真值**（正是 §2.3 要防的形态）；改 ⇒ 会**动既有已测实现**（`SmsLoginRoleGateTest` 有 4 条拒绝用例 + 台账补偿控制文字要同步） |
| 2 | **S2 格（命中非 admin）文案** | **有意**单独回「该账号非管理员，请使用员工登录入口」+ 源码逐字论证「『你是员工』这件事在本路径上已由『手机号在这家企业里命中非 admin 账号』确定」 | §4.3 原稿要求并入 A 组（反枚举） | 🔴 **沿用还是收紧？** 沿用 ⇒ 承认「该手机号是某企业非管理员员工」可被探测；收紧 ⇒ 改既有实现 |

- **本文的推荐**：**两处都统一到裁定③的口径（权限码）+ 收紧 S2 到 A 组** —— 理由：① 用户已裁定「按权限码」（裁定③），让另一条渠道继续用角色码就是**两套真值**；② 反枚举对**两条**渠道应当同强度（`LoginFailureGuard` 的既有教训逐字：「同一认证链上两条路防护强度必须对齐，**否则弱的那条就是实际入口**」—— 同一逻辑适用于文案面）。
- ⚠️ **代价**：这**超出「只加微信登录」的最小改动面**（会动 `smsLogin` + `SmsLoginRoleGateTest` + 台账文字）。⇒ **若用户希望本单只做微信侧，则该差异必须登记为「已知的两套口径」并留去向**（不能默默不一致 —— 至少要有一条注释/台账指向它）。
- **若不做**：**必须显式登记**「`smsLogin` 用角色码、微信登录用权限码，两条渠道口径不同」+ 去向，否则下一个人会以为是漏改。

### 待裁定-1（**任务要求保留**）：是否绑定 `openid`？
| 选项 | 内容 | 代价 | 收益 |
|---|---|---|---|
| **绑** | 首次微信登录成功后，把 `(openid, tenant_id, user_id)` 落一张映射表 | **多一张表 + 必须设计解绑流程**（换微信号 / 离职 / 换手机号）；且 openid **跨租户不唯一**（同一微信在不同小程序 appid 下 openid 不同；同 appid 下**同一租户**内唯一）⇒ 表设计必须**带 tenant_id**，否则又造一个跨租户主键 | 后续登录**免手机号授权**（少一次点击 + **省 0.03 元/次** ⇒ 直接缓解 B2） |
| **不绑（推荐，视 B2 计费敏感度）** | 每次登录都走 `getPhoneNumber` | 每次多一次授权点击 + 每次计费 | **零新表、零解绑流程、零 openid 跨租户风险**；实现面最小 |
- **推荐**：**若月活调用量 × 0.03 元可忽略 ⇒ 不绑**（最少代码阶梯 + 少一处身份面）；**若计费敏感 ⇒ 绑**，但**必须**在表上用 `UNIQUE(tenant_id, openid)` 而**不是** `UNIQUE(openid)`。
- ⚠️ **与 #5485 的关系**：绑 openid 是**部分回退** #5485（它把「绑定 openid → 二次免密」整条退役）⇒ **文档必须显式登记**（§7.1 表格已列）。

### 待裁定-2（**任务要求保留**）：「授权唤出米宝」的**粒度**与**权限码**

> ⚠️ **前提已变**：任务给这一条时的假设是「授权的码 = 复用既有码 or 新增码」。**§3.2.1 已实测否掉了「复用既有码」** —— 因为**唯一语义相近的 `agent:session` 承载的是「人工接待工位」，不是「唤出米宝」**，复用会让两个授权意图焊死。⇒ 本条现在**只剩一个子问题**（粒度），权限码那一栏已经**由 §3.2 定案**。

| 子问题 | 选项 | 代价 | 推荐 |
|---|---|---|---|
| **粒度**（**唯一仍需裁定的**） | (a) **员工级**（该员工可唤）<br>(b) **岗位级**（该岗位默认可唤） | (b) 需岗位默认权限勾选 → 但**本仓权限是快照式**（`docs/wiki/RBAC.md` 逐字：「员工权限 = 员工管理页保存的勾选（`users.permissions` 快照），与岗位脱钩」）⇒ 岗位级**不改变**已有员工的生效权限（只影响**新建**时的预填模板 + 迁移回填那一批） | **(a) 员工级** —— 因为快照式语义下「岗位级」**不是**一个生效口径，把它当成生效口径会造**第二套真相源**。⚠️ 但注意 §12 待裁定-0 的「回填范围」本质上是**一次性**的岗位级动作（迁移按岗位回填）—— **这不矛盾**：回填是**一次性初始化**，之后一律走员工级勾选 |

🔴 **「授权」到底勾哪个码（已定，不再是待裁定）**：
- **勾的就是 `agent:chat`**（新码，§3.2.2 的完整清单）。它与 `agent:session`（坐席读码）、`agent:session:manage`（坐席写码）**三者互不蕴含**。
- **为什么这不需要「新造开关表」**（回应 issue 范围 3 的约束）：授权动作**仍然是**「员工管理页里勾一个权限码、落 `users.permissions` 快照」—— **复用既有交互与既有存储**。**新增的只是目录里的一个码，不是一套开关机制。** ⇒ 「复用既有权限体系」与「新增一个权限码」**不矛盾**：前者说的是**机制**，后者说的是**目录内容**。

🔴 **由此消除的「冲突」（原稿曾担心的那个，现已不成立）**：原稿担心「若唤出码 == `agent:session`，则客服（持 `agent:session`）会**未经逐个授权**就默认可唤 ⇒ 三码集合失去约束力」。**新增独立码 `agent:chat` 之后这个冲突消失**：
- 客服持 `agent:session`（坐席）**但默认不持** `agent:chat` ⇒ **客服默认不可唤**（符合裁定⓪「其他员工需要授权才能唤出」）；
- 「管理员默认可唤」由 `三码全持` 保证（`employee:create` 是这套集合里真正把「管理员」与「客服」区分开的码 —— 见 §2.2 矩阵）。
- ⇒ **判定式三项互不干扰**：`三码全持`（管理员）/ `持 agent:chat`（显式授权）/ `持 "*"`（平台旁路）。**这就是 §3.2.4 的那条 OR。**


---

## 13. 未核实项（**照实登记，不粉饰**）

| # | 未核实内容 | 影响 | 取证方式 |
|---|---|---|---|
| **U1** | 微信快验证组件「自主添加号码」流程**是否要求短信验证**（⇒ 是否构成持有者证明） | **单独决定** §5.6 走路 A 还是路 B | 真机实测（用一个非本人号码走「自主添加」）；或查阅「手机号快速验证组件常见问题」 |
| **U2** | 本仓（或线上）**「同一手机号跨多租户」的存量规模** | 决定路 A 是否掏空本单价值 | 只读 SQL：按手机号 `GROUP BY HAVING COUNT(DISTINCT tenant_id) > 1` |
| **U3** | 「手机号实时验证组件」的**可用性 / 额度 / 计费** | 决定路 B 可不可走 | 微信公众平台后台 + 官方文档 |
| **U4** | `#5485` 的 **I1 / I3 逐字原文**（本文按 #5642 正文**转述**引用，未回溯原单） | 编号 / 措辞可能有偏差 | `gh issue view 5485` |
| **U5** | 既有「员工编辑 / 岗位授权」路径**是否已写审计**（⇒ §8.4 的留痕是不是真的缺） | 决定 §8.4 是「补」还是「已具备」 | 读 `AdminUserController` / 员工管理服务的写路径 |
| **U6** | `frontend/bmini-app` 是否已有 **`TARO_ENV` 分流**的既有范式（§6.1 / §7.3 C3 依赖它） | 影响 H5 分支的实现成本 | `git grep TARO_ENV frontend/bmini-app/src` |
| **U7** | `service` 令牌在**登录端点**上是否可达（§3.3 / R5 的前置） | 影响判定函数的写法 | 读 `SecurityConfig` / `ServiceTokenFilter` 的放行面 |
| **U8** | `UserMapper.selectActiveUsersByPhoneIgnoreTenant` **当前是否已被任何生产路径调用**（§4.4） | 若仍有活调用点，本单处置须一并收口 | `git grep -n selectActiveUsersByPhoneIgnoreTenant origin/main` |
| **U9** | **`WechatService` 的 Mock 模式覆盖到哪一步** —— `bminiGetPhoneNumber` 在未配置 appid 时是否**也**返回可用手机号（决定「无真凭据时能否端到端联调登录链路」） | 影响 B1 对**开发期**的阻塞程度（真机验收仍需真凭据） | 读 `WechatService` 的 `getPhoneNumber(...)` 私有实现里 Mock 分支的返回形态 |
| **U11** | 🔴 **短信登录的管理员门禁要不要同批改成权限码口径？**（`smsLogin` 现走 `roles ∋ 'admin'` 角色码，本单走权限码 ⇒ 同一句「管理员」在两条渠道上是两个口径，正是 §2.3 要防的「两套真值」） | 决定要不要把 `smsLogin` 一并收窄 | 需用户裁定（§12 待裁定-3） |
| **U12** | 🔴 **§4.3 的 S2 格沿用 vs 收紧**：`smsLogin` 在「命中非 admin」时**有意**回「该账号非管理员，请使用员工登录入口」并逐字论证了为什么可以不同 ⇒ 本单沿用（承认该手机号是某企业非管理员员工可被探测）还是收紧成 A 组？ | 决定反枚举强度与既有实现是否要改 | 需用户裁定（§12 待裁定-3） |
| **U10** | `agent:quickreply` 现是否**已从 `RegistrationService.defaultPermissions` 彻底移除**（它仍出现在 `migration-archive/V29`、`V32` 与 `.github/templates/frontend-fix.yml`） | 决定「移除一个码」的完整弧线长什么样（§3.2.2 的先例复用） | `git grep -n "agent:quickreply" origin/main -- backend/ frontend/` |

---

## 附录 A：现状复算命令（**全部实测于 `origin/main @ 78c67effc`**）

```bash
# A1 agent:chat 不存在（本单最关键的一条读数）
git grep -n "agent:chat" origin/main                       # ⇒ 0 命中

# A2 实测的权限码全集（agent 命名空间只有两个码）
git grep -ohE '"[a-z_]+:(view|chat|manage|create|update|delete|use|send|list)"' origin/main -- 'backend/**' \
  | sort | uniq -c | sort -rn

# A3 权限目录真值源（含 agent:session 的逐字中文名）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java \
  | grep -nE 'defaultPermissions|"agent:session' 

# A4 role='admin' ⇒ ["*"]（四处分支）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/RoleService.java \
  | grep -n '"\*"'

# A5 米宝唤出现状：小程序端零权限门
git grep -n "permission" origin/main -- 'frontend/bmini-app/src/pages/chat/' 'frontend/bmini-app/src/store/'   # ⇒ 0 命中

# A6 wechat appid/secret 只有空占位
git show origin/main:backend/admin-api/src/main/resources/application.yml | grep -n "WECHAT_BMINI"

# A7 元守卫现状（三条判据 + stripComments + 两项防空跑前置）
git show origin/main:frontend/bmini-app/tests/bmini-login-retired.test.ts

# A8 501 占位仍在
git grep -n "NOT_IMPLEMENTED" origin/main -- 'backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java'

# A9 LoginFailureGuard 的常量与调用点
git grep -n "LoginFailureGuard" origin/main -- 'backend/**'

# A10 bmini 双编译能力
git show origin/main:frontend/bmini-app/package.json | grep -nE 'plugin-platform-(weapp|h5)|build:(weapp|h5)'

# A11 废弃端点的实际形态：端点仍在、仍 permitAll、仍收 phoneCode，但恒抛 401（不是 404、不是可用）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java | grep -n -A8 "public LoginResponse bminiLogin"
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/controller/AuthController.java | grep -n -B2 -A6 'PostMapping("/bmini/login")'
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java | grep -n "api/auth/bmini/login"

# A12 微信 B 端渠道调用能力已实现（本单不是零起点；Mock 分支在 code2Session 里）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/WechatService.java \
  | grep -nE "bminiGetPhoneNumber|bminiCode2Session|Mock 模式"

# A13 跨租户按手机号查账号的方法仍在主线上（本单核心冲突）
git grep -n "selectActiveUsersByPhoneIgnoreTenant" origin/main

# A14 权限码目录真值源**不在 db/**：employee:create 只在 Java 种子里（抽取面若只看 db 会漏一批码）
git grep -n "employee:create" origin/main -- 'backend/admin-api/src/main/resources/db/**'      # ⇒ 0 命中
git grep -c "employee:create" origin/main -- 'backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java'

# A15 agent:quickreply 的退役弧线（「权限码新增/移除」的既有先例）
git grep -n "agent:quickreply" origin/main

# A16 空跑陷阱：登录端点在 permitAll 里被逐条点名（新端点不加进去就永远 401）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java | grep -n "api/auth/"
```

## 附录 B：本文的引用纪律（自证）

- 引用源码**一律写仓库相对全路径**，**一律不写行号**（规避 `Case Trust Gate` 规则 G 的 `CASE-TRUST-STALE-LINE-REF`，且活跃文件行号数分钟即失效）；定位改用**符号 / 文本锚点**（类名、方法名、常量名、端点路径、目录描述逐字）。
- **不把推断写成事实**：主会话转述的内容标「据 … 转述 / 待核」（如 I1/I3，见 §5.2 与 U4）；网查内容**附来源 URL 与实取日期**（§5.1）。
- **未核实项**统一登记在 §13，**不散落在正文里伪装成结论**。
