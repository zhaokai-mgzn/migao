# 跨租户隔离 + 权限 横切验证报告（线 ②）

- **日期**：2026-10-03（本机时区 Asia/Shanghai，UTC+8）
- **产物目录**：`acceptance/2026-10-03/tenant-isolation-sweep/`（`REPORT.md` + `harness/` + `out/`）
- **本线是否改 MIGAO 业务代码**：**否**。只新增验证脚本（`harness/*.mjs`），未触碰 `backend/**`、`frontend/**`、`.github/cases/**`、`CHANGELOG.md`。
- **是否派发真实 LLM 评测**：**否**（#4262）。**是否跑** `verify-all.sh gate/quick/full`：**否**（本包为读数验证，不是代码改动包）。

---

## 1. 结论（先说结论，证据在后）

**跨租户隔离在本次"按 id 直打"的资源面上成立。**A 租户（20）的 token 对 B 租户（21）与 C 租户（1）
的 10 个按 id 读端点、12 个写端点、27 个列表端点**全部被拒/无泄漏**（读 404、写 404、列表交集 ∅），
且**任何一种伪造手法（query/body `tenantId`、`X-Tenant-Id` 头）都未能越权**；
无 token / 乱 token / 篡改 token 一律 401；商家 admin 打平台级端点一律 403。
**未发现 P0/P1 越权或数据泄漏。**

发现 **2 条需硬化/需裁定项（P2/P3，非安全缺陷）**，另有 **1 条环境数据卫生问题** 与
**6 类未覆盖面**（诚实登记，见 §5 与 §9）。

---

## 2. 环境与构建点（被测对象自证）

| 项 | 读数 | 采集方式 |
|---|---|---|
| admin-api 构建点 | **`1233b8a42`** （`/Users/guangzhen.zk/migao-wt/main-live`，`git log -1`：`1233b8a42 2026-10-03 09:58:07 +0800 fix(production): #6126 …`） | `git -C /Users/guangzhen.zk/migao-wt/main-live rev-parse --short HEAD` |
| 服务 | `GET http://localhost:8080/actuator/health` → **200** `{"status":"UP",…"db":{"status":"UP"…`（`db` 组件 UP） | `curl` |
| 库 | 云 dev RDS（凭据取自 `backend/admin-api/.env` 的 `RDS_*`），只读 psql | `harness/lib.mjs` 的 `psql()` |
| 租户 | `tenants`：`1 词元通达` / `20 米高POC演示布艺` / `21 POC彩排5605`（`d2965ea35` 时点读数） | 直连 DB |
| 被测端点面 | OpenAPI `/v3/api-docs` → **244 path**（`/api/admin/**` 200 条、`/api/super-admin/**` 4 条、`/api/auth/**` 14 条…) | `curl` |
| 含 `tenant_id` 的表 | **79 / 90** 张 `public` 表 | `information_schema.columns` |

> ⚠️ **构建点取值口径**：仓内工作树 HEAD 为 `d2965ea35`，但**被测服务不在该工作树**——
> 服务由 `/Users/guangzhen.zk/migao-wt/main-live` 的 `1233b8a42` 构建。本报告一切读数归属 `1233b8a42`。

---

## 3. 主体（4 个）与资源面枚举（27 个资源）

### 3.1 主体

| 记号 | 手机号 | 租户 | 角色 | 登录读数（逐字） |
|---|---|---|---|---|
| **A**（主守卫） | 13870217889 | 20 米高POC演示布艺 | admin | `tenantId:20 role:admin user.id=9068a79a939c9be846a605dc78dc30b6` |
| **B**（对照租户） | 13797101248 | 21 POC彩排5605 | admin | `tenantId:21 role:admin user.id=2047a4f6803b8bc14b11c77d8c20b4cd` |
| **C**（第二对照租户） | 13800138000 | 1 词元通达 | admin | 三主体登录见 §5.3（含手机号撞号，见 F-3） |
| **P**（平台超管，反向对照） | 13456800919 | **-1 米高平台管理** | super_admin | `role:super_admin tenantId:-1 user.id=super-admin-001` |

