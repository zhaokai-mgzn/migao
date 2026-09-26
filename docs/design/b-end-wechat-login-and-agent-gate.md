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
> | 裁定⑤ ~~（已改判）~~ | 2026-09-26 | 租户消歧方式 = **手机号全局匹配；命中多个企业时，让用户选企业**（不是「先填企业编码」，也不是「每企业独立小程序」） | 🔴 **已被裁定⑥改判**：「**让用户选企业**」**不再是设计分支** ⇒ 改为**在入驻入口消灭歧义**（§14）。原文保留在此**仅作沿革**，**不得据此实现** |
> | 裁定⑥ | 2026-09-26 | 「**不应该出现同一手机号有多家企业的情况，从商家入驻入口应该限定死**」 | 🔴 **本稿的核心改判**：「登录时消歧」→「**入驻时不允许产生歧义**」⇒ §4（登录分支改判）+ **新增 §14（入驻入口唯一性约束设计）** |
> | 裁定⑦ | 2026-09-26 | 「**路 X / 路 Y**」之争**作废**：路 Y（换实时验证组件、证明持有者后再列企业名）**不再必需** ⇒ 不必引其成本与新令牌机制；**路 X 的 fail-closed 形态保留**（异常兜底） | §4.4.4 / §5.6（路 Y 降级为「已评估、因源头消歧不采用」）；**不变式 I4 / I5 保留**（§5.2.2，与歧义无关） |
> | 裁定⑧ | 2026-09-26 | `agent:chat` 回填范围 = **只回填 `admin` 角色**（严格）；🔴 **交付物必须包含「上线当天批量授权」** | §3.2.3 + **§3.2.5**（批量授权：给谁 / 谁执行 / 怎么一次性完成 / 失败怎么发现） |
> | 裁定⑨ | 2026-09-26 | **不绑 `openid`** ⇒ 每次微信授权拿手机号（约 0.03 元/次）；**不新增表、不做解绑流程、不引入跨租户主键风险** | §5.7 R6 / §7.1 / §12（原待裁定-1 **已裁**） |
> | 裁定⑩ | 2026-09-26 | 「授权唤出米宝」的粒度 = **员工级**（因 `users.permissions` 是**快照式**，「岗位级」不是生效口径） | §8.2 / §12（原待裁定-2 **已裁**） |
>
> **本单只出设计**：先定口径，再落码。**本文不含任何实现改动**。
>
> ## 修订记录（2026-09-26，第二轮：裁定⑥~⑩）
>
> | 轮次 | 改了什么 | 依据 |
> |---|---|---|
> | 第 1 轮 | 初稿：**登录时消歧**（0/1/N 三分支 + 路 X / 路 Y / 路 Z 权衡）+ 米宝唤出授权门 | 裁定⓪~⑤ |
> | **第 2 轮（本稿）** | ① **0 命中 / 1 命中 = 正常路径**；**N 命中不再是「让用户选」的设计分支** ⇒ 改判 **fail-closed + 告警 + 可行动引导**（§4.1 / §4.3 / §4.4.4）；② **路 X / 路 Y 之争作废**（路 Y **已评估、不采用**，§5.6）；③ **新增 §14「入驻入口唯一性约束设计」**（含**粒度待裁定**、落点、存量核对 SQL、并发兜底）；④ 回填范围 / `openid` / 授权粒度三条落定；⑤ 新增**「上线当天批量授权」交付物**（§3.2.5） | 裁定⑥~⑩ |
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
> | 3 | 「§4.3 必须五合一（连『有几家』都不能说）」+「只回『命中多家』不列名 ⇒ 仍是枚举位 ⇒ 不成立」 | ❌ **证伪**：既有 `smsLogin` **就**单独回「该手机号关联多个租户账号…」⇒ 「说有几家」是**已被接受的既有口径**。⇒ 该形态**成立**（= 路 X）；**第 2 轮起**路 X 的 **fail-closed 形态**已是本单正式口径（作为**异常兜底**，§4.4.4 / §4.3.1），原稿那一格判断错误 | §4.3 / §5.6 |
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

小程序端给**企业管理员**一条免密路径（微信授权拿手机号 → 在**跨租户**范围内按手机号查账号 → **期望恰好命中 1 家企业** → 签发与 #5485 **同一套** JWT），**浏览器仍走账号密码**；「**同一手机号有多家企业**」这件事**从源头消灭**（入驻入口限定死，**§14**）⇒ 登录侧 **0 命中 / 1 命中是正常路径**，**N 命中只是数据完整性异常**（**fail-closed + 告警 + 可行动引导**，**不再让用户选企业**）；同时把「谁能唤出米宝」从「人人可唤」改成**按权限码**：管理员（持该组权限码）默认可唤，其他员工**需被管理员授权**才可唤，未授权时给「需要管理员授权」+ 可行动引导（**两端同样生效**）。

**与 issue 正文的关系（已收敛，沿革登记，不藏）**：#5642 正文的「范围 · 1 🔴 租户怎么确定」与「关键设计裁定」两处写的是「在**已确定租户内**匹配」「匹配**只在已确定的租户内**做」；第 1 轮曾按**裁定⑤**（手机号全局匹配 + **多企业让用户选**）判定「正文与裁定⑤ 冲突」，并在 §5.6 论证「让用户选」在微信快验证组件下不成立。

⇒ **本稿按裁定⑥ 收口**：**全局匹配保留**（与既有 `smsLogin` 同形，且 I1 只管签发不管查询 —— §4.4.1 / §5.2.1），**「让用户选」取消**（歧义改由**入驻入口**消灭，§14）。⇒ **正文「手机号在多企业命中 ⇒ fail-closed」这一条现在直接成立**；第 1 轮登记的「正文与裁定⑤ 冲突」**已随改判消失**（§9.1 第 2 条的 ⚠️ 注同步更新）。

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

### 1.1 🔴 六条「issue 正文与实测不符」的读数（**必须先看**）

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
| **3** | **岗位矩阵**（回填给谁） | ✅ **已裁定（裁定⑧）：只回填 `admin`**，其余岗位**有意不回填**（见 §3.2.3 / §3.2.5） | `attachDefaultPermissions(tenantId, <role>, List.of(...), permissionByCode)` 五个岗位逐个点名 |
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

🔴 **这里有一个必须由用户确认的取舍**（第 1 轮登记为「§12 待裁定-0」；**现已由裁定⑧ 裁定**，见下）：
**「只回填 `admin`」意味着上线当天，除管理员外所有员工的米宝入口从「可唤」变成「需授权」** —— 对**客服**（其岗位职责就是天天用米宝查单/查售后）尤其明显。两条路：
- **(i) 严格收窄**：只回填 `admin`。**符合裁定⓪的字面**（「其他员工需要授权才能唤出」），但上线是一次**行为回退面较大的变更**，需配套**告知 + 批量授权工具**（或在员工管理里支持按岗位批量勾选）。
- **(ii) 宽回填 + 后续收窄**：把 `agent:chat` 回填给**原本就持 `agent:session` 的岗位**（= 客服 + 运营），理由是「这两类岗位今天就是米宝的高频使用者」。**但**这与裁定⓪「其他员工需要授权」**张力明显**，且**开了「按现状回填」的口子就再也收不回来**（同 `V129` 的「只收窄不放宽」纪律）。
- **本文推荐 (i) 严格收窄**，并把「上线告知 + 批量授权」列为**落码必做的配套**（否则会变成「功能上线了但客服当天干不了活」的事故）。**理由**：裁定⓪是**用户逐字的产品意图**，而 (ii) 是用迁移把意图改掉 —— 那是**改判**，不该由迁移来做。

> ✅ **本条已由用户裁定（2026-09-26，裁定⑧）**：**取 (i) 严格收窄 —— 只回填 `admin` 角色**；且**交付物必须包含「上线当天批量授权」**（否则客服 / 运营等岗位的米宝从「可唤」变「需授权」，属「功能上线了干不了活」的事故形态 —— **本仓有先例**）。执行细则见 **§3.2.5**。⇒ 本节的两条路**不再是待裁定项**（原「§12 待裁定-0」已裁）。

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

#### 3.2.5 🔴 上线当天的批量授权（**裁定⑧ 的交付物，必做**）

**为什么必须有**：回填**只给 `admin`**（裁定⑧）⇒ 上线当天**除管理员外所有员工**的米宝从「可唤」变「需授权」。而**客服 / 运营的岗位职责就是天天用米宝**（查单、查售后）⇒ 若没有当天的批量授权，上线 = **一线干不了活**。**这是本仓登记过的「功能上线了干不了活」事故形态**，因此它不是「配套建议」，是**交付物**。

| # | 问题 | 答案（**落码必须按此写进上线单**） |
|---|---|---|
| **①** | **给谁** | **非 `admin` 角色的在册员工中、上线当天仍需使用米宝的岗位**（由**各企业管理员**决定）。平台侧给出的**建议名单**（不是自动执行）：客服（`customer_service`）、运营（`operator`）、销售（`sales`）—— 依据 §2.2 岗位矩阵：这三类岗位在改动前**本来就能唤**（现状「人人可唤」），其中持 `agent:session` 的是米宝高频使用者。**财务 / 仓管等**不在建议名单（由商家按需勾）。🔴 **平台侧不代勾**：代勾 = 用数据改动改掉裁定⓪「其他员工需要授权」的产品意图（同 §3.2.3 的 (ii) 宽回填，属**改判**） |
| **②** | **谁执行 + 何时** | 执行人 = **企业管理员**（持 `employee:create` 的人），在**员工管理页**勾选 `agent:chat`（既有交互，落 `users.permissions` 快照）；平台侧负责**上线前告知 + 上线后对账**。⏰ **时机 = 与本单代码同一次发布窗口**（不得延到「下次发版」） |
| **③** | **怎么一次性完成**（三条形态，须选定一条） | **B-a 逐人勾选**：现状能力，零新增实现（员工管理页逐个勾 ⇒ 落 `PUT /api/admin/users/{id}`，`@RequirePermission("employee:create")`）；**20 人以上企业不现实**，且**漏勾不会被任何机制发现**（除非做 ④）。**B-b 一次性 SQL（运维 attended）**：对「租户 × 岗位名单」把 `agent:chat` **合并**进 `users.permissions` —— ⚠️ `users.permissions` 是 **`TEXT`**（存 JSON 数组字符串，`V1__add_permissions_to_users.sql` 加列；`schema.sql` 亦有同一句），**必须**按 `permissions::jsonb` 解析后**数组合并**（不能字符串拼接；非法 JSON 会让整条语句报错）、且必须**幂等**；⚠️ 它**绕过**「授予集 ⊆ 操作者自身权限」护栏（§2.2 问题 C）与既有审计 ⇒ 走这条**必须**留可复算名单 + 事后补审计。**B-c 新增「按岗位批量授权」入口（本单外的实现，推荐终态）**：员工管理页支持按岗位 / 多选批量勾 `agent:chat`，走既有 `@RequirePermission("employee:create")` + 授权护栏 + `AuditLogService` ⇒ **唯一「既不绕过护栏、又能一次性完成」的形态**。**推荐**：交付物按 **B-c** 落（排期不允许时用 **B-b 兜底 + 事后补审计**；**B-a 只作为员工数很少的企业的默认**） |
| **④** | **失败怎么发现**（**不许只写「注意」**） | 四条读数，缺一条就不算做了：**(1) 对账（现取，按企业）** — 粗筛 `SELECT u.tenant_id, count(*) FROM users u WHERE u.deleted=0 AND u.status='active' AND u.permissions IS NOT NULL AND u.permissions LIKE '%agent:chat%' GROUP BY 1` 与目标名单逐企业比对；精确判定用 `u.permissions::jsonb @> '["agent:chat"]'::jsonb`（先排除非法 JSON 行）⇒ **差集非空 = 漏授权**。**(2) 上线冒烟（每企业抽 2 个账号）** — 被授权账号：`GET /api/auth/me` ⇒ `capabilities.mibaoChat == true` **且**能发出第一条消息；未授权账号 ⇒ `false` **且**看到「需要管理员授权」（§8.5 G2~G4）。**(3) 审计计数** — §5.5 的 `MIBAO_ACCESS_GRANT` 行数 == 操作次数（**走 B-b 而没有补审计 ⇒ 这里就是缺口**）。**(4) 用户可自陈（最后一道，不是主要手段）** — 未授权态的可行动引导（少了它就只剩「客服自己来问」） |

