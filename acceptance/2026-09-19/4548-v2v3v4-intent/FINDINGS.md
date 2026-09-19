# #4548 V3/V4「业务意图是否在应用层生效」核对报告（2026-09-19）

> 范围：**只核问题 2**（应用层意图核对）。问题 1（git 溯源 = 有意占号）已由 #4543 交付方复验，本单不重复。
> 被测口径锚点：`origin/main @ 6bbdf768c`。证据均为只读取证（git / grep / 单测定位）。
> 环境：云 dev 库 `ai_customer_service`（阿里云 RDS，本地 admin-api 同源）。凭据从 `backend/admin-api/.env` 读取，**未写入任何产物**。
> 复跑：`./run.sh`（纯 `SELECT`，无写操作；见 §4 —— 本机出口 IP 不在 RDS 白名单，实测 `Operation timed out`）。
> 交付形态：**零代码改动**（本目录为取证产物）；核对结论见 §0~§3，补偿迁移建议见 §5。

## 0. 一句话结论

| 迁移 | 名字里的意图 | 应用层是否实现 | 数据层是否已落地 |
|---|---|---|---|
| `V3__backfill_position_from_role` | 按角色回填岗位 | ✅ **已实现**（读时兜底 + 写时默认，双处） | ❌ **未落地**（回填 UPDATE 随 Flyway 一起消失，无任何替代） |
| `V4__migrate_in_warehouse_to_on_sale` | 在库 → 在售 | ❌ **未实现**（应用层只剩「拒绝 in_warehouse」，无任何迁移路径） | ❓ **未取证**（需真库分布；本机 RDS 不可达） |

两条的共同点：**应用层都不会去补这两笔存量数据**。区别是 V3 的「用户可见后果」被兜底掩盖了，
V4 的后果**没有任何兜底**（没有读时伪装、没有状态机入口）。

---

## 1. 前置事实：两条迁移的**原始 SQL 内容**（决定了「意图」是什么）

`b11c172ad`（占号提交）之前，两条文件都**有真实 SQL**；占号提交把 SQL 换成了注释。
（此层属问题 1 的考古，此处只作为「意图定义」引用，不再展开。）

| 文件 | Flyway 时代原文（`5bb68d18b^`） | 占号后（`b11c172ad`，即今天） |
|---|---|---|
| `V3__backfill_position_from_role.sql` | `UPDATE users SET position = role WHERE position IS NULL OR position = '';` | `-- 从角色表回填职位字段（历史数据迁移，已完成）` |
| `V4__migrate_in_warehouse_to_on_sale.sql` | `UPDATE products SET status = 'on_sale' WHERE status = 'in_warehouse';` | `-- 在仓 → 在售状态迁移（历史数据迁移，已完成）` |

⇒ **V3 的意图 = 把 `users.position` 从 `users.role` 回填**（`position` 在 `users` 上，不在 `roles` 上）。
⇒ **V4 的意图 = 把 `products.status` 从 `in_warehouse` 改成 `on_sale`**。

---

## 2. V3 —— 「按角色回填岗位」

### 2.1 字段位置（先纠正一个容易走偏的预设）

`roles` 表**没有** position 字段。`position` 只存在于 `users`：

- `backend/admin-api/src/main/java/com/migao/admin/entity/User.java` → `private String position;`
- DDL 落点：`docs/sql/migrations/V20260614__add_user_position.sql` → `ALTER TABLE users ADD COLUMN IF NOT EXISTS position VARCHAR(64);`
  （该文件注释原文：`-- #328 Role → 岗位：position 不绑定权限，仅作为展示标签`）
- 迁移链落点：`V41__align_bootstrap_schema_missing_columns.sql` → `ALTER TABLE users ADD COLUMN IF NOT EXISTS position VARCHAR(64);`

### 2.2 谁写（**已实现**，两处）