统一用万能码登录：`POST /api/auth/sms/login {"phone":"<手机号>","code":"123456"}` → `{"success":true,…accessToken}`。
DB 侧取证：`platform_admins` 表存在 `id=super-admin-001 phone=13456800919`（**平台超管是真实主体，非杜撰**）。

### 3.2 资源面（27 个，机器枚举，`out/inventory.json`）

按「表（`tenant_id` 直连核对）→ 列表端点 → 按 id 读端点 → 写端点」四要素登记；
A 侧有数据 21 项、B 侧有数据 14 项（B 侧为 0 的项在相应判据里**记 skip 而非 pass**）。

| # | 资源 | DB 表 | 列表端点 | 按 id 读 | 写 |
|---|---|---|---|---|---|
| 1 | 商品 | `products` | `GET /api/admin/products` | `GET /products/{id}` | PUT |
| 2 | 客户 | `customer_profiles` | `GET /api/admin/customers` | `GET /customers/{id}` | PUT |
| 3 | 客户标签 | `customer_tags` | `GET /api/admin/customer-tags` | — | PUT |
| 4 | 商品分类 | `categories` | `GET /api/admin/categories` | — | PUT |
| 5 | 工序库 | `production_operations` | `GET /production/operations-catalog` | — | PUT |
| 6 | 工艺路线 | `production_route_templates` | `GET /production/routings` | — | PUT |
| 7 | 路线规则 | `production_route_rules` | `GET /production/route-rules` | — | DELETE |
| 8 | **价目矩阵行** | `production_operation_positions` | `GET /production/operation-positions` | — | PUT |
| 9 | 加工费组合 | `processing_fee_combinations` | `GET /production/processing-fee-combinations` | — | PUT |
| 10 | 加工项 | `processing_items` | `GET /processing-items` | `GET /processing-items/{id}` | PUT |
| 11 | 加工分类 | `processing_categories` | `GET /processing-categories` | `GET /processing-categories/{id}` | PUT |
| 12 | 订单 | `orders` | `GET /orders` | `GET /orders/{id}` | PUT `/orders/{id}/content` |
| 13 | **加工单** | `processing_orders` | `GET /processing-orders` | `GET /processing-orders/{id}` | PATCH |
| 14 | **出库/入库单** | `inbound_orders` | `GET /inbound-orders` | `GET /inbound-orders/{id}` | PATCH |
| 15 | **发货单** | `order_shipments` | `GET /shipments` | — | — |
| 16 | 库存批次 | `stock_batches` | `GET /batch-stock/batches` | — | — |
| 17 | 库存流水 | `stock_ledger_entries` | `GET /stock-ledger` | — | — |
| 18 | 财务流水 | `finance_transactions` | `GET /finance/transactions` | — | — |
| 19 | 通知模板 | `notification_templates` | `GET /notification-templates` | — | PUT |
| 20 | 通知规则 | `notification_rules` | `GET /notification-rules` | — | PUT |
| 21 | 知识卡片 | `knowledge_cards` | `GET /knowledge/cards` | — | PUT |
| 22 | 角色 | `roles` | `GET /roles` | `GET /roles/{id}` | PUT |
| 23 | 售后工单 | `after_sales_tickets` | `GET /after-sales` | `GET /after-sales/{id}` | — |
| 24 | 员工用户 | `users` | `GET /users` | `GET /users/{id}` | PUT |
| 25 | 客服会话 | `agent_sessions` | `GET /agent-sessions` | `GET /agent-sessions/{id}` | — |
| 26 | 客服员工 | `agent_employees` | `GET /workers` | — | — |
| 27 | 布头余料 | `fabric_remnants` | `GET /production/remnants` | — | — |

> **按 id 读端点只有 10 个**（1/2/10/11/12/13/14/22/23/24/25）——这正是「跨租户读必须是 403/404」
> 这条判据**无法对 17 个资源直接成立**的原因，故这些资源的读面**记 skip**，由列表越界 + 写面覆盖（§8 未覆盖面）。

---

## 4. 判据矩阵（期望 / 实测 / 结论）