**本单的交付物边界（照实登记）**：本单**只出设计**（含上面这份操作单的形态与判据）；**批量授权入口本身的实现（B-c）与上线当天的执行动作都不在本单**。

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
   │   8a. 0 命中（正常）/ N 命中（🔴 数据完整性异常 ⇒ fail-closed + 告警 +      │
   │       可行动引导，**不列企业名、不让用户选**，§4.3 S3 / §14）/ 非管理员 ⇒ 失败 │
   │   8b. 1 命中且是管理员：                                            │
   │       ← 签发与 #5485 同一套 JWT（RS256，claims 同构）               │
   │       ← **不绑 openid**（裁定⑨ ⇒ 每次授权都走 getPhoneNumber）        │
   │                                   │                               │
   │ 9. 存 TOKEN / USER / TENANT_ID（复用既有 STORAGE_KEYS）             │
```

**逐条口径**：

| # | 口径 | 依据 / 约束 |
|---|---|---|
| 1 | 新增端点 `POST /api/auth/bmini/wechat-login`，**不得**复活已废弃的 `POST /api/auth/bmini/login` | 后者是元守卫判红的字面量之一（`frontend/bmini-app/tests/bmini-login-retired.test.ts` 的 `hits(/\/api\/auth\/bmini\/login/)`）；**本单改造守卫时也只放行新路径**（§7） |
| 2 | 前端**只**传 `loginCode` + `phoneCode`，**不传 `tenantId`** | 与 #5485 同纪律（`frontend/bmini-app/src/utils/auth.ts` 注释逐字：「租户**只**由标识里的企业编码解析，前端**不解析租户、不传 tenantId**（否则『任意数字即可切租户』）」）⇒ 本单的租户由**服务端查库结果**决定，同样**不由前端传**；🔴 **且本单不存在「用户选企业」这一步**（裁定⑥/⑦）⇒ **没有任何前端传入的租户/企业标识**（I5 的机械形态见 §5.2.2） |
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

> ⚠️ **本节已修订两次**：① 第 1 轮按 §4.4.1 的实测修订（原稿要求「五合一」全合并，与**既有的 `smsLogin` 实现冲突**）；② 第 2 轮按**裁定⑥/⑦** 改判（S3 从「一个设计分支」改为「**异常态**」，§4.3.1）。以下表为准；修订理由见本节末「§4.3 修订说明」。

**总原则（本稿修订后）**：**凡「不能签发凭据」的路径，一律 `401 + AUTH_FAILED`**（同状态码 + 同 `error.code`）。**文案是否逐字相同分三组**（见下）：A 组=正常失败（**逐字合并**，反枚举）；B 组=**异常态**（多企业命中 = 脏数据，单独文案 + **必须告警**）；C 组=与账号存在性无关（锁定 / 基础设施 / 参数）。既有实现**已经有意**区分了其中一格 ⇒ 本单**要么沿用、要么显式改判**，不能默默不一致。

| # | 情形 | HTTP | `error.code` | 文案（**逐字**） | 是否与其它情形合并 | 备注 |
|---|---|---|---|---|---|---|
| S1 | 手机号**未命中任何**租户账号 | `401` | `AUTH_FAILED` | 「手机号授权未通过，请用账号密码登录」 | **A 组**（`smsLogin` 逐字：「该手机号未注册」⇒ 语义同格，文案按本渠道重写） | 与 #5485 的 `BusinessException.authFailed(...)` 同源 |
| S2 | 命中 **1** 个企业，但该手机号**不是管理员**（在册员工 / 管理员以外岗位 / 被停用） | `401` | `AUTH_FAILED` | **逐字同 S1** | **A 组** | 🔴 任务要求的「反枚举」正落在这一格。⚠️ **但 `smsLogin` 在格上「有意不同」**：它逐字回「该账号非管理员，请使用员工登录入口（用户名@企业编码 + 密码）」，并在源码注释里**显式论证**了为什么可以不同（见下） |
| S3 | 命中 **N≥2** 个企业 | `401` | `AUTH_FAILED` | 「该手机号关联多个企业，无法免密登录，请改用浏览器账号密码登录，并联系管理员核对入驻信息」（**逐字待定稿**，形态见 §4.3.1） | 🔴 **异常态单独一格（B 组）—— 与 S1 不同** | 🔴 **本稿改判（裁定⑥/⑦）**：N 命中在「入驻入口限定死」之后**期望取值恒为空** ⇒ 它**不再是一个设计分支，而是一条数据完整性断言** ⇒ **fail-closed + 服务端告警 + 可行动引导**，**绝不列出企业名、绝不进入任何「选择企业」流程**（§14.4 的 M6 判据） |
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
| **B 组（异常态单独文案）** | S3（多企业命中 = **脏数据/异常**） | `401` + `AUTH_FAILED`，文案**说明「关联多个企业」并给可行动引导**（改账号密码 + 核对入驻信息），**不列企业名**；**同时必须告警**（日志 + 指标计数 + 审计行，见 §4.3.1） | **改判后**：正常数据下**永不出现** ⇒ 允许单独文案的代价（泄露「≥2 家」这一位）**只在异常态发生**；沿用既有 `smsLogin` 的同格口径，**但不再是「让用户选」的入口**。⚠️ 若选择「与 A 组逐字合并」，则用户侧拿不到任何线索（只能靠服务端告警 + 运营外呼）—— 取舍见 §4.3.1 |
| **C 组（与存在性无关，允许不同）** | S6 锁定, S7 基础设施, S9 参数 | 各自文案 | `LoginFailureGuard` 的键语义（「被尝试的标识」而非「已存在的账号」）⇒ 对任意手机号一视同仁 ⇒ 不构成枚举位（其 Javadoc 逐字论证） |

#### §4.3 修订说明（**与原稿的差异，逐条登记**）

| # | 原稿 | 修订后 | 为什么改 |
|---|---|---|---|
| 1 | S3 并入 S1（**五合一**） | S3 **独立为异常态**（B 组）：文案说明 + 引导 + **告警**，**不列企业名、不让用户选** | 既有 `smsLogin` **已经**单独回这一格（逐字「该手机号关联多个租户账号…」）⇒ 不必比它更严；**更关键的是裁定⑥/⑦**：入驻入口限定死后 N 命中**期望为空** ⇒ 它退化为**数据完整性断言**（该 fail-closed 并告警，而不是让用户选） |
| 2 | S2 并入 S1 | **保留** S2 并入 S1（A 组） | ✅ 但**与 `smsLogin` 有意不同** —— 它在 S2 格上回「该账号非管理员，请使用员工登录入口」，并在源码注释里逐字论证：「这里与员工登录的反枚举口径**有意不同**：员工登录失败不区分病因（防探测账号是否存在），而「**你是员工**」这件事在本路径上已由「手机号在这家企业里命中非 admin 账号」确定。」⇒ 🔴 **本单必须二选一**：① 沿用（= 承认「该手机号是某企业的非管理员员工」可被探测）；② 收紧成 A 组（= 改判既有实现）。**登记为 U12** |
| 3 | — | 新增 B 组 / C 组的显式分组 | 原稿只有「合并 / 可区分」两句话，不足以指导实现 |

🔴 **S3 已定案，S2 仍待裁定**：**S3（多企业命中）随裁定⑥/⑦ 定案** —— 它是**异常态**（源头消歧后期望恒为空）⇒ **fail-closed + 告警 + 可行动引导**，**不列企业名、不让用户选**（§4.3.1）。**S2（命中但非管理员）**的「沿用 vs 收紧」**仍是待裁定项**（原 §12 待裁定-3，= 短信登录口径统一，**唯一仍待用户拍板的一条**）。

#### 4.3.1 🔴 S3（多企业命中）的落法：fail-closed + 告警 + 可行动引导

**裁定⑥/⑦ 之后 S3 的性质变了**：它**不再是一个产品分支**（「让用户选企业」已作废），而是一条**数据完整性断言** —— 正常数据下**永不出现**；一旦出现 ⇒ **是脏数据或异常**（存量核对见 §14.5；源头约束见 §14）。

| 面 | 落法 | 判据 / 红证 |
|---|---|---|
| **用户侧（必须可行动）** | `401 + AUTH_FAILED` + 文案给出**两条出路**：① **改用浏览器账号密码登录**；② **联系管理员核对入驻信息**。⚠️ **不列企业名**、**不下发候选集**、**不签发任何选择令牌** | 响应体里出现企业名 / 候选列表 ⇒ **红**（M6，§14.7）；文案退回泛化「登录失败」⇒ 红（用户失去可行动线索） |
| **服务端侧（必须告警）** | `WARN` 日志（**不落手机号明文**，用 §4.2 的 `HMAC` 前 16 字节或后四位掩码）+ **指标计数**（新增一个计数位，命名归落码时定）+ 一条 `AuditLogService` 审计行（`action` 建议 `LOGIN_WECHAT_MULTI_TENANT_ANOMALY`，`actionDetails` **不含手机号明文**） | 去掉告警 ⇒ 红（**"不出声的异常"等于没有兜底**：脏数据会一直存在而无人知道） |
| **反枚举边界（诚实登记）** | 该文案**确实泄露「该号 ≥2 家企业」这一位** —— 但：① 它**只在异常态**出现（正常数据下为空）；② 走到这一步的人**已通过微信手机号授权证明了手机号可解出**（§5.1：**不保证**是持有者，故这仍是残余风险）；⇒ 登记为 **R8**（§5.7） | — |

🔴 **一处留给评审的取舍（本文给出推荐，但不假装它已被裁定）**：S3 文案**是否保留「关联多个企业」字样**？
- **(a) 保留（本文推荐）**：它把「我该怎么办」说清楚（核对入驻信息）—— 符合裁定⑥/⑦「可行动引导」的逐字要求；代价 = 异常态泄露「≥2 家」这一位（R8）。
- **(b) 收紧为与 A 组**逐字**相同**：泄露面归零，但用户侧**拿不到任何线索**，只能靠**服务端告警 + 运营主动外呼**兜 —— 这要求告警链路**真的有值守面**（否则脏数据用户只会看到「登录失败」）。
⇒ **推荐 (a)**；若选 (b)，则**告警必须有值守面**（判红自己开单那一类），否则就是把问题藏起来。

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
| 多租户歧义 | 拒绝（未指定租户时） | **同形：拒绝**（**fail-closed**）；区别见右栏 —— 但**不再是「让用户选」** | ✅ **裁定⑥/⑦ 后二者一致**（第 1 轮登记的「冲突」消失）：N 命中在两条渠道上都 = **拒绝**；本单额外要求 **告警 + 可行动引导**（§4.3.1），因为源头消歧后它是**异常态**（§14） |
| 管理员门禁 | `roles ∋ 'admin'`（**按角色码**） | **按权限码**（裁定③） | ⚠️ **口径升级**：本单用权限码，比既有更细（§2） |
| 凭据 | 既有 JWT | **同一套** | ✅ 复用 |
| 限频 | `SmsService` + `LoginFailureGuard`（#5531） | **`LoginFailureGuard`**（同族，新 scope） | ✅ 复用（§5.4） |

🔴 **注意上面第 4 行：`smsLogin` 的管理员门禁走的是 `roles ∋ 'admin'`（角色码），而裁定③要求本单走权限码。** ⇒ **本单比既有实现更严**（权限码集合可被自定义岗位/快照满足，而 `role='admin'` 只有一个值 —— 见 §2.2）。**这不是回退，是收窄/精细化。** 但同时暴露一个**待决问题**：**短信登录要不要同批改成权限码口径？**（否则同一句「管理员」在两条渠道上是两个口径 —— 正是 §2.3 要防的「两套真值」）。**登记为 U11。**

### 4.4.4 多企业命中：**裁定⑥/⑦ 之后的定案**（原「与裁定⑤ 的正面冲突」已消失）

**第 1 轮的冲突**：`smsLogin` 的既有行为是「多租户命中 ⇒ 拒绝」（逐字「该手机号关联多个租户账号，**请通过对应租户入口登录或指定租户后重试**」），而**裁定⑤**要求「多企业命中 ⇒ **让用户选企业**」⇒ 二者互斥（要列企业名就得先把企业名给到可能**不持有**该号的操作者，§5.1 官方逐字：快验证组件**不保证**是持有者）。

**本稿的定案（裁定⑥ + 裁定⑦）**：**冲突消失** —— 因为「让用户选」**不再是设计分支**。多企业命中**改从源头消灭**（入驻入口限定死，**§14**），登录侧只保留**异常兜底**：

| 路 | 内容 | 本稿处置 |
|---|---|---|
| **X（= 既有 `smsLogin` 的 fail-closed 口径）** | 多租户 ⇒ **拒绝**；文案给可行动引导（改账号密码登录 + 核对入驻信息），**不列企业名** | ✅ **本单的正式口径**（= §4.3 S3 + §4.3.1），**作为异常兜底保留**；与既有实现**同形**，且**零新机制、零新表、零新码、零持有者证明成本**，已被 `AU-002` / `SmsLoginRoleGateTest` / 豁免台账覆盖 |
| **Y（先证明持有者，再列企业名让选）** | 换用**手机号实时验证组件** `getRealtimePhoneNumber` + 一次性选择令牌（`selectToken`） | ❌ **已评估，因源头消歧而不采用**（裁定⑦）。**因此省掉**：① 实时验证组件的调用（**其计费 / 额度本单未取证 = U3** ⇒ 不得声称省下某个具体金额）；② **新令牌机制**（一处 Redis 键 + 一个端点 + 其失败路径）。⚠️ **口径澄清（不是改判）**：0.03 元/次是**手机号快速验证组件**的官方资费，它在本单**仍然每次登录都调用**（裁定⑨ 不绑 `openid`）⇒ **那笔成本照付**；见 §5.6 末与 §5.7 R6 |
| **Z（直接列企业名，不额外证明）** | 快组件 + 直接列出企业名 | ❌ **明确不成立**（§5.1 官方逐字：不保证实时验证 + 用户可自主添加号码） |

🔴 **两点必须一起读**：① **路 X 保留的是它的「fail-closed 形态」**，**不是**「只说有多个」这个泄露位被认可 —— 后者在本稿里降级为**异常态**（§4.3.1，含告警 / R8）；② **`selectActiveUsersByPhoneIgnoreTenant` 仍然不需要改**（它是候选集查询，正常路径 0/1 命中都要用它）—— **这就是「复用 + 只补差量」的具体含义**。

### 4.5 🔴 落码前置：新端点必须进 `SecurityConfig` 的 `permitAll`

实测 `backend/admin-api/src/main/java/com/migao/admin/security/SecurityConfig.java` 的 `permitAll` **逐条列了**认证入口（含 `"/api/auth/employee/login"`、`"/api/auth/bmini/login"`）。
⇒ 新增的 `/api/auth/bmini/wechat-login` **若不加进该列表**，请求会在 **Spring Security 层**被拦（**不是**业务 401），表现为「端点写了、单测也过、前端永远 401」——

> 🔴 这是本仓多次登记过的「**绿了但没跑**」形态：**本地单测直调 service 层全绿，而真实入口在最外层就被挡掉**。

⇒ **落码必做**：① 加进 `permitAll`；② 落一条判据（§9.2 N9）断言「该路径在 `permitAll` 里」——**否则没人会因此变红**。⚠️ 该判据必须是**静态读 `SecurityConfig`** 或**真实 HTTP 打端点**，**不能**是「直调 service 断言成功」（那是空跑）。

---

## 5. 🔴 手机号全局匹配的安全论证（**+ 裁定⑥/⑦ 的收口**：歧义改从源头消灭）

> 本节回答两件事：① 微信 `getPhoneNumber` 到底证明了什么（**核实，非凭印象**，§5.1）；② 在裁定⑥/⑦ 之后，**歧义为什么不需要在登录侧解决**（源头消歧，§14）。**第 1 轮的结论「裁定⑤ 不成立」仍然成立且已被用户采纳**（裁定⑤ 明文改判为裁定⑥）。

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
⇒ 因而：**把「该手机号所属企业列表」展示给操作者，是信息泄露**（操作者可能只是**自主添加**了一个不属于自己的号码）。⇒ 这正是**「让用户选企业」被取消**（裁定⑥/⑦）的**技术理由**：既然登录侧拿不到「持有者已验证」，那就不该在登录侧展示归属；**改在源头（入驻入口）不产生归属歧义**（§14）。

**残余不确定度（照实登记，未核实）**：用户在「自主添加号码」流程里是否**必须**通过一次短信验证码（若必须，则「自主添加」也只证明「可收该号短信」⇒ 仍是**持有者证明**，本节的结论要**弱化**为「快验证组件的**返回值**不保证实时，但添加流程可能已含持有者校验」）。**本次未取证**（微信文档未写该流程细节；需真机实测或查阅「手机号快速验证组件常见问题」）。
🔴 **本稿对该条的处置（裁定⑦ 的结果）**：**它不再决定任何设计分支** —— 第 1 轮里它「单独决定走路 X 还是路 Y」，而**路 Y 已评估、不采用**（§4.4.4 / §5.6）⇒ 降级为**背景事实**，保留在**未核实项 U1**（§13）**仅为记录**，**不构成落码前置**（除非将来有人要重启「展示企业归属」这一类设计）。

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
| 「**让用户选企业**」违反 I1 / I3 吗？ | 🔴 **该设计已被取消**（裁定⑥/⑦），不构成需要论证的形态 | 第 1 轮的论证仍然成立且留档：「选 = 用户自己挑 ≠ 系统兜底」⇒ 不违反 I1 的意图；**但** I3 的字面是「多租户命中且未指定 ⇒ **拒绝**」，而「让用户选」是**先不拒绝**。⇒ 当时要自洽必须补新不变式；**本稿改从源头消歧（§14）**：多企业命中在正常数据下**永不出现**，故 **I3 的字面**（拒绝）**逐字成立**，不再需要为「让用户选」补任何东西 |
| 需要补新不变式吗？ | ✅ **需要，但只剩两条（I4 / I5），且 I4 的形态简化了** | 见下 |

**建议新增的不变式（修订后两条，作为本单的护栏，写进 RBAC / 登录真值源）**：

- **I4（可见性门槛，本稿保留并简化）**：跨租户「**可见信息**」的强度**不得超过**持有者证明的强度。**本稿的具体形态**（因为「让用户选」已取消）：
  ① **正常路径（0 命中 / 1 命中）**：**不下发任何企业归属信息**（不列企业名、不给候选集）；
  ② **异常路径（N 命中）**：**同样不列企业名、不下发候选集**，只给「改用账号密码 + 核对入驻信息」的可行动引导（§4.3.1）；
  ③ **禁止**在未来以「证明持有者」为名重启「列出企业名让用户选」（路 Y）—— 若真要重启，**必须先回到本设计单并重新裁定**（并重新引入 cost / 令牌机制的评估）。
  > 第 1 轮 I4 的原始表述（「要列出企业名仍须先有当次持有者证明」）**保留其精神**；本稿把它的**机械判据**从「有没有 selectToken」换成更简单也更可判的形态：**响应里不存在企业名列表**（§14.7 M6）。
- **I5（签发守卫）**：任何一次签发，`tenant_id` 必须等于**服务端查库得到的那一行账号的 `tenant_id`**；**不存在**「前端传入 / 用户选择 / 默认回退」任一来源的 `tenant_id` 进入签发路径。（把 I1 的**意图**机械化：串号在结构上不可表达。）
  > ⚠️ **注意与既有实现的差异**：`smsLogin` **接受**一个 `tenantId` 入参（用于消歧），但它的用法是「**在候选集里筛**，筛不到就拒绝」—— **不是**「按传入的 tenantId 查库」。⇒ I5 的准确表述是「**传入的 `tenantId` 只能用于筛选服务端已查出的候选集，绝不能作为查询键**」。这两者有本质区别（前者不可能串号，后者可以）。**本单的微信登录端点连这个入参都没有**（§4.1 第 2 条：前端只传 `loginCode` + `phoneCode`）⇒ I5 在本单是**结构上成立**的。
- ~~I6（选择后重鉴权）~~ ⇒ **并入 I4**（「选择前必须证明」已覆盖「选择后重鉴权」的场景；单列会造成两条互相重叠的不变式）。

⇒ **回答第 1 轮的那个问题「选企业 ≠ 跨租户兜底？还是必须补一条新的不变式？」**：**「选企业」在语义上确实 ≠ 跨租户兜底**（兜底 = 系统替用户挑一个；选择 = 用户自己挑），**但因为 I3 的字面是 fail-closed，所以当时必须补 I4 + I5 才能自洽**。**本稿按裁定⑥/⑦ 把「选企业」整条取消** ⇒ I3 的字面**逐字成立**，I4 简化为「不下发归属信息」、I5 结构上成立。
🔴 **且实测给出的更强结论仍然成立**：**I1 从来不禁止跨租户查库**（§5.2.1）⇒ 本单在 I1 上**没有**需要新补的东西。

### 5.3 反枚举：不得用任意手机号探出「某手机号是不是某企业管理员」

**威胁模型**：
1. 攻击者持有手机号 `P`（或任意猜测的号段）；
2. 攻击者在小程序里走登录链路，令 `phoneCode` 解出 `P`；
3. 若服务端**区分**了「未命中 / 命中但非管理员 / 命中且是管理员」，攻击者即得到 **`P` 的归属与权限画像**（跨**全部**租户！比单租户探测更严重）；
4. ~~若服务端还会**列出企业名**（裁定⑤字面）~~ ⇒ **本稿已取消该形态**（裁定⑥/⑦）：**不列企业名、不下发候选集** ⇒ 攻击者**无法**建立 **`P` ↔ 企业**映射表。（第 1 轮登记的风险 4 随之关闭；残余只剩 §4.3.1 的「≥2 家」这一位，且**只在异常态**出现 = R8。）

**处置**：**A 组的逐字合并（{S1,S2,S4,S8} ⇒ 同 401 + 同 code + 同文案）就是这条要求的落地**；**S3（多企业命中）不再并入 A 组，而是作为异常态单独处置**（§4.3.1：说明 + 引导 + **告警**），**但它绝不进入「让用户选企业」的流程**。**关键点**：
- A 组文案**不得**出现「该手机号不是管理员」这类**区分性**措辞；
- ⚠️ §4.3 的 S6「尝试次数过多」是**允许**不同的 —— 依据是 `LoginFailureGuard` 的键语义（「被尝试的标识」而非「已存在的账号」），它对**任意**手机号一视同仁 ⇒ **不构成枚举位**（既有 Javadoc 逐字论证）。这条**已在原实现里被论证过**，本单**沿用不另立**。

**红证（可执行）**：对 `{未命中, 命中非管理员, 命中但停用, phoneCode 无效}` 四组输入，断言响应 **逐字节相同**（`status` + `error.code` + `error.message`）；任一组不同 ⇒ 红。**且**必须有一条**正证**（命中唯一管理员 ⇒ 200）防「全部拒绝」蒙过判据；**再加一条**异常态判据（多企业命中 ⇒ 401 **且**响应体**不含企业名 / 候选列表**，§14.7 M6）。

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

### 5.6 🔴 多企业命中：**本稿的结论 + 路 X / Y / Z 的最终处置**

**结论（一段话，已按裁定⑥/⑦ 改写）**：**「全局匹配」部分成立且无需新增机制**（`smsLogin` 已在跑同样形态，见 §4.4.1）；**「多企业让用户选企业」这条设计已取消** —— 因为快 `getPhoneNumber` **不证明持有者**（§5.1 官方逐字），列出企业名 = 把「某手机号属于哪些企业」交给一个**可能只是自主添加了该号码**的操作者。⇒ **歧义改从源头消灭**（入驻入口限定死，**§14**）⇒ 登录侧 **N 命中 = 异常态**，按 **fail-closed + 告警 + 可行动引导**处置（§4.3.1）。**这就是裁定⑦ 的「路 X 的 fail-closed 形态保留为异常兜底」。**

**三条路的最终处置（第 1 轮的「互斥、由用户选」已消失 —— 只剩一条被采用）**：

**路 X（= 既有 `smsLogin` 的 fail-closed 口径；✅ 本单采用，作为异常兜底）**
- 服务端**全局查**手机号（✅ 成立）；**恰好 1 个企业命中且是管理员** ⇒ 登录成功（= **正常路径**）；**0 命中** ⇒ 按 A 组失败；**多企业命中** ⇒ **拒绝** + 可行动引导 + **服务端告警**（**不列企业名**，§4.3.1）。
- **为什么采用**：① 满足裁定①②（免密登录真的可用）；② **与既有实现同形**（`smsLogin` 就是这么做的）⇒ **零新机制、零新表、零新码、零持有者证明成本**，且已被 `AU-002` / `SmsLoginRoleGateTest` / 台账覆盖；③ 与 I3 的 **fail-closed 字面一致**；④ 相对既有的**唯一新增泄露面 = 0**（异常态那一位见 R8）。
- **它不再有第 1 轮登记的那个代价**（「多企业命中的用户拿不到免密 ⇒ 若他们正是目标用户则本单无效」）：**该形态被裁定⑥ 从源头消灭** —— 多企业命中**不应存在**，若存在就是**待修的脏数据**（核对 SQL 见 §14.5），**不是需要用设计去迁就的用户群**。

**路 Y（先证明持有者，再列企业名让选；❌ 已评估，因源头消歧而不采用 —— 裁定⑦）**
- 原设计要点（**留档**，防将来有人重新发明）：换用**手机号实时验证组件** `getRealtimePhoneNumber`（官方逐字「在每次请求时，平台均会对用户选择的手机号进行**实时验证**」）；**仅当**实时验证通过 ⇒ 才返回「命中 N 家企业」与**企业名列表**；`tenant_id` **绝不**作为查询键 —— 服务端为本次选择签发一次性、短 TTL、绑本次验证的 `selectToken`，用户选定后按**服务端侧记录的候选集**筛选，再签发真 JWT。
- **不采用的理由**：歧义在源头已被消灭（§14）⇒ 登录侧**不再需要**「证明持有者后展示归属」这条能力。
- **因此省掉的东西（逐条，不许含糊）**：① **实时验证组件的调用** —— ⚠️ 其**计费 / 额度本单未取证（U3）** ⇒ **只能写「省掉这项调用」，不得声称省下某个具体金额**；② **新令牌机制**（一处 Redis 键 + 一个端点 + 一次性 / 短 TTL / 失败路径的完整设计）；③ 为「展示归属」必须补的 I4 强化形态与一组新判据。
- 🔴 **口径澄清（不是改判，是防误读）**：第 1 轮文档与裁定文字里都出现过「0.03 元/次」。**0.03 元/次是「手机号快速验证组件」的官方资费**（§5.1 官方逐字「每次组件调用成功，收费 0.03 元」），而它在本单**仍然每次登录都调用** —— 因为裁定⑨ 明确**不绑 `openid`**（每次微信授权拿手机号）⇒ **那笔成本照付，不因作废路 Y 而省掉**。把「省掉 0.03 元/次」读成「本单零调用成本」是误读；**要真的省掉它，唯一路径是绑 `openid`**，而这条已被裁定⑨ 否掉（取舍已做过一次，本文只登记、不重开）。

**路 Z（快组件 + 直接列出企业名；❌ 明确不成立）**
- **信息泄露**（§5.1 官方逐字：不保证实时验证 + 用户可自主添加号码），**且比既有实现更宽**（既有至多说「有多个」）。**本稿连「列企业名」这个能力都不保留**（I4 的形态②）。

**路 W（前端传 `tenantId` 当查询键 / 先填企业编码；❌ 已被 #5485 否掉）**
- `frontend/bmini-app/src/utils/auth.ts` 注释逐字：「否则『任意数字即可切租户』」。⚠️ 第 1 轮曾提示「路 Y 里前端**也**回传一个选择，但它只是候选集里的一个索引」—— **本稿连这个回传都不存在**（§4.1 第 2 条）⇒ I5 在结构上成立。

### 5.7 残余风险登记（**照实登记，不粉饰**）

| # | 风险 | 现状 | 处置 / 去向 |
|---|---|---|---|
| **R1** | **手机号自主添加是否校验持有者**未取证 ⇒ §5.1 结论的强度不确定 | **未核实（U1）** | **不再是落码前置**（裁定⑦：路 Y 不采用）⇒ 降级为**背景事实**：它只影响「将来是否有人重启『展示企业归属』设计」这一件事。真机实测（用一个非本人号码走「自主添加」）仍**可选**做，但**不挡本单** |
| **R2** | 实时验证组件的**可用性与额度**未取证 | **未核实（U3）** | **不再阻塞**（路 Y 不采用，裁定⑦）⇒ 仅当将来重启路 Y 时才需要 |
| **R3** | 「同号跨多租户」的**存量规模**未知 | 🔴 **仍未查证**（= §14.5） | 本机**无法连库**（无本地 Postgres / 无 Docker）⇒ **必须由有库权限的人**跑 §14.5 的两条只读 SQL 并把输出粘回 #5642。**不假设干净** |
| **R4** | `LoginFailureGuard` 的键是**单维度** ⇒ 「员工密码登录」与「微信登录」两条路**分摊尝试次数** | **本单有意不改** | 登记；改进属 #5531 的口径扩展，不在本单 |
| **R5** | `super_admin` / `service` 旁路身份**天然满足**三码判定 ⇒ 若该判定被用于**端点授权**，旁路身份会绕过「微信登录才可唤」的意图 | 判定函数设计成**只用于「能力位」下发**（§3.3 的 `capabilities.mibaoChat`），**不**作为端点 `@RequirePermission` 的替代 | 落码时须复核：**不得**把 `capabilities.mibaoChat` 当作授权（授权仍由 `@RequirePermission` 强控） |
| **R6** | 快验证组件**计费**（0.03 元/次成功） | **每次登录都调**（裁定⑨：**不绑 `openid`**）⇒ 该成本**照付** | 运营项：估量调用量。⚠️ **不要把它与「作废路 Y」混为一谈**（§5.6 末的口径澄清）：路 Y 省掉的是**实时组件**的调用与其**未取证**的计费（U3）+ 选择令牌机制；**0.03 元/次这笔钱不省** |
| **R8** | **S3 异常态文案泄露「该号 ≥2 家企业」这一位**（§4.3.1）：走到这一步的人只证明「手机号可解出」，**不保证是持有者**（§5.1） | **仅在异常态出现**（源头消歧后正常数据下为空） | 处置：① **不列企业名**（已定）；② **必须告警**（否则脏数据无人知）；③ 存量核对 + 修复后该形态收敛为 0（§14.5 / §14.6）；④ 若选择「与 A 组逐字合并」（§4.3.1 取舍 (b)）⇒ 该位归零，代价是用户拿不到线索 |
| **R9** | **入驻唯一性的绕过面**（§14.9）：① 管理员手机号可被 `updateUser` **改成**另一个租户管理员在用的号（其查重**只到租户内**）；② 超管 / 运维直接改库；③ 将来新增的建租户入口 | **本单给出设计，不改码** | ① 落码时把该处校验扩为「管理员维度跨租户」（§14.9 推荐）；②③ **无机械判据**可拦（照实登记）；④ 若要求「改号也不能绕过」⇒ 必须上 DB 层约束（§14.4 的 D2） |
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

⚠️ **两处共用 `agent:session` 这个码 —— 但本单不再扩大它的语义负载**（**本稿修正一处过期表述**）：第 1 轮初稿曾把 `agent:session` 当作「可唤出米宝」的判据（= 那个被否掉的「复用既有码」选项），**该选项已被 §3.2.1 实测否掉**：本单**新增独立码 `agent:chat`**，与 `agent:session`（坐席读码）、`agent:session:manage`（坐席写码）**三者互不蕴含**。⇒ 「持 `agent:session`」**不**自动获得米宝唤出权（**客服默认不可唤**，符合裁定⓪）；本单**不新增菜单节点**、**不动 `admin-web` 的「在线接待」入口**。**若用户希望「客服默认可唤」，正确做法是在 §3.2.5 的批量授权里给客服岗位授权 `agent:chat`，而不是让两个码互相蕴含。**

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
| openid | 绑定已整条退场 | **不绑**（裁定⑨：每次微信授权拿手机号；**不新增表、不做解绑流程、不引入跨租户主键风险**） | ❌ **不回退** |
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
⇒ **这个权限码已经由 §3.2 定案**（**就是 `agent:chat`**，新增码）—— 粒度也已由**裁定⑩** 定为**员工级**（§12 待裁定-2 **已裁**；上线当天的按岗位动作见 §3.2.5，那是**一次性初始化**，不是生效口径）。

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
   > ✅ **本稿已收敛**：裁定⑥/⑦ 之后，这一条与设计**逐字一致**（N 命中 = 异常态 ⇒ fail-closed + **告警** + 可行动引导，**不列企业名**，§4.3.1）。第 1 轮登记的「正文与裁定⑤ 冲突」**已消失**。
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
| N1 | **A 组逐字合并**：`{未命中, 命中非管理员, 命中但停用, phoneCode 无效}` 的响应 `status` + `error.code` + `error.message` **逐字节相同** | 任一组不同 ⇒ 红 | §4.3 |
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
| **N13** | 🔴 **N 命中 = 异常态 fail-closed**（裁定⑥/⑦）：多企业命中 ⇒ `401 AUTH_FAILED` + **响应体不含任何企业名 / 候选列表 / 选择令牌** + **告警已触发**（日志 + 指标计数各一条断言） | 改成「列出企业让用户选」/ 去掉告警 ⇒ 红 | §4.3.1 / §14.7 M6 |
| **N14** | 🔴 **入驻入口唯一性（应用层两层，§14.3）**：① 提交时「该手机号已是**任一租户的管理员**」⇒ 拒绝且**不落库**（断言 `tenant_applications` 零新增）；② 审批建号前二次校验（构造 submit→approve 之间该号成为管理员的 TOCTOU）⇒ **拒绝且不建租户**（断言 `tenants` 零新增） | 去掉任一层 ⇒ 红 | §14.3 / §14.7 M1~M2 |
| **N15** | 🔴 **上线当天批量授权可对账**（裁定⑧ 的交付物）：存在一条**现取**的对账读数（按企业的目标名单 vs `users.permissions` 实际命中），且被授权账号的 `GET /api/auth/me` ⇒ `capabilities.mibaoChat == true`、未授权账号 ⇒ `false` + 看到「需要管理员授权」 | 去掉对账 / 冒烟断言 ⇒ 红（**否则「批量授权做没做」无人知道**） | §3.2.5 ④ |

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
- ❌ **不做「让用户选企业」**（路 Y / 路 Z 不采用 —— 裁定⑦；见 §4.4.4 / §5.6）；
- ❌ **不在登录侧做「先证明持有者 ⇒ 再展示企业归属」**（I4 的形态②：本单连这个能力都不保留；要重启须回到本设计单重新裁定）；
- ❌ **不绑 `openid`**、**不新增 openid 映射表**、**不做解绑流程**（裁定⑨）；
- ❌ **不在本单做存量数据修复**：若 §14.5 的核对 SQL 命中「同号多企业」⇒ 修复是**独立改动**（§14.6），本单只给核对 SQL 与 fail-closed 口径；
- ❌ **不动 `CHANGELOG.md`**（docs-only 豁免，AGENTS.md 铁律 7）。

---

## 11. 依赖与阻塞

| # | 项 | 类型 | 影响 | 处置 |
|---|---|---|---|---|
| **B1** | `WECHAT_BMINI_APPID` / `WECHAT_BMINI_SECRET` **全仓只有空占位** | 🔴 **阻塞（环境）** | 无 appid ⇒ 连 `code2Session` 都调不了 ⇒ **微信登录链路无法真机验证** | 需**运维**提供（非个人主体 + 已完成认证的小程序 —— 快验证组件官方逐字：「目前该接口针对**非个人主体**，且完成了**认证**的小程序开放」）|
| **B2** | 快验证组件**计费** 0.03 元/次成功 | ⚠️ 成本 | 登录链路**每次**调用计费（裁定⑨：不绑 `openid` ⇒ **不省**） | 估量调用量；⚠️ **不要**把它算作「作废路 Y 省下的成本」（§5.6 末口径澄清） |
| **B3** | 实时验证组件（路 Y）**可用性与额度**未取证 | ✅ **已无影响** | 路 Y 已评估、不采用（裁定⑦） | 仅在将来重启路 Y 时取证（U3） |
| **B4** | 手机号「自主添加」是否校验持有者**未取证** | ✅ **已解除阻塞** | **不再决定任何设计分支**（路 Y 不采用）⇒ 降级为背景事实 | 可选：真机实测（U1）；**不挡本单** |
| **B5** | 「同号跨多租户」存量规模未知 | 🔴 **仍未查证（照实登记）** | 决定**脏数据修复**的工作量，**不再决定登录侧设计**（登录侧已定 fail-closed） | **必须**由有库权限的人跑 §14.5 的两条只读 SQL，把输出粘回 #5642（本机无库、无 Docker ⇒ 主会话做不到） |
| **B6** | `agent:chat` 不存在 ⇒ 裁定④**字面**不可落码 | ✅ **已解（本单）** | 结论：**必须新增该码**（§3.2.1 论证「无码在管 ⇒ 不存在复用选项」）⇒ 不再是阻塞项，转为**落码任务**（§3.2.2 五处清单）。「回填给谁」已由**裁定⑧** 定为**只回填 `admin`**（§3.2.3 / §3.2.5） |
| **B8** | 🔴 **新端点若不加进 `SecurityConfig.permitAll`，真实入口会在最外层 401**（而单测直调 service 全绿） | 🔴 **落码必做（易漏）** | 「绿了但没跑」形态 | 加进 `permitAll` + 落判据 §9.2 N9（§4.5） |
| **B9** | ✅ **不阻塞（已解除）**：`selectActiveUsersByPhoneIgnoreTenant` 仍在，**但它是被台账登记的既有豁免**，且 `smsLogin` 已在跑同一形态 | ✅ **已解** | **复用即可**（§4.4.2）；**不新增**第二个跨租户查询（新增会多一条台账条目，而台账**只许缩短**） | 只补台账文字（说明它**同时**服务两条渠道）+ 更正 `AuthService.bminiLogin` 的过期 Javadoc 措辞（§4.4.2） |
| **B10** | 🔴 **两处口径不一致需裁定**：`smsLogin` 管理员门禁走 **`roles ∋ 'admin'`**（角色码）而本单走 **权限码**；且 `smsLogin` 在 S2 格**有意**单独回文案 | 🔴 **需裁定** | 不统一 = 同一句「管理员」两条渠道两套真值（§2.3 要防的形态） | §12 待裁定-3 |
| **B7** | `agent:session` 同时承载「人工接待工位」 | ✅ **已解除** | 本单**不**用它当唤出判据（§3.2.1 定案：新增 `agent:chat`）⇒ 语义负载**未扩大**（§6.3 已修正过期表述） | 无需用户确认 |
| **B11** | 🔴 **「上线当天批量授权」目前没有批量入口**：`AdminUserController` 只有 `GET 列表 / GET 单个 / POST / PUT {id} / DELETE {id} / PUT {id}/reset-password / PUT {id}/status`，**无批量端点**；员工管理页也无按岗位批量勾选 | ⚠️ **交付物缺口** | 只有 B-a（逐人）能立刻用 ⇒ 大企业上线当天不可行 | 见 **§3.2.5 ③**（推荐 B-c：新增按岗位批量授权入口；B-b：一次性 SQL 兜底 + 事后补审计）。**本单只出设计，实现不在本单** |

---

## 12. 待裁定（**本文不拍板**；各给选项 + 推荐 + 理由）

> 🔴 **本稿的状态**：裁定⑥~⑩ 落定后，**本节只剩 `待裁定-3` 一条仍待用户拍板**。其余各条**保留原文作为沿革**（并标注「已裁定」+ 依据轮次），**不得据旧文实现**。

### 待裁定-0（✅ **已裁定，2026-09-26 = 裁定⑧**）：`agent:chat` 的**回填范围**

**已定（本来就不是待裁定项）**：`agent:chat` **必须新增**（§3.2.1：**「谁能唤出米宝」今天没有任何码在管 ⇒ 不存在「复用既有码」的选项**）。

**裁定结果**：取 **(i) 严格收窄 —— 只回填 `admin` 角色**；其余岗位（客服 / 运营 / 销售 / 财务 / 自定义）**有意不回填**，迁移头部须逐字登记「这是有意收窄，不是漏授」。
🔴 **同时裁定：交付物必须包含「上线当天批量授权」**（否则上线当天客服 / 运营等岗位的米宝从「可唤」变「需授权」= 「功能上线了干不了活」的事故形态，**本仓有先例**）⇒ 执行细则（给谁 / 谁执行 / 怎么一次性完成 / 失败怎么发现）见 **§3.2.5**。
⇒ **第 1 轮的 (ii) 宽回填选项作废**（它与裁定⓪「其他员工需要授权才能唤出」张力明显，等于用迁移改掉产品意图）。

### 待裁定-0b（✅ **已收敛为设计定论，不再是待裁定**）：`agent:session` 与「人工接待工位」的语义耦合

「在线接待」菜单节点（`frontend/admin-web/src/config/menu.ts`）用的是 `agent:session`。本单**不改**它。**定论**：本单新增的 `agent:chat` 与它**是两个独立的码**（§3.2.1）⇒ 「持 `agent:session`」**不**自动获得米宝唤出权，**语义负载未被本单扩大**（§6.3 已同步修正那处过期表述）。**若希望「客服默认可唤」** ⇒ 正确做法是在 **§3.2.5 的批量授权**里给客服岗位授 `agent:chat`，**而不是**让两个码互相蕴含。⇒ **无需用户裁定。**

### 待裁定-3（🔴 **本稿唯一仍待用户拍板的一条**）：短信登录与本单的**口径统一**

> ✅ **本稿的范围声明**：裁定⑥~⑩ 落定之后，**本文只剩这一条待裁定**。**标注：等用户裁定后再定实现范围**（不影响本设计单的其他结论）。

实测发现 `backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java` 的 `smsLogin` **已经在做同一件事**（跨租户手机号 + 仅管理员 + 多租户 fail-closed），但有两处口径与裁定③/本单**不一致**：

| # | 差异 | 现状（`smsLogin`） | 本单（裁定③） | 需要裁定 |
|---|---|---|---|---|
| 1 | **管理员判定口径** | `roles ∋ 'admin'`（**角色码**） | **权限码**（三码全持） | 🔴 **要不要把 `smsLogin` 同批改成权限码口径？** 不改 ⇒ **同一句「管理员」在两条渠道上是两套真值**（正是 §2.3 要防的形态）；改 ⇒ 会**动既有已测实现**（`SmsLoginRoleGateTest` 有 4 条拒绝用例 + 台账补偿控制文字要同步） |
| 2 | **S2 格（命中非 admin）文案** | **有意**单独回「该账号非管理员，请使用员工登录入口」+ 源码逐字论证「『你是员工』这件事在本路径上已由『手机号在这家企业里命中非 admin 账号』确定」 | §4.3 原稿要求并入 A 组（反枚举） | 🔴 **沿用还是收紧？** 沿用 ⇒ 承认「该手机号是某企业非管理员员工」可被探测；收紧 ⇒ 改既有实现 |

- **本文的推荐**：**两处都统一到裁定③的口径（权限码）+ 收紧 S2 到 A 组** —— 理由：① 用户已裁定「按权限码」（裁定③），让另一条渠道继续用角色码就是**两套真值**；② 反枚举对**两条**渠道应当同强度（`LoginFailureGuard` 的既有教训逐字：「同一认证链上两条路防护强度必须对齐，**否则弱的那条就是实际入口**」—— 同一逻辑适用于文案面）。
- ⚠️ **代价**：这**超出「只加微信登录」的最小改动面**（会动 `smsLogin` + `SmsLoginRoleGateTest` + 台账文字）。⇒ **若用户希望本单只做微信侧，则该差异必须登记为「已知的两套口径」并留去向**（不能默默不一致 —— 至少要有一条注释/台账指向它）。
- **若不做**：**必须显式登记**「`smsLogin` 用角色码、微信登录用权限码，两条渠道口径不同」+ 去向，否则下一个人会以为是漏改。

### 待裁定-1（✅ **已裁定，2026-09-26 = 裁定⑨**）：是否绑定 `openid`？

**裁定结果：不绑。** ⇒ **每次微信授权拿手机号**（约 0.03 元/次，**照付**，= §5.7 R6 / §11 B2）；**不新增表**、**不做解绑流程**、**不引入跨租户主键风险**。⇒ §7.1 的对应行同步改为「**不回退**」。
**第 1 轮的选项与取舍留档（不删，供将来重启时复用）**：

| 选项 | 内容 | 代价 | 收益 |
|---|---|---|---|
| **绑** | 首次微信登录成功后，把 `(openid, tenant_id, user_id)` 落一张映射表 | **多一张表 + 必须设计解绑流程**（换微信号 / 离职 / 换手机号）；且 openid **跨租户不唯一**（同一微信在不同小程序 appid 下 openid 不同；同 appid 下**同一租户**内唯一）⇒ 表设计必须**带 tenant_id**，否则又造一个跨租户主键 | 后续登录**免手机号授权**（少一次点击 + **省 0.03 元/次** ⇒ 直接缓解 B2） |
| **不绑（✅ 已采纳）** | 每次登录都走 `getPhoneNumber` | 每次多一次授权点击 + 每次计费 | **零新表、零解绑流程、零 openid 跨租户风险**；实现面最小 |
- ⚠️ **与 #5485 的关系**：绑 openid 是**部分回退** #5485（它把「绑定 openid → 二次免密」整条退役）⇒ 已裁**不绑** ⇒ **本单在 openid 面零回退**（§7.1 表格已列）。

### 待裁定-2（✅ **已裁定，2026-09-26 = 裁定⑩**）：「授权唤出米宝」的**粒度**与**权限码**

**裁定结果：粒度 = (a) 员工级**（按原设计单推荐）。理由：`users.permissions` 是**快照式**（`docs/wiki/RBAC.md` 逐字：「员工权限 = 员工管理页保存的勾选（`users.permissions` 快照），与岗位脱钩」）⇒ 「岗位级」**不是生效口径**，说成生效口径会造**第二套真相源**。
⚠️ **与 §3.2.5 的关系（不矛盾）**：上线当天的「按岗位批量授权」是**一次性初始化动作**（= 按岗位生成待勾名单），**之后一律走员工级勾选**。⇒ 粒度裁定是「**生效口径**」，批量授权是「**上线动作**」。

> ⚠️ **前提已变**：任务给这一条时的假设是「授权的码 = 复用既有码 or 新增码」。**§3.2.1 已实测否掉了「复用既有码」** —— 因为**唯一语义相近的 `agent:session` 承载的是「人工接待工位」，不是「唤出米宝」**，复用会让两个授权意图焊死。⇒ 本条现在**只剩一个子问题**（粒度），权限码那一栏已经**由 §3.2 定案**。

| 子问题 | 选项 | 代价 | 推荐 |
|---|---|---|---|
| **粒度**（第 1 轮曾列为「唯一仍需裁定」；**已由裁定⑩ 定为 (a)**） | (a) **员工级**（该员工可唤）<br>(b) **岗位级**（该岗位默认可唤） | (b) 需岗位默认权限勾选 → 但**本仓权限是快照式**（`docs/wiki/RBAC.md` 逐字：「员工权限 = 员工管理页保存的勾选（`users.permissions` 快照），与岗位脱钩」）⇒ 岗位级**不改变**已有员工的生效权限（只影响**新建**时的预填模板 + 迁移回填那一批） | **(a) 员工级**（✅ 裁定⑩）—— 因为快照式语义下「岗位级」**不是**一个生效口径，把它当成生效口径会造**第二套真相源**。⚠️ 与 §3.2.5 的「按岗位批量授权」**不矛盾**：那是**一次性初始化动作**，**生效口径仍是员工级** |

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
| **U1** | 微信快验证组件「自主添加号码」流程**是否要求短信验证**（⇒ 是否构成持有者证明） | ✅ **不再影响本单**（裁定⑦：路 Y 不采用 ⇒ 不展示企业归属）⇒ 保留为背景事实，仅在将来重启「展示归属」类设计时才有意义 | 可选：真机实测（用一个非本人号码走「自主添加」）|
| **U2** | 本仓（或线上）**「同一手机号跨多租户」的存量规模** | 🔴 **仍未查证**（本机无库、无 Docker）⇒ 决定**脏数据修复**的工作量；**不再决定登录侧设计** | **可执行 SQL 已给**：§14.5（含**规整后判重**的加固版 + 申请单维度 + 全用户维度三组）。**必须由有库权限的人跑**并把输出粘回 #5642 |
| **U3** | 「手机号实时验证组件」的**可用性 / 额度 / 计费** | ✅ **不再影响本单**（路 Y 不采用） | 仅在将来重启路 Y 时取证 |
| **U4** | `#5485` 的 **I1 / I3 逐字原文**（本文按 #5642 正文**转述**引用，未回溯原单） | 编号 / 措辞可能有偏差 | `gh issue view 5485` |
| **U5** | 既有「员工编辑 / 岗位授权」路径**是否已写审计**（⇒ §8.4 的留痕是不是真的缺） | 决定 §8.4 是「补」还是「已具备」 | 读 `AdminUserController` / 员工管理服务的写路径 |
| **U6** | `frontend/bmini-app` 是否已有 **`TARO_ENV` 分流**的既有范式（§6.1 / §7.3 C3 依赖它） | 影响 H5 分支的实现成本 | `git grep TARO_ENV frontend/bmini-app/src` |
| **U7** | `service` 令牌在**登录端点**上是否可达（§3.3 / R5 的前置） | 影响判定函数的写法 | 读 `SecurityConfig` / `ServiceTokenFilter` 的放行面 |
| **U8** | `UserMapper.selectActiveUsersByPhoneIgnoreTenant` **当前是否已被任何生产路径调用**（§4.4） | 若仍有活调用点，本单处置须一并收口 | `git grep -n selectActiveUsersByPhoneIgnoreTenant origin/main` |
| **U9** | **`WechatService` 的 Mock 模式覆盖到哪一步** —— `bminiGetPhoneNumber` 在未配置 appid 时是否**也**返回可用手机号（决定「无真凭据时能否端到端联调登录链路」） | 影响 B1 对**开发期**的阻塞程度（真机验收仍需真凭据） | 读 `WechatService` 的 `getPhoneNumber(...)` 私有实现里 Mock 分支的返回形态 |
| **U11** | 🔴 **短信登录的管理员门禁要不要同批改成权限码口径？**（`smsLogin` 现走 `roles ∋ 'admin'` 角色码，本单走权限码 ⇒ 同一句「管理员」在两条渠道上是两个口径，正是 §2.3 要防的「两套真值」） | 决定要不要把 `smsLogin` 一并收窄 | 🔴 **本稿唯一仍待用户拍板的一条**（§12 待裁定-3）；**等裁定后再定实现范围** |
| **U12** | 🔴 **§4.3 的 S2 格沿用 vs 收紧**：`smsLogin` 在「命中非 admin」时**有意**回「该账号非管理员，请使用员工登录入口」并逐字论证了为什么可以不同 ⇒ 本单沿用（承认该手机号是某企业非管理员员工可被探测）还是收紧成 A 组？ | 决定反枚举强度与既有实现是否要改 | 需用户裁定（§12 待裁定-3，**与 U11 同一条**） |
| **U13** | 🔴 **若在 `users` 上加「跨租户」唯一索引（§14.4 的 D2），是否会与 `.github/cases/auth.yml` 的 `AU-008` 口径打架**？该用例逐字钉的是「数据库侧唯一索引**只到租户内**」（对象是 `uk_users_tenant_username`，**不是** `phone`），其判据 `tests/unit_ci_workflows/test_tenant_scoped_user_queries.py` **同时校验迁移 V128 与建库脚本两份真相** | 决定 D2 能否直接落，或必须**同批扩写该用例/判据** | 落码前读该判据的实现面（`git show origin/main:tests/unit_ci_workflows/test_tenant_scoped_user_queries.py`）核它对 `phone` 索引是否敏感 |
| **U10** | `agent:quickreply` 现是否**已从 `RegistrationService.defaultPermissions` 彻底移除**（它仍出现在 `migration-archive/V29`、`V32` 与 `.github/templates/frontend-fix.yml`） | 决定「移除一个码」的完整弧线长什么样（§3.2.2 的先例复用） | `git grep -n "agent:quickreply" origin/main -- backend/ frontend/` |

