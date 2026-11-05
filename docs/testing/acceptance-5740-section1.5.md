# #5740 §1.5 独立验收报告 —— 2026-09-27 批（#5730 / #5732 / #5733）

> **执行者**：DSH 独立验收包（不是三个单的实施者；只读 + 临时变异，产品代码零永久改动）
> **执行时间**：2026-11-06 07:03–07:2x +08（`date '+%F %T %Z'` 现取）
> **依据**：`docs/testing/acceptance-protocol.md`、`migao-acceptance`（L1/L2/UA + 红证 + 交付物可达性三问）
> **被测版本（交付态）**：
> - `#5730` = `1ef347dac44e4017186cfb2185c3dedde92851dc`（2026-09-27T13:25:52Z = **21:25 +08** 合并）
> - `#5732` = `c8a143f995857bf43d73ce984edffb7e15958efe`（2026-09-27T13:50:02Z = **21:50 +08** 合并）
> - `#5733` = `d1c86dca36b028f23387d2652836b75513ae9b72`（2026-09-27T14:58:52Z = **22:58 +08** 合并）
> **复核面**：`origin/main` = `071245c08851345ec3eff2dfecff03ccf661bb46`（2026-11-06 07:03 +08 `git fetch` 后现取）
> **环境边界**：本机**无真库凭据**（`DATABASE_URL` 未设、`pg_isready` 对默认 5432 无响应）、**无真机**、
> **未起浏览器栈**；**真实 LLM 评测 0 派发**（#4262 用户裁定）。
> **引用纪律**：按本仓 `migao-dev-flow` §16.7，本文一律用「仓库相对全路径 + `::符号`」定位，
> **不写行号**（行号会被 Case Trust 规则 G / ref-freshness 判红且很快失效）。
> **结论口径（先读这句）**：本报告**不宣布整体「验收通过」**。逐条断言给读数与红证；
> **双 AI 交叉验证未执行**（本会话无子代理能力，见 §5）⇒ 每条结论都是**单侧**，
> 按 `migao-acceptance` 不得写成「已验收」。

---

## 1. 结论摘要

| 单 | 交付面 | 结论 | 一句话证据索引 |
|---|---|---|---|
| **#5730** | RBAC P5 存量收敛 + P6 两个历史岗位正式定义 + I4 生产写动作改由 `production:execute` 把守 | **有条件通过** | L1：`40 passed`（4 个判据文件）+ 真 PG 活迁移链 `2 passed`；红证：注入 `system:manage` ⇒ 2 条具名红、还原后 `10 passed`；**缺**：真库存量读数（R1/R2）、四端点 403 的端到端判据、真栈 UI |
| **#5732** | 精裁输出清单（只读）—— 商家加工单生产明细页 + 工人扫码详情页**同源** | **有条件通过** | L1：Java `82 passed` + admin-web `41 passed` + worker-h5 `41 passed`；红证：把定宽分解分支改坏 ⇒ 具名红、还原后绿；**缺**：真实浏览器旅程 / 真机 / 实时栈 |
| **#5733** | C 端 H5 发布通路（人工发布 + 红线不碰 `w/`、`b/`）+ 新鲜度判据翻 gate | **通过（仅单侧；附 2 条 P2 声明漂移）** | L1：`173 passed`；红证：把 `publish` 默认值改 `true` ⇒ **4 failed / 47 passed**、还原后 `51 passed`；**真实发布实跑**：`2026-11-05T01:02:34Z`（= **09:02 +08**）发布成功（run `41945734691`），`w/`、`b/` BEFORE==AFTER，线上 `last-modified` = `Thu, 05 Nov 2026 01:05:16 GMT`（= **09:05 +08**） |

**交叉验证列的统一说明**：本会话的 `subagent` / `subagent_fork` 委派深度 = 0（不可再起子代理），
**无法让第二个模型独立复核同一份证据** ⇒ 下文每行「交叉验证」列一律为
**「仅单侧（无交叉验证）」**，不逐行重复。这**不是**「已通过双 AI 验收」。

---

## 2. 逐条断言表

### 2.1 #5730（存量授权面）

