# 2026-10-06 岗位 × 页面 深度验收 · 报告（承载体）

> **状态**：读数、判定、**独立复核（GLM 3 裁判 22 条 objection）与逐条处置**均已完成（§7）。
> **本轮不下「验收通过 / 交付达标」结论**（`migao-acceptance` 铁律 1：开发者 ≠ 验收者）。
> 协议 = `migao-acceptance`；流程 = `migao-dev-flow` §15.7 / §17 / §27。
> 时间口径 **Asia/Shanghai（+08）**；引用 GitHub/CI（UTC）处逐处换算标注。
> **v2 修订**：按 §7.1 的 22 条 objection 订正了计数、证据引用与结论强度（修订点见 §7.2）。

---

## 0. 一句话（**已按复核收窄口径**）

7 个岗位用**自己的账号**、在**真浏览器**里跑完各自可见的菜单页面（82 次访问，覆盖 7 岗位 × 菜单顶层页），
无码页面在抽样范围内**全部被拦**（每岗位最多抽 3 条，共 17 条 —— **不是全量**）；
写面有 **3 条**真的打通（管理员建员工、知识编辑建卡片、API 夹具建订单），另有 **4 条未驱动完成**（如实记 skip）。
查出 **1 条权限面缺陷**（写按钮不随权限显隐）与 **1 条文档漂移**，另有 **5 条待归因观察项**（证据不足以判缺陷）；
同时把本轮**判据自身的 14 条缺陷**留档修复（§6）——后者是本轮最有价值的产出。
**补探（§3.5）已把首轮的两处覆盖缺口补满**：正向 82 → **231** 次真访问（静态路由 33/33 全覆盖）、负向 17 → **65/65** 组合逐条真探；
**补探本身 0 条产品缺陷**（3 项疑似形态已按 durable 真值源逐条核销）。

---

## 1. 被测坐标（先钉事实，再看结论）

| 项 | 值 | 证据 |
|---|---|---|
| **被测 SHA** | **`73327161f`**（= `origin/main` HEAD） | §1.1 |
| admin-web / admin-api | `https://merchant.migaozn.com` · `https://api.migaozn.com` | 全部页面与接口读数取自它们 |
| 工人端 / bmini / 一体机 | `https://app.migaozn.com/w/?tenant_id=25` · `/b/` · `/w/machine.html` | §5 |
| 被测租户 | tenant 25「米高测试环境」`shop-8yn7` | — |
| **清理前**快照 | users=10（active）· knowledge=2 · orders=2 · tickets=1 · inbound=18 | `out/p7-cleanup.json#before` |
| **开测基线** | products=8 · orders=0 · knowledge=0 · tickets=1 · inbound=15 · users=7 | ⚠️ **现场读数、未落产物**（命令：`node harness/q.mjs "select count(*) …"`）⇒ 见 §6.D16 证据缺口 |
| 部署在飞（协议 v1.9 前置） | 无（最近 `deploy-admin-api.yml` run 结论 `success`，其后无 `in_progress`/`queued`） | `gh run list --workflow=deploy-admin-api.yml` |

### 1.1 坐标钉法（步骤级 + 日志级；**不拿「run 绿」当部署证据**）

run `37357202049`（`headSha=73327161f`，2026-10-05T18:36:19Z = **2026-10-06 02:36 +08**）：

- `Deploy to SWAS (测试环境)` = **success**（非 skip）；
- `Assert running tag == target` = **skipped** —— **设计如此**：该步只在 `sync.skip == 'true'`（跳过部署那条路径）时跑
  （`.github/workflows/deploy-admin-api.yml` 第 380 行 `if: always() && steps.sync.outputs.skip == 'true'`）；
- 部署步远端输出逐字：`✅ SWAS 部署成功（tag=sha-7332716）；本次实际生效：admin-api=sha-7332716 / ai-agent=sha-7332716 / admin-web=sha-7332716`。

⇒ **三服务在跑 tag = `sha-7332716` = `73327161f`**，全部读数锚定它。

---

## 2. 四态计数（汇总 · 与产物逐格对齐）