---

## 14. 🔴 入驻入口唯一性约束设计（**裁定⑥ 的源头消歧**，本稿新增）

> **裁定⑥ 逐字**：「**不应该出现同一手机号有多家企业的情况，从商家入驻入口应该限定死**」
> **一句话**：把「同号多企业」从**登录时消歧**改判为**入驻时不允许产生** —— **在源头不产生歧义 > 在消费端处理歧义**。本节回答四件事：**约束粒度（🔴 仍需用户拍板）**、**落点**、**存量处置**、**并发兜底**。

### 14.1 实测现状（`origin/main @ 78c67effc`，锚点全部为符号 / 文本，无行号）

| # | 事实 | 证据（锚点） |
|---|---|---|
| 1 | ✅ **建租户入口只有一个** —— 生产代码里 `tenantMapper.insert` **唯一**调用点就是入驻审批 | `backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java` 的 `approveApplication`（`git grep -c "tenantMapper.insert" origin/main` ⇒ 命中文件**只有这一个**）。⇒ 「从入驻入口限定死」在这一面**是完备的**：没有第二条建租户路径可以让约束被绕过 |
| 2 | ⚠️ **既有的手机号查重只到「申请单」维度** | `RegistrationService` 的 `checkPhoneDuplicates(phone)` 查的是 `tenant_applications`：`status ∈ {pending, approved}` ⇒ 「该手机号已有入驻申请，请勿重复提交」；被 AI 驳回后 24h 冷却（`system` 降级驳回不冷却）。⇒ **效果上已经能挡住「同号开第二家企业」**（approve 后申请单行**不删除**，见 #3） |
| 3 | ✅ **申请单不会被删** ⇒ 上一行那道检查**有真实牙口** | `git grep -n "applicationMapper.delete" origin/main` ⇒ **0 命中**；`tenant_applications` 在生产 Java 代码里只有插入与更新。⇒ 这是 #2 能当约束用的前提 |
| 4 | 🔴 **缝隙 A（并发）** | `checkPhoneDuplicates` 是「先 `selectCount` 再 `insert`」，而 `tenant_applications(phone)` 只有**普通**索引（`backend/admin-api/src/main/resources/db/init/schema.sql` 的 `idx_tenant_applications_phone`，**不是**唯一索引）⇒ 两个并发请求可**同时**通过 ⇒ 两条 `pending` ⇒ **都能被 approve** ⇒ 同号两家企业。⚠️ Redis 那道限频是「每手机号每日 3 次提交 + 每 IP 每小时」（`RegistrationService` 的 `PHONE_DAILY_SUBMIT_LIMIT` / `REG_PHONE_KEY` / `REG_IP_KEY`）—— 它**限频但不防并发** |
| 5 | 🔴 **缝隙 B（管理员手机号可被改）** | `backend/admin-api/src/main/java/com/migao/admin/controller/AdminUserController.java` 的 `updateUser`（`PUT /api/admin/users/{id}`）**接受 `phone` 字段**；落 `backend/admin-api/src/main/java/com/migao/admin/service/UserService.java` 的 `updateUser(...)`，其口径逐字是「变更时校验**租户内**唯一」⇒ 可以把 A 企业管理员的手机号改成 B 企业管理员**正在用**的号 ⇒ **不经入驻入口**造出「同号多企业」 |
| 6 | 🔴 **缝隙 C（存量未查证）** | 本机**无法连库**（无本地 Postgres、无 Docker）⇒ 存量是否已有「同号多企业」**未查证**（照实登记，**不许假设干净**）⇒ 核对 SQL 见 §14.5 |
| 7 | **`users.phone` 的约束现状** | `VARCHAR(32)`、**可空**、**无唯一约束**，只有普通索引 `idx_users_phone`（均在 `schema.sql`）。两条既有部分唯一索引**都是租户内**的：`uk_users_tenant_worker_no`（`(tenant_id, worker_no) WHERE worker_no IS NOT NULL AND deleted = 0`）与 `uk_users_tenant_username`（`(tenant_id, username) WHERE username IS NOT NULL AND deleted = 0`，由 `backend/admin-api/src/main/resources/db/migration/V128__add_users_username_and_must_change_password.sql` 建）⇒ **「手机号跨租户唯一」在本仓是新东西** |
| 8 | **`users.permissions` 是 `TEXT`**（不是 JSONB），存的是 JSON 数组字符串 | `schema.sql` 的 `ALTER TABLE users ADD COLUMN IF NOT EXISTS permissions TEXT;`（同一句的源头是 `backend/admin-api/src/main/resources/db/migration-archive/V1__add_permissions_to_users.sql`）；写入形态见 `AdminUserController.updateUser` 的 `OBJECT_MAPPER.writeValueAsString(list)` ⇒ **影响 §3.2.5 与 §14.5 的 SQL 写法** |
| 9 | 入驻申请端点与审批端点 | `backend/admin-api/src/main/java/com/migao/admin/controller/RegistrationController.java`：提交 = `POST /api/auth/register`；审批 = `PUT /api/super-admin/registrations/{id}/approve`（`checkSuperAdminPermission()` 门禁） |