| # | 断言 | 层 | 证据（命令 + 读数 + 文件） | 红证（怎么才会红） | 交叉验证 |
|---|---|---|---|---|---|
| A1 | P5 生成物新鲜度 + 收敛不变量在**现取树**上成立 | L1 | `python3 -m pytest tests/unit_ci_workflows/test_rbac_migration_convergence.py tests/unit_ci_workflows/test_rbac_endpoint_write_codes.py tests/unit_ci_workflows/test_rbac_submenu_granularity.py tests/unit_ci_workflows/test_agent_permission_parity.py -q` ⇒ **40 passed**（23.16s）。活树判据 = `tests/unit_ci_workflows/test_rbac_migration_convergence.py::test_p5_p6_invariants_are_green_on_the_current_tree` | 往 `rbac/manifest.json` 的 `roles.seed` 里加一个迁移链没有的码 ⇒ 见 A9 的实测红 | 仅单侧 |
| A2 | P5 差集是**现取**（不是手抄固定读数） | L1 | 同一判据文件里 `sales` 的固定差集 = `['order:create']`；注入后现取变成 `['order:create', 'system:manage']` ⇒ 判据当场报「差集读数变了」 | 改迁移链 / 手改固定读数 ⇒ 具名红（实测见 A9 第 2 条） | 仅单侧 |
| A3 | P6 把 `knowledge_editor` / `product_manager` 从历史岗位**正式定义**为岗位 | L1 | 合并提交前后现取：`git show 1ef347dac^:rbac/manifest.json` ⇒ `roles.seed` 5 个；`git show 1ef347dac:rbac/manifest.json` ⇒ **7 个**（新增 `knowledge_editor`、`product_manager`）；`backend/admin-api/src/main/resources/db/migration/V137__formalize_legacy_roles.sql::INSERT INTO roles` 逐租户建行 + 授权 + 终态对账 | 从 `roles.seed` 删掉任一角色 / `V137` 授权多一个码 ⇒ 具名红（判据 `test_p6_formal_definition_is_load_bearing`） | 仅单侧 |
| A4 | I4 四条**真写**端点挂写码 `production:execute`，且新码零外溢 | L1/L2 | 现取 `backend/admin-api/src/main/java/com/migao/admin/controller/ProductionController.java`：`instantiate` / `ship` / `printOrder` / `report` 各一个 `@RequirePermission("production:execute")`；`rbac/manifest.json` 的 `codes.names` 31→32、`ledger_counts.AUTHORIZATION_CENSUS` 15→16；判据 `tests/unit_ci_workflows/test_rbac_endpoint_write_codes.py::test_i4_is_green_on_the_current_tree` 在 40 passed 内 | 删任一处方法级注解 ⇒ 具名红；给台账外端点也挂该码 ⇒ 具名红（`test_dropping_a_method_level_override_is_red` / `test_an_extra_endpoint_on_the_new_code_is_red`，二者均在 40 passed 内实跑） | 仅单侧 |
| A5 | 三条新迁移在**真 PG** 上可执行、可幂等重跑 | L1 | `./mvnw -o test -Dtest=MigrationRunnerLiveChainRealDbTest` ⇒ **Tests run: 2, Failures: 0**（`PgCluster` 起本机临时 PG；不是存量租户库） | 迁移语法/列名/幂等性坏 ⇒ 该判据红（本机可复算；真库数据面另见 A6） | 仅单侧 |
| A6 | **存量租户**的实际 `role_permissions` 补齐 / `users.permissions` 快照回填 | L2 | **无法验证**：无真库凭据；`docs/testing/production-readonly-verification-pack.md` 的 R1/R2 只读 SQL 在本机不可执行。本机只有一个**别的一次性空库**实例（`listen_addresses=127.0.0.1`、非默认端口），不能代表存量租户 | 真库跑 R1：事前 >0、事后 0 行；R2：事后计数 == 事前、`widened = 0`。任一不满足 ⇒ 该断言红 | 仅单侧（且无读数） |
| A7 | 四端点的**运行时 403**（无 `production:execute` 的用户被拒） | L2 | **未端到端验证**：`backend/admin-api/src/test/java/com/migao/admin/controller/ProductionControllerTest.java` 用 `MockMvcBuilders.standaloneSetup(...)`（不挂拦截器），只断言「注解存在且值等于 `production:execute`」；通用拦截器另有 `backend/admin-api/src/main/java/com/migao/admin/security/PermissionInterceptor.java` + `PermissionInterceptorTest` 的「缺权限 ⇒ AccessDenied」覆盖，但**没有**「这四个端点 × 无码用户 ⇒ 403」的专门判据。**不把「字段存在」当「功能生效」** | 补一条 HTTP 集成用例（真实过滤器链 + 无码用户）⇒ 若仍 200 则红；或真栈用无码账号打四个端点 | 仅单侧 |
| A8 | 商家可见：岗位管理页能授予/看到「生产执行」 | UA | 读代码：`frontend/admin-web/src/app/(dashboard)/roles/page.tsx` 的 `allPermissions` 来自 `permissionApi.getPermissions()`，非菜单码进「操作权限」节；后端 `backend/admin-api/src/main/java/com/migao/admin/service/PermissionService.java::ensureFullPermissionCatalog` 与 `RegistrationService.java::initializeDefaultRolesAndPermissions` 写入目录「生产执行 / production:execute」。`frontend/admin-web/tests/unit/pages/roles.test.tsx` ⇒ **26 passed**（页面级渲染） | 目录读失败 / 权限树漏项 ⇒ 页面显式失败态；若 `production:execute` 不在目录 ⇒ 该页勾不到。**未起真栈，无真实浏览器证据** | 仅单侧（无真栈） |
| A9 | **红证（外部注入）**：判据真的会红，且还原后真的会绿 | L1 | ① 备份 `rbac/manifest.json`（sha256 `9d176bcb…`）→ 给 `roles.seed.sales` 追加 `system:manage`（sha256 `e8835bdf…`）→ 跑 `tests/unit_ci_workflows/test_rbac_migration_convergence.py` ⇒ **3 条具名断言失败**（P5/P6 不变量、对照组、差集现取）：核心原文「岗位 `sales`：清单声明里有、**迁移链累计没有**的码 ['system:manage']」+「P5 差集读数变了」；② 从备份还原（sha256 回到 `9d176bcb…`，`git diff --stat` 空）→ 再跑 ⇒ **10 passed** | 若注入后仍绿 ⇒ 判据是空断言（本次实测会红） | 仅单侧 |

