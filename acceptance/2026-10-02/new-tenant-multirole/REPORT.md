# 新企业入驻 + 多岗位 RBAC 全链路功能验收报告

- **验收日期**：2026-10-02（Asia/Shanghai）
- **被测版本**：`main` @ `3fa84ab89`（开工时 `git rev-list --count HEAD..origin/main` = **0**，即与远端主干一致；工作树干净）
- **被测对象**：本地三组件真栈 + 真云 dev 库
  - admin-api `:8080`（`./mvnw spring-boot:run`，`SMS_BYPASS_CODE=123456`，`AI_AGENT_BASE_URL=http://localhost:8001`）
  - ai-agent-service `:8001`（仅用于入驻 AI 甄别链路，Agent 对话能力**不在本次验收范围**）
  - admin-web `:3001`（`next dev`，`NEXT_PUBLIC_API_BASE_URL=http://localhost:8080`）
  - worker-h5 `:3100`（B 端 H5：静态直出 + `/api` 反代到 8080，与线上 nginx 同源部署同构）
  - DB/Redis：云 dev（`ai_customer_service` @ 阿里云 RDS）
- **验收方式**：真浏览器（Playwright/Chrome）+ 真 API + `psql` 直查 + admin-api 日志四方对证；每步落盘截图与 JSON 证据。
- **范围**：企业入驻 → 多岗位/工人建号 → RBAC 权限矩阵 → 各功能单据（按钮/输入框/校验，跑两轮）→ B 端 H5。**排除 Agent（对话/工具）功能**。
- **证据目录**：`acceptance/2026-10-02/new-tenant-multirole/out/`（`SUMMARY.md` 为自动生成的汇总）

---

## 一、结论

| 维度 | 结论 | 读数 |
|---|---|---|
| 新企业入驻 | ✅ 通过 | 16/16（含注册页两步骤 5 条负向校验、蜜罐、AI 甄别、租户+管理员自动开通、岗位与权限预置） |
| 多岗位/工人建号 | ✅ 通过 | 22/23（唯一 fail 为**本脚本自身**的探针口径错误，见 §四·H1；修正后 4/4 通过） |
| RBAC 权限（读+写） | ⚠️ 通过，附带 3 项前端纵深缺口 | 读面 180 格矩阵 + 写面 63 格复核：**越权 0 例**；页面守卫缺 2 处、校验顺序 1 处（§四·F1~F3） |
| 功能单据（页面/DB/校验，各两轮） | ✅ 通过 | 41/41（商品/订单/售后/财务/入库单 + 客户档案 upsert；含列表计数 == DB 计数一致性） |
| B 端 H5（工人端） | ✅ 通过 | 15/15（登录/校验/会话续期/扫码/报工记账/进度推进/登出/机台页） |
| 连贯链路（入库过账→下单→加工→报工→发货） | ✅ **补验通过** | 18/18（§八；首轮只做了五段孤立探针，经追问后补成一条单跑通） |
| 仓库自带 UI 冒烟脚本 | ❌ 脚本过期（非产品缺陷） | 20/32 通过；12 条失败逐条归因为**脚本与当前 UI/接口脱节**（§四·H2） |

**自建阶段合计：pass=145 / fail=16 / skip=1**（16 条 fail 中：11 条为首轮 RBAC 探针写法缺陷 F3、3 条为同一类页面守卫缺口 F1/F2、1 条为本脚本探针口径 H1、1 条为生产链路的 `@Valid` 顺序探针 RBAC3-02 —— **无一为产品功能缺陷**，逐条见 §四）。

**总判定：功能链路可用，RBAC 生效且与权限码一致；无越权、无数据泄露。** 需要处理的是 3 项前端纵深防御缺口、1 项校验顺序取舍，以及 1 个仓库自带冒烟脚本的同步更新。

---

## 二、验收对象与环境（可复算）

| 项 | 值 |
|---|---|
| 新企业（租户） | `tenants#23` 验收布艺940121，企业编码 `940121-rcyh`，status=active |
| 企业管理员 | `users#1dc724d6…` phone `13996940121`，role=admin，`/api/auth/me` → `permissions=["*"]` |
| 岗位种子（实测） | admin(32 码) / customer_service 客服(11) / finance 财务(8) / knowledge_editor 知识编辑(2) / operator 运营(26) / product_manager 商品管理员(8) / sales 销售(8) |
| 员工样本 | 6 个内置岗位 + 2 个自定义岗位（一个 2 码、一个 0 码）各 1 名，均完成「建号 → 用户名@企业编码 登录 → 首登强制改密 → 复登」 |
| 工人样本 | `workerNo=W978212`，PIN 6 位，role=worker（供 B 端 H5） |
| 孤儿租户（需处置） | `tenants#22` 验收布艺870495 —— 首轮脚本在 `saveCtx` 落盘前中断，`REUSE` 守卫未生效而重复注册所留（§五·遗留物） |

复算入口（脚本即证据生成器，全部可重跑）：

```bash
cd "acceptance/2026-10-02/new-tenant-multirole"
node harness/s1-onboard.mjs      # 阶段1（已入驻则自动进入 REUSE 模式，不重复建租户）
node harness/s2-seed.mjs         # 阶段2
node harness/s2b-custom-role.mjs # 阶段2b
node harness/s3-rbac.mjs         # 阶段3  一轮矩阵
node harness/s3b-rbac2.mjs       # 阶段3b 二轮复核
node harness/s3c-rbac3.mjs       # 阶段3c 三轮收口
node harness/s4-docs.mjs         # 阶段4  单据两轮
node harness/s5-h5.mjs           # 阶段5  B 端 H5
node harness/summary.mjs         # 汇总
```

---

## 三、验收矩阵（验收点 × 层级 × 证据）

层级：**L1** = 机器可判（HTTP 码 / DB 行 / DOM 断言）；**L2** = 需引用证据的判定；**UA** = AI 用户代理判定（话术可懂度）。