| # | 落点（符号锚点） | 分支条件 | 写入值 |
|---|---|---|---|
| 写-1 | `UserService.createUser` → `User.builder()...position(...)` | 员工被创建时 | `position` 有值则用之，否则 `role`，再否则 `"operator"` |
| 写-2 | `UserService.updateUser(...)` → `if (position != null) user.setPosition(position)` | 员工被编辑且请求体带 `position` | 请求体值（注释：「岗位=角色体系 #2969，编辑切岗位时随角色联动」） |
| 写-3 | `AdminUserController.createUser` → `if (position.isBlank()) position = role;` | 创建时未传 position | `role`（注释原文：`// fallback: 岗位 = 角色名`） |
| 读-兜底 | `AdminUserController.toEmployeeMap` → `if (position == null \|\| position.isBlank()) position = user.getRole()` | 员工列表/详情读时 | 内存里换成 `role`（注释原文：`// position 为空时回退到 role 名称`） |

⇒ **`position` 的「按角色取值」语义在应用层是活的**：新建/编辑写值 + 读取兜底，两条腿都在。

### 2.3 哪个入口可达（**已确认可达**）

- API：`POST /api/admin/users`（`AdminUserController` `@PostMapping`）、`PUT /api/admin/users/{id}`（`@PutMapping("/{id}")`），类级 `@RequestMapping("/api/admin/users")`。
- 商家路径：admin-web 员工管理「新建员工 / 编辑员工」（表单含「岗位」）。
- 另有独立 UI 旅程证据（**非本单产出，引用既有验收产物**）：
  `acceptance/2026-09-14/merchant-ui-smoke/REPORT.md` 旅程 23「员工管理」：
  「**新建（name/phone/岗位/权限）→ 列表可见 → 编辑改手机号 → 落库验证 → 删除**」= ✅；
  A3 场景 3：「**users.phone / users.position 更新值落库** ✅」。

### 2.4 测试锚点

| 层 | 锚点 | 覆盖了什么 |
|---|---|---|
| ✅ 写路径 | `AdminUserControllerTest`（`@DisplayName("下发 phone → 手机号进入更新实参…")`、`roleIdsIsResolvedToRoleCode`） | 创建/更新入参透传（`verify(userService).createUser(..., eq("manager"), ...)`） |
| ⚠️ 读兜底 | **无**。`toEmployeeMap` 的 `position == null → role` 分支**没有任何单测钉住**（该测试类是 `@WebMvcTest` + mock `UserService`，`toEmployeeMap` 的真实逻辑不进测试） | —— |
| ✅ 端到端 | `acceptance/2026-09-14/merchant-ui-smoke/REPORT.md` 旅程 23 + A3 场景 3（真 UI + DB 回读） | 岗位可写、可落库、列表可见 |

### 2.5 结论：**意图已实现，但「回填存量」这一笔从未落地**

- **应用层意图**（岗位按角色取值）→ ✅ **生效**，有写路径 + 读兜底 + UI 旅程锚点。
- **V3 的 SQL 那一笔**（`UPDATE users SET position = role WHERE position IS NULL OR position = ''`）→ ❌ **全仓不存在任何替代实现**：
  `grep -rn "SET position|position = role"` 全仓仅命中 `AdminUserController` 那行**内存兜底**，无任何 SQL。
- **后果分级（不夸大）**：存量库中 `position IS NULL` 的老用户，**展示不会出错**（读兜底把 role 顶上了），
  但**数据本身仍是 NULL** ⇒ 任何**绕过 `toEmployeeMap`** 的读取面拿到的是空值：
  `UserController.getCurrentUser` → `UserInfoResponse.UserInfo.position`（无兜底）、
  `AuthService`（登录返回）→ 同上（无兜底）。前端若在这两处直接展示岗位，会得到空值。
- **旁证**：#383 的根因推测第 1 条原文即「**`users.position` 字段在生产 DB 上全为 NULL（V1 迁移没给已有用户填默认值）**」，
  该 issue 的修复以「读兜底」收口（PR #393），**未包含任何回填 SQL**（PR diff 只有 `toEmployeeMap` + 新增迁移文件）。

### 2.6 缺什么证据

`users.position` 在**当前**真库的分布（NULL / 有值）——本机无法取证（见 §4）。

---

## 3. V4 —— 「在库 → 在售」