**#5730 的证据链小结**：P5/P6/I4 的**静态面 + 迁移机制面**有可复算的绿与红；
**存量数据面**（真库 R1/R2）与**端点运行时 403** 两格是空的 —— 这两格正是「改存量授权面」最接近用户的那部分。

### 2.2 #5732（精裁读面，两读面同源）

| # | 断言 | 层 | 证据（命令 + 读数 + 文件） | 红证（怎么才会红） | 交叉验证 |
|---|---|---|---|---|---|
| B1 | 精裁清单只有**一份实现**，商家详情面 / 商家列表行 / 工人扫码面**同源** | L1 | `backend/admin-api/src/main/java/com/migao/admin/service/ProcessingSetReadService.java::cutPlan` 为唯一聚合；`setOverview` 与 `setRowView` 各调它一次；`CuttingPlanCalculator.java::pieceLengths` 被排料器 `StockBatchConsumptionService.java::piecesOf` 复用。判据：`ProcessingSetReadServiceTest::cutPlanIsIdenticalAcrossReadFacesAndListRow`、`::mutatingCutPlanChangesBothReadFaces`、`::aggregationLivesOnlyInTheSharedReadService` ⇒ Java 侧 **82 passed**（`./mvnw -o test -Dtest=ProcessingSetReadServiceTest,ProcessingOrderSetControllerTest,CuttingPlanCalculatorTest,StockBatchConsumptionServiceTest`） | 任一读面自己算一份 / 三面逐值不等 ⇒ 具名红；`ProductionScanService` 长出第二份 `cutPlan` ⇒ 结构判据红 | 仅单侧 |
| B2 | 数字口径正确：定宽买高按幅分解，定高买宽 = 整窗 1 片 | L1 | `ProcessingSetReadServiceTest::cutPlanFreezesKeySetsAndDecomposesFixedWidth` / `::cutPlanFixedHeightIsOneWholeWindowPiece` 在 82 passed 内；外部红证见 B6 | 把 `CuttingPlanCalculator.pieceLengths` 的定宽分支改坏 ⇒ 实测具名红（B6） | 仅单侧 |
| B3 | 缺值**不造数**：`—` + 原因；接口失败只降级该块；`processing_info` 为 NULL 不 NPE | L1/UA | Java：`::cutPlanNeverSubstitutesFakeNumbers` / `::cutPlanToleratesMissingProcessingInfo`；商家端 `frontend/admin-web/tests/unit/components/CutPlanTable.test.tsx` 与 `frontend/admin-web/tests/unit/pages/processing-orders-production.test.tsx` ⇒ **41 passed**，断言屏上出现 `6.15 米 × 2 片`、缺值 `—`/`缺幅数`、且不得出现 `0.00 米 × 0 片`；工人端 `node --test frontend/worker-h5/tests/worker-h5-scan-complete.test.mjs` ⇒ **41 passed**（含 ⑪ / ⑪-b） | 把 null 折成 0 / 缺值不显示原因 / 整页白屏 ⇒ 上述用例红 | 仅单侧 |
| B4 | 商家**用户可见面**：加工单生产明细页出现「精裁输出清单」 | UA | `frontend/admin-web/src/app/(dashboard)/processing-orders/[id]/production/page.tsx` 渲染 `CutPlanTable`（`testid=production-cut-plan`），页面向 `GET /api/admin/processing-order-sets` 按**加工单号**取数（页面测试断言了取数入口点名加工单号）；`frontend/admin-web/src/components/production/CutPlanTable.tsx` 只渲染入参，不二次计算 | 页面不渲染该块 / 前端自己算一份 / 取数按订单号猜 ⇒ 页面测试红。**未起真栈：无浏览器截图** | 仅单侧（无真栈） |
| B5 | 工人端**扫码详情**上屏「裁多长（米）× 几片」 | L1/UA | `frontend/worker-h5/src/render.mjs::cutPlanView` 两处挂载（`mainView` 两个分支）；`node --test frontend/worker-h5/tests/worker-h5-scan-complete.test.mjs` ⇒ **41 passed**，其中 `⑪` 断言 `裁 6.15 米 × 2 片` 逐字上屏、`⑪-b` 断言清单缺失时整块一个字节都不出现 | 删掉两处 `${cutPlanView(v)}` ⇒ ⑪ 三红（PR body 已给读数）；本报告在 41 passed 内实跑了该用例 | 仅单侧 |
| B6 | **红证（外部注入）**：值断言真的会红 | L1 | 备份 `backend/admin-api/src/main/java/com/migao/admin/service/CuttingPlanCalculator.java`（sha256 `c2fc8f7c…`）→ 把 `pieceLengths` 的 `if (MODE_FIXED_WIDTH.equals(cuttingMode))` 改成 `if (false)` → `./mvnw -o test -Dtest='ProcessingSetReadServiceTest#cutPlanFreezesKeySetsAndDecomposesFixedWidth'` ⇒ **FAILURE**，读数 `["panel_count"=null (expected: 2)]`；还原（sha256 回到 `c2fc8f7c…`，`git diff --stat` 空）→ 同一条 ⇒ **Tests run: 1, Failures: 0** | 注入后仍绿 ⇒ 该值断言是空断言（本次实测会红） | 仅单侧 |

**#5732 的证据链小结**：后端三读面同源、两条前端（商家/工人）**DOM 级**渲染都有可复算的绿与红；
缺的是**真实浏览器旅程**（点卡 / 刷新 / 换窗口）与**真机**，这两项本报告没有取证。