| # | 验收点 | 层级 | 期望 | 实测 | 证据引用 |
|---|---|---|---|---|---|
| 1 | 注册步骤一：空提交 | L1 | 两条必填提示 | 「请输入手机号」「请输入验证码」均可见 | `s1-onboard.json` ON-01；`screenshots/s1-reg-01-required-errors.png` |
| 2 | 注册步骤一：手机号格式 | L1 | 11 位以外被拦 | 提示「请输入正确的11位手机号」 | ON-02 |
| 3 | 注册步骤一：验证码长度 | L1 | 非 6 位被拦 | 提示「验证码为6位数字」 | ON-03 |
| 4 | 注册步骤二：必填 | L1 | 企业名称/联系人被拦 | 两条提示均可见 | ON-05 |
| 5 | 蜜罐字段 | L1 | 不参与填写 | `#website` 提交时为空 | ON-06 detail |
| 6 | 提交 → AI 甄别 | L2 | 秒级返回结论 | 3849ms 返回「审核通过，欢迎入驻！」；`tenant_applications#2105…` `status=approved` `review_source=ai` | ON-06 / ON-07a；日志 `RegistrationController - 收到企业入驻申请` |
| 7 | 自动开通租户+管理员 | L1 | 落库 | `tenants#23`、`users#1dc724d6…(role=admin)` | ON-07b/07c（SQL 原文见 JSON） |
| 8 | 岗位与权限预置 | L1 | role_permissions 非空 | 7 岗位、32 权限码、各岗位码数见 §二 | ON-08/ON-09 |
| 9 | 管理员登录与权限 | L1 | `["*"]` | `/api/auth/me` → `permissions=["*"]`，菜单 21 项 | ON-10/11/13 |
| 10 | 建员工（6 岗位 + 自定义） | L1 | 建号并登录 | 8 名员工全部「建号→登录→首登强制改密→复登」成功 | SEED-03/SEED-05 |
| 11 | 员工权限快照 == 岗位默认权限 | L1 | 逐岗位相等 | 7/7 相等（客服 11、运营 26、销售 8、财务 8、商品管理员 8、知识编辑 2、自定义 2） | SEED-10（每行附 SQL） |
| 12 | 工人建号 + 唯一性 + 缺 PIN | L1 | 200 / 409 / 422 | 工号重复 → **409**；缺 PIN → **422**；响应不含口令字段 | SEED-06/07/08 |
| 13 | 员工管理页可见新建员工 | L2 | 列表命中 | 7/7 命中；页面文本含「工人」标签 | SEED-11/12；`screenshots/s2-employees-list.png` |
| 14 | RBAC 读面矩阵 | L1 | 有码放行 / 无码 403 | 9 身份 × 13 读端点 **全部匹配** | `out/s3-rbac-matrix.json` |
| 15 | RBAC 写面矩阵（修正探针） | L1 | 同上 | 9 身份 × 7 写端点 **63/63 匹配** | `out/s3b-write-matrix.json` |
| 16 | 越权检测（合法载荷打建单） | L1 | 无码必 403、有码必建 | 8 身份 **越权 0 例**；判别性对照 = `POST /api/admin/users {}`：运营(有码)422 vs 客服(无码)403 | RBAC2-01/02、RBAC2-03 |
| 17 | 页面路由守卫 | L1 | 无码 ⇒ 403 页 | 16 路由 × 9 身份：**除 `/inbound-orders`、`/agent-workspace/human-sessions` 外全部正确** | RBAC-UI、RBAC3-04 |
| 18 | 菜单可见性 | L1 | 无越权项 | 9 身份菜单项均为其权限码子集（admin 21 / 运营 19 / 商品管理员 11 / 客服 10 / 销售 9 / 财务 7 / 知识编辑 5 / 自定义 4 与 1） | RBAC2-05（期望值从 `config/menu.ts` 现取） |
| 19 | 工人身份不得进商家后台 | L1 | 403 | `GET /api/admin/orders` 带 `X-Worker-Session-Id` → **403**（垂直越权防护生效） | RBAC-W3 |
| 20 | 商品创建（两轮） | L1 | 422 空校验 / 200 落库 / SKU | 空提交 422「商品名称不能为空」；正向 `products#…` `base_price=88.50`；`product_skus` 1 行 | DOC-PRD-1/2/3 |
| 21 | 订单创建（两轮） | L1 | 4 类校验 + 落库 | 空提交/缺物流/手机号格式/空明细 **4 条校验全部命中预期文案**；正向 `orders#2026…` 金额 300.00、明细 1 行 3.00 | DOC-ORD-1~5 |
| 22 | 订单状态流转 + 备注 | L1 | 200 且落库 | 待付款→已确认 DB `status=confirmed`；备注端点 200 | DOC-ORD-6/7 |
| 23 | 客户档案随下单 upsert | L1 | 有客户行 | `customer_profiles#34dd22d7…` phone=13100000001 tenant=23 wechat_nickname=验收客户R1363156 | DOC-CUS-1（SQL 原文见 JSON） |
| 24 | 售后建单（两轮） | L1 | 校验 + 落库 | 空提交 422；退货需订单处于允许态（422 文案点名）→ 已确认单建 `AS-20261002-0003` | DOC-AS-1/2 |
| 25 | 财务登记（两轮） | L1 | 下限校验 + 落库 | `amount=0` → 422「金额必须大于 0」；正向 `amount=88.50 payment_method=cash` | DOC-FIN-1~3 |
| 26 | 入库单（两轮） | L1 | 明细必填 + SKU 归属 + 落库 | 空明细 422；SKU 不属该商品 422（服务端挡住串写）；正向 `RK-20261002-0002/0003` | DOC-INB-1/2 |
| 27 | 列表计数 == DB 计数 | L1 | 5 类单据相等 | 商品/订单/售后/财务/入库单 **5/5 相等** | DOC-CNT |
| 28 | B 端 H5 登录与校验 | L1/L2 | 渲染 + 负向拦截 | 空提交 →「参数校验失败」；错误 PIN →「工号或 PIN 不正确」且不放行 | H5-01~03；`screenshots/s5-0*.png` |
| 29 | B 端 H5 会话与登出 | L1 | 刷新不掉线 / 登出回落 | 刷新后页头仍显示当前工人；登出回登录视图 | H5-05、H5-10b |
| 30 | B 端 H5 扫码 → 报工 | L1/L2 | 服务端定工序、记账落库 | 旧码路径（选套+选部位）→ 工序「精裁」应做 2.00 米 → 开工 → 回执「已领活 · 下一道：三边」 | H5-08/09 |
| 31 | 报工记账与进度 | L1 | DB 行 + 进度推进 | `production_work_logs#ed3715a7…` worker_name=验收工人978212 qty=2；`done 0 → 1`(total 12) | H5-10/11/12 |
| 32 | 机台页 | L1 | 渲染 | 「机台模式 · 裁高」+ 未登录提示 | H5-13 |