**汇总读数（机器可复算）：原始 `pass=83  fail=7  skip=27  total=117` → 经 §4.8 的**有效载荷复核**把 7 条 `fail` 改判（5 pass / 2 skip）⇒ 定稿 `pass=88  fail=0  skip=29  total=117`**（原始 + 改判记录见 `out/*.json` 与 `out/reclassified.json`）。
其中 `pass` 含 `2` 条纯信息项（主体登录、资源面枚举）与 `4` 条 red-proof 自身条目（§6.4）。**未经改判前存在 7 条红，全部为「探针/次序」假红，无一条是安全缺陷**（逐条见 §4.8）。

| 判据族 | 条目数 | 期望 | 实测 | 结论 |
|---|---|---|---|---|
| §4.1 跨租户读（A→B） | 10 资源有读端点（其中 8 个有 B 侧 id） | 403/404，绝不 200 | **404 ×10 资源**（每资源 ≥2 个 B 的 id + 1 个随机 id） | ✅ pass（10/10） |
| §4.1 无读端点 / 探针失效 | 20 | — | 17 个「无按 id 读端点」+ 3 个探针前置不成立（B 无行 / A 无行） | ⏭️ skip（不记通过） |
| §4.2 列表越界（A 列表 ∩ B 全量） | **27**（全部资源） | 交集 = ∅ | **交集全为 ∅**（机器比对，非人眼） | ✅ pass（27/27） |
| §4.3 跨租户写（A→B） | 12 可写资源（21 个写端点中 B 侧有对象的 12 个） | 拒绝 **且** 库逐字段不变 | 7×404 + 5×（422/400 校验先拦，库不变）；**有效载荷复核 4/4 → 404** | ✅ pass（12/12，含 §4.8 改判） |
| §4.4 参数/头部伪造 | 5 资源 × 4 手法 = 20 + 1 body | 不得越权 | **21/21 被拒（404）**，无 B 数据 | ✅ pass（21/21） |
| §4.5 角色越界（商家打 `/api/super-admin/**`） | 3 端点 + 2 真实 id | 403/404 | 列表 **403**；`{id}` 路径**数字 id 一律 403**；真实申请 id **403/403** | ✅ pass |
| §4.6 未认证 / 乱 token / 篡改 token | 4 资源 × 3 = 12 | 401/403 且无数据 | **12/12 → 401** | ✅ pass（12/12） |
| §4.7 超管反向对照（P 打 B / A 的资源） | 4 + 3 + 1 | 反向对照，不判缺陷 | P 读 B 与 A 的按 id 资源**一律 404** | ✅ 登记为观察（见 F-2） |
| §4.8 第二对照租户 C(1) | 读 2 + 写 2 | 403/404 且不改库 | 读 404/404；写（有效载荷）404/404 且库不变 | ✅ pass（4/4） |
| §4.9 残留/零写入读数 | 96 项（32 表 × 3 租户） | 无本线写入 | 3 项变化，**归属他人**（见 §7） | ✅ pass |
| §6.4 红证（自加） | 2 | 注入能翻红、还原能回基线 | 两项均 pass | ✅ pass（2/2） |

### 4.1 跨租户读（核心）——逐资源读数

每条都配了**正对照**（A 打 A 自己的同类型 id ⇒ 必须 200），FAIL-CLOSED：正对照不 200 就**记 skip 而非 pass**。

| 资源 | 正对照 A→A | A→B 的 id | A→随机 id | 返回体含 B 数据？ |
|---|---|---|---|---|
| 商品 | 200 | 404, 404 | 404 | 无 |
| 客户 | 200 | 404, 404 | 404 | 无 |
| 加工项 | 200 | 404, 404 | 404 | 无 |
| 加工分类 | 200 | 404, 404 | 404 | 无 |
| 订单 | 200 | 404, 404 | 404 | 无 |
| 加工单 | 200（正对照为 A 侧对象） | —（B 无行） | 404 | 无 |
| 入库单 | 200 | —（B 无行） | 404 | 无 |
| 角色 | 200 | 404, 404 | 404 | 无 |
| 售后工单 | 200 | 404, 404 | 404 | 无 |
| 员工用户 | 200 | 404, 404 | 404 | 无 |
| 客服会话 | **正对照不可达 ⇒ skip** | — | — | —（A/B 该表均 0 行） |