### 2.3 #5733（发布腿）

| # | 断言 | 层 | 证据（命令 + 读数 + 文件） | 红证（怎么才会红） | 交叉验证 |
|---|---|---|---|---|---|
| C1 | 触发面 = `push` 仅 `frontend/mini-app/**` + 手动 `workflow_dispatch`（`publish` 默认 `false`）；合并本 PR **不会发布** | L1 | 现取 `.github/workflows/c-end-h5-publish.yml`：`on.push.paths` = `['frontend/mini-app/**']`；`workflow_dispatch.inputs.publish.default` = `false`；发布步 `if: steps.mode.outputs.mode == 'publish'`；`Resolve mode` 只在 `workflow_dispatch && publish=='true'` 时写 `mode=publish`。判据 `tests/unit_ci_workflows/test_c_end_h5_hosting.py` 在 173 passed 内 | 把 `publish` 默认改 `true` ⇒ 实测 **4 failed / 47 passed**（C7）；删发布步 `if` / 只判 event 不判 `publish` ⇒ 具名红 | 仅单侧 |
| C2 | 红线：发布**不碰** `w/`、`b/`；删除集 = 上一次托管清单 ∩ 磁盘现值（首次无清单 ⇒ 空集） | L1 | 规则在 `deploy/swas/c-end-h5-publish-remote.sh::collect_protected_readings` / `::compute_replacement` / `::apply_publish`；CI 包装 `deploy/scripts/c-end-h5-publish-ci.sh` 断言 `PROTECTED_UNCHANGED=1` 且逐前缀 BEFORE==AFTER；**真实 run 读数**（`41945734691`）：`PROTECTED_w_BEFORE/AFTER = 5eaae509…`、`PROTECTED_b_BEFORE/AFTER = 17f99acb…`、`PROTECTED_UNCHANGED=1`、落地面断言 ④ `GET /w/ 200 哈希 f19e5bd1…≠ C 端产物`、`GET /b/ 200 哈希 919d6e10…≠ C 端产物` | 改坏 `collect_protected_readings` 的两次采样（**同一时刻算两遍**）⇒ 判据会退化成恒等（空断言）；改删除范围到静态根 / 删 `is_reserved` 守卫 ⇒ 沙箱判据红。**本报告没有对「未托管文件的保留」做逐项枚举**（脚本只按清单删，结构上不枚举其它条目） | 仅单侧 |
| C3 | 落地面身份：线上 = 本次构建；不串端；根级 SPA fallback；入口 MIME | L1 | 真实 run `41945734691`：`ROOT_INDEX_AFTER_SHA256 = 7f7e6d61…`、`PUBLISHED_INDEX_SHA256 = 7f7e6d61…`、本地 dist 哈希 = `7f7e6d61…`；落地面断言 ① `GET / 200 哈希 == 本仓库产物`、② `引用只落在根级`、③ `GET /__c_end_spa_probe__/deep/route 回根 index`、⑤ `/js/21.js`、`/js/app.js` 的 `Content-Type: application/javascript`；线上现取 `last-modified: Thu, 05 Nov 2026 01:05:16 GMT`（= **09:05:16 +08**，落在该 run 的发布窗口内） | 线上哈希 ≠ 本地 / 引用出现 `/w/`、`/b/` / 深层路由不回根 index / MIME 错 ⇒ 断言红 | 仅单侧 |
| C4 | 新鲜度判据**默认判红**（gate），且三态分离（陈旧=2 / 无法判定=3 / 新鲜=0） | L1 | 外部实跑（本机造一个**非浅克隆**的临时仓 + 本地 HTTP server；源改动 2026-11-01）：陈旧（线上 2020）⇒ `::error:: 线上产物**陈旧**…` **RC=2**；新鲜（线上 2026-11-05）⇒ `RC=0`；取不到 ⇒ **RC=3**（`::warning:: 取不到…**不等于**新鲜`）。另：本工作区是浅克隆，直接跑 `scripts/h5_freshness_guard.py --ref origin/main` ⇒ **RC=3**（判据自己点名浅克隆），**没有**把「无法判定」塌成「新鲜」 | 把 `--no-gate` 设为默认 / 把 rc=3 塌成 rc=0 或 rc=2 ⇒ `tests/unit_ci_workflows/test_h5_freshness_guard.py` 红（11 条，173 passed 内）；外部实跑已覆盖三态 | 仅单侧 |
| C5 | 兜底面（每日 cron）只报告、不写盘；线上落后时**给出可执行命令** | L1/UA | 订阅/手动面：`schedule` = `53 18 * * *`；`Notify` 步 `if: steps.mode.outputs.mode != 'publish'`，调 `scripts/h5_freshness_guard.py`（单一实现）。真实读数：`2026-11-04T23:57:28Z`（= **2026-11-05 07:57 +08**）schedule run `41937701022` **failure**，日志原文 `::error:: 线上产物**陈旧**：2026-11-02T14:45Z 早于 frontend/mini-app 最近改动 2026-11-03T21:31Z（落后 1.3 天）` + `gh workflow run c-end-h5-publish.yml --ref main -f publish=true`；`2026-11-03T01:20:31Z`（= **09:20 +08**）schedule run `41559106190` **success**（当时不落后） | 把 notify 改为恒绿 / 摘掉 `::error::` / 删 `schedule` ⇒ `test_c_end_h5_hosting.py` 的 24b/24c 类红 | 仅单侧 |
| C6 | **真实发布实跑**：人工发布成功，且线上确实更新 | L1 | run `41945734691`（`2026-11-05T01:02:34Z` = **09:02 +08**，`workflow_dispatch`，`headSha=e2e02af37…`，`conclusion=success`）：`mode=publish`、`TAKEOVER_FIRST_PUBLISH=1`、托管顶层 `chunk css index.html js`、`MANAGED_TOP_LEVEL_DELETE=（空）`、`PROTECTED_UNCHANGED=1`、落地面断言 ①–⑤ 全 ✅；线上 `curl -sI` ⇒ `last-modified: Thu, 05 Nov 2026 01:05:16 GMT`（`/`、`/js/app.js`、`/css/app.css` 同一时刻） | 发布步失败 / 任一自证行缺失 ⇒ job 红；线上 `last-modified` 不前进 ⇒ 发布没生效（C3 会红） | 仅单侧 |
| C7 | **红证（外部注入）**：默认值判据真的会红 | L1 | 备份 `.github/workflows/c-end-h5-publish.yml`（sha256 `3e14d7ce…`）→ 把 `workflow_dispatch.inputs.publish.default` 改成 `true` → `python3 -m pytest tests/unit_ci_workflows/test_c_end_h5_hosting.py -q --tb=no` ⇒ **4 failed / 47 passed**，含 `publish 默认不是 false ⇒ 对账 dispatch 会直接发布`；还原（sha256 回到 `3e14d7ce…`）→ **51 passed** | 注入后仍绿 ⇒ 门禁是空断言（本次实测会红） | 仅单侧 |
| C8 | PR body 声称的「`ROOT_INDEX_BEFORE_SHA256`（旧）≠ `ROOT_INDEX_AFTER_SHA256`（新）」 | L2 | **实际读数相反**：成功 run 里两者**相等**（`7f7e6d61…`）；根因是可解释的——此前 2026-11-02 已有一次成功发布（run `41464650916`，sha `03bc371ff`），到 2026-11-05 的 `frontend/mini-app` 只多了 1 个样式提交（`08c8c2abd`），Taro `index.html` 用**稳定文件名**（`/js/app.js`、`/css/app.css`）⇒ 入口 index 内容不变、CSS/JS 变（线上 `css/app.css`、`js/app.js` 的 mtime 均为 01:05:16）。CI 也**没有**断言 `BEFORE != AFTER`（只断言 `PUBLISHED == LOCAL`） | 若把「BEFORE != AFTER」当成门禁 ⇒ 本次发布会被**误判红**。登记为 P2 声明漂移（见 §3） | 仅单侧 |
| C9 | PR body 声称线上静态根 `robots.txt` 为 200/503 字节且发布后逐字节不变 | L2 | **无法复现**：现取 `https://app.migaozn.com/robots.txt` = **404 / 153 字节**；`https://migaozn.com/robots.txt` = 200 / 353 字节（admin-web 的 robots）。从 run `41945734691` 的 `MANAGED_TOP_LEVEL_DELETE=（空）` 与脚本删除集（= 清单 ∩ 磁盘）看，**本腿不会删未托管条目** ⇒ 404 **不归因于该次发布**；但该声明不能当验收证据 | 若要证明「未托管条目被保留」，需在发布前后对**根目录全量顶层**取指纹（当前脚本只对 `w/`、`b/` 取）；缺这一步 = 该子断言无红证 | 仅单侧（无读数） |