---

## 四、问题清单（含证据与归因）

> 归因纪律：每条给出**强度**。证据不足的写「待归因」，不硬归。

### F1 · P1｜前端路由守卫缺 `/inbound-orders`（纵深防御缺口，无数据泄露）

- **现象**：商品管理员（无 `inbound:view`）在地址栏直达 `/inbound-orders`，**未被 403 页拦截**，页面完整渲染，含「新建入库单」「期初建账导入」等操作入口。
- **证据**：
  - RBAC2-06 / RBAC3-04 读数：`403 页可见=false`；页面文本含「入库单 商品布料入库：建单（草稿）→ 过账…期初建账导入 新建入库单」；同页 `GET /admin/inbound-orders?status=` 返回 **403**（后端挡住数据）。
  - 截图：`out/screenshots/s3c-guard--inbound-orders.png`
  - 源码对照：`frontend/admin-web/src/app/(dashboard)/layout.tsx` 的 `ROUTE_PERMISSION_MAP` **没有** `/inbound-orders` 前缀；而 `frontend/admin-web/src/config/menu.ts` 该节点声明了 `permissionCode: 'inbound:view'`（菜单隐藏、路由不拦 = 两条防线只生效一条）。
- **影响**：菜单不可见但可直达；误以为有权限的员工会看到操作按钮，点下去被后端 403（体验/一致性受损）。**不构成越权或数据泄露**（API 与写权限均在服务端强制）。
- **归因强度**：机制级（源码级定位：守卫表缺项，非运行时偶发）。

### F2 · P1｜前端路由守卫缺 `/agent-workspace/human-sessions`（同上）

- **现象**：销售（无 `agent:session`）直达 `/agent-workspace/human-sessions`，未被 403 页拦截；页面渲染「在线接待工作台」，并弹出两次「没有权限执行此操作」。
- **证据**：RBAC3-04 读数 + `out/screenshots/s3c-guard--agent-workspace-human-sessions.png`；`ROUTE_PERMISSION_MAP` 只有 `/chat` → `agent:session`，覆盖不到 `/agent-workspace/*`。
- **影响**：同 F1（空壳页 + 报错弹窗；后端接口已拒绝）。
- **归因强度**：机制级。

### F3 · P2｜写端点的 `@Valid` 参数校验**先于**权限校验（422 早于 403）

- **现象**：对 `POST /api/admin/orders`、`/products`、`/after-sales`、`/finance/transactions` 发空 body，**9 个身份一律 422**（含完全无权限的自定义岗位），而不是 403。
- **判别性对照（证明不是越权）**：改用**无 `@Valid`** 的端点，权限判定立刻分出胜负 —— `POST /api/admin/users {}`：运营（有 `employee:create`）→ **422**，客服（无）→ **403**；`DELETE /api/admin/orders/{不存在}`：运营 → 404，客服 → 403。修正探针后 9 身份 × 7 写端点 **63/63 全部匹配**。
- **影响**：无权限身份可借字段级报错推断接口契约（信息面），**不产生任何写入**。属取舍而非漏洞，但值得在产品口径里显式记录（或把权限判定提到参数绑定之前）。
- **归因强度**：机制级（Spring MVC 参数解析/校验 → 方法调用 → AOP 权限切面的顺序所致）。

### F4 · P2｜岗位「知识编辑」不含任何 knowledge 权限

- **现象**：`knowledge_editor` 岗位默认权限 = `[dashboard:view, product:list]`，**没有** `knowledge:view/manage`；该岗位员工菜单里没有「知识库」，调 `/api/admin/knowledge/cards` 得 403。
- **证据**：DB `role_permissions` 计数=2；`backend/admin-api/src/main/resources/db/migration/V137__formalize_legacy_roles.sql` 与 `backend/admin-api/src/main/java/com/migao/admin/service/RoleService.java` 的硬编码**两处一致**（⇒ 不是代码漂移，是口径问题）。
- **影响**：岗位名与实际能力不符（该岗位做不了本职）。
- **归因强度**：机制级（两处真值源一致，属产品口径待确认）。

### F5 · P2｜`GET /api/admin/roles`、`/api/admin/roles/all` 无权限注解

- **现象**：RBAC 矩阵的审计项显示：**9 个身份（含 0 权限自定义岗位）全部 200**。
- **归因**：与 `docs/wiki/RBAC.md` 记载的 #4727「分支 ③：没有 `@RequirePermission` 的端点 = 对所有商户员工开放」一致，属**已登记**审计面的存量。
- **影响**：本企业岗位名/权限码集合对所有员工可见（低敏感）。

### F6 · P2｜陈旧构建产物会让**已退休的迁移**被重新执行，并污染同一 JVM 的后续请求

- **现象 A（迁移失败）**：启动日志报 **5 条迁移失败**，含
  `V108/V111/V112__product_roll_length_and_selling_method_base_attribute.sql`（`column "selling_method" does not exist`）、
  `V72__switch_routing_model_consumers.sql`（`relation "production_option_factors" does not exist`）、
  `V79__seed_fabric_route_and_packing_operation.sql`（唯一键冲突），
  并打印「本次有 5 条迁移失败，schema 可能与代码不一致」。