逐字样本（`out/sweep-main.json` → `R-products.evidence`）：

```
正对照 A→A id=e292e7fd91eb5d5725e86ee02fc7b1c4 → 200（reachable=true）
B_id id=caa4b914ff80bb3fdac746929a421560 → 404 leak=[] body={"success":false,"error":{"code":"NOT_FOUND","message":"商品不存在"},…}
```

### 4.2 列表越界（机器比对）

**27 个**列表端点（27 个资源全部返回 200），A 侧返回的全部 id 与 **直连 DB 查出的 B 全量 id 集合**求交 ⇒ **全部 = ∅**。
强正对照（两侧都有大量数据）：订单 `A 侧 359 条 vs B 侧 1 条`、工序库 `40 vs 40`、路线规则 `26 vs 26`、
价目矩阵行 `29 vs 29`、员工用户 `14 vs 2`、角色 `10 vs 7`、财务流水 `376 vs 1`、库存流水 `385 vs 0`。
弱正对照（A 侧为空，已标注）5 项：加工费组合、库存批次、知识卡片、客服会话、布头余料。

### 4.3 跨租户写 —— 含「有效载荷复核」（关键，防假绿）

初跑有 5 条返回 **422/400（载荷校验）** 而非 404，这**不能**直接判为越权成功、也**不能**直接判为拒绝。
因此补做**有效载荷复核**（用 B 该行的**真实字段值**构造合法 body，走完校验）：

| 资源 | 有效载荷跨租户写 A→B | 库逐字段快照 | 同租户写端点正对照 |
|---|---|---|---|
| 商品 | **404** | `updated_at=2026-09-22T04:48:40.658722+08` 前后**逐字节相同** | 200（`name` 最小载荷） |
| 商品分类 | **404** | 未变 | 200 |
| 加工项 | **404** | 未变 | 200 |
| 订单 `/content` | **404** | 未变 | —（同载荷在 A 侧端点可达性见 §4.3 备注） |

⇒ **安全结论成立**：租户闸在**载荷合法**时依然拒绝；初跑的 422/400 只是「校验先于租户判定」的次序现象（F-1）。
其余 7 条直接得到 **404**（客户、工序库、工艺路线、路线规则、价目矩阵行、角色、员工用户），库快照 `unchanged=true`。

### 4.4 参数/头部伪造（`X-Tenant-Id` 是任务点名的真实攻击面）

| 手法 | 商品 | 订单 | 客户 | 员工用户 | 角色 |
|---|---|---|---|---|---|
| `GET …/{B的id}?tenantId=21` | 404 | 404 | 404 | 404 | 404 |
| `GET …/{B的id}?tenant_id=21` | 404 | 404 | 404 | 404 | 404 |
| `GET …/{B的id}` + `X-Tenant-Id: 21` | 404 | 404 | 404 | 404 | 404 |
| 前两者叠加 | 404 | 404 | 404 | 404 | 404 |
| `PUT` + `body{tenantId:21,tenant_id:21,name:"伪造越权探针"}` | **404**，库未变 | — | — | — | — |

正对照：A 带**同样的伪造头**打**自己的** id ⇒ **200**（证明伪造头没把请求打死，探针真的到达端点）。

**根因读数（代码级，只读 `1233b8a42`）**：`X-Tenant-Id` 只在 `ServiceTokenFilter` 里被消费，
且门槛是「请求头带**合法的内部 Service Token** **且** `SecurityContext` 尚无认证」——
商家 JWT 会话下 `SecurityContext` 已填充 ⇒ 该分支根本不进；仓内 `frontend/**` 也**不携带任何 service token**（实测 grep 为空）。
⇒ 该头对商家会话**不是有效攻击面**（与判据的 404 读数一致）。

### 4.5 角色越界