**#5733 的证据链小结**：这是三个单里唯一有**真实生产实跑**的 —— 发布腿修好后真跑过一次，
线上已更新，`w/`/`b/` 红线在 run 内被**两次真实采样**钉住。两条 P2 是「PR 声明与实际读数不一致」，
不影响发布通路本身。

---

## 3. 不通过 / 有条件通过：缺什么、怎么补、谁补

> 分级：P1 = 阻断「把该单当已完成」；P2 = 声明/覆盖面缺口，不阻断但必须登记。

### 3.1 #5730 —— 有条件通过（3 项）

| # | 缺什么 | 级别 | 怎么补 | 谁补 |
|---|---|---|---|---|
| 1 | **真库存量读数**：R1（`V136` 补码前后行数/租户分布）、R2（`V138` 快照回填命中数、`widened` 必须 0） | **P1** | 在有凭据的环境跑 `docs/testing/production-readonly-verification-pack.md` 的 R1/R2 只读 SQL，把「事前/事后」两组读数贴回本报告或 #5699 | 有真库凭据的人/环境（AI 无法在本机执行） |
| 2 | **四端点运行时 403**：没有「无 `production:execute` 的用户打 `instantiate`/`ship`/`printOrder`/`report` ⇒ 403」的端到端判据 | P1（对「功能生效」的声称） | 加一条 HTTP 集成测试（真实过滤器链 + 无码账号）；或真栈用无码账号打四个端点。**本报告不把「注解存在」当「已生效」** | 下一个动该面的实施包；判据落 `backend/admin-api/src/test/...` |
| 3 | **真栈 UI**：岗位管理页在真实租户下显示「生产执行」并被勾选 | P2 | 起 admin-api + admin-web，按 `docs/testing/frontend-acceptance-checklist.md` 走一次岗位管理页 | 环境侧 / 下一轮验收 |
| 4 | 声明小漂移：`V138` 文件头写「授予四个岗位（admin 恒 `*`，无需补行）」，而 SQL 的 `r.code IN (...)` **包含 `admin`**；终态对账只校验 4 个岗位 | P2 | 要么把 `admin` 从 INSERT 移除，要么把文件头改成「admin 也补行（与 P5 口径一致）」；**不要**只改对账（那会掩盖差异） | 实施包/维护者（下一条动该迁移的 PR） |