| 面 | 产物 | pass | fail（产品） | skip（未覆盖） | 合计 |
|---|---|---|---|---|---|
| A. 岗位读面（登录/菜单/页面/负向） | `p2-roles-ui.json` | **27** | 0 | 1 | 28 |
| B. 写按钮显隐矩阵 | `p4-writes.json#buttonMatrix` | 5 | **2** | 0（另 18 格无读码跳过） | 24 实查格 |
| C. 写面旅程（UI→DB + 1 条 API 夹具） | `p4-writes.json` + `p4d-writes2.json` | **3** | 0 | **4** | 7 |
| D. 权限负向（API） | `p5-perm-api.json` | 3 | 0 | 1 | 4 |
| E. H5 跨端 | `p6-h5.json` | **6** | 0 | 0 | 6 |
| F. bmini `/b/` 旅程 | `out/bmini/bmini-journey.json` | **6** | 0 | 0 | 6 |

- A 面的 1 条 skip = `P2-NEG:admin`（全码岗位**无负向项** ⇒ 该判据对它恒真 = **空断言**，改记未覆盖；本轮由复核抓出，见 §6.D9）。
- B 面 2 条 fail = 同一形态的**产品缺陷 F1**（客服 / 运营在 `/knowledge` 看得见无码写按钮）。
- C 面 3 条 pass = `P4-W1`（管理员建员工）· `P4-W2`（知识编辑建卡片）· `P4D-1`（**API 夹具**建订单，非 UI 旅程）；
  4 条 skip = `P4-W3` · `P4-W4` · `P4D-2` · `P4D-3`（理由见 §3.3）。
- 逐条订正台账（`fail`→`skip`）见 `out/p8-reclassify.json`（**由行内 `rawState` 派生，重跑 `harness/p8-reclassify.mjs` 得同一结果**）。

### 2.1 覆盖边界（**不许把抽样说成全量**，独立复核 A-OBJ-2/4）

| 维度 | 首轮（p2） | **补探（§3.5，p2b）** | 补探后仍未覆盖 |
|---|---|---|---|
| 正向页面 | 82 次访问 = 7 岗位 × **菜单顶层页**（并集 21 条路径） | **231** 次 = 7 岗位 × **33 条静态路由**（并集 33 条） | **7 条动态段**（`/orders/:id` 等 × 7 岗位 = 49 格）——无夹具 id，记 `skip` |
| 负向页面 | 每岗位**最多抽 3 条** ⇒ 17 条 | **65/65** 组合逐条真探，全部命中「无权访问该页面」 | 0（该项已补满） |
| 写按钮矩阵 | 24 个「页 × 岗位」实查格 | 18 个「无读码」格中 **12 格没有任何负向探测**（含 `/employees` × 5 个岗位）⇒ 见 §6.D14 |
| 写面旅程 | 3 条打通（2 条 UI + 1 条 API 夹具） | 4 条未驱动完成（§3.3），入库单/登记收支**未尝试驱动完成** |

---

## 3. 验收矩阵（面 × 判据 × 证据）

### 3.1 A 面：岗位「能进 / 该进的都进」（抽样范围内）

期望值来自 **DB `role_permissions`（真值源）+ `origin/main` 提交对象的 `menu.ts` / `layout.tsx`**，
**不读被测读面自证**；页面「可用」= 非 403 ∧ 稳定帧 ∧ 非加载态 ∧ 正文非空（该门强度见 §6.D10）。

| 岗位 | 登录 | 期望菜单 / DOM 实测 | 访问页面 | 负向（抽样 ≤3） |
|---|---|---|---|---|
| 管理员 admin（32 码） | ✅ 管理员登录（短信） | 21 / 21 | 21 | **—（全码 ⇒ 无负向项，本项记 skip）** |
| 客服 customer_service（12） | ✅ 员工登录 | 10 / 10 | 10 | 3/3（`/finance`、`/production`、`/production/processing`） |
| 运营 operator（26） | ✅ | 19 / 19 | 19 | 2/2（`/roles`、`/settings`） |
| 销售 sales（9） | ✅ | 9 / 9 | 9 | 3/3（`/agent-workspace/human-sessions`、`/knowledge`、`/after-sales`） |
| 财务 finance（9） | ✅ | 8 / 8 | 8 | 3/3（`/agent-workspace/human-sessions`、`/knowledge`、`/after-sales`） |
| 商品管理员 product_manager（8） | ✅ | 10 / 10 | 10 | 3/3（`/agent-workspace/human-sessions`、`/customers`、`/knowledge`） |
| 知识编辑 knowledge_editor（4） | ✅ | 5 / 5 | 5 | 3/3（`/agent-workspace/human-sessions`、`/customers`、`/after-sales`） |