- **根因（已核实）**：`src/main/resources/db/migration/` 只剩 V123–V143（V1–V122 已移入 `db/migration-archive/`，117 个文件），但 `target/classes/db/migration/` 仍留有 **136 个**旧文件 —— Maven 资源增量 copy **不删除**已从源码移除的文件，而 `MigrationRunner` 按 `classpath:db/migration/*.sql` 扫描（`migao.migration.locations`）⇒ 退休迁移被反复执行。
- **现象 B（同 JVM 后续请求异常）**：同一进程内，07:19:00 的定时简报任务与 07:19:02 的入驻申请请求均返回
  `ERROR: current transaction is aborted, commands ignored until end of transaction block`（SQL state 25P02），导致该次入驻申请直接失败。
- **处置与对照**：删掉 `target/classes/db`（构建产物）后重启 ⇒ 迁移**零失败**，此后日志中 25P02 计数 **0**。
- **归因强度**：现象 A 为**机制级**（源码/构建产物逐文件比对）；A→B 的因果链**证据不足，记为待归因** —— `MigrationRunner` 用的是 `JdbcTemplate`（默认自动提交），理论上不应把失败语句留在事务里；要坐实需在迁移失败瞬间抓取连接的事务边界。
  ⚠️ 另注：修复前那段日志已被重启时的 `tee` 覆盖（`/tmp/acc-admin-api.log`），本报告引用的是本会话当时的读取原文；若要再复核需重放该场景。
- **建议**：跑本地栈前 `mvn clean`（或让运行脚本主动清理 `target/classes/db`）；`MigrationRunner` 对「classpath 中存在、台账中无、执行即失败」的迁移可考虑 fail-fast 而非静默跳过。

### F7 · P3｜文档与实现漂移：新租户种子岗位「五岗」实为 **7 岗**

- **现象**：`docs/wiki/RBAC.md` 写「新租户注册初始化**五岗**种子（管理员/客服/运营/销售/财务）+ role_permissions 预置」；本次**新建租户实测为 7 个岗位**：`admin / customer_service / finance / knowledge_editor / operator / product_manager / sales`（多出 `product_manager`、`knowledge_editor`）。
- **证据**：`tenant_id=23` 的 `roles` 查询 7 行（ON-08，报告 §二）；`V137__formalize_legacy_roles.sql` 明确把这两个 POC 期历史岗位「正式定义」为岗位。
- **归因强度**：机制级（文档未随 V137 更新），属**文档漂移**而非实现缺陷。

### H1 · 探针自身缺陷（**非产品问题**，已修正并复跑）

- 现象：阶段 2 有一条 `SEED-10 自定义岗位` fail（`snapshot=[] vs role_permissions=[...]`）。
- 归因：**本脚本**用 `permissions`（权限码）提交，而 `POST /api/admin/roles` 只认 `permissionIds`（与前端岗位权限弹窗同口径）。
- 处置：改用 `permissionIds` 后重跑 → 4/4 通过（`s2b-custom-role.json`）。原始那次误提交的产物被保留为**「零权限自定义岗位」边界样本**，用于验证「门禁放行、细粒度全拒」（RBAC2-04 该身份 7/7 全 403）。

### H2 · 仓库自带 UI 冒烟脚本与当前 UI/接口脱节（12/32 失败，**非产品缺陷**）

`scripts/ui-smoke-merchant/spec.mjs`（2026-09-24 最后修改）在新租户上 20/32 通过。逐条用**截图 + 报错原文**归因：

| 失败旅程 | 归因 | 证据 |
|---|---|---|
| `01-login`（本轮已适配） | 登录页改为「员工登录/管理员登录」双页签（#5485），默认页签无 `#phone` | 复制版脚本需先点「管理员登录」页签才通过 |
| `23-employees` | 建员工表单新增**必填**「登录用户名」「初始密码」（#5485），脚本未填 ⇒ 创建被拦 | `screenshots/23-employees.png`：两个必填框为空、创建未生效 |
| `32-production-qr-and-piecework` | 建单新增**必填** `logisticsType`/`logisticsCompany`（#5840） | 报错原文 `HTTP 422 … 常用物流/快递不能为空` |
| `08-products-list` / `10-product-detail` | 页面标题由「商品列表」改为「商品管理」 | `screenshots/08-products-list.png`（列表数据正常渲染） |
| `09-products-new` / `11-product-edit-doorwidth` | 新增商品页已改为「商品分类 + 售卖方式 + SKU」表单，旧「规格尺寸/门幅下拉」不存在 | `screenshots/09-products-new.png` |
| `12-processing` | 新增加工项新增**必填「加工分类」**（需先建分类） | `screenshots/12-processing.png`（弹窗内黄色提示「请先创建」） |
| `24-roles` | 岗位权限页改为卡片，编辑入口是**铅笔图标**（无文字），脚本按文字找按钮 ⇒ 弹窗不开 | `screenshots/24-roles.png`（9 张岗位卡片全部正常） |
| `15-orders-new` / `16` / `17` | 脚本按名字搜「遮光窗帘」——**新租户没有种子商品** | 报错原文「商品搜索结果为空（未找到 遮光窗帘）」 |
| `07-chat` | 米宝对话页空白面板（Agent 功能，**不在本次范围**）；需另判是否需会话前置 | `screenshots/07-chat.png` |

**建议**：该脚本是人工冒烟工具（不在 CI），但会把「脚本过期」呈现成「页面坏了」。按上表逐条同步（或纳入 CI 后自然暴露）。

### 正面确认（值得记录）

- `GET /api/admin/products/{id}` 返回的 bigint `id`（如 `2105802414311309314`）是**字符串**而非数字 ⇒ 避免了 JS 精度丢失（本脚本在 `psql row_to_json` 路径上正好踩到这个坑，反证该实践必要）。
- 工人身份（`X-Worker-Session-Id`）访问 `/api/admin/**` 被 **403**；工人错误 PIN 返回 **401**，均与设计一致。