**结论（可落性判断）**：裁定⑥ **可落** —— 唯一建租户入口就在入驻审批链上（#1），既有查重已在正确的位置（#2），但**缺三样**：**一次「管理员维度」的显式校验**（落点见 §14.3）、**并发兜底**（§14.4）、**存量核对**（§14.5）。

### 14.2 🔴 待裁定 A（**粒度**）：管理员维度 vs 全用户维度

| 选项 | 含义 | 拦住了什么 | 影响面 / 误伤 |
|---|---|---|---|
| **(A1) 管理员维度（🔴 本文推荐，但需用户拍板）** | 一个手机号**只能作为一家企业的管理员**；它同时是**另一家企业的员工**是**合法**的 | 「同号开两家企业」= **用户逐字关心的那件事** | **无误伤**：「同一人在两家公司任职」不受影响。落点只需覆盖**入驻链**（§14.3）+ 管理员手机号变更面（§14.9） |
| **(A2) 全用户维度** | 一个手机号**不能同时**是 A 企业管理员与 B 企业员工，也不能是两家企业的员工 | A1 的全部 + 同号跨租户**任职** | 🔴 **误伤合法场景**（一人两司 / 员工跳槽未迁号）；且要**改既有实现语义** —— `UserService.createUser` 的「验证手机号唯一性」其 wrapper **带 `tenant_id`**（租户内唯一），A2 意味着**每个租户的员工写入路径都要多一次跨租户判定**；DB 层还需 §14.4 的 D2 |