### 3.2 #5732 —— 有条件通过（2 项）

| # | 缺什么 | 级别 | 怎么补 | 谁补 |
|---|---|---|---|---|
| 1 | **真实浏览器旅程**：登录 → 加工单生产明细页 → 滚动/缩放/空态；工人端手机浏览器扫码 → ⑪ | P2 | 起真栈后按 `docs/testing/frontend-acceptance-checklist.md` 走查并留截图；本报告只到 **MockMvc + vitest + node:test** 层 | 环境侧 / 下一轮验收 |
| 2 | **真机**（扫码、车间屏字号、`w/` 只在手机浏览器） | P2 | 真机按 #5052 的 U1~U10 清单走 | 有设备的人（本机无设备） |
| 3 | 覆盖面登记（不阻塞）：`panels`/`cuttingMode` 读订单行现值而非加工单快照；商家端一次最多 100 套、超出显式截断但不分页；`missing_reason` 是自由文本 | P2 | 保持现状（PR 已登记重启条件），出现真实工单被改后下料出错 / >100 套真实单时再立包 | 产品/实施 |

### 3.3 #5733 —— 通过（2 条 P2 声明漂移）

| # | 缺什么 | 级别 | 怎么补 | 谁补 |
|---|---|---|---|---|
| 1 | PR body 的「`ROOT_INDEX_BEFORE ≠ ROOT_INDEX_AFTER`」预期读数与实际相反（相等） | P2 | 把该预期改成「**身份**：`PUBLISHED == LOCAL`；入口 index 与上次**可以**相同（样式/脚本变化不一定改 index）」；**不要**为它加硬断言（会把正常重发判红） | 维护者在下次改该 workflow/脚本时同步措辞 |
| 2 | PR body 的「线上静态根 `robots.txt` 200/503 字节且逐字节不变」现状不可复现（app 域 404） | P2 | 澄清是哪个域；若确实要守「未托管条目不被删」，在发布前后对**根目录全量顶层**取指纹（当前只对 `w/`、`b/` 取） | 维护者/实施包 |
| 3 | **首次接管**（无清单 → 有清单）的路径只在 2026-11-02 的 run `41464650916` 成功过，本次 11-05 run 已有清单（`MANAGED_TOP_LEVEL_FROM_MANIFEST=chunk css index.html js`），**没有**逐行复核首次接管日志 | P2 | 需要时回看 run `41464650916` 的 `TAKEOVER_FIRST_PUBLISH` / `UNCLAIMED` / `MANAGED_TOP_LEVEL_DELETE` 读数 | 下一轮验收（不影响「线上一支可用」这一结论） |

---

## 4. 本报告没验证到的（照实登记）+ 重启条件

| # | 没验证到 | 为什么 | 重启条件 |
|---|---|---|---|
| 1 | **真库存量数据**（#5730 的 R1/R2；#5699 的 P5/I4 数据效果） | 本机无 `DATABASE_URL`、默认 5432 无服务；只有一个别的一次性空库实例，不能代表存量租户 | 提供真库/云测试环境只读凭据；跑 `docs/testing/production-readonly-verification-pack.md` |
| 2 | **四端点 403 的端到端生效** | `ProductionControllerTest` 是 standalone MockMvc（不挂拦截器）；只有注解在场判据 + 通用拦截器单测 | 补一条真实过滤器链的 403 用例，或真栈用无码账号打四个端点 |
| 3 | **真实浏览器 / 真栈 UI**（#5730 岗位页、#5732 商家页与工人端） | 本机未起 admin-api / admin-web / worker-h5；`lsof` 面没有对应服务 | 起栈后按 `docs/testing/frontend-acceptance-checklist.md` 走查并截图 |
| 4 | **真机**（DP30S 标签打印、50×30 耗材、扫码全链路、小程序真机） | 本机无设备 | 有设备时按 #5052 的 U1~U10 执行 |
| 5 | **真实 LLM 评测** | #4262 用户裁定：不自动验证、手动集中跑一次；本报告 **0 派发**（含任何 workflow） | 人工集中跑时按各 PR body 的 §13.2 清单（#5730：`MC-012/026/029~037/043~045` + `HR-011`；#5732/#5733 自身 §13.2 判定为 0 条） |
| 6 | **双 AI 交叉验证** | 本会话 `subagent` / `subagent_fork` 剩余委派深度 = 0，**不能**起第二个模型复核 | 由能起 GLM-5.3-Flash（或其它不同模型族）的会话，只看本报告的证据与读数做独立复核；不一致以证据引用充分者为准，仍不一致 ⇒ 待裁定 |
| 7 | **#5733 首次接管路径 / 未托管条目的全量保留** | 11-05 run 已有清单；脚本只对 `w/`、`b/` 取保留读数，不枚举根上其它条目 | 回看 run `41464650916`；若要守「未托管不被删」，加根目录全量顶层指纹的前后对比 |
| 8 | **C 端发布后的功能正确性**（登录、聊天、下单等真实旅程） | 发布腿只证明「线上字节 = 本次构建、不串端、`w/`/`b/` 未变」；功能正确性不在其覆盖面 | 线上冒烟/真实用户旅程（本次未做） |
| 9 | **全量档 `verify-all.sh gate/quick/full`** | 本次只按定点判据跑（四组 pytest + 定向 Maven + vitest + node）。在**本包 worktree** 直跑 `./verify-all.sh gate` 被**拒绝（exit 5）**：D 口径 = 一批只跑一次全量，那一次属于**批次集成**；判定原文指出「当前工作区是子包 worktree 且没有批次标记」⇒ **本次没有跑任何检查，这不是「通过」**（拒绝是机制，不是故障） | 需要全量时按批次集成跑一次（`./scripts/batch-gate.sh`）或交给 CI；本报告的「绿」不代表全量 |
| 10 | **浅克隆下的新鲜度判据真实读数** | 本工作区 `git rev-parse --is-shallow-repository` = `true` ⇒ 判据如实 `rc=3`；我用**临时全历史仓 + 本地 HTTP server** 取三态读数作为替代 | CI 的 `fetch-depth: 0`（`c-end-h5-publish.yml` / `h5-freshness-guard.yml` 均已在位）即真实环境 |