---

## 五、遗留物与收口

| 项 | 状态 | 处置建议 |
|---|---|---|
| `tenants#22` 验收布艺870495 | 首轮脚本中断留下的孤儿租户（含 1 管理员） | 如需清理：按本报告 §二 的 tenant_id 定向删除；**未执行**（共享 dev 库，破坏性动作留给人类裁定） |
| `tenants#23` 验收布艺940121 | 本次验收租户，含 8 员工 + 1 工人 + 若干单据 | 保留作为复算基线；确认后可整租户清理 |
| 本次改动 | **未改任何仓库源码**；仅新增未跟踪目录 `acceptance/2026-10-02/`（`git status` 干净） | 按需归档或删除 |
| 后台服务 | admin-api/ai-agent/admin-web/H5 静态服务 | 验收结束后可停（本轮未停，便于复算） |

---

## 六、复核抽验（独立视角）

- **抽验方式**：对本报告 §三 的 32 条验收点，逐条回到 `out/*.json` 核对「判定 ↔ 证据引用」是否同源；对 5 条 L2 项另开截图/DOM 原文比对。
- **抽验发现并已修正的自身缺陷（4 处，均已复跑）**：
  1. 写探针用空 body 打 `@Valid` 端点 → 422 被误读成「放行」（§四·F3）；改用无 `@Valid` 端点后 63/63 匹配。
  2. `psql row_to_json` 把 bigint 交给 JS ⇒ 精度丢失，导致入库单 SKU 被服务端判「不属于该商品」（§四·正面确认）；改为 `id::text` 后通过。
  3. 脚本内 `ctx` 只写文件不同步内存 ⇒ 跨轮次读到上一轮的 product/order id（已在阶段 4 修正并复跑）。
  4. 「客户档案 upsert」判据一度**静默未执行**（探针查了不存在的 `customers` 表，被 `tbl()` 守卫挡下、既不计 pass 也不计 fail）—— 这正是 `migao-acceptance` 所说的「看起来有覆盖」；改用 `customer_profiles` 复算后确认 1 行命中（`DOC-CUS-1` 现为 pass）。
- **未覆盖 / 有意不做**：
  - Agent（米宝/小布）对话与工具调用 —— 用户明确排除；
  - 小程序（mini-app / bmini-app）与 C 端 H5 —— 不在本次范围；
  - 并发/压测、越权之外的横向越权（跨租户）矩阵 —— 本轮只做**同租户内岗位越权**验证；
  - `07-chat` 空白面板的定性 —— 属 Agent 面，未展开。

---

## 七、建议的后续动作（按优先级）

1. **补 2 处前端路由守卫**（`/inbound-orders`、`/agent-workspace/human-sessions`）到 `ROUTE_PERMISSION_MAP`，并与 `config/menu.ts` 的 `permissionCode` 做**一致性判据**（避免「菜单有码、守卫无码」再次发生）。
2. **同步 `scripts/ui-smoke-merchant/spec.mjs`**（H2 的 8 类），或把它接进 CI 让过期脚本自己变红。
3. **确认「知识编辑」岗位口径**（F4）：是有意留空，还是应补 `knowledge:view`（读）/`knowledge:manage`（写）。
4. **本地栈卫生**（F6）：跑之前清 `target/classes/db`（或 `mvn clean`）；评估 `MigrationRunner` 对「classpath 有、台账无、执行失败」的迁移是否应 fail-fast。
5. **口径记录**（F3）：把「`@Valid` 校验先于权限切面」写成已知取舍，或把权限判定前移到参数绑定之前。
6. **文档同步**（F7）：`docs/wiki/RBAC.md` 的「新租户五岗种子」更新为实测 7 岗（含 V137 正式化的 `product_manager`/`knowledge_editor`）。


---

## 八、连贯链路补验（2026-10-02 追问后新增）

### 8.1 为什么补：首轮的覆盖是**五段孤立探针**，不是一条链路

用户追问「你走的是入库-下单-加工-报工-发货链路？」——**当时的答案是「不是」**。逐段核对源码与库内真实状态：

| 环节 | 首轮实际做到 | 缺口（实测读数） |
|---|---|---|
| 入库 | 建了 3 张**草稿**入库单 | ❌ 没过账 ⇒ `stock_batches=0`（无批次号）、现货未增、台账无分录 |
| 下单 | 建单/明细/状态/备注/客户 upsert | ⚠️ 未与入库批次联动（没消费自己入的货） |
| 加工 | `generate` + 工序实例 + qr_token | ⚠️ 未在生产看板页面确认；未走批次指派 |
| 报工 | ✅ B 端 H5 全链路 | 与上述单据**不在同一张单上** |
| 发货 | **完全没做** | ❌ `order_shipments=0`；worker-h5 发货模块一个端点都没调 |

### 8.2 补验结果：一条单跑通，18/18

脚本：`harness/s6-chain.mjs`（单条命令可复跑）。链路对象：入库单 `RK-20261002-0006` → 订单 `20261002402820017` → 加工单 `JG-20261002-7764` → 发货。