证据：`out/p2-roles-ui.json`（逐页 `stable/loading/textLen/errors/textHead`；**截图仅每岗位前 4 页，共 28/82 —— 见 §6.D13**）、
`out/shots/*.png`、`out/text/*.txt`；**负向探针 0 张截图**（同 D13）。

### 3.2 B 面：写按钮随权限显隐（**24** 个实查格）

| 页面 | 写码 | 实查格数 | 不符 |
|---|---|---|---|
| `/orders` | `order:create` | 5 | 0 |
| `/products` | `product:create` | 5 | 0 |
| `/after-sales` | `order:refund` | 3 | 0 |
| `/knowledge` | `knowledge:manage` | 4 | **2**（客服 / 运营） |
| `/inbound-orders` | `inbound:create` | 5 | 0 |
| `/employees` | `employee:create` | 2 | 0 |

合计 **24** 实查格（与 §2 一致）；另有 18 格因「无读码」跳过，其中 **12 格无任何负向探测支撑**（§6.D14）。

### 3.3 C 面：写面旅程（页面操作 → DB 落库）

| 旅程 | 角色 | 结果 | 证据 |
|---|---|---|---|
| `P4-W1` 建员工 | 管理员 | ✅ **pass** | 页面提交 → `users#…` 落库 `position=客服 status=active`，**权限快照(12) == 岗位默认权限(12)**；`out/shots/w1-employee.png` |
| `P4-W2` 建知识卡片 | 知识编辑 | ✅ **pass** | 页面提交 → `knowledge_cards` 1 → 2 条，最新行含探针串；`out/shots/w2-knowledge.png` |
| `P4D-1` 建订单（**API 夹具**） | 销售（token） | ✅ **pass** | `POST /api/admin/orders` → `orders#…` `status=pending` 金额=128；**非 UI 旅程产物**，仅为 W4 提供前置 |
| `P4-W3` 建订单（UI） | 销售 | ⏭ **skip** | 页面逐字「还差 1 项 … 有 1 行加工费未定价（组合那半按 0 计）⇒ 请先定价再下单：拼接」= **产品有意的业务闸门**，驱动未去定价 |
| `P4-W4` 建售后工单（UI） | 客服 | ⏭ **skip** | 前置不成立（当轮无订单）⇒ 驱动自记 skip |
| `P4D-2` 建售后工单（UI，带 API 夹具订单） | 客服 | ⏭ **skip** | 关联订单为必填，UI 驱动未把订单解析进表单（提交后对话框仍在，库内无新行） |
| `P4D-3` 建商品（UI） | 商品管理员 | ⏭ **skip** | 页面逐字「表单校验未通过：还有 6 处必填内容未完成」（分类 / 主图 / 计价单位 / 售卖方式…）；两次补齐仍未通过 |

**订正留痕**：W3 / P4D-2 / P4D-3 在原始产物里被驱动记成 `fail`，已按「驱动未走完表单 ≠ 产品缺陷」订正为 `skip`：
原值在 `rawState`、理由与**实测证据原文**在 `reclassReason`（行内），台账 `out/p8-reclassify.json` 由行内字段派生。
未覆盖的写面：**入库单（运营）· 登记收支（财务，页面无匹配「新建」按钮）** 本轮连驱动都未做 ⇒ 记未覆盖。

### 3.4 D 面：权限负向（API，L1）

| 探针 | 期望 | 实测 |
|---|---|---|
| 客服 / 运营 / 商品管理员 `POST /api/admin/knowledge/cards` | 403 + 库内零变化 | **403**（`PERMISSION_DENIED`「权限不足，需要权限: knowledge:manage」）+ 库内 1 → 1 ✅ |
| `P5-positive` 正对照（知识编辑同一端点，API） | 200 + 落库 | ⏭ **skip**：载荷未对上契约（422 缺 `title` 等）；**正对照已由 UI 侧 `P4-W2` 承担**（同一写码、真建卡片、库内 0→1→2） |

⇒ **后端护栏在位**（`backend/admin-api/src/main/java/com/migao/admin/controller/KnowledgeCardController.java` 的 `@RequirePermission("knowledge:manage")`）；
所以 F1 是**前端显隐层**缺陷，不是越权。

### 3.5 补探面（独立复核 A-OBJ-2/4 指出的覆盖缺口 → 专门补满）

承载体：`out/p2b-COVERAGE.md`（结论）· `out/p2b-coverage.json`（逐条读数）· `harness/p2b-coverage.mjs`（可复跑）· `out/shots/p2b_*.png`（42 张）。
窗口 = 2026-10-06 09:40–09:48 (+08)，同 SHA `73327161f`；期望值来源 = `out/map.json`（前缀序按 `layout.tsx` 的 `find` 语义）+ **DB 现取**岗位权限（数组序 vs 最长前缀偏离数 = 0）。

