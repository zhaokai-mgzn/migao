# RBAC 单一真值源：架构设计 + 精确行为差量表（第一阶段）

> **状态：设计阶段。本文件不改任何行为。**
> 本单只做两件事：① 穷举「角色 → 码 / 页面 → 码」现在被写在哪些地方（每处**机器现取的读数**）；
> ② 给出目标架构、逐角色 × 逐码 × 逐消费面 × 分三场景的**行为差量表**，供人过目后再决定动手。
> 关联：#5683（已关闭，「岗位默认权限写在两处」）、#5675 / #5682（菜单节点码 vs 页面第一屏读端点码，
> 残留 6 条）。**本单不开新 issue、不新增迁移、不改 `RoleService` / `RegistrationService` / 迁移 /
> ai-agent 镜像 / `menu.ts` / 端点注解中的任何一处。**

---

## 0. 一句话

「**某岗位有哪些码**」这一事实，仓库里现在**写在 7 处**；「**某页面/端点要哪些码**」这一事实，
现在**写在 8 处**；两处事实之间靠**注释、绊线、只许缩短的台账**维持一致。
issue #5683 已经用**两次补丁 + 一条不变量**把「角色 → 码」这一对的**两个副本**钉住了 ——
但副本仍然是两个，而且同一事实的另外 5 个副本（ai-agent 镜像、迁移链、`AUTHORIZATION_CENSUS` …）
仍然各写各的。**本单要治的是副本数，不是副本间的差值。**

---

## 1. ① 穷举现状的全部真值源（每处：位置 + 生效条件 + 消费方 + 同步机制）

> 全部读数为**机器现取**，机具 = `tests/unit_ci_workflows/test_agent_permission_parity.py` 里
> **既有的**解析器（`_source_map` / `build_world` / `parse_role_defaults` / `parse_role_fallback` /
> `parse_catalog` / `parse_menus` / `parse_menu_ts_nodes` / `parse_route_guard`）——
> 本单**没有造第二套解析器**（仓内 #3570 的既有教训，该文件头部逐字写着这条纪律）。

### 1.1 二十处真值源（逐处点名）

#### A 类 —— 「**角色 → 码**」（谁有什么）