| # | 环节 | 三路证据（读数原文见 `out/s6-chain.json` / `screenshots/`） |
|---|---|---|
| CH-03 | **入库过账**（四联） | `inbound_orders.status` draft→**posted**；`product_skus.stock` 0→**100**；`stock_batches` 0→1（批次号 `PC-20261002-0003`｜100｜@12.5｜金额 1250｜缸号｜来源单号）；`stock_ledger_entries` +1（`inbound` delta=100，0→100，操作人=13996940121） |
| CH-04 | **移动加权平均成本** | 台账 `avg_cost` null→**12.5**（过账前现货 0、本次 100@12.5）⇒ 与加权平均公式一致，成本金额 1250 |
| CH-05 | 批次读面 | `GET /api/admin/inbound-orders/batches?skuId=` → 1 条 |
| CH-06 | 下单引用入库商品 | `order_items.product_id` = 入库批次同一商品；**下单不扣现货**（100→100，扣减发生在备料/发货） |
| CH-08 | 加工单实例化 | `processing_orders#JG-…` status=generated；`processing_position_operations` **12 行**；qr_token 32 位 hex |
| CH-09 | 生产看板**页面** | DOM 文本含该加工单号（截图 `s6-01-production-board.png`） |
| CH-10 | **发货守卫正向生效** | 加工单未完成时发货页不放表单，文案「须先完成加工单后再发货」（截图 `s6-02-ship-guard-blocked.png`）· `OrderShipGuard.assertProcessingCompletedBeforeShip` |
| CH-11 | **B 端 H5 扫码报工** | 扫本链路的码 → 工序「精裁」→ 回执「已领活 · 下一道：三边」；`production_work_logs` 0→1 条（10.00 米 @0.40，工人=验收工人978212） |
| CH-12 | 报满 → 加工单完成 | 12 轮补齐 → 进度 **12/12**，`processing_orders.status=completed`，累计 12 条 / 75 米 / 计件 31.4 元 |
| CH-13 | **商家侧发货页** | 页面操作 → `orders.status` confirmed→**shipped** + 物流留痕，页面出现「发货成功」（截图 `s6-04/05`） |
| CH-17 | **派工指定批次 ⇒ 入库批次被本单消耗** | `generate(batches=[{orderId,itemId,batchNo}])` → `stock_batch_consumptions` 新行 `delta=-20`（100→80，原因 `processing_order`，带订单号/加工单号） |
| CH-18 | **工人侧发货**（打包→发货） | `pack` → `orders.status=packed`；`ship` → `order_shipments#SH202610020749520520`（来源 worker，打包人=发货人=验收工人978212，运单 SF…)；`order_shipment_items` 实发 1 行 / 5.00 米；`orders.status=shipped` |

### 8.3 补验暴露的三条**语义事实**（此前口径不清，现已留证）

1. **两条发货路的证据载体不同**（源码 + 实测）：**商家侧** `POST /api/admin/production/orders/{id}/ship` → `OrderService.shipWithLogistics` 只写 **`orders`**（状态 + 物流两列）+ 日志，**不写** `order_shipments`（CH-13 实测该表行数=0）；**工人侧** `/api/worker/shipment/**` → `OrderShipmentService` 才写 `order_shipments` + `order_shipment_items`（含打包人/发货人/实发明细）。两条路共用同一个 `OrderShipGuard`。
2. **订单明细不存 SKU**：`order_items` 只有 `product_id`（无 `sku_id` 列），SKU 经 `processing_info` 带到加工，**SKU 级消耗证据在 `stock_batch_consumptions.sku_id`**。
3. **「现货」与「批次余量」是两个口径，差额有正式解释腿**：派工消耗批次 20 米后 `product_skus.stock` 仍 100、`Σ批次余量` 80 ⇒ 对账读面 `diff=-20`、`explainedDiff=-20`（腿名 `soldUnbatchedMeters`）、`reconciled=true`、服务端 0 条 WARN ⇒ **设计如此**（`docs/design/old-system-migration-and-opening-balance.md` 的「SKU 库存 ≡ Σ批次余量」是**过账/期初时刻**的不变量，我当时按恒定不变量去读，属误读，已纠正）。缺省不指派批次时**不扣批次也不出台账行**，是 `ProcessingOrderGenerateRequest` 明写的本阶段定义特征。

### 8.4 新增发现

### F8 · P3｜`GET /api/admin/batch-stock/reconcile` **不带 `productId` 时静默返回「一切正常」的空结果**

- **现象**（可复算，A/B 对照）：

| 调用 | 返回 |
|---|---|
| `/api/admin/batch-stock/reconcile`（无参） | `rows: []`、`totalDiff: 0`、`unreconciledCount: 0` |
| `…?productId=c8d45de5…`（同一份数据） | `rows: 1`、`totalDiff: -20`、行内 `reconciled: true` |

- **归因**：`StockBatchConsumptionService#reconcile` 的 SKU 列表用 `productSkuMapper.selectList(new LambdaQueryWrapper<ProductSku>().eq(ProductSku::getProductId, productId) …)` —— `productId` 为 null 时该条件仍被拼进 SQL（`product_id = NULL`）⇒ 匹配 0 行。而方法体前半段是**按全租户**聚合批次/消耗/台账的，可见设计意图本就是「productId 可省 ⇒ 全租户对账」；控制器两个参数也都声明 `required = false`，契约台账同样把 `productId`/`skuId` 记为可选。
- **影响面**（已核实，不夸大）：前端 `BatchStockPanel` 有 `if (!productId) return` 且恒传 `productId` ⇒ **当前 UI 不受影响**；服务端测试 `StockBatchControllerTest.reconcileOk` **只覆盖带 `productId` 的分支** ⇒ 无参分支**无判据**。风险 = 任何新调用方（导出/巡检脚本/新报表）漏传 `productId` 时，会读到「差额 0 / 无异常」的**假清白**读数 —— 与验收协议里「不会红的断言 = 空断言」同族的**产品侧**形态。
- **建议**：`eq(StringUtils.hasText(productId), …)` 让条件随参数缺席而消失（或对无参调用显式回全租户），并补一条**无参**用例（现在只有带参用例）。

### 8.5 补验中自查并修正的探针缺陷（4 处，均在 `s6-chain.mjs` 内留注释）

1. **假绿陷阱**：首轮商品创建因缺 `categoryId` 失败，但 `productId` 为 `undefined` 被 `JSON.stringify` 丢掉 ⇒ 订单照样 200、探针判「通过」。现每步加 `need(value, what)` 前置断言（空则直接 fail 并写明缺哪个对象）。
2. `order_items` **无 `sku_id` 列**（首轮按该列断言 ⇒ 恒 false）；改为判 `product_id` + `processing_info` 含 skuId。
3. `production_work_logs` **无 `started_at` 列**、`worker_sessions` **无 `session_id` 列** ⇒ 首轮 SQL 直接报错、后续 401；工人 session 改为走 `POST /api/worker/login` 取。
4. `stock_batches` 无 `remaining_qty`、台账表名是 `stock_ledger_entries`、工序实例表用 `processing_order_id`（非 `order_id`）——全部按 `information_schema` 实测校正。