🔴 **这一条的粒度主会话未能从裁定里唯一确定** ⇒ **必须由用户拍板**（本文不替用户决定）。
- **推荐 A1**，理由：① 它**恰好**达成裁定⑥ 的目的（「同一手机号有多家企业」）；② 全用户维度会**误伤**「同一人在两家公司任职」这一**合法**场景（布艺/建材行业里老板兼着两家公司并不罕见）；③ A1 的落点**收敛在入驻链**（一个平台级流程），A2 要动**所有租户的员工写入路径**（风险面完全不同）。
- ⚠️ **A1 的边界（照实说清）**：A1 下「同一手机号既是 A 的管理员、又是 B 的员工」是**允许**的 —— 若用户要的其实是 A2，**必须在裁定里明说**（因为 A2 的代价显著更大，且要一并处理 DB 索引与既有实现语义）。

### 14.3 落点（**应用层两层**，缺一层就漏）

| 层 | 位置（符号锚点） | 现状 | 本单要做的 |
|---|---|---|---|
| **① 提交时** | `RegistrationService.submitApplication` → `checkPhoneDuplicates(phone)`；端点 `POST /api/auth/register` | 只查 `tenant_applications`（**申请单维度**） | **扩为**「该手机号是否**已是任一租户的管理员**」的判定（按 A1 维度查 `users`：`role = 'admin'` ∧ `deleted = 0` ∧ 手机号规整后相等）；**保留**原有的「已有申请」文案（它是**更早**的一道，且申请单维度**仍需**保留） |
| **② 审批建号前** | `RegistrationService.approveApplication`（建 `Tenant` → `initializeDefaultRolesAndPermissions` → `userService.createUser(application.getPhone(), …, "admin", …)`）；端点 `PUT /api/super-admin/registrations/{id}/approve` | 🔴 **无任何跨租户手机号校验**；`UserService.createUser` 的手机号查重**只到租户内**（wrapper 带 `tenantId`） | 🔴 **必须**在建 admin 用户**之前**再校验一次 —— 理由是 **TOCTOU**：`submit` 与 `approve` 之间可能隔着数小时/数天，该号完全可能已在别处成为管理员（**并发 + 异步审批**两条路都通向这里）。冲突 ⇒ **拒绝批准**（fail-closed：**不建租户、不建管理员**）+ 给超管可行动文案 |