---

## 5. 交付物可达性三问

| 对象 | ① 用户怎么到 | ② 到了看到什么 | ③ 出问题怎么知道 |
|---|---|---|---|
| **#5730** | 商家 admin-web → **岗位管理**（`/roles`）→ 权限树 / 「操作权限」节；员工创建时按岗位预填 | 权限项名「**生产执行**」（权限码按 §31 P3 **不上屏**）；新租户 5 个内置岗位默认已勾；存量租户由 `V136`/`V138` 补齐（**数据面待真库读数**） | 无码用户打四个写端点应 **403**（**此格未端到端验证**，见 §3.1-2）；`rbac` 判据红（清单/迁移新鲜度/端点对齐）；真库 R1/R2 读数异常 |
| **#5732** | 商家：加工单生产明细页 `/processing-orders/<id>/production` → 「精裁输出清单」块；工人：手机浏览器扫码详情（同一 `set_overview.cut_plan`） | 套号 / 部位 / 组件·货号 / 用料（米）/ **裁多长 × 几片** / 备注；缺值 `—` + 原因；>100 套显式提示截断 | 三读面逐值不等的判据红；`null` 被折成 0 / `× 1 片` 的判据红；接口失败只降级该块（`production-cut-plan-error`，页不白屏）；工人端 ⑪ 红 |
| **#5733** | GitHub Actions → **Publish C-end H5 (app.migaozn.com 根)** → Run workflow（分支 `main`，`publish` 勾 `true`）；或 `gh workflow run c-end-h5-publish.yml --ref main -f publish=true` | `mode=publish`、托管顶层、`PROTECTED_w/b BEFORE==AFTER`、`PROTECTED_UNCHANGED=1`、`PUBLISHED_INDEX == 本地 dist`、落地面断言 ①–⑤、线上 `last-modified` 前移；notify 面红时逐字打印上面那条命令 | 发布步/任一条自证断言红 ⇒ job 红；每日 cron 的 notify 红（真实读数见 C5）；`H5 Freshness Guard` 红；线上 `last-modified` 不前进 |

---

## 6. 三把工具与执行记录

> 本报告是**纯文档**；为遵守仓库「提交前必跑」纪律，执行了下列命令。
> `./verify-all.sh gate` 在子包 worktree 被**拒绝（exit 5）**——那是 D 口径的机制，**不是通过**；
> 定点判据的读数如下，全量档与 CI 留给批次集成/CI。

