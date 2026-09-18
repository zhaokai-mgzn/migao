# 验收报告：工艺路线商家可配（#4308 后端 + #4307 前端）

- **被测 SHA**：`75c7310e`（main HEAD，含 PR #4329 → `88632f4e` 与 PR #4323 → `75c7310e`）
- **验收者**：集成方（非实现者；两包实现分别由独立 agent 完成，前端包原执行 agent 中途失败后由集成方接手修复）
- **结论**：**确定性层：通过。§15.2 真实浏览器走查：未执行（环境阻塞）⇒ 本报告不下「验收通过」结论**，只给「确定性层已交付 + UI 层待补跑」的分级结论与残余风险。

## 1. 验收对象（可枚举）

| 对象 | 交付证据（内容级，非 commit 可达性） |
|---|---|
| 迁移 V60（信号表 + 版本账 + 加工单三列） | `git show origin/main:...V60__create_routing_customization_tables.sql` = 147 行 |
| `ProductionRoutingCommandService`（写面 + 5 护栏 + 版本账） | 同法 = 476 行 |
| 写面端点（`POST/PUT /routings`、`GET/POST/PUT/DELETE /route-signals`、`POST /operations`、`GET /routing-gaps`） | `ProductionController` 命中 10 处 |
| 四态路线来源 + `route_requested_key` | `ProcessingOrderService` 命中 `missing_route`/`INCIDENT_*`/`route_requested_key` |
| 前端配置页 + 四态提示 + 菜单接线 | `frontend/admin-web/.../production/routings/page.tsx`、`lib/route-source.ts`、`config/menu.ts` 第 4 项 |
| 用例 | `.github/cases/processing-order.yml` PG-026~035、`.github/cases/processing.yml` PP-014 |

## 2. 验收矩阵与判定（每条引证据）

| # | 验收点 | 层 | 判定 | 证据 |
|---|---|---|---|---|
| L1-1 | 路线解析**不再静默回落**：四态 `route_source` + `route_requested_key` 落库，T1/T2 各有 incident 日志 | L1 | ✅ | 集成方**独立复跑** `ProcessingOrderRouteSourceTest` ⇒ `Tests run: 7, Failures: 0, BUILD SUCCESS`（从被推送的 `206cc926` 在独立 worktree 执行，非实现方自述） |
| L1-2 | V60 种子 = 迁移前常量表**逐行等价** | L1 | ✅ | 集成方用自建仪器（从 `git show origin/main:…ProcessingOrderService.java` 抽两张常量表）与 V60 的 10 行 VALUES 按 `(signal, curtain_type, craft, priority)` 比对 ⇒ **10/10 相等**，`帘头` 两用途位次相反被保留 |
| L1-3 | 写面 5 条护栏 + 版本账 + 信号 CRUD + 新增工序 | L1 | ✅ | CI `admin-api unit tests` 在 PR #4329 上 pass；实现方报 `./mvnw -o test` **1687 全绿**（集成方核过该数字口径与 CI 一致） |
| L1-4 | 护栏失败返回 `422 + error.details[]` 逐条理由 | L1 | ✅ | 前端「对**虚构**信封读理由」的缺陷已由集成方修掉并**转正为回归守卫**：`production-routings-guard-envelope.test.ts`（原探针**修复前 2/2 红**、received `"Request failed with status code 422"` → **修复后 2/2 绿**） |
| L1-5 | 前端页面/四态提示/菜单接线 | L1 | ✅ | 集成方独立跑 `vitest`（rebase 到 main 后）⇒ **30 passed**（含菜单四节点断言、四态映射、护栏理由） |
| L1-6 | 三把工具 | L1 | ✅ | `check-ui-regression.sh` ✅、`contract-check.sh` ✅、`verify-all.sh gate` 2/2；`Case Trust Gate` 本地 exit=0（burn-down **条目 86→85**） |
| L1-7 | 交付物**被触发**（可达性判据 v1.11） | L1 | ✅ | ① `GET /routing-gaps` → 调用方 = 前端 `production/routings` 页（`getRoutingGaps`），页面测试断言其渲染；② `PUT /routings/{id}` → 页面保存动作，测试断言**请求体顺序 = 屏幕顺序**；③ 四态提示 → `route-source.ts::routeSourceNotice` 被加工单详情页调用；④ 菜单 → `MenuController` pr4 + `menu.ts` 第 4 项，两侧各有断言钉住 |
| §15.2 | **真实浏览器走查**（新页面 + 写操作闭环） | L2 | ⛔ **未执行** | 见下节 |

## 3. §15.2 未执行 —— 如实登记（含归因与残余风险）