**错误文案与「免枚举」**：✅ **本链路不需要免枚举** —— 论证：`submitApplication` 的**第 1 步就是短信验证码校验**（`smsService.verifyCode(dto.getPhone(), dto.getSmsCode())`，`backend/admin-api/src/main/java/com/migao/admin/service/SmsService.java`），而手机号查重在**第 3 步** ⇒ 走到查重时，调用者**已经证明自己能收该手机号的短信**（= **持有者证明**，这比登录链路的微信快组件强：§5.1）。⇒ 告诉「该手机号已开通过企业」**不构成对未持有者的泄露**。
- ⚠️ **但顺序是判据**：短信前置校验必须**保持在查重之前**；判据要钉住这一点（§14.7 M3），否则「查重先跑」会把该端点变成**免证明的枚举口**。
- 文案形态：沿用既有 `BusinessException.validationError(...)` 口径（`checkPhoneDuplicates` 现状就是它）；**审批侧**的拒绝文案给超管/运营看（可与提交侧不同，它**不是**用户侧反枚举面）。
- ⚠️ **副作用登记**：这条约束意味着「**同一老板用同一手机号开第二家公司会被拒**」⇒ 需要一条**人工处置路径**（由超管在核对后放行 / 或让申请人改用另一持有号）。**本单只登记该需求，不设计该流程**。