| # | 位置（文件 + 符号锚） | 生效条件 | 谁消费它 | 与别处如何保持同步 |
|---|---|---|---|---|
| **A1** | `backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java` 的 `initializeDefaultRolesAndPermissions`（`attachDefaultPermissions(tenantId, <role>, List.of(...), permissionByCode)`） | **仅新租户注册**时执行一次，落库 `role_permissions` | 新租户的 `PermissionInterceptor` / `AuthService` / `UserController`（经 `RoleService.getUserPermissions` 读 `role_permissions`）；岗位权限页回填；员工弹窗预填 | **与 A2 靠注释 + 判据 14 逐角色码穷举**（`ROLE_FALLBACK_DIVERGENCES` 只许缩短，现取 **0** 条、上限 **0**）。**没有任何机制**保证它与 A6（迁移链）一致 —— 见 §3.1 |
| **A2** | `backend/admin-api/src/main/java/com/migao/admin/service/RoleService.java` 的 `getPermissionCodesForRole`（`switch (roleCode)`，7 个 `case` + `default -> List.of()`） | **三条运行时路径**（下表 1.2） | `PermissionInterceptor.getUserPermissions`、`AuthService` 的菜单/权限下发、`UserController`、`getEffectivePermissionCodesForRoleCode` | 与 A1 靠 **判据 14**（`problems_role_default_parity`）+ 注释。注释本身**不是**判据 —— #5683 的原始前提正是「把一句窄注释读成了全面声明」 |
| **A3** | `backend/ai-agent-service/tests/test_tool_permission_codes.py` 的 `ROLE_PERMISSIONS` | **测试/CI 期**（工具层授权判据的输入）；不参与运行时 | `tests/test_tool_permission_codes.py` 的 `TestRoleMirrorMatchesTheAdminApiSource`（6 条）+ `TestRoleMirrorGuardIsNotVacuous`（8 条） | **手抄件**（该文件 javadoc 逐字自述「`admin-api` 源码的**手抄件**」）。与 A1/A2 靠 `java_seeded_role_permissions()` / `java_fallback_role_permissions()` 现取解析 Java 源码后**集合比较**；`seeded_role_gaps == []` ∧ `fallback_role_gaps == []` |
| **A4** | 迁移链：`V29__backfill_default_positions.sql` / `V32__ensure_default_positions.sql` / `V43__create_processing_orders.sql` / `V111__create_inbound_orders_and_batches.sql`（以上四个在 `backend/admin-api/src/main/resources/db/migration-archive/`）+ `V124__backfill_read_permissions.sql` / `V125__backfill_write_permissions.sql` / `V129__backfill_domain_read_permissions.sql` / `V132__add_agent_chat_permission.sql`（在 `backend/admin-api/src/main/resources/db/migration/`）里的 `INSERT INTO role_permissions … JOIN permissions p ON p.tenant_id = r.tenant_id AND p.code …` | **仅存量租户**，每条按自己的谓词、按 `schema_migrations` 台账**只跑一次** | `RoleService.getUserPermissions` 的 `role_permissions` 分支（**优先级最高**，命中即返回） | **没有任何机制**与 A1 保持同步。判据 14 比的是「**种子 vs 回退**」，**不是**「存量 `role_permissions` vs 种子」（#5683 PR body ⑨ 的「适用边界」逐字登记了这一条）。**实测后果见 §3.1 第三行** |
| **A5** | `users.permissions` 列（员工级快照）—— 由 `backend/admin-api/src/main/java/com/migao/admin/service/UserService.java` 的 `createUser` / `updateUser` 写入，由 `RoleService.parseSnapshotPermissions` 读出 | **有非空快照即短路**（`parseSnapshotPermissions` 对 `null`/空白/非 JSON 数组返回 `null` ⇒ 落回退） | `RoleService.getUserPermissions` 的**第一分支**（优先于 `role_permissions` 与 A2） | **有意不参与同步**（#2969 的「快照式语义」：保存的勾选 = 最终权限，与岗位脱钩）。它是**实例**数据，不是**声明** —— 目标架构**不动它** |
| **A6** | `tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `AUTHORIZATION_CENSUS`（现取 **15** 键） | 判据期 | 判据 14 ② 段（与代码机械对照：新增码未登记 ⇒ 红；登记了没新增 ⇒ 红） | 它把「A2/A1 新增了哪些码」**再写一遍**并附「打开了哪几扇门」。这是**必要**的授权变更台账，但它同时是「同一事实的第 7 份表达」——目标架构下由清单的 diff 生成 |

#### B 类 —— 「**码 → 元数据**（中文名 / 资源 / 动作 / 描述）」（这个码叫什么）

| # | 位置 | 生效条件 | 谁消费它 | 同步机制 |
|---|---|---|---|---|
| **B1** | `backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java` 的 `defaultPermissions`（**31** 码） | 新租户建库时 `INSERT INTO permissions` | 权限目录列表接口、岗位权限页、`permissionByCode` 校验 | 与 B2 靠**判据 9②**（`parse_catalog` 逐值 diff，现取两侧均 **31** 码、差集为空） |
| **B2** | `backend/admin-api/src/main/java/com/migao/admin/service/PermissionService.java` 的 `ensureFullPermissionCatalog`（**31** 码，懒补种） | 存量租户**首次**调用 `GET /api/admin/permissions` 等路径时补齐目录行 | 同上 | 同上。⚠️ 它带**写副作用**（这就是 `AdminPermissionController` 那个 GET 被补 `system:view` 时仍被点名的原因） |
| **B3** | `backend/ai-agent-service/app/graph/skills/base_skill.py` 的 `PERMISSION_LABELS`（**31** 键） | 运行时：拼 system prompt 的「权限范围注入块」 | `_inject_permission_scope` | **手抄件**。与 B1/B2 靠 `tests/test_permission_scope_injection.py` 的 `TestPermissionLabelsMirrorTheAdminApiCatalog`（4 条：目录可解析且非空 / 标签**恰好等于**全目录 / `PermissionService` 目录是标签子集 / 每个标签带码） |
| **B4** | `backend/ai-agent-service/tests/test_tool_permission_codes.py` 的 `PERMISSION_CATALOG`（`frozenset`） | 判据期 | `TestDeclaredCodesMatchReviewedMapping` 的「每个声明的码都在目录里」 | **手抄件第 3 份**。同 A3 的 6 条判据 |
| **B5** | 各迁移文件里的 `INSERT INTO permissions (…)` —— 逐字抄 `name` / `resource_type` / `action` / `description` | 存量租户一次性 | `permissions` 表 | 迁移文件头**逐字**声明「名称/资源/动作/描述与 `RegistrationService.defaultPermissions` **逐字一致**」（V124 / V125 / V129 各写了一遍）。**这是注释，不是判据** |

#### C 类 —— 「**页面 / 菜单节点 → 码**」（看见要什么）

| # | 位置 | 生效条件 | 谁消费它 | 同步机制 |
|---|---|---|---|---|
| **C1** | `frontend/admin-web/src/config/menu.ts` 的 `menuGroups` / `standaloneItems`（现取 **28** 节点，其中 **10** 个组头的 `permissionCode` 为 `undefined`） | 浏览器端 | `frontend/admin-web/src/components/layout/Sidebar.tsx`（`visibleMenuGroups(menuGroups, filterOpts)`）；`frontend/admin-web/src/app/(dashboard)/roles/page.tsx`（岗位权限页的**菜单化勾选树**，「menuGroups 单源」逐字写在注释里）；`frontend/admin-web/src/components/layout/CommandPalette.tsx` | **真实侧边栏真值源**（该文件是 `Sidebar.tsx` 唯一读取的菜单源）。与 C2/C3 靠 `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py` 的**三条**判据（组层三源逐值相等含顺序 / 导航节点层 C1↔C3 逐值相等含顺序与组归属 / C1↔C2 前缀子序列 + `ACTION_NODES` 白名单） |
| **C2** | `backend/admin-api/src/main/java/com/migao/admin/controller/MenuController.java` 的 `MENU_TREE`（现取 **24** 节点） | 运行时 `GET /api/admin/menus` | `frontend/admin-web/src/app/(dashboard)/employees/page.tsx`（`request.get('/api/admin/menus')`） | ⚠️ **语义与 C1 不同**：它是**权限目录**（除菜单项外还带**动作码**节点，如「新增商品」`product:create`、「商品分类管理」`product:category`、「新增员工」`employee:create`）⇒ 节点数少于 C1 **不是漂移**。守卫判据 3 = 「`menu.ts` 的项名必须是该组节点的**前缀子序列**」+「多出来的节点必须逐条命中 `ACTION_NODES` 白名单」（显式枚举，新增动作节点未登记即红） |
| **C3** | `backend/admin-api/src/main/java/com/migao/admin/service/AuthService.java` 的 `buildMenusByPermissions`（现取 **14** 节点） | 登录 / `/api/auth/me` 下发 `UserInfoResponse.menus` | 登录响应消费方 | ⚠️ 它是**登录下发的导航菜单** ⇒ 节点数为 C1 的子集属**语义差异**，非漂移。守卫判据 2 = 「前端 ↔ `AuthService` **逐值相等**（含顺序与组归属）」 |
| **C4** | `frontend/admin-web/src/app/(dashboard)/layout.tsx` 的 `ROUTE_PERMISSION_MAP`（现取 **19** 条前缀 → 码） | 浏览器端路由守卫 | 打开页面时的 403 | 与 C1 靠判据 11 ③（`ROUTE_MENU_ANCHORS` **15** 条 + `ROUTE_WITHOUT_MENU_NODE` **4** 条）。⚠️ 它是**第二份「页面 → 码」**，与 C1 是同一事实的两次书写 |
| **C5** | `tests/unit_ci_workflows/test_agent_permission_parity.py` 的 `MENU_READ_ENDPOINT_ANCHORS`（**21** 条 path → 页面文件 + 第一屏调用符号）、`MENU_READ_PARITY_RESIDUALS`（**6** 条，只许缩短）、`MULTI_READ_ENDPOINT_PAGES`（**3** 条，冻结） | 判据期 | 判据 12 | 它把「这个页面第一屏调哪几个端点」**再写一遍**（锚点 = 前端 api 符号名）。判据 12 再用这些符号去 `frontend/admin-web/src/lib/api.ts` 里解析出端点与生效码 —— **这是「页面 → 码」的第 3 份表达** |

#### D 类 —— 「**端点 → 码**」（能做要什么）

| # | 位置 | 生效条件 | 谁消费它 | 同步机制 |
|---|---|---|---|---|
| **D1** | `backend/admin-api/src/main/java/com/migao/admin/controller/**` 各 controller 的 `@RequirePermission`（**类级 + 方法级**；方法级优先）。现取 **289** 个端点，其中 **55** 个生效码为 `None` | 运行时每请求（`PermissionInterceptor`） | `PermissionInterceptor` 的 403 | **co-located 真值**（改端点的人就在同一个文件里）。与 B1/B2 靠判据 1/2/8 + `UNANNOTATED_ENDPOINTS`（**21** 条登记） |
| **D2** | `frontend/bmini-app/src/utils/adminPermission.ts` 的 `ADMIN_SURFACES`（**4** 个管理面，各带 `readPermission` / `readEndpoint` / `writePermission` / `writeEndpoint` / `controllerFile`） | 手机端 h5 | `canOpenAdminSurface` / `canWriteAdminSurface` / `visibleAdminSurfaces` / `missingPermissionText` | **手抄件**（该文件头逐字自述「权限码真值在后端注解，本台账是它的镜像」）。判据 = `frontend/bmini-app/tests/admin-surfaces-permission-codes.test.ts` 解析 4 个 Controller 的注解逐值比对 |
| **D3** | `backend/ai-agent-service/app/tools/*.py` 各工具类的 `required_permissions` | 运行时米宝工具调用前 | `BaseTool` 的权限闸 | 与 D1 靠判据 2（**工具码 ≡ 端点生效码**，逐工具逐端点） |

#### E 类 —— 「**库 / 新建库路径**」

| # | 位置 | 生效条件 | 谁消费它 | 同步机制 |
|---|---|---|---|---|
| **E1** | `backend/admin-api/src/main/resources/db/init/schema.sql` | 新建库（**不跑迁移链**） | 全新环境（docker `docker-entrypoint-initdb.d`，判据见 `tests/unit_ci_workflows/test_schema_integrity.py`） | V124 / V125 / V129 三个文件头**逐字**登记「该路径**不含任何** `permissions` / `role_permissions` 种子行；判据（可复算）：`grep -c "INSERT INTO permissions" docs/sql/schema.sql` ⇒ 0」。🔴 **那条判据命令指向的路径不存在**（见 §1.4 实例 6）——它是注释，且**是个空断言** |

### 1.2 A2 的三条运行时路径（#5683 逐行核实，本单复核）

| # | 调用点（符号锚） | 触发条件 | 逐字代码 |
|---|---|---|---|
| 1 | `RoleService.getUserPermissions` 的 `roles.isEmpty()` 分支 | 员工**没有 `user_roles` 行** 且 **没有 `users.permissions` 快照** | `new HashSet<>(getPermissionCodesForRole(user.getRole()))` —— **根本不经 `role_permissions`** |
| 2 | `RoleService.getPermissionCodesForRoleEntity` 的 `fromDb.isEmpty()` 分支 | 角色行**存在**，但该角色**一条 `role_permissions` 都没有** | `if (!fromDb.isEmpty()) { return fromDb; } return getPermissionCodesForRole(role.getCode());` |
| 3 | `RoleService.getEffectivePermissionCodesForRoleCode` | 该租户**查不到该角色行** | `return getPermissionCodesForRole(roleCode);` —— 消费方是 `PermissionInterceptor` 与 #4104 的 ⊆ 门禁 |

### 1.3 「同一事实写在 N 处」的重复计数（**本单的地基**）

| 事实 | 副本数 | 副本清单 |
|---|---|---|
| **角色 → 默认码** | **7** | A1（种子）· A2（回退）· A3（ai-agent 镜像）· A4（迁移链，8 个文件各一份谓词）· A5（员工快照，实例数据）· A6（census 台账）· 各岗位的 `RoleServiceTest` / `test_tool_permission_codes` 逐码点名断言 |
| **权限码目录（码 + 元数据）** | **5** | B1 · B2 · B3 · B4 · B5（迁移里的逐字抄写，6 个文件） |
| **菜单节点 → 码** | **4** | C1 · C2 · C3 · C4（`ROUTE_PERMISSION_MAP` 是同一事实的前缀形态） |
| **页面 → 第一屏读端点** | **3** | C5（锚点台账）· 页面源码本体 · `frontend/admin-web/src/lib/api.ts` 的符号表 |
| **端点 → 码** | **3** | D1（注解，真值）· D2（bmini 镜像）· D3（工具声明，经判据 2 对齐） |

⇒ **「改一个码要动几个文件」的现取答案**：新增一个「域读码」最少要动 **9** 处
（B1 目录 + B2 目录 + A1 种子 + A2 回退 + A3 镜像 + B3 标签 + B4 目录 + A4 一条新迁移 +
D1 端点注解），若该码还要上菜单，再加 C1/C2/C3 + C4 共 **13** 处。
**这正是历史上 #5246 / #5291 / #5675 / #5683 反复分叉的机制成因**（不是谁不细心）。

### 1.4 已发生的「散文与判据会分叉」实例（含本单新增的两条）

| # | 实例 | 散文说 | 判据/机器说 | 有东西会红吗 |
|---|---|---|---|---|
| 1 | `RoleService` 里 issue #5291 的那句注释 | 「**两个域读码**与种子矩阵逐值同步」 | 对（两个码都在）—— 但它被**读成**了「整个回退表与种子全面同步」，而当时 `operator` 差 4 码 | ❌ 没有。注释准确，**读者读到的对象与它声称的对象不是同一个** |
| 2 | `RoleService` 里 issue #5246 追加单的那句登记 | 「finance 与 customer_service **没有**硬编码回退……（如实登记，非静默遗漏）」 | 字面为真，但它的**主题是「写码」**、自述范围是 #5246 那一单 ⇒ 对「三岗在回退里整体为空」**没有作出决定**；`sales` **更从未被点名** | ❌ 没有（#5683 的复核结论 (b) 类） |
| 3 | `frontend/admin-web/src/config/menu.ts` 的 #5291 注记 | 「节点、四个页面的读端点、以及 8 个只读工具**同批**改挂 `production:view`」 | `GET /api/admin/production/piecework/summary` **漏改**（#5675 才发现） | ❌ 当时没有；#5675 补了判据 12 |
| 4 | `StockBatchController` 的类 javadoc | 「权限复用商品域 `product:list`」 | 是**方法级**注解，**不是**类级 —— 残留登记此前写成「类级」 | ❌ 当时没有；#5675 收口包更正 |
| 5 | **`#5690` PR body §⑨ census 表** | **`order:list` 行写「6」（端点）** | **`AUTHORIZATION_CENSUS['order:list'].endpoints` 现取 = 25（17 GET + 8 POST）** | ❌ **没有**。判据用 `len(entry.endpoints)` 现取，**不看那句手写汇总** ⇒ 少报 19 个端点、其中 8 个 POST（建加工单/报工/打印/发货）无人察觉。已在 #5683 补更正评论 |
| 6 | **V124 / V125 / V129 三个迁移文件头**里的「可复算判据」 | 「判据（可复算）：`grep -c "INSERT INTO permissions" docs/sql/schema.sql` ⇒ 0」 | **`docs/sql/schema.sql` 这个文件不存在**（`docs/sql/` 下只剩 `archive/`；建库脚本真身已迁到 `backend/admin-api/src/main/resources/db/init/schema.sql`，判据见 `tests/unit_ci_workflows/test_schema_integrity.py`）。实跑该命令 = `grep: No such file or directory`、**exit 2**、打印 **0**。真身那份的实际读数也确实是 0（`INSERT INTO permissions` 0 行、`INSERT INTO role_permissions` 0 行）⇒ **结论碰巧对** | ❌ **没有，而且它永远不会红**：命令读的对象（不存在的文件）与它声称的对象（建库终态脚本）不是同一个，而「读不到 ⇒ 0 ⇒ 判据成立」正好把**空断言**伪装成绿灯 —— 若哪天有人往**真身**里塞了 `INSERT INTO permissions`，这条「可复算判据」照样打印 0 |

> 🔴 **第 5 条是本单的形态标本**：同一事实（`order:list` 打开了多少扇门）存在两份 —— 判据里的真值
> 与 PR 正文里的手写汇总 —— 而**两份的分叉没有任何判据会报**。目标架构下，这类汇总必须**由清单生成**
> （生成物新鲜度判据），不许手写。
>
> 🔴 **第 6 条是同一形态的更危险变体**：不是「两份分叉」，而是**「判据读的是一个不存在的对象」**
> —— 因为读不到而恰好得到一个「通过」的读数。它与 `migao-acceptance` 的「空跑」同族：
> **绿了，但没跑**。目标架构下，凡「可复算判据」必须**自证坐标**（被读的文件存在 + 读到的内容非空 +
> 红证会红），这也是 `AGENTS.md` 铁律 8 的「核验前自证坐标」在文档里的落地形态。

### 1.5 本单自查（一次自我更正，如实登记）

本文件初稿在 C1/C2/C3 三行写过「节点数 **24 ≠ 28** / **14** ⇒ 三源**并非逐值同构**，
同构守卫的射程是『共有结构 + 组名/组序』，不是节点全集」。**该断言是错的**；读
`tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py` 的判据段后更正为：

- 该守卫的判据 **2** 就是**导航节点层逐值相等**（前端 ↔ `AuthService`，含顺序与组归属）——
  节点**数**不同（28 / 24 / 14）不是漂移，而是三者的**语义不同**（真实侧边栏 / 权限目录 / 登录下发菜单）；
- 前端 ↔ `MenuController` 的关系由判据 **3** 处理（前缀子序列 + `ACTION_NODES` 白名单）。

⇒ 我初稿犯的是**与 §1.4 同类**的错：**读到的文本（`parse_menus` 的三份投影长度）与它声称的对象
（守卫实际断言的关系）不是同一个**。登记在这里是因为本单的验收标准之一就是这一条
（「每一句『现状』断言都能逐字对上代码」）—— **自我更正也属于该标准的证据，不属于免责**。

---

## 2. ② 目标架构

### 2.1 候选与比较

| 候选 | 形态 | 能不能表达「岗位 → 码」 | 能不能表达「页面 → 码」 | CI 能不能读 | 致命问题 |
|---|---|---|---|---|---|
| **A. 声明式单清单**（仓库内一份机器可读的 RBAC 清单，含码目录 / 岗位矩阵 / 页面表；各消费面**由它派生**） | 文件（YAML/JSON） | ✅ 天然 | ✅ 天然 | ✅ 零依赖纯文本 | 需要一次「清单 = 现取」的对齐工作；清单本身要进新鲜度判据 |
| **B. DB 为唯一真值源**（`permissions` + `role_permissions` 表） | 运行时状态 | ✅ | ❌ 菜单码不在库里 | ❌ **判据面读不到** | ① CI 与本机无库，「唯一的机械判据面」会被拆掉；② 新建库路径（`db/init/schema.sql`）**不跑迁移链** ⇒ 库里根本没有种子；③ 「新租户该有什么」是**声明**不是**状态** —— 今天 `admin` 的新租户/存量差异（§3.1）正是「用状态当声明」的实证 |
| **C. 端点注解为唯一真值源**（反向生成岗位矩阵与菜单码） | 代码注解 | ❌ **不能** | ⚠️ 部分 | ✅ | ① 注解只表达「这个端点要哪个码」，**不表达「哪个岗位该持哪个码」** —— 而后者正是本单的病灶；② 目录里有**零端点**的码（现取：`order:detail` 的 census 端点数 = **0**；`agent:chat` 是米宝唤出码）⇒ 会被判成孤儿；③ 反向生成要求「改端点必须改清单」，把 co-located 的真值外置 ⇒ **新造一个分叉面** |
| **D. 只加判据、不动结构**（把 #5683 的做法推广到每一对副本） | 加强守卫 | ✅ 已做到 | ✅ 已做到 | ✅ | **这正是已经打过两次补丁的路**。用户 2026-09-27 明确叫停「不要打补丁了」：#5683 之后副本仍是 7 份，**判据数随副本对数平方增长**，而每加一条判据就多一处「判据读到的文本与它声称的对象不是同一个」的风险（§1.4 五条实例里有四条是这类） |

### 2.2 选型：**A′（A 为主 + 端点注解保持 co-located + DB 为该清单的物化）**

```
                    ┌──────────────────────────────────────┐
                    │  rbac 清单（仓库内，唯一声明真值源）   │
                    │  codes[] · roles[] · pages[] · tools[]│
                    └───────────────┬──────────────────────┘
        ┌───────────────┬───────────┼───────────┬───────────────┐
        ▼               ▼           ▼           ▼               ▼
   B1/B2 目录      A1 种子      A2 回退   A3 镜像 / B3 标签   C1/C2/C3/C4
   （生成）        （生成）     （生成）    （生成）          （生成）
        │               │                                      │
        │               ▼                                      ▼
        │          role_permissions（物化）              菜单可见性 / 路由守卫
        │               ▲
        │               │
        │          A4 迁移（**由清单 diff 生成**，不再是手写谓词）
        ▼
   D1 端点注解（**co-located，仍为真值**）── 判据只核对「码 ∈ 清单.codes」＋ 三条不变量
```

**为什么是 A′ 而不是纯 A**：端点注解是**唯一真正 co-located 的**真值 —— 改端点的人就在那个文件里。
把它也搬进清单会引入「改一个端点要同步两个文件」的新分叉面，且注解的**优先级语义**
（方法级覆盖类级）无法在清单里无损表达。⇒ 清单管**声明**（谁该有什么、哪个页面叫什么门），
注解管**准入**（这个端点要哪个码），两者用一个**闭合性**判据连接（I3）。

**为什么 DB 只做物化**：「新租户该有哪些岗位默认权限」是一个**产品声明**；
把它交给「租户**历史上**跑过哪些迁移」这个状态去决定，就是今天 `admin` 差异的成因（§3.1）。

### 2.3 清单形态（四段）

```yaml
codes:                      # 现分散在 B1/B2/B3/B4/B5
  - code: production:view
    name: 生产查看
    resource: production
    action: view
    description: 查看生产看板/加工项/工艺配置/计件

roles:                      # 现分散在 A1/A2/A3/A4
  - code: operator
    builtin: true           # 是否为「新租户种子岗位」
    default_codes: [ ... ]  # **唯一一份**；种子 / 回退 / 镜像 / 迁移全部由它派生

pages:                      # 现分散在 C1/C2/C3/C4/C5
  - key: production-processing
    name: 加工项管理
    path: /production/processing
    gate: production:view                 # 菜单可见性码（**由本表派生到三处菜单源 + 路由守卫**）
    units:                                # 页面内可独立渲染/独立 403 的单元（tab / 区块）
      - label: 加工项
        read_codes: [production:view]
        endpoints: ["GET /api/admin/processing-items", ...]
      - label: 加工费组合
        read_codes: [order:list]
        endpoints: ["GET /api/admin/production/processing-fee-combinations",
                    "GET /api/admin/production/processing-fee-gaps"]
      - label: 加工分类
        read_codes: [processing:manage]
        endpoints: ["GET /api/admin/processing-categories"]

ledger:                     # 只许缩短的登记（把今天散在三张表里的条目收拢）
  visibility_gaps: []       # 原 MENU_READ_PARITY_RESIDUALS
  multi_code_pages: []      # 原 MULTI_READ_ENDPOINT_PAGES（由 pages[].units 派生 ⇒ 本可自动得出）
  partial_visibility_ack: [ ... ]   # 新增：显式承认「看得见但某些 unit 不可用」
```

### 2.4 各个消费面怎么从它派生

| 消费面 | 现在（手写副本） | 目标（派生） | 派生成 **零 delta** 的判据 |
|---|---|---|---|
| 新租户种子 A1 | 手写 `List.of(...)` ×4 | 生成 / 读清单 | 「清单的 `roles[].default_codes` ≡ 现取 `parse_role_defaults`」逐值 |
| 回退 switch A2 | 手写 `switch` ×7 case | 生成 / 读清单 | 同上，用 `parse_role_fallback` |
| 存量迁移 A4 | 手写谓词 ×8 文件 | **由清单 diff 生成 SQL**（含幂等 `WHERE NOT EXISTS` / `ON CONFLICT DO NOTHING` + `DO` 块终态对账） | 生成器对「清单 vs 各迁移累计」求差 ⇒ 差集非空即红 |
| ai-agent 镜像 A3 / B4 | 手抄件 | 生成 | 「生成物 == 现值」逐字节 + 现有 6+8 条判据 |
| 权限标签 B3 | 手抄件 | 生成 | 「标签 == 清单.codes 的名字」逐值 |
| 目录 B1/B2 | 两份手抄件 | 生成（两份同一个来源） | `parse_catalog` 逐值（判据 9② 已有） |
| 菜单可见性 C1/C2/C3 | 三份手写表 | 生成（**同一份 pages[] 投影三次**，投影规则显式声明） | 三源同构守卫 + 节点码 ≡ `pages[].gate` |
| 路由守卫 C4 | 手写 `ROUTE_PERMISSION_MAP` | 由 `pages[].path` + `gate` 生成 | 守卫码 ≡ `pages[].gate`（判据 11 ③ 已有，真值方向反转） |
| 员工级快照 A5 | `users.permissions` | **不变**（实例数据，不是声明） | — |
| 端点准入 D1 | 注解 | **不变**（co-located） | I3 闭合性：「注解里的码 ∈ 清单.codes」fail-closed |
| bmini 镜像 D2 | 手抄件 | 生成（4 面） | 现有 `admin-surfaces-permission-codes.test.ts` |

### 2.5 🔴 「可见面 == 可做面」怎么变成**结构性质**（#5675 / #5682 残留 6 条的根）

**现状为什么只能靠判据钉**：菜单节点码（C1）与页面第一屏读端点码（D1）是**两个独立手写的事实**，
判据 12 只能事后断言「这两处相等」。而**它们本来就不该相等** —— 一个页面第一屏可以并发三个不同码
（`MULTI_READ_ENDPOINT_PAGES` 现取 3 条），此时「那**一个**码」不存在，判据退化成「挑一个 + 登记残留」。

**结构解法：把「页面」提升为一等对象，并使菜单节点**不再有手写的码**。**

1. **页面 = `pages[]` 的一个 `units[]` 集合**，每个 unit 声明自己的 `read_codes`（tab 粒度）。
2. **菜单节点可见性 = `∃ unit: read_codes(unit) ⊆ defaults(角色)`**（OR over units）——
   **不再手写 `gate`**（`gate` 若存在，只是「至少一个 unit」的投影，供路由守卫做前缀匹配用）。
3. ⇒ **结构上不可能出现「整页可见但一个 unit 都打不开」**：可见性的定义就是「至少一个 unit 可打开」。
   判据 12 的命题（节点码 ≡ 第一屏读端点码）**消失** —— 因为**只剩一处**在表达这件事。
4. 每个 unit 独立 403 时**必须在 UI 上明示**（`frontend/bmini-app/src/utils/adminPermission.ts` 的
   `missingPermissionText` 已有同款形态；admin-web 侧 `production/processing` 页的
   `Promise.allSettled` 降级提示是同族做法）。若某 unit 的不可用**不打算明示** ⇒ 必须登记进
   `ledger.partial_visibility_ack`（带理由 + 人 + 日期，**只许缩短**）。

**「部分 unit 不可用」仍是一个产品选择，架构不替人选**。架构的贡献是把它从
「**沉默的、散在 6 条残留台账里的不一致**」变成「**pages[] 里一句显式声明**」——
这是本单能给的、也是唯一诚实的结论（见 §3.4 问题 1）。

### 2.6 历史角色码怎么办（`product_manager` / `knowledge_editor`）

**机器现取的事实**（零抽取，全仓）：

| 事实 | `product_manager` | `knowledge_editor` |
|---|---|---|
| 在 A1 种子里 | ❌ **不在**（种子只有 admin / customer_service / operator / sales / finance） | ❌ 不在 |
| 在 A2 回退里 | ✅ 8 码 | ✅ 2 码（`dashboard:view` / `product:list`） |
| 在 A3 镜像里 | ✅ 8 码（= 回退） | ✅ 2 码（= 回退） |
| 在 A4 迁移链里 | ❌ **一条谓词都不提它**（V29 建的岗位只有 sales / finance + 三个改名） | ❌ 同 |
| 在 `roles` 表里（结构性推断） | ❌ **没有 roles 行** —— 判据里逐字登记「POC 期的历史岗位码（`mibao.py` 的 `allowed_roles` 仍在用）：**无 roles 行，只有回退表口径**」 | ❌ 同上（登记为「知识库编辑岗」） |
| 在其他消费面 | `frontend/bmini-app/src/pages/profile/index/index.tsx` 的角色名映射表（UI 显示「商品管理员」）；`frontend/bmini-app/src/types/index.ts` 的注释 | 同（UI 显示「知识编辑」） |
| 拿码的路径 | **A2 路径 3**（该租户查不到该角色行 ⇒ 回退）+ A2 路径 1（员工无 `user_roles` 行） | 同 |

⇒ **它们是「未定义的幽灵角色码」，不是「遗留岗位」**：一个**既不在岗位表、也不在种子矩阵**
的角色码，靠 `switch` 里的一行 `case` 拿到 **8** 个权限码，而**没有任何岗位权限页能编辑它**
（岗位权限页的数据源是 `roles` 表）。⇒ 目标架构必须把它变成一个**显式决定**：

| 出口 | 含义 | 代价 |
|---|---|---|
| **(i) 正式定义** | 在 `roles[]` 里 `builtin: true` + 一条迁移给存量租户建 `roles` 行 + 授权 | 首次让它们出现在岗位权限页；需要一次授权确认 |
| **(ii) 显式退役** | 从 `roles[]` 删除；`default -> List.of()`（fail-closed）兜底 | 🔴 **收窄**：持这些 `users.role` 值的账号从 8/2 码掉到 0 码；`mibao.py` 的 `allowed_roles` 与 bmini 的角色名映射要同批处理 |
| **(iii) 保持现状 + 登记** | 在清单里显式写一条 `ghost_roles: [...]`（理由 + 人 + 日期 + 只许缩短） | 今天的形态，但**显形**；不再靠「回退表里多一行 case」这种隐身形态 |

🔴 **本单不裁决**（属 §3 差量表里「需要人点头」的项）。

### 2.7 迁移路径（与既有数据共存）

**现状**：存量租户的 `role_permissions` 是「**该租户历史跑过的迁移的并集**」——
路径依赖、没有任何 Java 路径会给既有岗位补码（四个迁移文件头逐字登记了这一点）。

**目标**：清单是声明，迁移是**它的一次次物化**。共存规则：

1. **已发布迁移只增不改**（`tests/unit_ci_workflows/test_migration_immutability.py` 的账本冻结 + `.github/danger_scan.py` 的 `rewrite-migration` 放行需要 owner）。
   ⇒ 收敛**必须靠新迁移**，不许改 V124/V125/V129/V132。
2. **新迁移由「清单 vs 各迁移累计」的差集生成**，谓词 = 「该角色**当前**应有的 `default_codes` 减去它**已经有**的 `role_permissions`」，
   幂等形态沿用仓内既成范式：`INSERT INTO permissions … WHERE NOT EXISTS (同租户同码)` +
   `INSERT INTO role_permissions … ON CONFLICT (role_id, permission_id) DO NOTHING` + 文末 `DO` 块终态对账（fail-closed）+ 显式 `BEGIN/COMMIT`。
3. **`admin` 的收敛**（§3.1 的 11 码差距）是这条生成的第一个产物 —— 但它是 **UI 可见、运行时零影响** 的一格。
4. **`users.permissions` 快照不回填、不迁移**（#2969 的语义：快照是最终权限；回填快照 = 静默改授权）。

### 2.8 明确的边界（**不要把本设计读成覆盖面更大的东西**）

- 本设计**只覆盖**「角色 → 默认码」「码目录」「页面 → 码」「端点 → 码」四类事实。
  **不覆盖**：`users.permissions` 快照的取值、`platform_admins` 的 `super_admin` 直通、`ServiceTokenFilter`
  的 `X-User-Id` 身份解析与 `hasBypassRole`、C 端（`customer` / `agent`）无 `permissions` claim 的
  不可判形态、`worker` 的拒绝分支 —— 它们是**身份/边界**问题，不是**声明重复**问题。
- 清单**不承诺**消除「同一件事需要改多处」：`codes` 里加一个码，仍然要让某个端点注解用它
  （D1 是 co-located 的，架构**有意**不把它搬走）。清单消除的是**同一事实的副本**，
  不是**同一变更的多处落地**。
- 「未登记即红」类机制**只覆盖它显式扫描的语料**（见 §5.3 的覆盖面登记）。
- 本节的「派生」**不等于**「运行时读清单」：可以是**生成物 + 新鲜度判据**（推荐，零运行时依赖），
  也可以是运行时读清单。选型留给实施阶段，**本单不预设**。

### 2.9 不做（有意不碰，照仓内「明确的边界」写法）

| 不做 | 理由 |
|---|---|
| 不改 `frontend/worker-h5` | 工人端不走 `/api/admin/**`（`worker` 在 `ADMIN_API_REJECTED_ROLES` 里被 403），它的权限面不在本设计的四类事实内 |
| 不动 `users.permissions` 快照语义与存量快照 | #2969 的裁定；回填 = 静默改授权 |
| 不把 `@RequirePermission` 搬进清单 | §2.2 —— 会新造分叉面，且丢失方法级覆盖类级的优先级语义 |
| 不改 `hasBypassRole` / `ServiceTokenFilter` / `ADMIN_API_REJECTED_ROLES` | 身份边界，非声明重复（用户已多次裁定不动） |
| 不改 `frontend/admin-web/src/config/menu.ts` 的分组 / 组名 / 组顺序 / 节点顺序 / `keywords` / `icon` | #5271 与三源同构守卫的地盘 |
| 不新增 issue | 会话内零新开（`AGENTS.md` 铁律 11）；需要跟踪单时**在报告里提出**，由人决定 |
| 不在本单实现目标架构 | 本单是**第一阶段：设计 + 差量表** |

---

## 3. ③ 精确行为差量表

> **读数口径**：全部由 §1 的既有解析器现取。`seed` = A1，`fb` = A2，`migr` = A4 的并集（§3.1）。
> 「有效权限集合」= `RoleService.getUserPermissions` 对该场景返回的集合。
> 🔴 **本单不改任何行为** ⇒ 下表是「**若照目标架构落地**」的差量，不是已发生的变更。

### 3.1 三场景的真值源与**现状**读数（先把现状读准，再算差量）

| 场景 | 真值源 | 现取读数 |
|---|---|---|
| **S1 新租户** | A1 种子矩阵（写 `role_permissions`；`admin` = `permissionByCode.keySet()` = 全目录） | `admin`=31 码 · `customer_service`=10 · `operator`=25 · `sales`=7 · `finance`=7 |
| **S2 存量租户**（🔴 精确口径 = **跑过 `V29` 的老租户**；在 `db/init/schema.sql` 成为唯一建库路径**之后**创建的租户直接吃种子，其 `admin` = 31 码，不在此列） | A4 迁移链并集（V29/V32 基线 ∪ V43/V111/V124/V125/V129/V132 增量） | `customer_service`=**10** · `operator`=**25** · `sales`=**7** · `finance`=**7** —— **与 S1 逐值相等**；🔴 `admin` = **20 码**（= 31 − 缺的 11，见下） |
| **S3 无权限快照账号** | A2 回退 switch（三条运行时路径之一） | `admin`=`["*"]` · `customer_service`=10 · `operator`=25 · `sales`=7 · `finance`=7 · 🔴 **`product_manager`=8** · 🔴 **`knowledge_editor`=2** |

**S2 的 `admin` 差距（本单新发现，机器可复算）**：
`V43` / `V111` / `V124` / `V125` 四条迁移**都是新码的引入者**，而**四条都没有给 `admin` 授码**
（可复算：`grep -c "r.code = 'admin'"` 对这四个文件 ⇒ **0**；它们的 `role_permissions` 谓词逐条只点名
`customer_service` / `operator` / `sales` / `finance`）。它们引入的 **11** 个码 =
`processing:view` `processing:update` `inbound:view` `inbound:create` `after_sales:view` `knowledge:view`
`order:update` `order:create` `customer:create` `finance:create` `agent:session:manage`。
⇒ **跑过 `V29` 的老租户的「管理员」岗位在岗位权限页回填时缺这 11 个码**（新租户是 31/31）。
（⚠️ 该「缺 11」的推导**不依赖** V29 文件头那句「与 `RegistrationService` 种子权限目录同源：`dashboard:view` 等 **17** 条」——
那句的条数与今天的 31 码目录对不上（`17 + 11 + 3 + 1 = 32 > 31`），**登记为存疑**，见 §6。）
**运行时零影响**（`RoleService.getUserPermissions` 对 `admin` 首行短路返回 `["*"]`，`role_permissions` 一字不读），
**但岗位权限页的勾选树回填、以及「员工管理」弹窗选管理员岗位时的预填会不同**。

### 3.2 逐角色 × 逐码（**若照目标架构落地**）

**结论先说：目标架构的落地本身（清单对齐 + 派生 + 生成物 == 现值）是零 delta 的**；
**所有 delta 都发生在「处置清单暴露出的不变量违反」那一步**（§4 的 P4 / P5）。

#### S1 新租户 · S2 存量租户 —— 零 delta（除 `admin` 的一格）

| 角色 | 得 | 失 | 说明 |
|---|---|---|---|
| `customer_service` / `operator` / `sales` / `finance` | ∅ | ∅ | S1/S2/S3 **三场景逐值相等**（10/25/7/7），且生成物 == 现值 ⇒ 零 delta |
| `admin` | ∅ | ∅（运行时） | 运行时恒 `["*"]`（首行短路）⇒ **零 delta** |
| `admin`（岗位权限页回填 / 员工弹窗预填） | **+11 码**（S2） | ∅ | 若 P5 收敛；**UI 可见、运行时零影响** |

#### S3 无权限快照账号 —— 零 delta（除两个幽灵角色）

| 角色 | 得 | 失 | 说明 |
|---|---|---|---|
| 五个种子岗位 | ∅ | ∅ | #5683 之后回退 == 种子 ⇒ 生成物 == 现值 |
| `product_manager` | ∅ | ∅ **或** −8（出口 ii 退役） | 见 §2.6 三出口 |
| `knowledge_editor` | ∅ | ∅ **或** −2（出口 ii 退役） | 同 |
| 自定义岗位（`roles` 表里但无 `role_permissions` 行） | ∅ | ∅ | 落 `default -> List.of()` ⇒ 空表，不变 |

### 3.3 逐消费面：每个变更让哪些端点 / 菜单节点 / Agent 工具变为可达或不可达

🔴 **本单不改行为 ⇒ 本节列出的是「P4/P5 若按下表任选一项落地，会动到哪几个面」的现取读数。**

#### (a) `order:list` 的授权面（**问题 1 与问题 2 的共同分母**）

| 读数 | 值 |
|---|---|
| 生效码**恰为** `order:list` 的端点数 | **25** |
| 其中 GET | **17** |
| 其中非 GET | **8** |
| 8 个非 GET 的**注解形态** | 4 个**方法级**（`backend/admin-api/src/main/java/com/migao/admin/controller/OrderController.java` 的 `POST /api/admin/orders/auto-features`、`/craft-calc`、`/door-width-plan`、`/fee-preview`）+ 4 个**类级**（`backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java` 的 `POST /api/admin/production/orders/{}/instantiate` 建加工单、`.../operations/{}/report` 报工、`.../print` 打印、`.../ship` 发货） |
| 持 `order:list` 的岗位（seed / fallback 两来源） | `admin`（`*`）· `customer_service` · `operator` · `sales` · `finance`（**两来源逐值相同**） |

#### (b) 六条菜单残留的**现取**结构（判据 12 的残留台账 + 多端点页表）

| path | 节点名 | 节点码（C1） | 第一屏读端点**生效码**（现取） | 持节点码的岗位 | 持各第一屏码的岗位 |
|---|---|---|---|---|---|
| `/dashboard` | 经营看板 | **无**（`undefined`） | `dashboard:view`（5 个端点全同码） | **全员**（无码 ⇒ 不过滤） | CS · operator · sales · finance · product_manager@fb · knowledge_editor@fb · admin |
| `/production/pool` | 智能派单 | `processing:manage` | `processing:view`（1 个端点） | admin · operator · product_manager@fb | 同上 + CS · sales · finance |
| `/production/saving-board` | 省料看板 | `processing:manage` | `product:list`（2 个端点） | admin · operator · product_manager@fb | admin · operator · sales · product_manager@fb · knowledge_editor@fb |
| `/production/processing` | 加工项管理 | `production:view` | `production:view` ∧ `order:list` ∧ `processing:manage`（3 码） | admin · operator · product_manager@fb | 见 (c) |
| `/production/routings` | 工艺配置 | `production:view` | `processing:manage` ∧ `production:view`（2 码） | admin · operator · product_manager@fb | 同 `/production/pool` 两列 |
| `/settings` | 企业基础信息 | `system:manage` | `system:manage` ∧ `dashboard:view`（2 码） | **admin 独有** | `dashboard:view` 见上；`system:manage` 只有 admin |

#### (c) 逐消费面的可达性变化（**若** P4 按下表任选一项）

| P4 的处置选项 | 端点上「变为可达」 | 端点上「变为不可达」 | 菜单节点 | Agent 工具 |
|---|---|---|---|---|
| (1) `/production/pool` 节点码 → `processing:view`（+ 路由守卫同批） | ∅ | ∅ | 智能派单对 **CS / sales / finance** 由不可见**变可见** | ∅（该码无工具） |
| (2) `/production/pool` 端点码 → `processing:manage` | ∅ | **CS / sales / finance** 失去 `GET /api/admin/production/pool`（1 个端点） | ∅ | ∅ |
| (3) `/production/saving-board` 节点码 → `product:list` | ∅ | ∅ | 省料看板对 **sales / knowledge_editor@fb / product_manager@fb** 由不可见**变可见** | ∅ |
| (4) `/production/saving-board` 端点码 → `processing:manage` | ∅ | **sales · knowledge_editor@fb** 失去 2 个端点 | ∅ | ∅ |
| (5) `/production/processing` 两个 `order:list` GET → `production:view` | ∅ | **CS / sales / finance** 失去「加工费组合 / 缺口」可读性（2 个端点） | ∅ | ∅ |
| (6) `/production/processing` 节点码 → `order:list` | ∅ | ∅ | 加工项管理对 **CS / sales / finance** 由不可见**变可见** | ∅ |
| (7) `product_manager@fb` 补 `order:list`（**#5683 已判为「不在已批准范围」**） | **product_manager@fb 新增 25 个端点**（17 GET + 8 POST，含建加工单/报工/打印/发货） | ∅ | 订单列表 / 订单详情 / **加工项管理**（该节点码是 `production:view`，本来已可见） | `order_query` · `logistics_track` · 及 4 个 POST 相关工具（**工具面变化需按判据 2 重算**） |
| (8) `/settings` 简报端点 → `system:manage` | ∅ | **CS / sales / finance / operator / product_manager@fb / knowledge_editor@fb** 失去 `GET /api/admin/briefing/config`（连带 `/briefing` 页与看板简报开关） | ∅ | `briefing_query` |
| (9) `/production/routings` 的 `processing:manage` 端点 → `production:view` | ∅ | ∅ | ∅ | ∅ |

> ✅ **第 (9) 行是唯一一条「零 delta」的处置，已机器核实**：`backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java`
> 的端点现取分布 = `processing:manage` **23** 个（全类级）+ `production:view` **7** 个 + `order:list` **12** 个（全类级）+ 无注解 **5** 个；
> 而 **`processing:manage` 与 `production:view` 的持有岗位集合在两来源里逐值相同**
> （seed = {`admin`（`*`）, `operator`}；fallback = {`admin`, `operator`, `product_manager@fb`}）
> ⇒ 把该控制器任一端点在这两个码之间改挂，**对所有角色的可见面与可做面零 delta**。
> ⚠️ **不要把这条结论外推到 `processing:view`**：那是**另一个码**（加工单查看），
> 持有者多出 `customer_service` / `sales` / `finance` ⇒ 第 (1)/(2) 两行的 delta 与它有关，与本行无关。
> （三个近名码的现取持有者：`processing:view` = admin · CS · operator · sales · finance · product_manager@fb；
> `production:view` = admin · operator · product_manager@fb；`processing:manage` = 同 `production:view`。）

> ⚠️ 上表每一项都是**授权变更**（放宽或收窄），**必须由人裁定**；本单**一项都不执行**。
> 表里「变为可达/不可达」的**端点数**取 §3.3(a) 同法现取；标注「∅」= 该码在这条处置里没变。

### 3.4 🔴 三个必须单独回答的具体问题

#### 问题 1：`product_manager@回退` 缺 `order:list`（⇒「加工费组合」tab 首屏 403），在目标架构下会变成什么？

**现取事实**：`product_manager@fb` = 8 码（`dashboard:view` `processing:manage` `processing:view`
`product:category` `product:category:view` `product:create` `product:list` `production:view`）。
`/production/processing` 的第一屏三码里它**持 2 缺 1**（有 `production:view` 与 `processing:manage`，
无 `order:list`）。

**目标架构给出的结论（不默认补码）**：

1. 该页在 `pages[]` 里被显式写成「**3 个 unit，3 个不同读码**」（§2.3 的 YAML 就是这个页面的现取形态）。
2. 结构不变量变成：**`gate ∈ defaults(R) ⇒ ∃unit: read_codes(unit) ⊆ defaults(R)`**
   （「整页可见但一个 unit 都打不开」= 缺陷；「部分 unit 不可用」= 需显式承认的产品形态）。
3. 对 `product_manager@fb`：`production:view ∈ defaults` 且 `read_codes(加工项) = {production:view} ⊆ defaults`
   ⇒ **不变量成立**（整页不会全 403）。
4. ⇒ **目标架构不会自动补 `order:list`**，它会给出**两条必须由人选的出口**：
   - **(甲) 承认部分可见**：在 `pages[].units[加工费组合]` 上写 `partial_visibility_ack`（理由 + 人 + 日期）
     ⇒ 该 tab 对 `product_manager@fb` 仍 403，但**页面必须明示**「该 tab 需要 `order:list`」，
     且这条承认是**显式声明**、不再是散在残留台账里的一句 `victims_ack`；
   - **(乙) 消除它**：把 `ProductionController` 那两个 GET 的**类级** `order:list` 改挂 `production:view`
     ⇒ 代价见 §3.3(c) 第 (5) 行：**CS / sales / finance 失去这 2 个端点的可读性**（收窄）。
5. 🔴 **为什么不是「补 `order:list`」**：§3.3(a) 现取读数 —— 该码的授权面是 **25 个端点（17 GET + 8 POST）**，
   而「让该页自洽」只支撑 **2** 个端点。**授权面与理由不匹配**（这正是用户叫停第三次补丁的理由，
   现在它成了结构性读数，而不是一次判断）。

#### 问题 2：那 25 个端点里的 **8 个 POST**，在目标架构下是否仍然只由类级码决定？

**答：是 —— 目标架构不会自动改变它，但会把它从「判据全绿」变成「必须显式登记」。**

- 4 个**方法级**（`OrderController` 的 `auto-features` / `craft-calc` / `door-width-plan` / `fee-preview`）
  = **计算/预览类** POST，挂读码 `order:list` 是合理的（不写库）。
- 4 个**类级**（`ProductionController` 的 `instantiate` 建加工单 / `report` 报工 / `print` 打印 / `ship` 发货）
  = **真写动作**，生效码**只由类级注解**给出 ⇒ 在目标架构下**仍然只由类级码决定**
  （§2.2：注解保持 co-located，架构有意不搬它）。
- 🔴 **本单实测到的一处判据盲区（机器读数，非推断）**：
  判据 5（读写码不错配，`problems_read_write`）的射程是**工具**（`_coded_b_end(w)` = 声明了码的 B 端工具），
  **不是端点**。它现取问题数 = **0**，而 `READ_WRITE_EXCEPTIONS` 台账现取 = **0 条、上限 0**。
  ⇒ **「写端点由读码把守」这一形态在端点层没有任何判据** —— 上表 4 个类级 POST 是**真写动作**却
  生效码为 `order:list`（action 段 = `list`），**判据 5 看不见它**。
  目标架构给出的处置是新增不变量 **I4（写动作不得只由读码把守；例外走只许缩短的台账）**，
  它一落地就会让 `ProductionController` 的这 4 个端点**具名报出** —— 那是**另一处需要人裁定的授权变更**，
  **不在本单**。

#### 问题 3：#5675 / #5682 的 **6 条菜单残留**在目标架构下各自变成什么？

| # | path | 目标架构下的形态 | 是否仍是「不一致」 | delta |
|---|---|---|---|---|
| 1 | `/dashboard` | 节点不再有手写码 ⇒ 可见性 = `dashboard:view`（该页 5 个端点同码） | ❌ **消失**（命题不再存在） | 🔴 **零权限的自定义岗位失去「经营看板」菜单项**（今天它无码 ⇒ 全员可见） |
| 2 | `/production/pool` | 节点码 = 该页唯一 unit 的读码 `processing:view`；路由守卫同批 | ❌ 消失 | 🔴 **CS / sales / finance 由不可见变可见**（它们**确实**能读该端点 ⇒ 看得见 == 打得开，不再制造 403） |
| 3 | `/production/saving-board` | 节点码 = `product:list` | ❌ 消失 | 🔴 **sales / knowledge_editor@fb / product_manager@fb 由不可见变可见** |
| 4 | `/production/processing` | 3 个 unit 各自声明读码；节点可见 = 任一 unit 可用 | ❌ 消失（不再有「那一个码」） | 见问题 1：`product_manager@fb` 的「加工费组合」tab 仍需 `partial_visibility_ack` 或按 (乙) 收窄 |
| 5 | `/production/routings` | 2 个 unit（`processing:manage` / `production:view`）；节点可见 = 任一 | ❌ 消失 | ✅ **零 delta，已机器核实**：两个码的持有岗位集合在 seed / fallback 两来源里**逐值相同**（`admin` · `operator` · `product_manager@fb`）⇒ 两侧任选一侧对齐都不改变任何角色的可见面或可做面 |
| 6 | `/settings` | 2 个 unit（`system:manage` / `dashboard:view`）；节点可见 = 任一 | ❌ 消失 | 🔴 **`dashboard:view` 的持有者（CS/sales/finance/operator + 两个幽灵角色）由不可见变可见「企业基础信息」菜单** —— 而该页的「基本设置」tab 仍要 `system:manage` ⇒ **这正是要避免的「看得见做不了」形态**，必须走 `partial_visibility_ack` 或把节点可见性改成**全部 unit 可用**（AND） |

> 🔴 **第 6 行暴露了「OR over units」这一条结构规则的代价**：它对 `/production/processing` 是解药
> （该页确实有可用的 unit），对 `/settings` 是毒药（该页的语义是「整页管理」，允许半个页面可见
> 会造出新的「看得见做不了」）。⇒ **`pages[]` 必须支持逐页声明 `visibility_rule: any | all`**，
> 并默认 `all`（fail-closed）。这条是本次差量分析**推翻了自己上一稿的结论**的地方，如实登记。

### 3.5 零 delta 的部分（**证明算过，不是省略**）

| 面 | 为什么零 delta | 判据 |
|---|---|---|
| 五个种子岗位的 `default_codes`（S1/S2/S3） | 生成物 == 现取（`seed` == `fb` == `migr`，逐值） | `parse_role_defaults` / `parse_role_fallback` 逐值比较 |
| ai-agent 镜像 A3 / B4 | `seeded_role_gaps == []` ∧ `fallback_role_gaps == []`（现取）；镜像 == 源 | `tests/test_tool_permission_codes.py` 的 `TestRoleMirrorMatchesTheAdminApiSource`（6 条） |
| 权限标签 B3 | 标签**恰好等于**全目录（现取 31 == 31） | `tests/test_permission_scope_injection.py` 的 4 条 |
| bmini 镜像 D2 | 4 面逐值 == 后端注解（现取）；本设计不动注解 | `frontend/bmini-app/tests/admin-surfaces-permission-codes.test.ts` |
| 端点准入 D1 | 注解一字不动 | 判据 1/2/8 |
| `users.permissions` 快照 | 明确不做（§2.9） | — |
| 三源菜单同构 | 只改「码从哪来」，不改分组 / 组名 / 组序 / 节点顺序 | `tests/unit_ci_workflows/test_menu_three_sources_are_isomorphic.py` |
| `super_admin` / `service` / `worker` / C 端 | 身份边界，不在四类事实内（§2.8） | — |

---

## 4. ④ 分阶段实施计划

每一阶段都：**可独立交付**（自带判据与 PR）、**可独立回滚**（回滚 = revert 该阶段，不留半成品）、
**有明确验收判据**。

| 阶段 | 内容 | 改行为？ | 验收判据 | 回滚 |
|---|---|---|---|---|
| **P1 清单落地 + 只读对账** | 建立 `rbac` 清单文件（初始值**逐值取自现取**）；写一个**只读**校验器：把 §1 的 20 处真值源与清单对账，**未登记即红** | ❌ **不改** | 清单 vs `parse_role_defaults` / `parse_role_fallback` / `parse_catalog` / `parse_menus` / `parse_menu_ts_nodes` / `parse_route_guard` 六项逐值相等；校验器对「人为改坏清单一行」出红证 | revert 整个 PR（纯新增文件） |
| **P2 派生「角色 → 码」与「码目录」** | 由清单**生成** A3 / B3 / B4（ai-agent 侧）与 B1 / B2 的码列 + A1 / A2 的码集 | ❌ **不改**（生成物 == 现值） | 「生成物 == 现值」逐字节；现有 6+8+4 条判据全绿；`verify-all.sh gate` + `contract-check.sh` 全绿 | revert（生成器与生成物同 PR） |
| **P3 派生「页面 → 码」** | 由清单 `pages[]` 生成 C1 / C2 / C3 / C4 的**码列**（**不动**分组/顺序/icon/keywords） | ❌ **不改**（生成物 == 现值） | 三源同构守卫 + 判据 11 ③ 全绿；节点码 == `pages[].gate`（或 `visibility_rule` 的投影）逐值 | revert |
| **P4 🔴 处置不变量违反（**第一次改行为**）** | 对 §3.4 问题 3 的 6 条 + 问题 1 逐条**由人裁定**并落地：合并码 / 收窄可见性 / `partial_visibility_ack` / 逐页 `visibility_rule: any\|all` 四类出口之一；同批新增 **I4（写动作不得只由读码把守）** 的台账与判据 | 🔴 **是** | 每条处置带 census（变可达/不可达的端点 / 菜单节点 / Agent 工具逐条现取）；§3.3(c) 的表逐行复算；`ROLE_FALLBACK_DIVERGENCES` 与 `visibility_gaps` 台账**只许缩短** | revert P4 单独一个 PR ⇒ 回到 P3 的零 delta 态 |
| **P5 存量收敛（含 `admin` 11 码）** | 由「清单 vs 各迁移累计」的差集**生成**一条新迁移（幂等 + `DO` 块终态对账）；收敛 A4 的路径依赖 | 🔴 **是**（**仅 UI 可见**：岗位权限页回填 / 员工弹窗预填；运行时零影响） | 终态对账 `DO` 块在真库上通过；`test_migration_immutability.py` 账本只增不改；「新租户 vs 存量租户」逐角色逐值相等（复算脚本） | revert（迁移只增不改 ⇒ 回滚走**新迁移**，删本文件会让已跑环境错位） |
| **P6 幽灵角色裁定** | §2.6 的三出口之一 | 🔴 **是**（若选退役 ⇒ 收窄） | 出口 (iii) 则是一条只许缩短的 `ghost_roles` 台账；出口 (ii) 需同批处理 `mibao.py` 的 `allowed_roles` 与 bmini 的角色名映射 | revert |

🔴 **第一次改行为发生在 P4** —— 那是唯一需要人**在看过 §3.3(c) 逐行 census 之后**再点头的地方。
P1–P3 全部是「**让结构对，但不让人察觉**」；P4 之后每一步都是授权变更。

---

## 5. ⑤ 类级固化（写给下一阶段用；本阶段先落判据、不动行为）

### 5.1 类 = 什么

> **同一事实（角色 → 码 / 页面 → 码 / 码 → 元数据）写在 N 处，靠注释、绊线与只许缩短的台账维持同步。**

类的判据是**副本计数**（§1.3）：`角色→码` 7 份 · `码目录` 5 份 · `菜单节点→码` 4 份 ·
`页面→首屏端点` 3 份 · `端点→码` 3 份。**修一个副本不会让计数下降** ⇒ 只修实例 = 没修。

### 5.2 让新的真值源**进不来**的机制（三件）

| # | 机制 | 判红形态 | 出口 |
|---|---|---|---|
| **M1 副本登记表（未登记即红）** | 一份 `rbac/sources.json`：每个「真值源副本」登记 `{file, symbol, kind, derived_from}`。守卫扫描约定的形态面（Java `List.of(...)`/`switch case`、TS 菜单数组、SQL `INSERT INTO role_permissions`、Python 字面量 dict/set），**任何未登记的副本 ⇒ 红** | 「有人手抄了第 4 份菜单源」⇒ 具名红 | 登记（并声明 `derived_from`）或改用派生 |
| **M2 台账只许缩短** | 把今天散在三张表（`MENU_READ_PARITY_RESIDUALS` / `MULTI_READ_ENDPOINT_PAGES` / `READ_WRITE_EXCEPTIONS`）+ #5683 的 `ROLE_FALLBACK_DIVERGENCES` + 新增的 `partial_visibility_ack` / `ghost_roles` **收进清单的 `ledger` 段，条数现取、上限只许降** | 新增未登记项 ⇒ 红；条目陈旧（违反已消失而条目还在）⇒ 红 | 销账（删条目） |
| **M3 单一生成器 + 生成物新鲜度** | 每个派生面一个生成命令；CI 跑「重新生成 → `git diff --exit-code`」 | 手改生成物 / 改清单没重生成 ⇒ 红 | 跑生成器并提交生成物 |

### 5.3 覆盖面登记（**这套机制覆盖不到什么**）

- **M1 只覆盖「用了约定形态」的副本**。有人把角色矩阵写成 `Map.of(...)`、写进 YAML、或从
  `@ConfigurationProperties` 注入 ⇒ **扫描器看不见**，与今天「完全不声明射程的新守卫不会有东西变红」
  是同一形态的残余。**降级措施**：M1 的形态集写进文件名正则 + 内容语料 glob 双登记，
  并由 §5.4 的元守卫核「声明集 == 实际扫描集」。
- **M1 不覆盖「同一事实写在已有副本的注释里」**（散文）。§1.4 五条实例里有 **1 条**是这个形态
  （#5291 那句注释本身准确，是读者读错了对象）—— **没有任何扫描器能判「读者理解对了没有」**。
  这一类只能靠「把事实从散文搬进结构」（本设计做的就是这件事）。
- **M2 的「只许缩短」不保证条目**正确**，只保证它不增长**。把一条真违反写成「有意」并登记，
  与把它修好，在 M2 眼里一样（这正是 `MENU_READ_PARITY_RESIDUALS` 今天已有的性质，
  它逐条要求 `reason` + `surfaces_when` + `owner` 来补偿，但那是**人类可读性**，不是机械判据）。
- **M3 不覆盖「清单本身就写错了」**。生成物 == 现值只能保证**零 delta**，不能保证现值**对**。
  「现值对不对」是**授权决定**，归 P4/P5/P6 的人类裁定。
- **M1/M2/M3 都不覆盖 `users.permissions` 快照**（实例数据，不是声明）。
- 本单**不新增任何守卫文件**（§7）⇒ 上表是**下一阶段**要落的机制，**今天没有一条生效**。

### 5.4 元守卫（覆盖 §5.3 的残余）

`test_guard_scope_declaration.py` 的既有范式（守卫结构化声明 `GUARD_SCOPE` == 实际扫描路径集；
引用语料未登记即红）可直接复用：M1 的「形态面」与 M3 的「每个派生面」都要有
**声明集 == 实测集**的元判据，且**未覆盖面台账只许缩短**。

---

## 6. 未取证与存疑（**照实登记，不粉饰**）

1. 🔴 **本机没有生产库**，也没有可跑的 `admin-api` 环境 ⇒ §3.1 的 S2 读数是**从迁移文件推算**的
   （谓词 + `INSERT INTO permissions` 的码列表 + `JOIN permissions` 的目录约束），
   **不是真库查询结果**；且「S2」的精确口径是**跑过 `V29` 的老租户**，不是「所有已存在租户」。
   重启条件：接上真库后复算「每个租户每个角色的 `role_permissions`」，
   与 S1/S3 逐值比对，才能确认 S2 的「与 S1 相等（除 admin）」这一条。
1-bis. **`V29` 文件头那句「同源：`dashboard:view` 等 17 条」的条数存疑**：`17 + 11 + 3 + 1 = 32 > 31`（今天的目录 31 码）
   ⇒ 要么当时的目录不是 17 条（16 条则恰好闭合：`16 + 11 + 3 + 1 = 31`），要么今天的目录少了 1 条。
   **本单未取证**（需要 V29 生效时刻的 `permissions` 目录快照，本机没有）。这不影响 §3.1 的「缺 11」结论
   —— 该结论只由「V43/V111/V124/V125 的 `role_permissions` 语句里没有 `admin`」推出，与条数无关。
2. 🔴 **「生产上是否真有走回退的账号」源码答不了**（#5683 已登记同一条）。同理，
   `product_manager` / `knowledge_editor` 这两个 `users.role` 值**是否还有活账号**，本单未取证。
3. **`admin` 的 11 码差距的 `roles` 页面可见性**未实机验证（推断依据：`attachDefaultPermissions`
   的 javadoc 逐字写「岗位权限页回显『全部权限』、员工弹窗选管理员岗位全选」⇒ 回填依赖 `role_permissions`）。
   重启条件：在测试租户上打开岗位权限页看管理员岗位的勾选数。
4. **P4 的 6 条处置我一条都没做** —— 它们是授权决定，本单只给差量。
5. **是否需要为这项架构工作开一个跟踪单**：**本单不开**（会话内零新开）。
   判断材料交人：本单涉及的落地工作量 = P1~P6 六个可独立交付的阶段，跨
   `backend/admin-api` / `backend/ai-agent-service` / `frontend/admin-web` / `frontend/bmini-app` /
   `tests/unit_ci_workflows` **五个模块**，且 P4/P5/P6 三次改行为。
   ⇒ **若人认为这超出一个会话的范围，建议开一个追踪单**（首行写「人为要求：<原话或出处>」，
   按 `AGENTS.md` 铁律 11 的形态）。**本单不代为开单。**