### 3.1 应用层：**明确不做这件事，且反向封死**

- 状态机表 `ProductService.STATUS_TRANSITIONS` 的键集 = `{draft, under_review, on_sale, off_sale}`，
  **`in_warehouse` 不是键也不是任何值**；`PRODUCT_STATUS_LABELS` 同样无 `in_warehouse`。
- 唯一状态流转入口 `ProductService.updateProductStatus` → `validateStatusTransition`：
  当前态 `in_warehouse` ⇒ `STATUS_TRANSITIONS.get("in_warehouse")` 为 `null` ⇒ 抛
  `状态流转无效: in_warehouse → …，允许的目标状态: 无`。
- 前端枚举同样已剔除：`frontend/admin-web/src/types/index.ts` → `export type ProductStatus = 'on_sale' | 'off_sale' | 'draft' | 'under_review'`
  （**仅引用，未改动 `frontend/**`**）。
- 测试锚点（钉的是**拒绝**，不是迁移）：
  `ProductServiceTest` → `@DisplayName("in_warehouse 已废弃 — 任何状态流转到 in_warehouse 均抛异常")`。

⇒ **应用层对 V4 意图是「零实现」**：既没有 `in_warehouse → on_sale` 的流转边，也没有批量上架兜底
（`batchOnShelf` 的 `allowedStatuses = Set.of("off_sale")`，注释原文仍写「只有 off_sale/in_warehouse 状态的商品可上架」——**注释漂移**，代码已不含 `in_warehouse`）。
⇒ 因此 `in_warehouse` 状态只可能是**历史存量**，而唯一能改它的东西就是 V4 那条 SQL —— 它今天是一条注释。

### 3.2 哪个入口可达

**没有入口。** 商家在 UI 上：
- 商品列表筛选下拉无「仓库中」（`frontend/admin-web/src/app/(dashboard)/products/page.tsx` → `STATUS_OPTIONS`）；
- 状态机不接受 `in_warehouse` 作为源态或目标态；
- 商品**编辑**表单不改 status（`ProductService` 更新路径刻意 `product.setStatus(originalStatus)` 还原，注释：「状态变更必须通过 updateProductStatus 接口（含状态机校验）」）。

⇒ 若真库存在 `products.status = 'in_warehouse'` 的行，它是**永久卡死行**：无法上架、无法下架、无法删除
（`batchDelete` 允许集 = `{draft, off_sale}`），且**不会变红**（无守卫、无测试）。

### 3.3 测试锚点

| 断言对象 | 是否存在锚点 |
|---|---|
| 「不允许流转**到** `in_warehouse`」 | ✅ `ProductServiceTest.updateProductStatus_InWarehouseIsRejected` |
| 「存量 `in_warehouse` 行已被迁走 / 为 0」 | ❌ **无任何锚点**。`.github/templates/product-sku-stock.yml` 的 `reviewer_asserts` 里三条 `expect: … NOT IN (in_warehouse)` 是**API 返回**口径（列表/详情），不是 DB 存量口径；同一模板的 `common_pitfalls` 自己承认：「V4 migration 未做幂等——**DB 内部事实**，由 admin-api 启动迁移日志保证，**verify 不直连库校验**」 |

⇒ 即：**V4 的意图「零测试钉住」**（按 #4548 判据：「没有钉住的声称 = 未实现」）。

### 3.4 结论

**未实现（应用层）+ 数据层未取证。**
V4 的意图**只在这条空迁移里被许诺过**，应用层从未、也不再实现它；且**没有任何机制会因它未生效而变红**。

### 3.5 缺什么证据（决定「是否需要补偿迁移」的唯一未知量）

真库 `products.status` 分布：`SELECT status, count(*) FROM products GROUP BY status;`
—— 特别是 `in_warehouse` 计数是否 > 0。

---

## 4. 真库取证：**已尝试，本机不可达**（如实登记，不编归因）

- 复用既有只读运行器先例 `acceptance/2026-09-18/4299-db-distribution/run.sh`（凭据取 `backend/admin-api/.env`），
  本单写了 `recon.sql` + `run.sh`（**纯 SELECT，只读**）。