**已执行到的部分**：本机起真栈（admin-api:8090 + admin-web:3101，均来自被测 SHA `75c7310e` 的 worktree）+ 真浏览器（Playwright/Chromium），**登录成功**（`13800138000` 万能码 → `/dashboard`，A0 ✅）。

**阻塞点**：登录后的**所有** API 调用返回 **401/400**（含**既有**页面「生产看板」），因此 A1~A8 的页面级断言**无法判定**。
- **归因（按归因纪律：证据不足就写"证据不足"）**：401/400 同时出现在**未改动**的既有页面上 ⇒ **不可归因于本单改动**；但**具体成因未查明**（候选：并发会话占用 :3001/:8080、本 ad-hoc 栈与云 dev DB 的鉴权/会话状态、`CORS_ALLOWED_ORIGINS` 刚改后的重启时序）。**不写成产品缺陷，也不写成"已通过"。**
- **A5 几何探针的"通过"是空断言**：`fixed=0 个`（本状态下页面未渲染出浮动元素）⇒ **无判别力，不计为证据**（"不会红的断言 = 空断言"）。

**残余风险（未覆盖的）**：新页面在真实浏览器下的 ① 面包屑/菜单名一致性、② 布局遮挡（底部锚定元素 vs 米宝 FAB）、③ 写操作成果物可见性（保存后列表刷新/错误逐条展示）、④ 与既有生产页的 IA 一致性 —— **均未取得证据**。

**复跑 recipe（给有干净端口的人）**：
```bash
# ① 从被测 SHA 建 worktree，并补齐 gitignored 的本地环境（否则 admin-api 起不来）
W=../migao-wt/<branch>; cp <main>/backend/admin-api/.env $W/backend/admin-api/.env
cp <main>/backend/admin-api/src/main/resources/rsa/private.pem $W/backend/admin-api/src/main/resources/rsa/
ln -sfn <main>/tests/node_modules $W/tests/node_modules
# ② 起栈（避开并发会话的 3001/8080）：admin-api SERVER_PORT=8090 + SMS_BYPASS_CODE=123456；
#    admin-web 用独立端口并指向 8090；把该 origin 加进 API 的 CORS_ALLOWED_ORIGINS
# ③ 跑走查（脚本见下），断言：菜单「工艺路线」存在 / 路线列表渲染真实工序 / 缺口区含
#    裁剪-布·裁剪-纱·质检·腰靠垫 / 保存被拒逐条理由 / 几何探针（此时 fixed 必须 > 0 才有判别力）
```

## 4. 已知缺口（照实登记，均已有独立 issue）

| 缺口 | issue | 影响 |
|---|---|---|
| 路线种子与**客户实证**不一致（缺 4 道 / 多 1 道 / 顺序相反 / 6 道工序名库中无） | #4343 | 错工序 ⇒ **错计件工资**；**待客户确认**（#4261），不得猜 |
| `POST /routings` 允许**初版空序列** ⇒ 该路线被派生命中会实例化 **0 道工序**（后端无护栏） | 实现方在 PR 内登记 | 建议裁定：`findRouting` 是否把「活跃但 0 工序」当 `missing_operations` |
| 种子只覆盖 `tenant_id = 1` ⇒ 非 1 号租户建单 422 | #4316 | 多租户不可用；本单**写面即其补救路径** |
| `route_key` 是多部位订单的**有损聚合**（单值列） | 实现方登记（3 条判别用例） | 逐部位明细只在工序实例里 |
| 计件金额**静默少算**（重新实例化软删旧实例 ⇒ 历史报工被跳过） | **#4351（P0）** | 直接少发工资；**修复中**（本单之外） |

## 5. §14 评测用例（零成本结论，未派发任何评测）

按 §13.2 映射表：本单 = 「admin-web 页面结构/写操作闭环」+「不涉及 agent 行为的改动」⇒ **不派发真实 LLM 评测**（与 #4262 用户裁定一致）。确定性层用例已随两包落地（PG-026~035 / PP-014，各带注入式红证）。**无新增工具 ⇒ Case Coverage Gate 无需额外动作。**

## 6. 结论

- **确定性层（契约 / 迁移 / 护栏 / 四态 / 前端单测 / 三把工具 / 交付物可达性）：通过**，且关键项由**集成方独立复跑**（非实现方自述）。
- **§15.2 真实浏览器走查：未执行**（环境阻塞，成因未查明，**不可归因于本单**）⇒ **不下「验收通过」**。
- 建议：① 在干净端口复跑 §15.2（recipe 见 §3）后补一份 L2 证据；② 按 §4 的 issue 顺序推进（**先 #4351 P0**）。