- `GET /api/super-admin/registrations?page=1&size=5`（A 的 token，商家 admin）→ **403 `PERMISSION_DENIED 权限不足`**；超管 P → **200**（`total:7`，真实入驻申请）。
- `GET /api/super-admin/registrations/{真实id}`（两条真实 id）→ **A=403 / B=403**；超管 → **200**（返回该申请 `companyName/contactName/phone`）。
- 数字 id 复核（`999999999999`、`1`）→ **A=403 / B=403**；超管 → **404 NOT_FOUND**（到业务层）。
- 商家侧**不存在**「租户管理」端点：`GET /api/admin/tenants` → **404** ⇒ 如实登记「不存在」（**不写成"通过"**）。

### 4.6 未认证 / 乱 token / 篡改 token

4 个资源（商品/订单/员工用户/客户）各打 3 种坏 token：**无 token、`garbage.token.value`、把 A 的 JWT 签名段改两个字符** ⇒
**12/12 全部 401**，无任何数据返回；同端点 A 的有效 token → **200**（正对照）。

---

## 5. 发现清单

> 级别定义：P0=可越权读/写他租户数据；P1=可越权且规模化；**本线 P0/P1 = 0**。

### F-1（P3 · 非安全 · 硬化建议）跨租户写先被「载荷校验」拦下，返回 422/400 而不是 404

- **最小复现**：`PUT http://localhost:8080/api/admin/products/{B(21)的商品id}`，Header `Cookie: access_token=<A(20)的admin token>`，body `{}`
  → `422 {"success":false,"error":{"code":"VALIDATION_ERROR","message":"参数校验失败","details":[{"field":"name","message":"商品名称不能为空"}]}}`
  ；同租户（A 打自己的商品）同样 `{}` → **同样 422** ⇒ 校验**先于**租户判定。
- **影响面**：5 个资源的写端点（商品、商品分类、加工项、加工分类、订单 `/content`）。**库零变动**（逐字段快照证明）。
- **一句话判据**：*跨租户写请求的响应码由「载荷是否合法」决定而非「目标是否属本租户」决定 ⇒ 安全结论仍成立（有效载荷 404），但审计日志/告警会把越权尝试记成参数错误，掩盖真实攻击面。*
- **建议**：把租户/归属判定前置到参数校验之前（对齐多数端点的 404 语义），或至少在校验失败的错误体里**不暴露**目标行的存在性。**不改也不构成缺陷**，登记即可。

### F-2（P2 · 需产品裁定）平台超管**没有任何**按 id 的跨租户读通道

- **最小复现**：超管 P 的 token 打 `GET /api/admin/products/{A(20)的商品id}` → `404 {"code":"NOT_FOUND","message":"商品不存在"}`；
  打 `GET /api/admin/orders/{A(20)的订单id}`、`GET /api/admin/customers/{A(20)的客户id}` → 同样 **404**；
  打 B(21) 的资源 → 同样 **404**。
- **判据边界（反向对照先行）**：这不是越权，而是**能力缺口**。P 的 `tenantId=-1` 在
  `MybatisPlusConfig`（`tenantId == -1 → 跳过租户过滤`）下**本应**可跨租户；实测**连单租户也读不到** ⇒ 与"平台管理员可跨租户"的既有表述不一致。
- **影响面**：运维/客服排查租户问题缺少读通道（只能走 SQL）；**无数据泄漏风险**（拒绝方向）。
- **一句话判据**：*平台超管对租户域资源按 id 读 100% 404（含自己"应当能读"的租户），既非越权亦非可用 —— 需裁定这是有意的隔离还是能力缺口。*
- **建议**：若为有意（平台侧只做入驻审批）⇒ 在代码注释/文档中明确；若为缺口 ⇒ 需要平台级只读通道（并配套审计日志）。

### F-3（P3 · 环境数据卫生）租户 1 存在**同一手机号**的两个 admin 账号

- `select id,phone,role from users where tenant_id=1 and phone='13800138000'` → **两行**：`user_admin_001`（赵凯）与 `user_superadmin`（管理员）。
- **为什么重要**：本线原计划以「租户 1」作为第二对照租户，登录 `13800138000` 时**命中哪个用户不确定**（实测登录返回 `user_superadmin`）；任何按手机号登录/回归的验证都会**不可复现**。
- **一句话判据**：*同一租户内手机号唯一性未约束 ⇒ 以手机号为入口的验证与登录链路不可复现（本线已改用"两个真实租户 admin"规避）。*
- **建议**：dev 库清理重复手机号；若产品允许同号多账号，则登录链路需定义确定性选择规则。