- 实测结果（两次，间隔数分钟，结果一致）：
  ```
  psql: 错误: 连接到"pgm-bp1p7w92k81ob5to-pub.pg.rds.aliyuncs.com" (8.139.140.111)上的服务器,
  端口5432失败：Operation timed out
  ```
- 网络探针：`nc -z 8.139.140.111 5432` → **TCP BLOCKED**；同时 `curl https://www.aliyun.com` → 403（**出网正常**）。
  ⇒ 指向 RDS 侧白名单/安全组未含本机出口 IP（**这是推断，不是已证结论**），不是本机断网。
- 同目录 `acceptance/2026-09-18/4299-db-distribution/*-output.txt`（2026-09-19 17:11 生成）证明**该库此前可读**，
  本机环境或出口 IP 在此期间发生了变化。
- **结论：数据层两个未知量（`users.position` 空值分布、`products.status` 是否仍有 `in_warehouse`）本单未能取证。**
  复跑入口已留：`acceptance/2026-09-19/4548-v2v3v4-intent/run.sh`（在有 RDS 白名单的机器上直接跑）。

---

## 5. 建议落点（**本单不自行开单、不自行修**，由决策人裁定）

若 §4 的未知量确认为「有存量」：

| 缺口 | 建议 | 先例 / 代价 |
|---|---|---|
| V3 的 `position` 回填 | 新增**补偿迁移** `V79__backfill_users_position_from_role.sql`：`UPDATE users SET position = role WHERE position IS NULL OR position = '';`（幂等、纯数据） | 照 `V75`/`V76` 先例（V72 整份回滚 ⇒ V76 重做）。代价：一条迁移 + `migration_fingerprints.json` 登记。**收益低**（读兜底已掩盖展示后果）⇒ 优先级可低于 V4 |
| V4 的 `in_warehouse → on_sale` | 新增**补偿迁移**（新号）：`UPDATE products SET status = 'on_sale' WHERE status = 'in_warehouse';` | 同上。**收益高**：这些行今天**无任何恢复路径**（状态机拒绝 + 前端无选项 + 无编辑入口），是真正的卡死数据 |
| 防复发（可选，另一单） | `.github/templates/product-sku-stock.yml` 的 `common_pitfalls` 那条「V4 migration 由启动日志保证，verify 不直连库校验」建议改为一条**可执行**的存量判据 | 属用例库演进（`migao-dev-flow` §14），**不在本单范围** |
| 注释漂移（可选，另一单） | `ProductService.batchOnShelf` 的 javadoc「只有 off_sale/in_warehouse 状态的商品可上架」与代码 `Set.of("off_sale")` 不一致 | 一行注释修正；`in_warehouse` 已废弃 ⇒ 属漂移 |

**硬约束遵守情况**：未改/未删 V2/V3/V4 任何一条；未碰 `.github/cases/**`；未碰 `frontend/**`；未派发任何真实 LLM 评测。

---

## 6. 证据索引（复现命令）

```bash
# V3/V4 原文（Flyway 时代）
git show 5bb68d18b^:backend/admin-api/src/main/resources/db/migration/V3__backfill_position_from_role.sql
git show 5bb68d18b^:backend/admin-api/src/main/resources/db/migration/V4__migrate_in_warehouse_to_on_sale.sql
# V4 引入时的完整 SQL + 业务口径（issue #646）
git show 5f6b0af00 --stat
# Flyway 何时被禁用（决定两条迁移是否曾执行）
git log -1 --format='%ad %s' --date=iso 80eae2796 2054207c7 5f6b0af00
# 应用层：position 写路径
grep -rn "setPosition\|\.position(" backend/admin-api/src/main/java/ | grep -v test
# 应用层：product 状态机
grep -n "STATUS_TRANSITIONS" -A 8 backend/admin-api/src/main/java/com/migao/admin/service/ProductService.java
# 全仓是否存在 V3/V4 的替代实现
grep -rn "SET position\|position = role\|in_warehouse" --include=*.java --include=*.sql backend/ docs/
```