| 态 | 数 | 构成 |
|---|---|---|
| `pass` | **303** | 7 登录 + 224 路由判读 + 7 负向汇总 + 65 负向逐条 |
| `fail(产品)` | **0** | 231 格静态访问：`expect=deny` 全命中 403 卡、`expect=allow` 无一条误拦 / 404 / 停载 / 空白；console+pageerror **0** |
| `skip(未覆盖)` | **56** | 49 = 7 动态段 × 7 岗位（无夹具 id）；7 = `/notifications`（**no-guard**，见下） |
| `假红(判据缺陷)` | **0** | — |

**补探侧 3 项疑似形态已逐条核销，均非缺陷**（原文见 `out/p2b-COVERAGE.md` §4）：
① 客服/运营进 `/chat` 只见门禁卡 = **设计如此**（`db/migration/V132__add_agent_chat_permission.sql` 只把 `agent:chat` 授给 admin，客服默认不持；文案给了出口）；
② `/notifications` 7 岗位一律可进 = **有意豁免**（`(dashboard)/layout.tsx` 内逐字登记「有意不登记…不凭空造码」）；
③ `/briefing`「未开启」与 `/production/pool`「合并派单未开启」= **租户开关关着**（`tenants.briefing_enabled=false` 现取）且页面给了可行动出口。

**补探侧判据/证据登记**：D-p2b-1 截图取样偏斜（42 张里 20 张是同一张 403 卡；截图**不是**任何判定依据）· D-p2b-2 空白门过弱（与 D10 同源）· D-p2b-3 `p7` 的 `users` 计数结构性不变（软禁用只清 `username`）⇒ 建议加 `and deleted=0`（**未擅自改既有 harness**）。

**补探强度边界（照实写"没测到什么"）**：7 条动态段 49 格仍 0 覆盖；只判「拦不拦 / 进不进得去」（写面不重复）；单租户 × 单 SHA × 单部署面，不外推；页面多为空态 ⇒「**有数据时**是否正常」未覆盖；`/chat` 里 admin 可见 **4 条 2026-10-05 遗留米宝会话**（`p7` 的表清单不含米宝会话表 ⇒ **证据不足**，只登记不判定）。

---

## 4. 问题清单（每条带证据引用 + 归因强度）

### F1 · P2 · 权限面 · 写按钮不随权限显隐：`/knowledge` 的「新建知识卡片」
- **现象**：客服（12 码）与运营（26 码）**都没有** `knowledge:manage`，但在 `/knowledge` 页**都看得见**「新建知识卡片」。
- **证据链**：
  1. `out/p4-writes.json#buttonMatrix` → `customer_service` / `operator` 两行 `{path:"/knowledge", write:"knowledge:manage", expectVisible:false, actualVisible:true, count:1}`；
  2. 后端对照（证明不是越权）：`out/p5-perm-api.json` → 同端点 `403 + 库内零变化`；
  3. 源码（`73327161f`）：`frontend/admin-web/src/app/(dashboard)/knowledge/page.tsx` 标题区**裸渲染**该按钮（`<Button onClick={openCreate}>… 新建知识卡片</Button>`），**全文件无 `hasPermission`**。
- **归因强度**：**存在性 + 值级**（DOM 可见性实测 + 权限码 DB 现取 + 后端 403 实测）⇒ 足以为**前端缺陷**。
- **家族**：与 #5983（列表页写按钮不随权限显隐）同形态；本轮把覆盖面扩到**知识库页**。
- **建议判据（会红）**：以「写码 ⇒ 页面写按钮」映射做**类级元守卫**：断言「无码岗位 DOM 中该按钮不存在」；
  负向夹具 = 摘掉某岗位写码后仍能看到按钮。