---

## 九、RBAC 与「不同岗位的所有功能」补验（2026-10-02 第二轮追问后）

### 9.0 ⚠️ 先披露一次**环境漂移**（影响本轮哪些结论、不影响哪些）

用户追问「不同岗位的所有功能以及 RBAC，别给我打折扣」后，我按铁律 11「核验前自证坐标」复核了被测对象，发现：

| 时刻(+08) | 事件 | 证据 |
|---|---|---|
| 07:00:56 | main 快进到 `3fa84ab89`（我开工时核对过） | `git reflog` |
| 07:20:47 | 我从主干起 admin-api | `Started AdminApiApplication in 4.792 seconds` |
| **07:44:40** | **同一 checkout 被切到 `feat/5939-shipments-menu`**（另一 agent 在开发 #5939） | `git reflog`：`checkout: moving from main to feat/5939-shipments-menu` |
| 07:54 / 08:04 | 该分支两次提交（含 merge origin/main） | `HEAD = b621d3a19` |

**结论口径**：
- **后端进程仍是主干**（07:20 启动未重启）⇒ 阶段 1–7、9 的 API 结论**对 `main@3fa84ab89` 有效**；
- **`next dev` 会跟随工作树源码** ⇒ 07:44 之后任何 UI 结论都描述**那个特性分支**；
- 我最初枚举「100 个受控端点」时读的是**工作树**（= 分支）⇒ 它对主干是**错的样本**：比主干**少 11 个** `/api/admin/agent/**` 端点、**多 1 个** `/api/admin/shipments`（这解释了那一行 404 —— 该端点只存在于分支，**不是产品缺陷**）。
- 处置：**不动那个工作树**（有人在上面干活），改为 `git worktree add /tmp/migao-main 3fa84ab89` 建**隔离检出**，前端在 **3002** 端口起（webpack 模式），端点面/路由面一律从**提交对象**导出（`git show 3fa84ab89:…`），不从工作树读。

### 9.1 全量端点矩阵：**111 个受控端点 × 9 个身份 = 999 格，零违规**

- 期望值 = 「该身份的权限快照是否含该端点要求的码」（快照取自运行时 `/api/auth/me`）。
- 逐格读数分类：`DENY`(403 且错误码 PERMISSION_DENIED) / `ALLOW`(2xx，或非 2xx 但**同行非持有者 403 反证**已过切面) / `EARLY`（切面之前早退，**不计入通过**）。
- 读数：**allow=307｜deny=674｜无法判定=18（2 行，已具名）｜违规=0**；**109/111 行有「非持有者被 403」的对照**。
- 复算：`node harness/s7-rbac-matrix.mjs`（产物 `out/s7-matrix.json`、`out/permission-surface-main.json`）
- **探针自证守卫**（本轮新增）：跑前跑后比对真实对象读数 —— `用户(在用 10/软删 0)、岗位名、订单 20、商品 18、发货单 1` **逐项一致** ⇒ 矩阵本身不改数据。

仍**无法判定**的 2 行（具名，不掩盖）：
| 端点 | 现象 | 归因 |
|---|---|---|
| `DELETE /api/admin/upload/image` | 矩阵内全员 400「请求体格式错误或缺失」；**同载荷直调返回 200** | 我的探针与直调不一致（未定论的那一侧在探针），1 行，已登记 |
| `PATCH /api/admin/agent/products/{productId}/skus/{skuId}` | 全员 **500 INTERNAL_ERROR** | Agent 工具面（需 AI 服务调用上下文），且 500 本身待归因 |

### 9.2 全量页面守卫矩阵：39 条路由 × 9 个身份（坐标 = `main@3fa84ab89` 的 `(dashboard)` 全部 `page.tsx`）

- 判定：直达路由后 DOM 是否出现 403 页（「无权访问该页面」）；期望 = `ROUTE_PERMISSION_MAP` 覆盖该前缀 **且** 该身份无该码。
- 守卫前缀 **19** 条、页面 **39** 条、**覆盖 33 条**。
- **未被任何守卫覆盖的 6 条**（与前端源码逐字一致，非人工记忆）：`agent-workspace`、`agent-workspace/human-sessions`、`agent-workspace/sessions`、`inbound-orders`、`inbound-orders/new`、`notifications` —— 即 §四 F1/F2 的完整清单，**主干上确认存在**。
- 复算：`BASE_URL=http://localhost:3002 node harness/s8-routes-buttons.mjs`（产物 `out/s8-routes.json`、`out/route-guard-map-main.json`）

### 9.3 每个岗位**用自己的账号**跑本岗位的功能（阶段 4 是 admin 代跑，这是补的真账）

8 个岗位 × 17 个动作 = **136 个方向，全部与权限码一致**（每个「做成」都以 **DB 计数差**为准，不看接口自称）：

| 岗位(码数) | 用自己账号真的做成了 | 按码被拒（403 且**库里无变化**） |
|---|---|---|
| 运营(26) | 建订单·落库、建商品·落库、登记流水·落库、建入库单·落库、**入库过账·落库**、建售后工单·落库 + 7 项读 | 建员工、建岗位、建知识卡 |
| 客服(11) | 读订单/售后/客户/入库/知识卡/看板 | 建订单、建商品、登记流水、建入库单、过账、**建售后工单**、建员工/岗位/知识卡、读加工单、读员工 |
| 商品管理员(8) | 建商品·落库、读加工单、读看板 | 其余 14 项 |
| 财务(8) | **登记流水·落库**、读订单/入库/看板 | 建订单、建商品、建入库、过账、建售后…（读客户/售后/知识卡也被拒） |
| 销售(8) | 读订单/客户/入库/看板 | **建订单**、建商品、… |
| 知识编辑(2) | 读看板 | 其余 16 项（含**读/建知识卡**） |
| 自定义岗(2) | 读订单、读看板 | 其余 15 项 |
| 零权限岗(0) | （无） | 全部 17 项（含读看板） |