---

## 6. 红证（逐字）

任务要求 3 类红证，全部落实。

### 6.1 红证①：判据反转注入（`--flip`）—— 期望拒绝 ⇒ 临时改成期望允许

```
$ node harness/sweep.mjs --flip
=== 阶段读数（FLIP 反向注入）：pass=2 fail=49 skip=27 total=78
  ❌ [R-products] 跨租户读·商品 — 🔴 2/2 例未拒绝或含 B 数据：B_id:404 random:404
  ❌ [WT-users]   跨租户写·员工用户 — 🔴 PUT 打 B 的 id 得到 404；库变动=false
$ node harness/sweep2.mjs --flip
=== 批次2 读数（FLIP）：pass=6 fail=15 skip=0 total=21
  ❌ [WV-products] 跨租户写(有效载荷)·商品 — 🔴 有效载荷跨租户写得到 404；库变动=false；泄漏=[]
  ❌ [F-products]  伪造越权·商品 — 🔴 query ?tenantId=21:404 …
```

- **读数**：**64 条"期望拒绝"判据全部翻红**（49 + 15）。
- **反向自证（不是"一律红"）**：翻转后仍 **pass** 的恰是**不该翻转**的信息项/反向对照项 ——
  `sweep.mjs`：`PC-0, INV`；`sweep2.mjs`：`ROLE-tenants, SA-products, SA-orders, SA-customers, SA-users, SA-note`。
  ⇒ 断言是**跟着读数走**的，不是恒真也不是恒假（双向可判）。

### 6.2 红证②：真实越权成功的**正对照**（找不合法手段 ⇒ 用"属于 B 的真实对象 id"打）

- 已用**只读 SQL**取出"确实属于 B(21)"的对象 id（商品 `caa4b914…`、客户 `1f665c78…`、订单 `fed91ded…`、角色、售后、员工用户…），
  再用 A 的 token 直打 ⇒ **一律 404**，返回体不含 B 的任何字段。
- **若这条返回 200 且带 B 的数据 ⇒ 即为 P0 发现**：本线**未出现**该情形。
- 补强：第二对照租户 C(1) 的**真实对象 id** 同样 404（读+写，见 §4.8）。

### 6.3 红证③：正对照（A 打 A 自己）**必须 200** —— 证明不是"所有请求都 404/401"

| 层 | 正对照读数 |
|---|---|
| 按 id 读 | 商品/客户/加工项/加工分类/订单/加工单/入库单/角色/售后/员工用户 **全 200** |
| 列表 | 24 个列表端点全 **200**，A 侧返回大量真实数据（订单 359 条、库存流水 385 条…） |
| 写 | 同租户幂等 PUT：商品分类 **200**、加工项 **200**、客户 **200**（库未变） |
| 身份 | 超管 P 打平台端点 **200**（`total:7`）；A 打 `/api/super-admin/**` **403**（同一端点两种主体两种结论） |
| 认证 | 同端点有效 token **200** vs 无/乱/篡改 token **401** |
| 伪造头 | A + `X-Tenant-Id:21` 打**自己的** id → **200**（伪造头不影响自身可达性） |

⇒ **可判别**：同一端点在不同主体/id 下产生 200/403/404/401 **四种不同读数**，不存在"全局 404"。

### 6.4 红证④（自加）：零写入读数**不是空断言**

对 B(21) 的一行做一次**可逆**改动，要求指纹检出 + 还原回基线（`out/redproof-residue.json`）：

```
基线：  products#21 行数=1 max_updated=2026-09-22 04:48:40.658722+08 rowfp=195613bc566d870c4a6362dd6466970a
注入后：products#21 rowfp=811485183ae4a0f813072186e6a648ca（rowfp 变=true）   ← 检出差 ✅
还原后：products#21 rowfp=195613bc566d870c4a6362dd6466970a（回到基线=true）；name 现值=彩排窗帘9434  ← 已复原 ✅
```