| 命令 | 用途 | 读数 |
|---|---|---|
| `python3 -m pytest tests/unit_ci_workflows/test_rbac_migration_convergence.py tests/unit_ci_workflows/test_rbac_endpoint_write_codes.py tests/unit_ci_workflows/test_rbac_submenu_granularity.py tests/unit_ci_workflows/test_agent_permission_parity.py -q` | #5730 判据 | **40 passed** |
| `python3 -m pytest tests/unit_ci_workflows/test_c_end_h5_hosting.py tests/unit_ci_workflows/test_h5_freshness_guard.py tests/unit_ci_workflows/test_publish_leg_fallback_surface.py tests/unit_ci_workflows/test_iron_rule_10_schedule_scope.py tests/unit_ci_workflows/test_config_change_triggers_deploy.py tests/unit_ci_workflows/test_reconcile_no_silent_skip.py tests/unit_ci_workflows/test_swas_deploy_ci_hardening.py -q` | #5733 判据 | **173 passed** |
| `./mvnw -o test -Dtest=ProcessingSetReadServiceTest,ProcessingOrderSetControllerTest,CuttingPlanCalculatorTest,StockBatchConsumptionServiceTest` | #5732 Java 面 | **82 passed / BUILD SUCCESS** |
| `./mvnw -o test -Dtest=MigrationRunnerLiveChainRealDbTest` | #5730 迁移机制（临时 PG） | **2 passed / BUILD SUCCESS** |
| `./node_modules/.bin/vitest run tests/unit/components/CutPlanTable.test.tsx tests/unit/pages/processing-orders-production.test.tsx` | #5732 商家 UI | **41 passed** |
| `./node_modules/.bin/vitest run tests/unit/pages/roles.test.tsx` | #5730 岗位页 | **26 passed** |
| `node --test frontend/worker-h5/tests/worker-h5-scan-complete.test.mjs` | #5732 工人端 | **41 passed** |
| `python3 scripts/h5_freshness_guard.py`（临时全历史仓 + 本地 server） | #5733 三态红证 | 陈旧 **rc=2** / 新鲜 **rc=0** / 取不到 **rc=3** |
| `gh run view 41945734691 --log` | #5733 真实发布 | `mode=publish`、`PROTECTED_UNCHANGED=1`、`PUBLISHED == 本地 dist`、落地面 ①–⑤ ✅ |
| `curl -sI https://app.migaozn.com/{,js/app.js,css/app.css}` | #5733 线上新鲜度 | 三者 `last-modified: Thu, 05 Nov 2026 01:05:16 GMT` |
| `./check-ui-regression.sh` / `./verify-all.sh gate` | 提交前门禁 | `check-ui-regression.sh` ⇒ **UI_RC=0**（UI 无回退）；`verify-all.sh gate` ⇒ **exit 5 拒绝**（子包 worktree + 无批次标记，D 口径：全量那一次属于批次集成）⇒ **未跑任何检查，不是「通过」**；CI 仍是权威（每 PR 并行） |

**临时变异已全部还原（逐字节自证）**：

| 文件 | 原 sha256 | 变异后 | 还原后 | `git diff` |
|---|---|---|---|---|
| `rbac/manifest.json` | `9d176bcb…` | `e8835bdf…` | `9d176bcb…` | 空 |
| `backend/admin-api/src/main/java/com/migao/admin/service/CuttingPlanCalculator.java` | `c2fc8f7c…` | 注入 `if (false)` | `c2fc8f7c…` | 空 |
| `.github/workflows/c-end-h5-publish.yml` | `3e14d7ce…` | `default: true` | `3e14d7ce…` | 空 |

> 为什么没有走 `scripts/red_proof.py` 的缓存清理：三次外部变异都在 **JSON / Java / YAML** 上，
> 不在 `.py` 模块上，不存在 `.pyc` 复用；Python 判据每次都在**新进程**里读现取文件。
> 注入/还原都用 **sha256** 自证，不用 mtime/size。

---

## 7. 验收方法自检（我有没有掉进自己验自己 / 字段当生效）

1. **我是不是「自己验自己」？** 我不是三个单的实施者，也没有改产品代码（三次变异均为临时注入 + 逐字节还原）。
   但**双 AI 交叉验证没有做**（无子代理能力）⇒ 本报告所有结论**只有单侧**，按协议**不构成最终验收**。
   这是本报告最大的方法缺口，已写进 §1/§4，不藏。
2. **我有没有把「字段存在」当「功能生效」？** 有意识地分开了三处：
   - #5730：**`@RequirePermission` 注解在场 ≠ 四端点运行时 403** —— A7 明确写「未端到端验证」，并在 §3.1-2 要求补判据；
   - #5730：**manifest 计数 / 迁移文件存在 ≠ 存量租户数据已补齐** —— A6 标「无法验证」；
   - #5733：**workflow 文件存在 ≠ 发布腿可用** —— 用真实 run `41945734691` 的步骤级读数 + 线上 `last-modified` 交叉证明。
3. **我有没有为了全绿降低断言？** 没有。三个单都保留了「无法验证」项；#5733 的两条 P2 是**声明与读数不一致**，
   我没有把它们洗成「无问题」，也没有为了让它变红去加不合理的硬断言（`ROOT_INDEX_BEFORE != AFTER` 明确**不建议**加）。
4. **空跑自检**：每次 pytest / Maven / vitest / node 都读了实际 `passed/failed` 计数与具名断言；
   真实发布 run 读了**步骤级 conclusion + 落地面断言原文 + 线上 curl**，没有把「run 绿」直接当「发布成功」。
5. **假绿高发点自检**：
   - **浅克隆**：本工作区 `is-shallow-repository=true`，原样跑新鲜度判据得到 `rc=3`（不是绿）；我另造全历史仓取三态读数，没有用「rc=3」冒充「新鲜」；
   - **密钥/注释漂移**：PR body 的 `ROOT_INDEX_BEFORE != AFTER` 与 `robots.txt` 两条均已按**实际读数**登记为 P2，没有转述成事实；
   - **日志里的转义文本**：判断发布结果时只取无 ANSI 前缀的真实输出行 + 步骤结论，避免把执行器回显的脚本当读数。
6. **没跑 ≠ 通过**：`quick/full` 全量档、真实 LLM 评测、真库、真机、真浏览器、双 AI 复核，全部在 §4 单列，
   不与「通过」并排。
7. **残余风险（下一个人该先看这里）**：
   - #5730 的**存量授权面**在真库上到底补了多少行，本报告一无所知；
   - #5730 的**四端点 403** 只有通用拦截器证据，没有端点级证据；
   - #5732 的**真实浏览器/真机**没有取证（DOM 层绿不等于车间看得清）；
   - #5733 的**功能正确性**（发布后的 C 端真实旅程）不在本报告范围。