- 复算：`node harness/s9-position-jobs.mjs`（产物 `out/s9-position-jobs.json`、`out/s9-menus.json`、`screenshots/s9-menu-*.png`）
- **工人身份**：`GET /api/worker/me` 200（`pages=["report","order","cut_calc","shipment"]`）｜`GET /api/admin/orders` **403** ⇒ 垂直隔离成立。

> **由此浮出的岗位口径问题**（值得产品确认，非缺陷）：**客服建不了售后工单**（缺 `order:refund`）、**销售建不了订单**（缺 `order:create`）、**知识编辑读不了知识库**（缺 `knowledge:view`）、**财务读不了客户列表**（缺 `customer:view`）。这些码都在种子矩阵里被有意排除还是漏配，需要口径裁定；它们与 §四 F4 是同一族。

### 9.4 元素级（按钮）RBAC：先把**真实门控点**数清

- **前端全仓只有 6 处 `hasPermission(...)` 元素级门控**（不含路由守卫）：`employees/page.tsx` 1 处（`employee:create` ⇒ 新增/编辑/删除/禁用）、`processing-orders/[id]/production/page.tsx` 4 处（`processing:manage` ⇒ 撤销码/重定价/自测码）、`layout.tsx` 1 处（路由）。
- ⇒ 其余 37 个页面**不做按钮级隐藏**，写动作由后端 403 拦 —— 这与 `layout.tsx` 里的具名注释一致（「前端不重复表达写权限」），是**有意取舍**，不是漏做。
- 已验证：员工页写操作按钮随 `employee:create` 显隐（`out/s8-buttons-employees.json` + 截图）。

### 9.5 本轮新增发现

### F9 · P2｜客户端漏传必填参数被报成**服务器内部错误（500）**

- **现象**：`POST /api/admin/inbound-orders/opening-import` 缺 `importRunId` ⇒ `500 {"code":"INTERNAL_ERROR","message":"服务器内部错误"}`；服务端日志原文：
  `ERROR GlobalExceptionHandler - 系统异常: Required request parameter 'importRunId' for method parameter type String is not present`
  （`MissingServletRequestParameterException`）
- **归因（机制级）**：`config/GlobalExceptionHandler` 有 `BusinessException / MethodArgumentNotValid / ConstraintViolation / AccessDenied / IllegalArgument / IllegalState / HttpRequestMethodNotSupported / NoHandlerFound / HttpMessageNotReadable / HttpMediaTypeNotSupported` 共 10 个具名分支，**唯独没有 `MissingServletRequestParameterException`** ⇒ 落到兜底 `@ExceptionHandler(Exception.class)` ⇒ 500。**这是全站性的**：任何带必填 `@RequestParam` 的端点在漏参时都会 500。
- **影响**：客户端集成错误被报成服务端故障（监控误报、排障走偏）；且该失败发生在**权限切面之前** ⇒ 该端点在漏参路径上 **RBAC 不可观测**（0 权限岗位与管理员得到同一结果）。**无数据泄露**（500 不落数据）。
- **修复建议**：加一个 `MissingServletRequestParameterException`（与 `MethodArgumentTypeMismatchException`）→ 400 + 字段名。

### F10 · P3｜2 行无法判定（已具名，不掩盖）

见 §9.1 表：`DELETE /api/admin/upload/image`（探针与直调不一致，1 行）与 `PATCH /api/admin/agent/products/{productId}/skus/{skuId}`（全员 500，Agent 工具面）。

### 9.6 探针自伤事件（必须记录，否则读者会把自伤读成产品缺陷）

第一轮 999 格跑出 **25 处「持有者被拒」**，全部集中在客服。逐层归因后确认**是探针自己造成的**，不是产品缺陷：

1. 我的写探针把**真实 id** 交给了 `PUT/DELETE /api/admin/users/{id}` ⇒ **软删了「客服」账号**（`users.deleted=1`，08:04:04）；同一批探针还把它**昵称改成「RBAC探针」**、用 `reset-password` **重置了它的密码**（置 `must_change_password=true`）、并把 **admin 岗位名改成「RBAC探针岗改39858」**。
2. 时间戳铁证：软删发生在 **08:03:59.344**，第一条 403 也在 **08:03:59.344**；此后 93 条拒绝全部来自这一个账号。
3. 我一度怀疑是「权限快照 vs 角色回退」不一致，**实测否证**：改完密码后 `after-sales / customers / inbound-orders` 全部 **200**；且当时 403 的错误码其实是 **`PASSWORD_CHANGE_REQUIRED`（首登强制改密）**，不是 `PERMISSION_DENIED`。
4. **已修复**：`users.deleted=0`、昵称还原、密码重设为 `Migao@2026y`（并写入 `out/context.json`）、admin 岗位名还原为「管理员」。
5. **已做类级固化**（避免同类再犯）：① 矩阵里**写端点一律用形态合法的假 id**；② 判定**按 `error.code` 而非仅 HTTP 状态**（`PASSWORD_CHANGE_REQUIRED` 单列 `PRECOND`）；③ 新增**探针自证守卫** `M-00b`：跑前跑后比对真实对象读数，任何变化即判红（本轮实测「逐项一致」）。

### 9.7 报告纪律补充

- 本报告此前写的「32 条验收点」等读数是**阶段 1–6** 的；§九 之后的维度面（999 格 / 39 路由 / 136 动作）是**补验**，两者不互相替代。
- 所有「全量」字样都以**坐标**限定：端点面/路由面 = `main@3fa84ab89`；后端进程 = 07:20 起的主干构建；前端（3002）= 同一提交的隔离检出。