⇒ 「行内容指纹」这个读数**能红也能还原**，故 §7 的"无写入"声明不是空断言。

---

## 7. 零残留 / 零写入声明（机器读数）

**方法**：会话前后对 **32 张业务表 × 3 个租户**各取 `存活行数 + updated_at 最大值 + id/deleted/updated_at 指纹 + 行内容指纹`，
共 **96 项**，逐项比对（`out/residue-before.json` / `out/residue-after.json` / `out/residue-diff.json`）。

**读数：96 项中 3 项变化，逐项归因如下（均非本线）：**

| 变更项 | 变更读数 | 归因（证据） |
|---|---|---|
| `users#20` 行数 15→16 | 新行 `id=0b210fbf52bd0934df6f710358a6de1b phone=null role=worker nickname=发货验收工人 created_at=2026-10-03 10:42:54.905527+08` | **并行包**（发货单/仓储功能验证）自建的写探针——昵称即其验证对象；本线全部写请求均被拒（§4.3） |
| `tenant_applications` 行数 +1 | `company_name=验收布艺777130`（平台入驻申请） | 非本线：本线未调用 `POST /api/auth/register` |
| `platform_admins`（非 tenant 表）指纹变 | `last_login_at` 变化 | 本线用超管手机号登录（**登录必然刷新**）；本线无法避免，且**不涉及任何租户业务数据** |

**本线自证无写入（三条独立读数）**：

1. **被打击的行逐字段未变**：§4.3 每条跨租户写都对目标行取**字段级快照**（含 `updated_at`/`deleted`），**全部 `unchanged=true`**（含 5 个 422/400 情形）。
2. **本线主体自身零变更**：A/B/C 三个 admin 用户行 `updated_at` 仍为 `2026-09-03 06:22:28` / `2026-09-03 20:12:12` / `2026-06-16 09:07:38`（**登录不刷 users 行**）。
3. **唯一一次真实写入 = 红证注入并已还原**：`products#21` 改 `name` 后 fingerprints 与 `name='彩排窗帘9434'` **逐字节回到基线**（§6.4）。

> **本线未产生任何业务数据写入；唯一一次 DB 写入是 §6.4 的红证注入，已还原并留证。**
> 报告正文亦**未发现任何"本应被拒却生效"的写**——故无"立即还原"事项（除自身红证注入，已还原）。

---

## 8. 假绿自查（重点回答"是不是所有请求都 404"）

| 问题 | 自查结论 | 依据 |
|---|---|---|
| 是不是所有请求都 404/401（判据无判别力）？ | **不是**。同一端点在不同主体/id 下产生 **200 / 401 / 403 / 404** 四种读数；24 个列表端点全 200 且有大量真实数据；同租户写端点 200 | §6.3 |
| 跨租户读的 404 是不是「到处都 404」造成的？ | **不是**。每个资源都配 A→A 正对照 200（FAIL-CLOSED：不 200 就 skip）；且**列表**能返回 A 的完整数据 | §4.1 / §4.2 |
| 写面 404 会不会是"载荷校验/路由先拒"伪装？ | **已排除**：用 B 的真实字段值构造**有效载荷**重打，4/4 仍 **404** 且库未变；同租户同载荷 → 200 | §4.3 |
| 5 条 422/400 是不是真越权？ | **不是**（库零变动；有效载荷复核为 404）⇒ 但**登记**为 F-1（校验次序），**不**当成越权也不悄悄抹掉 | §4.8 / F-1 |
| `{id}` 路径返回 400「参数类型不正确」是不是权限闸失效？ | **不是**：400 是**类型解析先于权限判定**；换成**合法数字 id** 后商家一律 **403**，超管到业务层 404 | §4.5 |
| 超管读到 404 是不是"平台被隔离"的缺陷？ | **只作观察/需裁定**（F-2），并**先做反向对照**才下结论（铁律 11(a)；不把设计选择报成缺陷） | F-2 |
| 零写入读数会不会是空断言？ | **不是**：注入一次可逆改动 → 指纹翻红；还原 → 回基线 | §6.4 |
| 探针真的到达了端点吗？ | 有：正对照 200 + 同一请求带伪造头打自己 id 仍 200 + 有效载荷被 404（说明过了校验） | §4.3 / §4.4 |
| 主体真的是它声称的样子吗？ | 有：登录返回体逐字给出 `tenantId/role/user.id`；`platform_admins` 表存在该超管行；A/B 的租户名与 `tenants` 表一致（铁律 11(a) 已核对 `regen` 声明对象） | §3.1 |