### 14.4 🔴 待裁定 B（**并发兜底**）：要不要 DB 层唯一性保证？放哪张表？

**结论：要。** 应用层**挡不住并发**（§14.1 #4：SELECT-then-INSERT + 无唯一索引；两个并发提交会双双通过）。但**放哪张表**是有代价取舍的：

| 方案 | 约束（建议形态） | 拦住 | 代价 / 风险 |
|---|---|---|---|
| **D1（🔴 本文推荐）** | **平台级表**上的部分唯一索引：`tenant_applications (phone) WHERE status IN ('pending','approved')` | 缝隙 A（并发双提交） | ✅ **写入只发生在入驻路径**（平台级表，**不进任何租户的业务写路径**）；✅ 与「同一手机号在多租户合法（作为员工）」**零冲突**（该表根本不记录员工）；⚠️ **代价**：同号**永久**不能再提交（**即便原企业已注销 / 转让**）⇒ 需要一条人工处置路径（§14.3 末的副作用登记同族）；⚠️ **建索引前必须先核对存量**（存在重复行时 `CREATE UNIQUE INDEX` **直接失败** ⇒ 迁移红、部署卡住） |
| **D2** | **跨租户**部分唯一索引：`users (phone) WHERE role = 'admin' AND phone IS NOT NULL AND deleted = 0` | 缝隙 A **+ 缝隙 B**（管理员改号） | 🔴 **进入所有租户的 `users` 写入路径**：任何租户建 / 改管理员都会命中它，冲突会从 `DuplicateKeyException` 冒出来 ⇒ **每一处写入点都必须给可行动文案**，否则是 500；🔴 它是**跨租户**索引，与仓里 `.github/cases/auth.yml` 的 `AU-008` 口径（逐字「数据库侧唯一索引**只到租户内**」—— 虽然那条钉的对象是 `uk_users_tenant_username` **不是** `phone`）**同面相邻** ⇒ 落码前必须核 / 扩写该用例（**U13**，§13） |

**推荐**：**D1 + 应用层两层校验（A1 维度）**。
**D2 只在两种情形下才值得**：① 用户选 **A2**（全用户维度）；② 用户要求「**连改手机号都不能绕过**」（缝隙 B 必须堵死）。
🔴 **顺序铁律（无论 D1/D2）**：**先核对存量（§14.5）→ 再处置存量（§14.6，独立改动）→ 最后才建索引**。⚠️ **不能靠 `CREATE UNIQUE INDEX CONCURRENTLY` 绕开**：本仓迁移链由 `MigrationRunner` 按**文件名**判已应用、且范式是显式 `BEGIN/COMMIT` 事务（`V129` 的写作范式），而 `CONCURRENTLY` **不能在事务块里执行**。

### 14.5 存量数据处置（**照实登记：未查证** + 可执行核对 SQL）