- **登记**：[#6392](https://github.com/zhaokai-mgzn/migao/issues/6392)；**修复**：[PR #6395](https://github.com/zhaokai-mgzn/migao/pull/6395)
  —— 用户 2026-10-06 裁定「藏按钮（不补权限码）」：`canWrite = hasPermission('knowledge:manage')` 后不渲染头部两个写入口与行内写操作；
  台账 `list_page_write_button_ledger.json` 删 `/knowledge` 条目（5 → 4）；UI-081 判据 6 + 新增 UI-085（岗位菜单矩阵）。
  红证：把该页回退到 `HEAD` ⇒ 守卫判据 `2 failed / 3 passed`、前端实例面 `1 failed / 5 passed`；恢复后 5 / 6 passed。

### F2 · P3 · 文档漂移：`docs/wiki/RBAC.md` 说「客服仍无 `order:refund`」，与种子/实测均不符
- **证据链**：① `docs/wiki/RBAC.md` 逐字「**仍无** `order:refund`」；
  ② `backend/admin-api/src/main/java/com/migao/admin/service/RegistrationService.java` 把 `"order:refund"` 授给 `csRole`，注释逐字「issue #5988（人类 2026-10-02 裁定「应允许」）：客服处理售后 = 本职」；
  ③ 实测：tenant 25 的 `role_permissions` 里 `customer_service` 含 `order:refund`，客服 UI 在 `/after-sales` 显示「新建工单」。
- **归因强度**：**值级**（三处逐字对照）。**处置**：文档订正（非涉钱、非权限放宽 ⇒ AI 可自裁）；**登记**：[#6393](https://github.com/zhaokai-mgzn/migao/issues/6393)。

### 观察项（**待归因**，不上缺陷结论、不派单）

| # | 观察 | 证据 | 说明 |
|---|---|---|---|
| O1 | 工人端**裸入口** `https://app.migaozn.com/w/` 页面能渲染登录页，但**提交登录**报「无法识别租户：请通过 `<租户ID>.app.migaozn.com` 域名访问或提供 tenantId」；带 `?tenant_id=25` 才可用。且**子域形态 `25.app.migaozn.com` 在 DNS 上不解析**（`ERR_NAME_NOT_RESOLVED`） | `out/p6-h5.json#entryProbes` + `#bareLoginProbe`（逐字含错误文案） | 入口可发现性 / 与 `frontend/worker-h5/src/scan-input.mjs` 注释所称「优先子域」不一致 |
| O2 | 知识卡片 `created_by` 落库为 `admin`，而创建者是知识编辑账号 | `out/p4-writes.json` P4-W2 行（DB 现取） | **证据不足**（缺该字段写入定义）⇒ 待归因 |
| O3 | bmini `/b/` 旅程 6/6 通过，但 console 记录 1 条运行时错误 `NotFoundError: Failed to execute 'insertBefore' on 'Node'…` | `out/bmini/bmini-journey.json#consoleErrors` | 不阻塞旅程；缺复现步骤与组件定位 ⇒ 待归因 |
| O4 | `inbound_orders` 在清理前快照为 18；本轮**从未写入** inbound（写入面只有 users/knowledge/orders） | `out/p7-cleanup.json#before` | 开测时的 15 属**现场读数未落产物**（§6.D16）；「非本轮写入」的结论与 §8 相容 |
| O5 | 一体机页 `/w/machine.html` 渲染正常（60 字符）但**无任何 `#wh5-*` 元素**，且文案停在「本台设备还没登录」 | `out/p6-h5.json` P6-M1 | 属设备态而非缺陷；未登录态的可读性观察 ⇒ 待归因 |

---

## 5. H5 跨端一致性

| 判据 | 结果 | 证据 |
|---|---|---|
| 工人端 `?tenant_id=25` 首屏渲染（#6306 修复后复探） | ✅ `#wh5-login` / `#wh5-worker-no` / `#wh5-pin` 就位，正文 47 字符 | `out/shots/h5-w-login.png` |
| 错 PIN 负对照 | ✅ 留在登录态 + 文案「**工号或 PIN 不正确**」+ 0 个已登录元素 | `out/shots/h5-w-badpin.png` |
| 真工号 + 真 PIN 登录 | ✅ `当前工人：A06验收工人…（工号 A06W…）` | `out/shots/h5-w-logged.png` |
| 登录后报工页 DOM | ✅ `#wh5-*` 8 个元素（`wh5-current-worker`/`wh5-scan`/`wh5-code`/`wh5-report`…） | `out/p6-h5.json` |
| 一体机页 `/w/machine.html` | ✅ 非空白（「机台模式 · 裁高 / 本台设备还没登录…」） | `out/shots/h5-machine.png` |
| bmini `/b/` 6 旅程（登录 → 首屏 → 数据 → 我的） | ✅ 6/6（`POST /api/auth/sms/send` 200、`login` 200） | `out/bmini/bmini-journey.json` + `out/bmini/shots/*` |

---

## 6. 判据侧缺陷（本轮最有价值的产出：**14 条**）

> 依据 `migao-acceptance`「假绿 / 假红：断言自身会双向骗人」。**判据错与产品错必须分开**。

| # | 形态 | 表现（错误读数） | 根因 | 处置 / 重放证据 |
|---|---|---|---|---|
| D1 | 假红 | 菜单大面积判缺（逐岗位 missing：admin 19 / 客服 8 / 运营 16 / 销售 6 / 财务 6 / 商品 7 / 知识 2） | 侧边栏**分组折叠**（`Sidebar.tsx` 的 `expandedGroups` 默认只展开当前路由组），v1 直接查 `nav a[href]` | 改：按 `[data-testid^="sidebar-group-toggle-"]` 展开全部组再采；**红证 = `out/p2-roles-ui.v1-false-red.json`（同一份 DOM，v1 判 fail / v2 判 pass）** |
| D2 | 假红 | 7 岗位一律「缺 `/briefing`」 | 未建模企业开关：`briefingToggle` 项按 `tenants.briefing_enabled` 过滤，本租户 = `false` | 改：期望集按 DB 开关过滤；实测 DOM 与过滤后期望**逐项相等** |
| D3 | 假绿（证据层） | 截图与断言时刻不符（`sales_orders.png` 只有「加载中…」） | `rec.shot = shot(...)` **漏 `await`** ⇒ JSON `shot:{}`、截图落到**下一页**加载态 | 改：`await shot(...)` |
| D4 | 假绿 | `/orders` 判 pass（实为加载态） | 「稳定帧」会稳定在**静态加载文案**上 | 改：`visit()` 轮询到**非加载态**再采（超时如实记 `loading:true`） |
| D5 | 假红 | 订单商品选择点 `tbody tr` 点不到 ⇒ 弹窗不关 ⇒ 「提交订单」永不可点 | 该弹窗把商品渲染成 **`<button>`**，不是表格行 | 改：按 `/布艺面料/` 定位商品按钮 → 关弹窗 → 校验「合计」变化 |
| D6 | 假绿 | 工人端「错 PIN 负对照」通过，但文案是「**无法识别租户**」 | 入参名错：worker-h5 用 `?tenant_id=`，v1 传 `tenantId` ⇒ 租户未解析，凭据比对没发生 | 改：带 `?tenant_id=25`；重放后文案变成「**工号或 PIN 不正确**」 |
| D7 | 假红 | 知识卡片「未落库」 | 断言按 `question=` 精确匹配，探针串落在别的字段（标题 / 常见问法 是两个输入框） | 改：按 `created_at desc` 取最新行 + 断言探针串出现在**任一字段**；重放 1 → 2 条、pass |
| D8 | 假红 | 建员工「未落库」 | `selectOption({label:'客服'})` 选不中 ⇒ 表单停在「请选择岗位」 | 改：按 **option 文本** 定位 select；重放后真实建号 + 权限快照相等 |
| **D9** | **空断言（恒真）** | `P2-NEG:admin` 判 pass | admin 全码 ⇒ `deniedMenu` 为空 ⇒ 循环不执行 ⇒ `leaked.length===0` **恒真** | 改记 `skip`（未覆盖）；由**独立复核 A-OBJ-1/C-OBJ-08** 抓出 |
| **D10** | 判据过弱 | 「正文非空」门 `textLen < 40` | body 文本含整条侧边栏壳层（82 页最小实测 113）⇒ 只有整个壳都没渲染才会红 | **如实登记**（本轮无实测假绿：抽读 `out/text/*` 主区有真内容、0 错误、0 加载态）；后续应按**主内容区**取文本 |
| **D11** | 声明 ≠ 实现 | 脚本头注称页面可用含「零 console error」，但 pass 过滤条件**不含** `errors` | 采集了 `errors` 却从不消费 | 如实登记；本轮 `errors` 全为空数组（`p2-roles-ui.json`），读数未失真 |
| **D12** | 未建模渲染条件 | 菜单第三条件 `adminOnly` 抽了字段却**不进判定** | `menu-nav.ts` 过滤三条件 = `adminOnly` ∧ `briefingToggle` ∧ `permissionCode` | 本轮 `adminOnly` 项为空集 ⇒ 无失真；**D2 同族复发点**，已登记 |
| **D13** | 证据声明 > 实际 | 报告曾称「含每页 `shot`」 | 实际只每岗位前 4 页有截图（28/82），**17 条负向探针 0 截图** | 已订正表述；截图缺口登记（负向「被拦」目前只有 `textHead` 文字证据） |
| **D14** | 悬空引用 | 18 个「无读码」跳过格一律写「见 p2 负向」 | 逐格配对后仅 **6/18** 有对应被拦记录，**12 格悬空**（含 `/employees` × 5） | 已改理由为「本格未覆盖」并落盘 `out/p4-writes.json#skippedCellCitation` |
| **D15** | 台账不可复算 | `p8-reclassify.json` 的 `changed` 被后一次运行覆写（p4/p4d 记为 `[]`） | 台账由脚本每次覆写，历史丢失 | 改为**从行内 `rawState`/`reclassReason` 派生**（重跑即得同一台账） |
| **D16** | 证据缺口 | §1「开测基线」与 O4 的 `inbound=15` 是**现场读数、未落产物** | 当时未落盘 | 如实标注为证据缺口（不冒充有据） |

**共同根因两条**：① **把「我看到的」当成「用户看到的」**（D1/D4/D5/D10 是采样或操作没对齐真实 UI 结构）；
② **断言/证据与真值错位**（D2/D6/D7/D8/D9/D13/D14/D15）。⇒ **14 条判据侧 : 2 条产品侧**。

---

## 7. 独立复核（双 AI 交叉验证）

- 主验收：本报告（DSH 主会话，DeepSeek）。
- 复核验收：**GLM-5.3-Flash ×3**（provider `scnet-token-plan`，模型族不同）：分别审
  ① A 面判据实现 ② B/C/D 面判据实现 ③ **对抗性一致性核查**（报告数字 vs 产物）。裁判**只读、只找问题**。
- 复核产出：**22 条 objection**（A 6 / B 4 / C 12），**全部成立或部分成立**，处置见 §7.1。

### 7.1 复核意见与处置（逐条）

| objection | 级别 | 成立 | 处置 |
|---|---|---|---|
| A-OBJ-1 · `P2-NEG:admin` 零探针仍记 pass | medium | ✅ | **已订正**：改记 `skip`（D9）；A 面 pass 28 → **27** |
| A-OBJ-2 · §0「全部打开/全部被拦」超强度 | medium | ✅ | **已订正**：§0 加限定语；新增 **§2.1 覆盖边界**（17/65 负向抽样、19/40 路由未访） |
| A-OBJ-3 · 「正文非空」门弱于壳层基线 | medium | ✅ | 登记为 **D10**（本轮无实测假绿，如实说明） |
| A-OBJ-4 · 头注称「零 console error」但实现不消费 | low | ✅ | 登记为 **D11** |
| A-OBJ-5 / C-OBJ-07 · 证据声明「每页 shot」不实 | low/medium | ✅ | **已订正**表述；登记为 **D13**（28/82 有截图） |
| A-OBJ-6 · `adminOnly` 未建模 | low | ✅ | 登记为 **D12**（本轮空集、无失真） |
| B-OBJ-1 / C-OBJ-04 · 订正台账不可复算、§5 指错节 | medium | ✅ | **已订正**：台账改为**由行内字段派生**（D15）；章节指针改为 §3.4 |
| B-OBJ-2 / C-OBJ-03 · §2 C 面计数与产物不符（P4D-1 被吞） | medium/high | ✅ | **已订正**：C 面 = **3 pass / 4 skip**；§3.3 补 `P4D-1` 行并标注「API 夹具」 |
| B-OBJ-3 / C-OBJ-02 · §3.2 每页检查数手抄错（合计 19≠24） | medium/high | ✅ | **已订正**：改为 **5/5/3/4/5/2 = 24**（与产物逐格一致） |
| B-OBJ-4 · 跳过格引用悬空 12/18 | medium | ✅ | **已订正**：理由改为「本格未覆盖」，悬空清单落盘（D14）；写入 §2.1 覆盖边界 |
| C-OBJ-01 · §1 基线引用错（`p7#before` 与「开测基线」混用） | high | ✅ | **已订正**：拆成「清理前快照（有据）」与「开测基线（**未落产物**）」两行，并在 §6.D16 登记缺口 |
| C-OBJ-05 · D1「一律缺 18 项」转述失真 | medium | ✅ | **已订正**：改为逐岗位读数（admin 19 / 客服 8 / 运营 16 / 销售 6 / 财务 6 / 商品 7 / 知识 2） |
| C-OBJ-06 · O4「15 → 18」所引证据实为 18→18 | medium | ✅ | **已订正**：O4 改为「清理前 18；15 为未落产物的现场读数」 |
| C-OBJ-08 · admin 空断言计 pass | medium | ✅ | 同 A-OBJ-1 |
| C-OBJ-09 · O1 裸入口报错无留证 | medium | ✅ | **已补证**：p6 增加 `entryProbes`（三条入口逐个探）+ `bareLoginProbe`（裸入口登录报错逐字落盘） |
| C-OBJ-10 · §7.1 为空却宣称已留档 | low | ✅ | **已订正**：本节即回填内容；报告头状态行同步 |
| C-OBJ-11 · §9.1 用例沉淀是占位符 `UI-0xx` | low | ✅ | **已订正**：改为「**未落库**（待办）」并给出落库计划（§9.1） |
| C-OBJ-12 · `out/shots/` 混入 v1 `*_briefing.png` 陈留 | low | ✅ | **已处置**：7 张移至 `out/shots-v1-superseded/` |

**复核确认成立（非异议）的部分**（裁判逐字核过）：F1 三腿证据链闭合、F1/F2 引文与 `73327161f` 一致、
`P4-W1/W2` 非空断言、`fail→skip` 方向保守且 `rawState` 保留、`p5` 403 + 库内零变化、
`deploy-admin-api.yml:380`、82 次访问 / 17 条负向、B 面 24 实查格、D 面 3+1、E 面 6、F 面 6+1 console error、§8 清理前后读数。
**A 面范围内未发现新的产品缺陷**。

### 7.2 v1 → v2 修订点（一句话）

计数（A 28→27、C 2/5→3/4、B 每页 19→24）· 口径（§0 加限定、新增 §2.1 覆盖边界）· 证据（补裸入口留证、拆开基线与清理前快照）
· 台账（改为可复算）· 引用（章节指针、悬空引用）· 证据卫生（陈留截图移出）· 新增判据侧条目 D9–D16。

---

## 8. 残留与清理（现取）

| 项 | 清理前 | 清理后 |
|---|---|---|
| users（`a06*` / `A06验收*` / 测工人） | 10 active | **0**（软删 + 停用 + 解绑 `username`/`phone`；累计 `deleted=19`，含此前轮次遗留的 5 名「造数探针工人」） |
| knowledge_cards | 2 | **0** |
| orders（API 夹具 2 张） | 2 | **0** |
| 其它（tickets=1 / inbound=18 / products=8） | 开测前即存在、**非本轮写入** | 未触碰 |

读数：`out/p7-cleanup.json`（含每条 SQL 与影响行数）；终态 `users_active=1`（仅管理员）。
**可复现**：`node harness/p1-roles-seed.mjs`（≈20s 重建 6 个岗位账号）→ `p2 → p4 → p5 → p6`（顺序即安全顺序）。

---

## 9. 沉淀

| 项 | 处置 |
|---|---|
| F1 写按钮不随权限显隐（`/knowledge`） | **#6392 → 已修 #6395**（藏按钮；台账 5→4 + UI-081 判据 6 + UI-085；红证与固化声明见该 PR body） |
| F2 `docs/wiki/RBAC.md` 客服权限漂移 | **#6393**（文档订正） |
| O1–O5 观察项 | 登记在 §4；**不派单**（证据不足） |
| 判据侧 D1–D16 | 已修复/登记；承载体 = 本轮 `harness/**`（后续轮次直接复用） |
| case 沉淀 | ⚠️ **未落库**（见 §9.1）——不为「看起来有沉淀」而写占位符 |

### 9.1 case 沉淀（**未完成的诚实登记**）

计划新增到 `.github/cases/ui.yml`（须同批跑 `render_cases.py` 并提交生成物，且测试文件头声明 `# case_ids:`）：

1. **岗位 × 页面写按钮显隐矩阵**：对「写码 ⇒ 页面写按钮」映射，断言「无码岗位 DOM 中该按钮不存在」（会红：把按钮改回裸渲染即红）。
2. **侧边栏菜单 = `role_permissions` × `menu.ts`（含 `adminOnly` ∧ `briefingToggle` ∧ `permissionCode` 三条件）** 的逐项相等判据（D2/D12 的类级固化）。

未落库原因：本轮为**验收轮**，产物目录按惯例入仓（`test(acceptance):` PR），用例落库需走「改 `cases/*.yml` + 渲染生成物 + `verify-all.sh gate`」的独立包；
本报告与对应 issue 已承载该待办（**不留只在上下文里的尾巴**）。