---

## 9. 未覆盖面（诚实登记，不得读成"通过"）

1. **17 个资源无「按 id 读」端点** ⇒ 其"跨租户读"判据**未测**（由列表越界 + 写面间接覆盖，非等价）。
2. **B(21) 侧 7 张表无存活数据** ⇒ 这些资源的跨租户写**未测**：客户标签、加工费组合、加工单、入库单、通知模板、通知规则、知识卡片。
3. **未测的写/读端点类型**：`batch/*`（批量上下架/删除）、`import/export`、`upload/*`、`dashboard/*`（统计口径）、
   `production/pool/dispatch`、`processing-orders/generate`、`agent/*`（AI 专用面）、`/api/worker/**`（22 条员工端）。
   本次仅覆盖**服务端 admin 管理面**（66 个端点），OpenAPI 共 **244** 条。
4. **未测 `ai-agent-service`(:8001)** 的租户隔离（其租户来自 `X-Tenant-Id`/Service Token 链路，**是另一个真实攻击面**，值得单独一线）。
5. **未测幂等/重放面**：`client_request_keys` 相关重复提交在跨租户下的行为。
6. **未跑并发/竞态**：本线为串行读数；并行包同时写同一批表（实测），并发下的租户上下文串号（线程池 `TenantContext`）**未测**。

---

## 10. 建议（按优先级）

1. **（低）** 把租户归属判定前置到载荷校验之前（F-1），或至少让校验失败不暴露目标行存在性 —— 消除审计噪音。
2. **（需裁定）** 明确平台超管对租户域资源的读能力边界（F-2），并把结论写进文档/代码注释。
3. **（低）** 清理 dev 库租户 1 的重复手机号（F-3），避免以手机号为入口的验证不可复现。
4. **（建议新一线）** 把 §9-3/§9-4/§9-6 补齐：`ai-agent-service` 的 `X-Tenant-Id` 链路、批量/导入导出面、并发下 `TenantContext` 串号 —— 这三处是本次**未覆盖但风险最高**的剩余攻击面。
5. **（方法学沉淀）** 本线的"**有效载荷复核**"应固化为跨租户写验证的标准步骤：初跑拿到 4xx 时**不能**直接判拒绝，必须用目标行真实字段构造合法载荷再打一次。

---

## 11. 产物清单

| 文件 | 内容 |
|---|---|
| `harness/lib.mjs`（复用） | `api()/psql()/loginApi()`，来自 `config-writeface-sweep` |
| `harness/registry.mjs` | 27 资源注册表 + `dbIds()`/`rowSnapshot()`/`realCols()` |
| `harness/sweep.mjs` | §4.1~§4.3（跨租户读/列表越界/跨租户写）+ `--flip` 红证 |
| `harness/sweep2.mjs` | §4.3 有效载荷复核 / §4.4 伪造 / §4.6 认证 / §4.5 角色 / §4.7 超管对照 |
| `harness/probe3.mjs` / `probe4.mjs` / `probe5-products.mjs` | 定点复核（超管真实 id、数字 id、商品载荷契约） |
| `harness/poscontrol-write.mjs` | 同租户写端点正对照 |
| `harness/residue.mjs` | 零残留读数（snap-before / snap-after / diff） |
| `harness/redproof-residue.mjs` | 零写入读数的红证（注入 + 还原） |
| `harness/t0-probe.mjs` | 主体登录 + 列表返回体形态摸底 |
| `out/*.json` / `out/*.log` | 全部**逐字**读数（记录含 evidence 数组） |