**状态**：主会话**无法连库**（无本地 Postgres、无 Docker）⇒ 「存量是否存在同号多企业」**未查证**。**不许按「干净」假设**（这是裁定⑥ 落地的前置，也是 §14.4 建索引的前置）。以下 SQL **只读**，需由**有库权限的人**在云 dev / 生产只读副本上跑，并**把输出粘回 #5642**（这样它就从未查证变成已取证）。

```sql
-- ① 管理员维度（A1）：同一手机号出现在 ≥2 个租户的管理员账号上（= 裁定⑥ 要消灭的形态）
SELECT u.phone,
       count(DISTINCT u.tenant_id)                          AS tenant_cnt,
       array_agg(DISTINCT u.tenant_id ORDER BY u.tenant_id) AS tenant_ids,
       array_agg(DISTINCT t.code      ORDER BY t.code)      AS tenant_codes
FROM users u
JOIN tenants t ON t.id = u.tenant_id
WHERE u.deleted = 0
  AND u.role = 'admin'
  AND u.phone IS NOT NULL AND btrim(u.phone) <> ''
GROUP BY u.phone
HAVING count(DISTINCT u.tenant_id) > 1
ORDER BY tenant_cnt DESC, u.phone;
```

⚠️ **口径注意（否则会低估）**：`users.phone` 是**自由文本**（`VARCHAR(32)`、无格式约束）⇒ 同一个号可能有 `+86` / 空格 / `-` 的不同写法，上面的 `GROUP BY u.phone` 会把它们算成两个号 ⇒ **加固版**：

```sql
-- ①' 规整后判重（去掉非数字字符、取后 11 位），避免写法差异漏判
WITH norm AS (
  SELECT u.id, u.tenant_id, t.code AS tenant_code,
         regexp_replace(u.phone, '\D', '', 'g') AS digits
  FROM users u
  JOIN tenants t ON t.id = u.tenant_id
  WHERE u.deleted = 0 AND u.role = 'admin' AND u.phone IS NOT NULL
)
SELECT right(digits, 11)                                     AS phone_tail,
       count(DISTINCT tenant_id)                             AS tenant_cnt,
       array_agg(DISTINCT tenant_code ORDER BY tenant_code)  AS tenant_codes
FROM norm
WHERE length(digits) >= 11
GROUP BY right(digits, 11)
HAVING count(DISTINCT tenant_id) > 1
ORDER BY tenant_cnt DESC;
```

```sql
-- ② 申请单维度：同号多条 pending/approved（若命中 ⇒ 说明缝隙 A（并发）已经发生过）
SELECT phone, count(*) AS rows, array_agg(status) AS statuses,
       array_agg(id ORDER BY id) AS application_ids
FROM tenant_applications
WHERE status IN ('pending','approved')
GROUP BY phone
HAVING count(*) > 1
ORDER BY rows DESC;
```

```sql
-- ③ 全用户维度（A2）：只有用户选了「全用户维度」才需要跑 —— 同号跨租户（含员工）
SELECT u.phone, count(DISTINCT u.tenant_id) AS tenant_cnt,
       array_agg(DISTINCT u.role ORDER BY u.role) AS roles
FROM users u
WHERE u.deleted = 0 AND u.phone IS NOT NULL AND btrim(u.phone) <> ''
GROUP BY u.phone
HAVING count(DISTINCT u.tenant_id) > 1
ORDER BY tenant_cnt DESC, u.phone;
```

**若命中（存在脏数据）**：
1. **登录侧 fail-closed**：这些号在微信登录时会落 **S3 异常态** ⇒ `401` + 可行动引导 + **告警**（§4.3.1）⇒ **脏数据不会变成「可以选企业」的入口**（这是裁定⑥ 与第 1 轮设计的接缝，本稿已对齐）；
2. **修复路径属独立改动，不在本单**（§14.6）；
3. ⚠️ **未命中 ≠ 永久安全**：缝隙 A（并发）在约束落地前**仍会产生新的脏数据** ⇒ 核对与 §14.4 的 D1 **应当同批推进**（否则一边修一边长）。

### 14.6 存量修复：**明确不在本单**

若 §14.5 命中 ⇒ 需要一条**独立改动**（独立 issue / PR，**不在本设计单**）：
- **决策**：同号的 N 个管理员账号里**保留哪一个**（判据建议：最近登录 / 账号创建更早 / 该租户是否仍在营）；
- **动作**：其余账号**改号**（换成该企业实际持有的号）或**停用**；⚠️ 改号要动的是**登录凭据**（手机号是微信免密的唯一键）⇒ 必须与商家确认后再改，并留审计；
- **通知**：通知受影响商家 + 告知其新的登录方式（避免出现「昨天还能免密、今天不行了」的静默行为变更）；
- **复核**：修复后复跑 §14.5 的 ① / ①'，**必须归零**（这是该独立改动的验收判据）。

### 14.7 判据（**每条能红**，接 §9.2 的 N 系列）

| ID | 判据 | 红证 |
|---|---|---|
| **M1** | 提交入驻时，若该手机号**已是任一租户的管理员** ⇒ 拒绝且**不落库**（断言 `tenant_applications` **零新增**） | 去掉该校验 ⇒ 红 |
| **M2** | 审批建号前**二次校验**：构造「submit 后、approve 前该号在别处成为管理员」⇒ `approveApplication` **拒绝**且**不建租户**（断言 `tenants` **零新增**、`users` 零新增） | 去掉二次校验 ⇒ 红（**这正是 TOCTOU**） |
| **M3** | **顺序判据**：短信验证码校验**在**手机号归属查重**之前**（走到查重 ⇒ 已证明持有；§14.3） | 调换顺序 ⇒ 红（否则该端点变成免证明的枚举口） |
| **M4** | （若采纳 D1）`tenant_applications` 的**部分唯一索引**存在且谓词与 §14.4 逐字一致 —— **迁移 + 建库脚本两处真相都要核**（同 `AU-008` 的「两份真相」范式） | 去掉谓词 / 改成全表唯一 ⇒ 红 |
| **M5** | **并发**：两个并发同号提交 ⇒ **只落一条**（或第二条被拒） | 去掉 DB 约束 ⇒ 红 |
| **M6** | **N 命中（脏数据）⇒ 登录 fail-closed + 告警 + 响应不含企业名 / 候选列表**（= §4.3.1 与 N13） | 改成「列出企业让用户选」⇒ 红 |
| **M7** | （条款面）`.github/cases/auth.yml` 需覆盖「入驻入口唯一性」——**本单不改 cases**；**落码时必须一并补用例**（否则新约束**只有单测、没有条款面**） | 不补 ⇒ 该约束在用例库**不可见**（本单登记为落码必做） |

### 14.8 与既有不变式 / 用例面的关系

- **I5 不变**（`tenant_id` 来源仍是服务端查库结果）；本单**不新增**跨租户**查询**（沿用 `selectActiveUsersByPhoneIgnoreTenant`，§4.4.2）⇒ `truths_ref: auth.tenant-local-identity` 不受影响。
- ⚠️ **`users` 上的跨租户唯一索引（D2）与 `AU-008` 同面相邻**：`AU-008` 逐字钉「数据库侧唯一索引**只到租户内**」，其判据同时校验**迁移 V128 与建库脚本两份真相**（对象是 `uk_users_tenant_username`）。若上 D2，**必须先核该判据对 `phone` 索引是否敏感**（U13），必要时**同批扩写用例**（否则是新索引与旧条款表述打架）。
- ⚠️ **`users.permissions` 是 `TEXT`** ⇒ §3.2.5 的批量授权与对账 SQL **必须**显式 `::jsonb`（并先排除非法 JSON 行），**不能**用字符串拼接改写快照。

### 14.9 遗留 / 边界（**照实登记，不粉饰**）

| # | 遗留 | 处置 |
|---|---|---|
| 1 | **缝隙 B 在「A1 + D1」下仍然存在**：`AdminUserController.updateUser` 的手机号变更只校验**租户内**唯一（§14.1 #5） | **推荐**：落码时把该处校验**扩为「管理员维度跨租户」**（复用 §14.3 ② 的判定；一处预检，最小改动）。⚠️ 但**它仍是应用层**（并发下不保证）⇒ 若要求「改号也不能绕过」，**必须上 D2** |
| 2 | **超管 / 运维直接改库**、以及**将来新增的建租户入口** | **没有机械判据**能拦住（照实登记）。可做的只有：① `tenantMapper.insert` 调用点数量的守卫（**新增调用点即红**，可落成一条静态判据）；② 迁移里对约束的终态对账 |
| 3 | **存量未查证**（§14.5） | 需有库权限的人跑 SQL 并粘回 #5642 |
| 4 | **同号开第二家企业被拒后的人工通路**（老板确实要开第二家） | 本单**只登记需求**，不设计流程（§14.3 末） |
| 5 | **本单不含任何实现** | 判据 M1~M7 是**落码时**要落的，**本单只出设计** |

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

# A17 建租户入口**只有一个**（裁定⑥ 可落的前提）：tenantMapper.insert 的命中文件唯一
git grep -c "tenantMapper.insert" origin/main

# A18 申请单不会被删（既有手机号查重因此有牙口）
git grep -n "applicationMapper.delete" origin/main            # ⇒ 0 命中

# A19 既有手机号查重只到「申请单」维度 + 入驻第 1 步就是短信校验（免枚举的依据）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java \
  | grep -nE "checkPhoneDuplicates|verifyCode|PENDING_OR_APPROVED|PHONE_DAILY_SUBMIT_LIMIT"

# A20 users.phone 的约束现状（可空 / 无唯一约束 / 只有普通索引）+ permissions 是 TEXT
git show origin/main:backend/admin-api/src/main/resources/db/init/schema.sql | grep -nE "idx_users_phone|permissions TEXT|uk_users_tenant_(worker_no|username)"

# A21 员工的手机号查重**只到租户内**（缝隙 B 的来源）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/service/UserService.java | grep -n -A6 "验证手机号唯一性"

# A22 无批量授权端点（§3.2.5 的交付物缺口）
git show origin/main:backend/admin-api/src/main/java/com/migao/admin/controller/AdminUserController.java | grep -nE "@(Get|Post|Put|Delete)Mapping"
```

## 附录 B：本文的引用纪律（自证）

- 引用源码**一律写仓库相对全路径**，**一律不写行号**（规避 `Case Trust Gate` 规则 G 的 `CASE-TRUST-STALE-LINE-REF`，且活跃文件行号数分钟即失效）；定位改用**符号 / 文本锚点**（类名、方法名、常量名、端点路径、目录描述逐字）。
- **不把推断写成事实**：主会话转述的内容标「据 … 转述 / 待核」（如 I1/I3，见 §5.2 与 U4）；网查内容**附来源 URL 与实取日期**（§5.1）。
- **未核实项**统一登记在 §13，**不散落在正文里伪装成结论**。
- **本稿（第 2 轮）新增的自我约束**：① 凡「已核定 / 已评估不采用」的结论都**标明依据轮次**（裁定⑥~⑩），不改写第 1 轮的历史判断（改判处一律写「已被裁定X改判」）；② **未亲自复核的事实不写成事实**：存量数据、实时组件计费、`AU-008` 判据对 `phone` 索引是否敏感，三处均标 **未查证 / 待核**（§13 U2 / U3 / U13）；③ 与裁定措辞不一致的地方**只做口径澄清、不静默改判**（见 §5.6 末「0.03 元/次」那条）。
